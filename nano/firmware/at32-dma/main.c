/* Aster MCA Nano AT32 v0.3 board bring-up, firmware 0.2.0.
 * This is a diagnostic sampler, not an MCA pulse-processing firmware.
 * PA0 = ADC1_IN0; PB12 = active-low RUN; PA9 = VBUS via 10k.
 * Artery's USB CDC stack and peripheral drivers are used under their license.
 */
#include "at32f423.h"
#include "usb_conf.h"
#include "usb_core.h"
#include "usbd_core.h"
#include "usbd_int.h"
#include "cdc_class.h"
#include "cdc_desc.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define SAMPLE_COUNT 8192u
#define FW_VERSION "0.2.0"
static otg_core_type usb;
static volatile uint32_t tick_ms, led_edges;
static uint16_t samples[SAMPLE_COUNT];
static char reply[768];
static uint8_t tx_packet[64] __attribute__((aligned(4)));
static uint32_t adc_fault, capture_id, adc_enabled;
static uint32_t sample_rate_hz = 1000000, sample_cycles_x2 = 13;
static uint32_t timer_ticks = 48;
static adc_sampletime_select_type sample_setting = ADC_SAMPLETIME_6_5;
static uint32_t count, minimum, maximum, sum, start_cycles;
static volatile uint32_t dma_done, dma_error, adc_overrun, dma_remaining, end_cycles;
static uint64_t sum_squares;
extern cdc_struct_type cdc_struct;

void _init(void) {}
void _fini(void) {}
void SysTick_Handler(void) {
  ++tick_ms;
  if ((tick_ms % 500u) == 0u) {
    gpio_bits_toggle(GPIOB, GPIO_PINS_12);
    ++led_edges;
  }
}
void OTGFS1_IRQHandler(void) { usbd_irq_handler(&usb); }
void usb_delay_us(uint32_t us) {
  uint32_t begin = DWT->CYCCNT;
  uint32_t ticks = us * (system_core_clock / 1000000u);
  while ((uint32_t)(DWT->CYCCNT - begin) < ticks) {}
}
void usb_delay_ms(uint32_t ms) { while (ms--) usb_delay_us(1000); }

static int connected(void) {
  return usbd_connect_state_get(&usb.dev) == USB_CONN_STATE_CONFIGURED;
}
static int tx_wait(void) {
  uint32_t t = tick_ms;
  while (!cdc_struct.g_tx_completed) {
    if (!connected() || tick_ms - t > 1000) return 0;
  }
  return connected();
}
static int send_bytes(const void *data, uint32_t len) {
  const uint8_t *p = data;
  /* Short packets terminate transfers without relying on the host's read size.
   * Keep the copied packet alive until the USB IRQ reports completion. */
  while (len) {
    uint32_t n = len > 63 ? 63 : len;
    if (!tx_wait()) return 0;
    memcpy(tx_packet, p, n);
    if (usb_vcp_send_data(&usb.dev, tx_packet, n) != SUCCESS) return 0;
    if (!tx_wait()) return 0;
    p += n; len -= n;
  }
  return 1;
}
static void send_text(const char *s) { send_bytes(s, (uint32_t)strlen(s)); }

