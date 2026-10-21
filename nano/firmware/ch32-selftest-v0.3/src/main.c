/* Aster MCA Nano CH32 v0.3 static bring-up, 2026-10-13.
 * Wiring checked against the released PCB-netlist.net.
 * Polled USB with optional ADC DMA waveform snapshots. No MCA/count-rate claims. */
#include "ch32x035.h"
#include "ch32x035_usbfs_device.h"
#include <stdint.h>
#include <string.h>

#define TICKS_PER_US 48u
#define SAMPLE_PERIOD (2000u * TICKS_PER_US)
#define HEARTBEAT_PERIOD (500000u * TICKS_PER_US)
#define BLOCK_SAMPLES 256u

/* n=normal, p=ADC off, a=ADC0 slow, w=waveforms, t=thresholded waveforms. */
volatile uint8_t diagnostic_command;
static uint8_t diagnostic_mode = 'n';

static uint32_t ticks(void) { return (uint32_t)SysTick->CNT; }
void Delay_Us(uint32_t us)
{
    uint32_t start = ticks();
    while ((uint32_t)(ticks() - start) < us * TICKS_PER_US) { }
}

static void analog_init(void)
{
    GPIO_InitTypeDef gpio = {0};
    OPA_InitTypeDef opa = {0};
    ADC_InitTypeDef adc = {0};
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA | RCC_APB2Periph_GPIOB |
                         RCC_APB2Periph_AFIO | RCC_APB2Periph_ADC1, ENABLE);
    /* PA7 and PB0 share physical pin 2 on X033F8P6. Both must be analog. */
    gpio.GPIO_Pin = GPIO_Pin_0 | GPIO_Pin_3 | GPIO_Pin_4 |
                    GPIO_Pin_5 | GPIO_Pin_6 | GPIO_Pin_7;
    gpio.GPIO_Mode = GPIO_Mode_AIN;
    GPIO_Init(GPIOA, &gpio);
    gpio.GPIO_Pin = GPIO_Pin_0;
    GPIO_Init(GPIOB, &gpio);

    /* Active-low RUN LED, off before enabling its output driver. */
    GPIO_SetBits(GPIOA, GPIO_Pin_11);
    gpio.GPIO_Pin = GPIO_Pin_11;
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Speed = GPIO_Speed_50MHz; /* Only supported speed enum on X035. */
    GPIO_Init(GPIOA, &gpio);

    OPA_Unlock();
    OPA_POLL_Unlock();
    OPA_StructInit(&opa);
    opa.OPA_NUM = OPA2;             /* PA7(+), PA5(-), PA4(out), first stage */
    opa.Mode = OUT_IO_OUT0;
    opa.PSEL = CHP0;
    opa.NSEL = CHN0;
    opa.FB = FB_OFF;                /* external feedback resistors on board */
    OPA_Init(&opa);
    OPA_Cmd(OPA2, ENABLE);
    opa.OPA_NUM = OPA1;             /* PB0(+), PA6(-), PA3(out), second stage */
    OPA_Init(&opa);
    OPA_Cmd(OPA1, ENABLE);

    ADC_DeInit(ADC1);
    ADC_CLKConfig(ADC1, ADC_CLK_Div6); /* 8 MHz ADC clock */
    adc.ADC_Mode = ADC_Mode_Independent;
    adc.ADC_ScanConvMode = DISABLE;
    adc.ADC_ContinuousConvMode = DISABLE;
    adc.ADC_ExternalTrigConv = ADC_ExternalTrigConv_None;
    adc.ADC_DataAlign = ADC_DataAlign_Right;
    adc.ADC_NbrOfChannel = 1;
    ADC_Init(ADC1, &adc);
    ADC_Cmd(ADC1, ENABLE);
    Delay_Us(1000);
}

static uint16_t conversion(uint8_t channel)
{
    ADC_ClearFlag(ADC1, ADC_FLAG_EOC);
    ADC_RegularChannelConfig(ADC1, channel, 1, ADC_SampleTime_11Cycles);
    ADC_SoftwareStartConvCmd(ADC1, ENABLE);
    uint32_t start = ticks();
    while (!ADC_GetFlagStatus(ADC1, ADC_FLAG_EOC)) {
        if ((uint32_t)(ticks() - start) > 100u * TICKS_PER_US)
            return UINT16_MAX;
    }
    return ADC_GetConversionValue(ADC1);
}

