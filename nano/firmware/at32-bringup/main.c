/* Aster MCA Nano AT32 v0.3 board bring-up, firmware 0.1.0.
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

#define SAMPLE_COUNT 4096u
#define FW_VERSION "0.1.0"
static otg_core_type usb;
static volatile uint32_t tick_ms, led_edges;
static uint16_t samples[SAMPLE_COUNT];
static char reply[512];
static uint8_t tx_packet[64] __attribute__((aligned(4)));
static uint32_t adc_fault, capture_id, adc_enabled;
static uint32_t period_us = 100, sample_cycles_x2 = 1281;
static uint32_t count, minimum, maximum, sum, start_cycles, end_cycles;
static uint32_t gap_min, gap_max, late_samples;
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
  common.div = ADC_HCLK_DIV_4; /* 48 MHz / 4 = 12 MHz */
  common.tempervintrv_state = FALSE;
  adc_common_config(&common);
  adc_base_default_para_init(&base);
  base.sequence_mode = FALSE;
  base.repeat_mode = FALSE;
  base.data_align = ADC_RIGHT_ALIGNMENT;
  base.ordinary_channel_length = 1;
  adc_base_config(ADC1, &base);
  adc_resolution_set(ADC1, ADC_RESOLUTION_12B);
  adc_ordinary_channel_set(ADC1, ADC_CHANNEL_0, 1, ADC_SAMPLETIME_640_5);
  adc_ordinary_conversion_trigger_set(ADC1, ADC_ORDINARY_TRIG_TMR1CH1, ADC_ORDINARY_TRIG_EDGE_NONE);
  adc_dma_mode_enable(ADC1, FALSE);
  adc_dma_request_repeat_enable(ADC1, FALSE);
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

static int capture(void) {
  if (!adc_enabled || adc_fault) return 0;
  count = sum = 0; sum_squares = 0;
  minimum = 4095; maximum = gap_max = late_samples = 0; gap_min = UINT32_MAX;
  uint32_t period = period_us * (system_core_clock / 1000000u);
  uint32_t next = DWT->CYCCNT + period, previous = 0;
  /* Firmware-paced diagnostic capture. USB IRQs stay enabled; measured trigger
   * gaps are reported. This is NOT a DMA/time-uniform narrow-pulse proof. */
  for (uint32_t i = 0; i < SAMPLE_COUNT; ++i) {
    while ((int32_t)(DWT->CYCCNT - next) < 0) {}
    uint32_t now = DWT->CYCCNT;
    if (i == 0) start_cycles = now;
    else {
      uint32_t gap = now - previous;
      if (gap < gap_min) gap_min = gap;
      if (gap > gap_max) gap_max = gap;
    }
    if (now - next > (system_core_clock / 1000000u)) ++late_samples;
    previous = now;
    next += period;
    if ((int32_t)(now - next) >= 0) next = now + period;
    adc_flag_clear(ADC1, ADC_OCCE_FLAG | ADC_OCCO_FLAG);
    adc_ordinary_software_trigger_enable(ADC1, TRUE);
    uint32_t deadline = DWT->CYCCNT;
    while (adc_flag_get(ADC1, ADC_OCCE_FLAG) == RESET) {
      if ((uint32_t)(DWT->CYCCNT - deadline) > system_core_clock / 100u) {
        adc_fault = 4; return 0;
      }
    }
    uint16_t v = adc_ordinary_conversion_data_get(ADC1);
    samples[i] = v;
    if (v < minimum) minimum = v;
    if (v > maximum) maximum = v;
    sum += v; sum_squares += (uint64_t)v * v; ++count;
  }
  end_cycles = previous;
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
  snprintf(reply, sizeof(reply),
    "{\"type\":\"info\",\"board\":\"Aster MCA Nano AT32 v0.3\",\"mcu\":\"AT32F423CCT7\",\"fw\":\"%s\","
    "\"core_hz\":%lu,\"adc_hz\":%lu,\"period_us\":%lu,\"sample_cycles_x2\":%lu,"
    "\"adc_on\":%lu,\"adc_fault\":%lu,\"xtest\":%lu,\"uptime_ms\":%lu,\"led_edges\":%lu}\r\n",
    FW_VERSION, (unsigned long)system_core_clock, (unsigned long)(system_core_clock/4u),
    (unsigned long)period_us, (unsigned long)sample_cycles_x2, (unsigned long)adc_enabled,
    (unsigned long)adc_fault, (unsigned long)ADC1->misc_bit.xtest,
    (unsigned long)tick_ms, (unsigned long)led_edges);
  send_text(reply);
}
static void stats(void) {
  char square_digits[24];
  char *digits = square_digits + sizeof(square_digits) - 1;
  *digits = 0;
  uint64_t sq = sum_squares;
  do { *--digits = '0' + (sq % 10u); sq /= 10u; } while (sq);
  snprintf(reply, sizeof(reply),
    "{\"type\":\"stats\",\"id\":%lu,\"n\":%lu,\"min\":%lu,\"max\":%lu,\"sum\":%lu,"
    "\"sum_sq\":%s,\"span_cycles\":%lu,\"gap_min\":%lu,\"gap_max\":%lu,\"late_gt_1us\":%lu,"
    "\"period_us\":%lu,\"core_hz\":%lu,\"crc32\":%lu}\r\n",
    (unsigned long)capture_id,(unsigned long)count,(unsigned long)minimum,(unsigned long)maximum,
    (unsigned long)sum,digits,(unsigned long)(end_cycles-start_cycles),
    (unsigned long)gap_min,(unsigned long)gap_max,(unsigned long)late_samples,
    (unsigned long)period_us,(unsigned long)system_core_clock,
    (unsigned long)crc32(samples,count*sizeof(samples[0])));
  send_text(reply);
}
static void command(const char *cmd) {
  if (!strcmp(cmd,"INFO")) info();
  else if (!strcmp(cmd,"PING")) send_text("PONG\r\n");
  else if (!strcmp(cmd,"SLOW") || !strcmp(cmd,"FAST")) {
    if (!adc_enabled || adc_fault) { send_text("ERR ADC_DISABLED_OR_FAULT\r\n"); return; }
    int slow = !strcmp(cmd,"SLOW");
    period_us = slow ? 100u : 10u; sample_cycles_x2 = slow ? 1281u : 95u;
    adc_ordinary_channel_set(ADC1, ADC_CHANNEL_0, 1, slow ? ADC_SAMPLETIME_640_5 : ADC_SAMPLETIME_47_5);
    info();
  } else if (!strcmp(cmd,"ADC OFF")) {
    adc_enable(ADC1,FALSE); adc_enabled=0; info();
  } else if (!strcmp(cmd,"ADC ON")) {
    period_us=100; sample_cycles_x2=1281; init_adc(); info();
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
    send_text("INFO PING STATS RAW SLOW FAST ADC OFF ADC ON REBOOT\r\n");
  } else send_text("ERR UNKNOWN_COMMAND\r\n");
}

int main(void) {
  init_clock_gpio_usb();
  usb_delay_ms(200); /* let VMID reservoir settle before calibration/sampling */
  init_adc();
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