static void init_clock_gpio_usb(void) {
  /* SystemInit has selected 8 MHz HICK. Set flash latency BEFORE 48 MHz.
   * Vendor helper handles the separate HICKDIV/HICK_TO_SCLK writes (ES0010).
   * No PLL or external crystal is used for this first diagnostic image. */
  flash_psr_set(FLASH_WAIT_CYCLE_1);
  crm_usb_clock_source_select(CRM_USB_CLOCK_SOURCE_HICK);
  system_core_clock_update();
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
  crm_periph_clock_enable(CRM_GPIOA_PERIPH_CLOCK, TRUE);
  crm_periph_clock_enable(CRM_GPIOB_PERIPH_CLOCK, TRUE);
  gpio_init_type pin;
  gpio_default_para_init(&pin);
  gpio_bits_set(GPIOB, GPIO_PINS_12);
  pin.gpio_pins = GPIO_PINS_12;
  pin.gpio_mode = GPIO_MODE_OUTPUT;
  pin.gpio_out_type = GPIO_OUTPUT_PUSH_PULL;
  pin.gpio_pull = GPIO_PULL_NONE;
  gpio_init(GPIOB, &pin);
  pin.gpio_pins = GPIO_PINS_0;
  pin.gpio_mode = GPIO_MODE_ANALOG;
  gpio_init(GPIOA, &pin);
  /* PA9 sees 5 V through R18. It must remain an input, never a driven pin. */
  pin.gpio_pins = GPIO_PINS_9;
  pin.gpio_mode = GPIO_MODE_INPUT;
  gpio_init(GPIOA, &pin);
  nvic_priority_group_config(NVIC_PRIORITY_GROUP_4);
  SysTick_Config(system_core_clock / 1000u);
  crm_periph_clock_enable(CRM_ACC_PERIPH_CLOCK, TRUE);
  acc_write_c1(7980); acc_write_c2(8000); acc_write_c3(8020);
  acc_calibration_mode_enable(ACC_CAL_HICKTRIM, TRUE);
  crm_periph_clock_enable(CRM_OTGFS1_PERIPH_CLOCK, TRUE);
  nvic_irq_enable(OTGFS1_IRQn, 1, 0);
  usbd_init(&usb, USB_FULL_SPEED_CORE_ID, USB_ID, &cdc_class_handler, &cdc_desc_handler);
}

static int init_adc(void) {
  adc_common_config_type common;
  adc_base_config_type base;
  crm_periph_clock_enable(CRM_ADC1_PERIPH_CLOCK, TRUE);
  adc_reset();
  /* ES0010: apply after peripheral clock/reset, before ADC enable/calibration. */
  ADC1->misc_bit.xtest = 0x09;
  crm_adc_clock_select(CRM_ADC_CLOCK_SOURCE_HCLK);
  adc_common_default_para_init(&common);
  common.div = ADC_HCLK_DIV_2; /* 48 MHz / 2 = 24 MHz */
  common.tempervintrv_state = FALSE;
  adc_common_config(&common);
  adc_base_default_para_init(&base);
  base.sequence_mode = FALSE;
  base.repeat_mode = FALSE;
  base.data_align = ADC_RIGHT_ALIGNMENT;
  base.ordinary_channel_length = 1;
  adc_base_config(ADC1, &base);
  adc_resolution_set(ADC1, ADC_RESOLUTION_12B);
  adc_ordinary_channel_set(ADC1, ADC_CHANNEL_0, 1, sample_setting);
  adc_ordinary_conversion_trigger_set(ADC1, ADC_ORDINARY_TRIG_TMR3TRGOUT, ADC_ORDINARY_TRIG_EDGE_NONE);
  adc_dma_mode_enable(ADC1, TRUE);
  adc_dma_request_repeat_enable(ADC1, TRUE);
  adc_occe_each_conversion_enable(ADC1, TRUE);
  adc_enable(ADC1, TRUE);
  uint32_t t = tick_ms;
  while (adc_flag_get(ADC1, ADC_RDY_FLAG) == RESET)
    if (tick_ms - t > 100) { adc_fault = 1; return 0; }
  adc_calibration_init(ADC1);
  t = tick_ms;
  while (adc_calibration_init_status_get(ADC1))
    if (tick_ms - t > 100) { adc_fault = 2; return 0; }
  adc_calibration_start(ADC1);
  t = tick_ms;
  while (adc_calibration_status_get(ADC1))
    if (tick_ms - t > 100) { adc_fault = 3; return 0; }
  adc_enabled = 1;
  adc_fault = 0;
  return 1;
}

static void init_acquisition(void) {
  crm_periph_clock_enable(CRM_TMR3_PERIPH_CLOCK, TRUE);
  crm_periph_clock_enable(CRM_DMA1_PERIPH_CLOCK, TRUE);
  tmr_reset(TMR3);
  tmr_cnt_dir_set(TMR3, TMR_COUNT_UP);
  tmr_clock_source_div_set(TMR3, TMR_CLOCK_DIV1);
  dmamux_enable(DMA1, TRUE);
  dmamux_init(DMA1MUX_CHANNEL1, DMAMUX_DMAREQ_ID_ADC1);
  nvic_irq_enable(DMA1_Channel1_IRQn, 0, 0); /* preempts USB */
}