typedef struct { uint32_t sum, n; uint16_t min, max; } Stats;
static Stats stats[3];
static uint32_t adc_errors;
static void clear_stats(void)
{
    memset(stats, 0, sizeof stats);
    for (unsigned i = 0; i < 3; i++) stats[i].min = 4095;
}
static void sample(void)
{
    const uint8_t channels[3] = {ADC_Channel_8, ADC_Channel_4, ADC_Channel_0};
    for (unsigned i = 0; i < 3; i++) {
        if (diagnostic_mode == 'a' && i != 2) continue;
        /* Discard one conversion after each channel switch. */
        uint16_t dummy = conversion(channels[i]);
        uint16_t v = conversion(channels[i]);
        if (dummy > 4095 || v > 4095) { adc_errors++; continue; }
        Stats *s = &stats[i];
        s->sum += v;
        s->n++;
        if (v < s->min) s->min = v;
        if (v > s->max) s->max = v;
    }
}

static char tx[512];
static const uint8_t *tx_data = (const uint8_t *)tx;
static unsigned tx_len, tx_sent;
static void text(const char *s)
{
    while (*s && tx_len < sizeof tx) tx[tx_len++] = *s++;
}
static void number(uint32_t v)
{
    char digits[10];
    unsigned n = 0;
    do { digits[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n && tx_len < sizeof tx) tx[tx_len++] = digits[--n];
}
static void hex32(uint32_t v)
{
    const char digits[] = "0123456789abcdef";
    text("0x");
    for (int shift = 28; shift >= 0; shift -= 4)
        if (tx_len < sizeof tx) tx[tx_len++] = digits[(v >> shift) & 15];
}
static void report(uint32_t sequence)
{
    if (tx_sent != tx_len) return; /* A slow/disconnected host cannot stall sampling. */
    tx_len = tx_sent = 0;
    tx_data = (const uint8_t *)tx;
    text("ASTER selftest v0.3 seq="); number(sequence);
    text(" mode=");
    text(diagnostic_mode == 'p' ? "ADC_OFF" : diagnostic_mode == 'a' ? "ADC0_ONLY" :
         diagnostic_mode == 'w' ? "WAVE" : diagnostic_mode == 't' ? "TRIGGER" : "NORMAL");
    text(" adc_errors="); number(adc_errors); text("\r\n");
    text("OPA_CTL1="); hex32(OPA->CTLR1);
    text(" OPA_CFG1="); hex32(OPA->CFGR1);
    text(" ADC_CTL2="); hex32(ADC1->CTLR2); text("\r\n");
    text("GPIOA_LO="); hex32(GPIOA->CFGLR);
    text(" GPIOB_LO="); hex32(GPIOB->CFGLR); text("\r\n");
    const char *labels[3] = {"M/ADC8", "O2/ADC4", "AD/ADC0"};
    for (unsigned i = 0; i < 3; i++) {
        Stats *s = &stats[i];
        text(labels[i]); text(" n="); number(s->n);
        text(" mean10="); number(s->n ? (s->sum * 10u + s->n / 2u) / s->n : 0);
        text(" min="); number(s->n ? s->min : 0);
        text(" max="); number(s->max); text("\r\n");
    }
}

static void usb_service(void)
{
    if (USBFSD->INT_FG) USBFS_Poll();
    if (!USBFS_DevEnumStatus || !USBFS_DevConfig || (USBFS_DevSleepStatus & 2)) {
        tx_len = tx_sent = 0;
        return;
    }
    if (USBFS_Endp_Busy[DEF_UEP3] || tx_sent == tx_len) return;
    unsigned len = tx_len - tx_sent;
    if (len > 63) len = 63; /* Short packets avoid requiring a trailing ZLP. */
    memcpy(USBFS_EP3_Buf, tx_data + tx_sent, len);
    USBFSD->UEP3_TX_LEN = len;
    USBFS_Endp_Busy[DEF_UEP3] = 1;
    __asm__ volatile ("fence rw,rw" ::: "memory");
    USBFSD->UEP3_CTRL_H = (USBFSD->UEP3_CTRL_H & ~USBFS_UEP_T_RES_MASK) | USBFS_UEP_T_RES_ACK;
    tx_sent += len;
}

/* One 12.288 ms block at nominal 333333 samples/s. The ADC clock remains
 * 8 MHz and the sample time 11 cycles, as in the verified slow diagnostic.
 * Acquisition pauses while a saved block is uploaded; this is NOT a counter.
 * No OPA or pin configuration is changed by these modes. */
#define WAVE_SAMPLES 4096u
#define TRIGGER_CODES 32u
#define CONVERSION_TICKS (6u * (11u + 13u))
typedef struct {
    uint8_t magic[8];
    uint32_t h[20];
    uint16_t sample[WAVE_SAMPLES];
} WavePacket;
static volatile WavePacket wave;
_Static_assert(sizeof(WavePacket) == 88u + WAVE_SAMPLES * 2u, "packet padding");
static uint32_t wave_sequence, acquired_blocks, previous_end;

static uint32_t fnv1a(const volatile uint8_t *data, unsigned n)
{
    uint32_t hash = 2166136261u;
    while (n--) hash = (hash ^ *data++) * 16777619u;
    return hash;
}

static void stop_dma(void)
{
    /* ADON=0 actually stops continuous conversion; clearing SWSTART alone
     * does not. Disable DMA before touching its descriptor or the buffer. */
    ADC_Cmd(ADC1, DISABLE);
    ADC_SoftwareStartConvCmd(ADC1, DISABLE);
    ADC_DMACmd(ADC1, DISABLE);
    DMA_Cmd(DMA1_Channel1, DISABLE);
    ADC1->CTLR2 &= ~ADC_CONT;
    DMA_ClearFlag(DMA1_FLAG_GL1);
}

static int capture_wave(void)
{
    DMA_InitTypeDef dma = {0};
    stop_dma();
    (void)ADC_GetConversionValue(ADC1);
    ADC_ClearFlag(ADC1, ADC_FLAG_EOC);
    ADC_RegularChannelConfig(ADC1, ADC_Channel_0, 1, ADC_SampleTime_11Cycles);
    ADC1->CTLR2 |= ADC_CONT;
    DMA_DeInit(DMA1_Channel1);
    dma.DMA_PeripheralBaseAddr = (uint32_t)&ADC1->RDATAR;
    dma.DMA_MemoryBaseAddr = (uint32_t)wave.sample;
    dma.DMA_DIR = DMA_DIR_PeripheralSRC;
    dma.DMA_BufferSize = WAVE_SAMPLES;
    dma.DMA_MemoryInc = DMA_MemoryInc_Enable;
    dma.DMA_PeripheralDataSize = DMA_PeripheralDataSize_HalfWord;
    dma.DMA_MemoryDataSize = DMA_MemoryDataSize_HalfWord;
    dma.DMA_Mode = DMA_Mode_Normal;
    dma.DMA_Priority = DMA_Priority_VeryHigh;
    DMA_Init(DMA1_Channel1, &dma);
    ADC_Cmd(ADC1, ENABLE);
    Delay_Us(1000);
    DMA_Cmd(DMA1_Channel1, ENABLE);
    ADC_DMACmd(ADC1, ENABLE);
    uint32_t start = ticks();
    uint32_t gap = previous_end ? start - previous_end : 0;
    ADC_SoftwareStartConvCmd(ADC1, ENABLE);
    while (!DMA_GetFlagStatus(DMA1_FLAG_TC1)) {
        if (DMA_GetFlagStatus(DMA1_FLAG_TE1) ||
            (uint32_t)(ticks() - start) > 20000u * TICKS_PER_US) {
            stop_dma();
            adc_errors++;
            diagnostic_command = 'a'; /* Return to a readable slow diagnostic. */
            return 0;
        }
        usb_service();
    }
    uint32_t end = ticks();
    uint32_t ctl2 = ADC1->CTLR2;
    stop_dma();
    __asm__ volatile ("fence rw,rw" ::: "memory");
    previous_end = end;
    acquired_blocks++;
    uint32_t sum = 0, lo = 4095, hi = 0;
    for (unsigned i = 0; i < WAVE_SAMPLES; i++) {
        uint32_t v = wave.sample[i];
        if (v > 4095) {
            adc_errors++;
            diagnostic_command = 'a';
            return 0;
        }
        sum += v;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
    }
    uint32_t mean = (sum + WAVE_SAMPLES / 2u) / WAVE_SAMPLES;
    /* A block-mean excursion is only a diagnostic trigger. Host analysis of
     * raw samples must determine pulse baseline/height and reject pile-up. */
    unsigned triggered = hi - mean >= TRIGGER_CODES || mean - lo >= TRIGGER_CODES;
    if (diagnostic_mode == 't' && !triggered) return 0;
    const uint8_t magic[8] = {'A','S','T','W','0','3','\r','\n'};
    for (unsigned i = 0; i < 8; i++) wave.magic[i] = magic[i];
    wave.h[0] = 3;
    wave.h[1] = ++wave_sequence;
    wave.h[2] = 0; /* AD/ADC0 */
    wave.h[3] = WAVE_SAMPLES;
    wave.h[4] = SystemCoreClock;
    wave.h[5] = CONVERSION_TICKS;
    wave.h[6] = end - start; /* Includes bounded completion polling latency. */
    wave.h[7] = gap;
    wave.h[8] = (lo <= 4 || hi >= 4091 ? 1u : 0u) |
                (diagnostic_mode == 't' ? 2u : 0u) | (triggered ? 4u : 0u);
    wave.h[9] = (sum * 10u + WAVE_SAMPLES / 2u) / WAVE_SAMPLES;
    wave.h[10] = lo;
    wave.h[11] = hi;
    wave.h[12] = adc_errors;
    wave.h[13] = acquired_blocks;
    wave.h[14] = TRIGGER_CODES;
    wave.h[15] = OPA->CTLR1;
    wave.h[16] = ctl2;
    wave.h[17] = ADC1->CTLR3;
    wave.h[18] = fnv1a((const volatile uint8_t *)wave.sample, sizeof wave.sample);
    wave.h[19] = fnv1a((const volatile uint8_t *)&wave, 84);
    tx_data = (const uint8_t *)&wave;
    tx_sent = 0;
    tx_len = sizeof wave;
    return 1;
}

int main(void)
{
    SystemCoreClockUpdate();
    SysTick->CTLR = 0;
    SysTick->CNT = 0;
    SysTick->CMP = UINT64_MAX;
    SysTick->SR = 0;
    SysTick->CTLR = 5; /* HCLK, counter enabled, interrupts and autoreload off. */
    analog_init();
    RCC_AHBPeriphClockCmd(RCC_AHBPeriph_DMA1, ENABLE);
    Delay_Us(200000); /* Allow VMID/AC-coupled stages to settle before telemetry. */
    USBFS_RCC_Init();
    USBFS_Device_Init(ENABLE, PWR_VDD_3V3);
    clear_stats();
    uint32_t last_sample = ticks(), last_led = ticks(), sequence = 0;
    unsigned count = 0, led_on = 0;
    for (;;) {
        usb_service();
        /* Finish an in-flight packet before changing its source buffer. */
        if (diagnostic_command && tx_sent == tx_len && !USBFS_Endp_Busy[DEF_UEP3]) {
            uint8_t command = diagnostic_command;
            diagnostic_command = 0;
            stop_dma();
            diagnostic_mode = command;
            ADC_Cmd(ADC1, command == 'p' ? DISABLE : ENABLE);
            if (command != 'p') Delay_Us(1000);
            clear_stats();
            count = 0;
            last_sample = ticks();
            previous_end = 0;
            report(++sequence);
            /* Keep OPA configuration, LED cadence and USB activity unchanged. */
        }
        uint32_t now = ticks();
        if ((uint32_t)(now - last_led) >= HEARTBEAT_PERIOD) {
            last_led = now;
            led_on ^= 1;
            if (led_on) GPIO_ResetBits(GPIOA, GPIO_Pin_11);
            else GPIO_SetBits(GPIOA, GPIO_Pin_11);
        }
        if (diagnostic_mode == 'w' || diagnostic_mode == 't') {
            if (USBFS_DevEnumStatus && USBFS_DevConfig && !(USBFS_DevSleepStatus & 2) &&
                tx_sent == tx_len && !USBFS_Endp_Busy[DEF_UEP3]) capture_wave();
            continue;
        }
        if ((uint32_t)(now - last_sample) >= SAMPLE_PERIOD) {
            last_sample = now;
            if (diagnostic_mode != 'p') sample();
            if (++count == BLOCK_SAMPLES) {
                report(++sequence);
                clear_stats();
                count = 0;
            }
        }
    }
}