void DMA1_Channel1_IRQHandler(void) {
  /* Stop triggers before inspecting completion. Do not run per-sample IRQs. */
  TMR3->ctrl1_bit.tmren = FALSE;
  end_cycles = DWT->CYCCNT;
  adc_overrun = ADC1->sts_bit.occo;
  ADC1->ctrl2_bit.ocete = ADC_ORDINARY_TRIG_EDGE_NONE;
  dma_error = (DMA1->sts & DMA1_DTERR1_FLAG) ? 1u : 0u;
  dma_remaining = dma_data_number_get(DMA1_CHANNEL1);
  dma_channel_enable(DMA1_CHANNEL1, FALSE);
  dma_flag_clear(DMA1_GL1_FLAG);
  __DMB();
  dma_done = 1;
}

static void rate_set(uint32_t rate) {
  sample_rate_hz = rate;
  timer_ticks = system_core_clock / rate; /* APB1 and TMR3 remain at HCLK */
  if (rate == 10000) { sample_setting=ADC_SAMPLETIME_640_5; sample_cycles_x2=1281; }
  else if (rate == 100000) { sample_setting=ADC_SAMPLETIME_47_5; sample_cycles_x2=95; }
  else if (rate == 500000) { sample_setting=ADC_SAMPLETIME_24_5; sample_cycles_x2=49; }
  else { sample_setting=ADC_SAMPLETIME_6_5; sample_cycles_x2=13; }
  adc_ordinary_channel_set(ADC1, ADC_CHANNEL_0, 1, sample_setting);
}

static int capture(void) {
  if (!adc_enabled || adc_fault) return 0;
  tmr_counter_enable(TMR3, FALSE);
  adc_ordinary_conversion_trigger_set(ADC1, ADC_ORDINARY_TRIG_TMR3TRGOUT, ADC_ORDINARY_TRIG_EDGE_NONE);
  adc_conversion_stop(ADC1);
  uint32_t t = tick_ms;
  while (adc_conversion_stop_status_get(ADC1))
    if (tick_ms-t > 100) { adc_fault=4; return 0; }
  dma_channel_enable(DMA1_CHANNEL1, FALSE);
  dma_reset(DMA1_CHANNEL1);
  NVIC_ClearPendingIRQ(DMA1_Channel1_IRQn);
  dma_init_type config;
  dma_default_para_init(&config);
  config.buffer_size = SAMPLE_COUNT;
  config.direction = DMA_DIR_PERIPHERAL_TO_MEMORY;
  config.memory_base_addr = (uint32_t)samples;
  config.memory_data_width = DMA_MEMORY_DATA_WIDTH_HALFWORD;
  config.memory_inc_enable = TRUE;
  config.peripheral_base_addr = (uint32_t)&ADC1->odt;
  config.peripheral_data_width = DMA_PERIPHERAL_DATA_WIDTH_HALFWORD;
  config.peripheral_inc_enable = FALSE;
  config.priority = DMA_PRIORITY_VERY_HIGH;
  config.loop_mode_enable = FALSE; /* completed data must never wrap/overwrite */
  dma_init(DMA1_CHANNEL1, &config);
  dma_flag_clear(DMA1_GL1_FLAG);
  dma_interrupt_enable(DMA1_CHANNEL1, DMA_FDT_INT | DMA_DTERR_INT, TRUE);
  /* Base init emits a software update: keep ADC external triggering OFF here. */
  tmr_primary_mode_select(TMR3, TMR_PRIMARY_SEL_RESET);
  tmr_base_init(TMR3, timer_ticks-1, 0);
  tmr_counter_value_set(TMR3, 0);
  tmr_flag_clear(TMR3, TMR_OVF_FLAG);
  tmr_primary_mode_select(TMR3, TMR_PRIMARY_SEL_OVERFLOW);
  /* Recover any late end-of-frame conversion left after stopping the timer. */
  adc_enable(ADC1, FALSE);
  (void)adc_ordinary_conversion_data_get(ADC1);
  adc_flag_clear(ADC1, ADC_OCCE_FLAG | ADC_OCCO_FLAG | ADC_RDY_FLAG);
  adc_enable(ADC1, TRUE);
  t=tick_ms;
  while (adc_flag_get(ADC1, ADC_RDY_FLAG)==RESET)
    if (tick_ms-t>100) { adc_fault=1; return 0; }
  dma_done=dma_error=adc_overrun=0; dma_remaining=SAMPLE_COUNT;
  dma_channel_enable(DMA1_CHANNEL1, TRUE);
  adc_ordinary_conversion_trigger_set(ADC1, ADC_ORDINARY_TRIG_TMR3TRGOUT, ADC_ORDINARY_TRIG_EDGE_RISING);
  uint32_t deadline_ms = (SAMPLE_COUNT*1000u)/sample_rate_hz + 100u;
  t=tick_ms;
  __DMB();
  start_cycles=DWT->CYCCNT;
  TMR3->ctrl1_bit.tmren=TRUE;
  while (!dma_done) {
    if (tick_ms-t > deadline_ms) {
      TMR3->ctrl1_bit.tmren=FALSE;
      ADC1->ctrl2_bit.ocete=ADC_ORDINARY_TRIG_EDGE_NONE;
      dma_channel_enable(DMA1_CHANNEL1,FALSE);
      adc_fault=5; return 0;
    }
  }
  __DMB();
  adc_conversion_stop(ADC1);
  t=tick_ms;
  while (adc_conversion_stop_status_get(ADC1))
    if (tick_ms-t>100) { adc_fault=4; return 0; }
  if (dma_error || dma_remaining) { adc_fault=6; return 0; }
  if (adc_overrun) { adc_fault=7; return 0; }
  count = sum = 0; sum_squares = 0; minimum=4095; maximum=0;
  for (uint32_t i=0;i<SAMPLE_COUNT;++i) {
    uint16_t v=samples[i];
    if (v<minimum) minimum=v;
    if (v>maximum) maximum=v;
    sum+=v; sum_squares+=(uint64_t)v*v; ++count;
  }
  ++capture_id;
  return 1;
}

static uint32_t crc32(const void *data, uint32_t len) {
  const uint8_t *p = data;
  uint32_t crc = 0xffffffffu;
  while (len--) {
    crc ^= *p++;
    for (unsigned i = 0; i < 8; ++i) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
  }
  return ~crc;
}
static void info(void) {
  snprintf(reply,sizeof(reply),
    "{\"type\":\"info\",\"board\":\"Aster MCA Nano AT32 v0.3\",\"mcu\":\"AT32F423CCT7\","
    "\"fw\":\"%s\",\"method\":\"timer_dma\",\"core_hz\":%lu,\"adc_hz\":%lu,"
    "\"sample_rate_hz\":%lu,\"timer_ticks\":%lu,\"sample_cycles_x2\":%lu,\"n\":%u,"
    "\"adc_on\":%lu,\"adc_fault\":%lu,\"xtest\":%lu,\"uptime_ms\":%lu,\"led_edges\":%lu}\r\n",
    FW_VERSION,(unsigned long)system_core_clock,(unsigned long)(system_core_clock/2u),
    (unsigned long)sample_rate_hz,(unsigned long)timer_ticks,(unsigned long)sample_cycles_x2,SAMPLE_COUNT,
    (unsigned long)adc_enabled,(unsigned long)adc_fault,(unsigned long)ADC1->misc_bit.xtest,
    (unsigned long)tick_ms,(unsigned long)led_edges);
  send_text(reply);
}
static void stats(void) {
  char square_digits[24]; char *digits=square_digits+sizeof(square_digits)-1; *digits=0;
  uint64_t sq=sum_squares;
  do { *--digits='0'+(sq%10u); sq/=10u; } while(sq);
  snprintf(reply,sizeof(reply),
    "{\"type\":\"stats\",\"method\":\"timer_dma\",\"id\":%lu,\"n\":%lu,\"min\":%lu,\"max\":%lu,"
    "\"sum\":%lu,\"sum_sq\":%s,\"sample_rate_hz\":%lu,\"timer_ticks\":%lu,"
    "\"nominal_span_cycles\":%lu,\"elapsed_cycles\":%lu,\"core_hz\":%lu,"
    "\"dma_remaining\":%lu,\"dma_error\":%lu,\"adc_overrun\":%lu,\"crc32\":%lu}\r\n",
    (unsigned long)capture_id,(unsigned long)count,(unsigned long)minimum,(unsigned long)maximum,
    (unsigned long)sum,digits,(unsigned long)sample_rate_hz,(unsigned long)timer_ticks,
    (unsigned long)((count-1u)*timer_ticks),(unsigned long)(end_cycles-start_cycles),
    (unsigned long)system_core_clock,(unsigned long)dma_remaining,(unsigned long)dma_error,
    (unsigned long)adc_overrun,(unsigned long)crc32(samples,count*sizeof(samples[0])));
  send_text(reply);
}
static void command(const char *cmd) {
  if (!strcmp(cmd,"INFO")) info();
  else if (!strcmp(cmd,"PING")) send_text("PONG\r\n");
  else if (!strcmp(cmd,"SLOW") || !strcmp(cmd,"FAST") || !strcmp(cmd,"TURBO") || !strncmp(cmd,"RATE ",5)) {
    if (!adc_enabled || adc_fault) { send_text("ERR ADC_DISABLED_OR_FAULT\r\n"); return; }
    uint32_t rate=0;
    if (!strcmp(cmd,"SLOW") || !strcmp(cmd,"RATE 10000")) rate=10000;
    else if (!strcmp(cmd,"FAST") || !strcmp(cmd,"RATE 100000")) rate=100000;
    else if (!strcmp(cmd,"RATE 500000")) rate=500000;
    else if (!strcmp(cmd,"TURBO") || !strcmp(cmd,"RATE 1000000")) rate=1000000;
    if (!rate) { send_text("ERR RATE_USE_10000_100000_500000_1000000\r\n"); return; }
    rate_set(rate); info();
  } else if (!strcmp(cmd,"ADC OFF")) {
    adc_enable(ADC1,FALSE); adc_enabled=0; info();
  } else if (!strcmp(cmd,"ADC ON")) {
    init_adc(); info();
  } else if (!strcmp(cmd,"STATS") || !strcmp(cmd,"RAW")) {
    if (!capture()) { send_text("ERR ADC_DISABLED_OR_FAULT\r\n"); info(); return; }
    stats();
    if (!strcmp(cmd,"RAW")) {
      /* Follow the JSON line with exactly n*2 LE bytes, then CRLF. */
      send_bytes(samples,count*sizeof(samples[0])); send_text("\r\n");
    }
  } else if (!strcmp(cmd,"REBOOT")) {
    send_text("OK REBOOT\r\n"); usb_delay_ms(50); NVIC_SystemReset();
  } else if (!strcmp(cmd,"HELP")) {
    send_text("INFO PING STATS RAW SLOW FAST TURBO RATE ADC OFF ADC ON REBOOT\r\n");
  } else send_text("ERR UNKNOWN_COMMAND\r\n");
}

int main(void) {
  init_clock_gpio_usb();
  usb_delay_ms(200); /* let VMID reservoir settle before calibration/sampling */
  init_adc();
  init_acquisition();
  uint8_t rx[64]; char line[64]; unsigned used=0; int overflow=0;
  for (;;) {
    if (!connected()) { used=0; overflow=0; continue; }
    uint16_t n=usb_vcp_get_rxdata(&usb.dev,rx);
    for (unsigned i=0;i<n;++i) {
      char c=(char)rx[i];
      if (c=='\n' || c=='\r') {
        if (overflow) send_text("ERR LINE_TOO_LONG\r\n");
        else if (used) { line[used]=0; command(line); }
        used=0; overflow=0;
      } else if (!overflow) {
        if (used<sizeof(line)-1) line[used++]=c; else overflow=1;
      }
    }
  }
}
