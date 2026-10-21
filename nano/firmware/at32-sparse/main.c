/* Aster MCA Nano AT32 v0.3 board bring-up, firmware 0.4.4.
 * Continuous ADC with selected lossless waveform windows; DSP remains on host.
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

#include "codec.h"
#include "selector.h"
#define SAMPLE_COUNT 8192u
#define BLOCK 4096u
#define QCOUNT 12u
#define PACKET_SAMPLES 512u
#define HEADER 80u
#define CAPACITY (HEADER+PACKET_SAMPLES*2u+4u)
#define FW_VERSION "0.4.4"
static otg_core_type usb;
static volatile uint32_t tick_ms, led_edges;
static volatile uint16_t samples[SAMPLE_COUNT] __attribute__((aligned(4)));
static char reply[768];
static uint8_t tx_packet[64] __attribute__((aligned(4)));
static uint32_t adc_fault, adc_enabled;
static uint32_t clock_fault;
static adc_sampletime_select_type sample_setting = ADC_SAMPLETIME_2_5;
typedef struct { uint32_t len; uint8_t data[CAPACITY]; } packet_t;
static packet_t queue[QCOUNT];
static uint32_t qhead,qtail,tx_active,tx_started_ms,queue_high;
static volatile uint32_t completed,sampling,stop_request,stream_error;
static volatile uint32_t irq_cycles[2],irq_ms[2],tail_samples;
static uint32_t processed,stream_active,end_queued,limit_blocks,session_id;
static uint32_t start_ms,encode_max;
static selector_t selector;
static uint8_t terminal[1200];
static uint16_t pending[PACKET_SAMPLES];
static uint64_t pending_first;
static uint32_t pending_n,pending_hits;
static uint32_t selection_threshold=64,selector_fault;
static volatile uint32_t irq_delta_min,irq_delta_max,last_irq;
static uint32_t wire_bytes,sent_blocks,session_start_cycles;
enum { ERR_DMA=1,ERR_ADC=2,ERR_IRQ=4,ERR_DEADLINE=8,ERR_QUEUE=16,
       ERR_USB=32,ERR_INPUT=64,ERR_TIMEOUT=128 };
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
  /* Establish 48 MHz HICK/USB before enabling HICK-fed PLL (ES0010).
   * CPU=144 MHz; APB1=72 MHz (TMR3=144 MHz); ADC=72 MHz. */
  flash_psr_set(FLASH_WAIT_CYCLE_4);
  crm_usb_clock_source_select(CRM_USB_CLOCK_SOURCE_HICK);
  system_core_clock_update();
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
  crm_periph_clock_enable(CRM_PWC_PERIPH_CLOCK,TRUE);
  pwc_ldo_output_voltage_set(PWC_LDO_OUTPUT_1V3);
  crm_pll_config(CRM_PLL_SOURCE_HICK,72,1,CRM_PLL_FR_2);
  crm_clock_source_enable(CRM_CLOCK_SOURCE_PLL,TRUE);
  uint32_t deadline=DWT->CYCCNT;
  while(crm_flag_get(CRM_PLL_STABLE_FLAG)!=SET) {
    if(DWT->CYCCNT-deadline>2400000u) {clock_fault=1;break;}
  }
  if(!clock_fault) {
    crm_ahb_div_set(CRM_AHB_DIV_1);
    crm_apb1_div_set(CRM_APB1_DIV_2);
    crm_apb2_div_set(CRM_APB2_DIV_1);
    crm_auto_step_mode_enable(TRUE);crm_sysclk_switch(CRM_SCLK_PLL);
    deadline=DWT->CYCCNT;
    while(crm_sysclk_switch_status_get()!=CRM_SCLK_PLL) {
      if(DWT->CYCCNT-deadline>4800000u) {clock_fault=2;break;}
    }
    crm_auto_step_mode_enable(FALSE);
  }
  system_core_clock_update();
  if(system_core_clock!=144000000u) clock_fault=3;
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
  common.div = ADC_HCLK_DIV_2; /* 144 MHz / 2 = 72 MHz */
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

static void halt_sampling(uint32_t error) {
  uint32_t primask=__get_PRIMASK(); __disable_irq();
  TMR3->ctrl1_bit.tmren=FALSE;
  ADC1->ctrl2_bit.ocete=ADC_ORDINARY_TRIG_EDGE_NONE;
  dma_channel_enable(DMA1_CHANNEL1,FALSE);
  if(sampling) {
    uint32_t pos=(SAMPLE_COUNT-dma_data_number_get(DMA1_CHANNEL1))%SAMPLE_COUNT;
    tail_samples=(pos-(completed%2u)*BLOCK+SAMPLE_COUNT)%SAMPLE_COUNT;
  }
  stream_error|=error; sampling=0;
  dma_flag_clear(DMA1_GL1_FLAG);
  __DMB(); __set_PRIMASK(primask);
}

static void init_acquisition(void) {
  crm_periph_clock_enable(CRM_TMR3_PERIPH_CLOCK,TRUE);
  crm_periph_clock_enable(CRM_DMA1_PERIPH_CLOCK,TRUE);
  tmr_reset(TMR3);
  tmr_cnt_dir_set(TMR3,TMR_COUNT_UP);
  tmr_clock_source_div_set(TMR3,TMR_CLOCK_DIV1);
  dmamux_enable(DMA1,TRUE);
  dmamux_init(DMA1MUX_CHANNEL1,DMAMUX_DMAREQ_ID_ADC1);
  nvic_irq_enable(DMA1_Channel1_IRQn,0,0);
}

void DMA1_Channel1_IRQHandler(void) {
  uint32_t flags=DMA1->sts;
  uint32_t expected=(completed&1u)?DMA1_FDT1_FLAG:DMA1_HDT1_FLAG;
  if(!sampling) { dma_flag_clear(DMA1_GL1_FLAG); return; }
  if(flags&DMA1_DTERR1_FLAG) { halt_sampling(ERR_DMA);return; }
  if(ADC1->sts_bit.occo) { halt_sampling(ERR_ADC);return; }
  if((flags&(DMA1_HDT1_FLAG|DMA1_FDT1_FLAG))!=expected) {
    halt_sampling(ERR_IRQ);return;
  }
  dma_flag_clear(expected);
  uint32_t now=DWT->CYCCNT;
  if(completed) {
    uint32_t dt=now-last_irq;
    if(dt<irq_delta_min) irq_delta_min=dt;
    if(dt>irq_delta_max) irq_delta_max=dt;
  }
  last_irq=now;
  irq_cycles[completed&1u]=now;
  irq_ms[completed&1u]=tick_ms;
  __DMB(); ++completed;
  if(stop_request || (limit_blocks && completed>=limit_blocks)) halt_sampling(0);
}

static int begin_stream(uint32_t ms) {
  if(!adc_enabled || adc_fault || clock_fault || selector_fault) return 0;
  halt_sampling(0);
  adc_conversion_stop(ADC1);
  uint32_t t=tick_ms;
  while(adc_conversion_stop_status_get(ADC1))
    if(tick_ms-t>100) { adc_fault=4;return 0; }
  dma_reset(DMA1_CHANNEL1);
  NVIC_ClearPendingIRQ(DMA1_Channel1_IRQn);
  dma_init_type cfg;dma_default_para_init(&cfg);
  cfg.buffer_size=SAMPLE_COUNT;
  cfg.direction=DMA_DIR_PERIPHERAL_TO_MEMORY;
  cfg.memory_base_addr=(uint32_t)samples;
  cfg.memory_data_width=DMA_MEMORY_DATA_WIDTH_HALFWORD;
  cfg.memory_inc_enable=TRUE;
  cfg.peripheral_base_addr=(uint32_t)&ADC1->odt;
  cfg.peripheral_data_width=DMA_PERIPHERAL_DATA_WIDTH_HALFWORD;
  cfg.peripheral_inc_enable=FALSE;
  cfg.priority=DMA_PRIORITY_VERY_HIGH;
  cfg.loop_mode_enable=TRUE;
  dma_init(DMA1_CHANNEL1,&cfg);
  dma_flag_clear(DMA1_GL1_FLAG);
  dma_interrupt_enable(DMA1_CHANNEL1,DMA_HDT_INT|DMA_FDT_INT|DMA_DTERR_INT,TRUE);
  tmr_primary_mode_select(TMR3,TMR_PRIMARY_SEL_RESET);
  tmr_base_init(TMR3,35,0);
  tmr_counter_value_set(TMR3,0);
  tmr_flag_clear(TMR3,TMR_OVF_FLAG);
  tmr_primary_mode_select(TMR3,TMR_PRIMARY_SEL_OVERFLOW);
  adc_enable(ADC1,FALSE);
  (void)adc_ordinary_conversion_data_get(ADC1);
  adc_flag_clear(ADC1,ADC_OCCE_FLAG|ADC_OCCO_FLAG|ADC_RDY_FLAG);
  adc_enable(ADC1,TRUE); t=tick_ms;
  while(adc_flag_get(ADC1,ADC_RDY_FLAG)==RESET)
    if(tick_ms-t>100) { adc_fault=1;return 0; }
  qhead=qtail=tx_active=queue_high=0;
  completed=processed=stream_error=stop_request=tail_samples=0;
  encode_max=irq_delta_max=wire_bytes=sent_blocks=end_queued=0;
  irq_delta_min=0xffffffffu;
  limit_blocks=ms?(uint32_t)(((uint64_t)ms*4000u+BLOCK-1u)/BLOCK):0;
  pending_n=pending_hits=0;
  selector_init(&selector,selection_threshold);
  ++session_id;
  sampling=stream_active=1;
  dma_channel_enable(DMA1_CHANNEL1,TRUE);
  adc_ordinary_conversion_trigger_set(ADC1,ADC_ORDINARY_TRIG_TMR3TRGOUT,ADC_ORDINARY_TRIG_EDGE_RISING);
  start_ms=tick_ms;session_start_cycles=DWT->CYCCNT;
  __DMB();TMR3->ctrl1_bit.tmren=TRUE;
  return 1;
}

static uint32_t make_header(uint8_t *data,uint32_t kind,uint32_t seq,
                        uint64_t first,uint32_t n,uint32_t length,
                        uint32_t raw_hash,uint32_t cycles,uint32_t hits) {
  memcpy(data,"ASTS04\r\n",8);
  uint32_t w[18];
  w[0]=1;w[1]=kind;w[2]=session_id;w[3]=seq;
  w[4]=(uint32_t)first;w[5]=(uint32_t)(first>>32);
  w[6]=n;w[7]=SELECT_RATE;w[8]=length;w[9]=(kind==1)?1:0;
  w[10]=raw_hash;w[11]=hash_bytes(data+HEADER,length);
  w[12]=stream_error;w[13]=completed;w[14]=cycles;
  w[15]=hits;w[16]=tick_ms-start_ms;
  memcpy(data+8,w,17u*4u);
  w[17]=hash_bytes(data,HEADER-4);
  memcpy(data+HEADER-4,&w[17],4);
  uint32_t len=HEADER+length;
  if(!(len%64u)) data[len++]=0;
  return len;
}

static void pump_tx(void) {
  if(tx_active) {
    if(!cdc_struct.g_tx_completed) {
      if(tick_ms-tx_started_ms>1000) halt_sampling(ERR_USB);
      return;
    }
    packet_t *p=&queue[qtail%QCOUNT];
    ++sent_blocks;wire_bytes+=p->len; ++qtail;tx_active=0;
  }
  if(qtail<qhead) {
    packet_t *p=&queue[qtail%QCOUNT];
    if(usb_vcp_send_data(&usb.dev,p->data,(uint16_t)p->len)==SUCCESS) {
      tx_active=1;tx_started_ms=tick_ms;
    } else halt_sampling(ERR_USB);
  }
}

static int flush_pending(void) {
  if(!pending_n)return 1;
  pump_tx();
  if(qhead-qtail>=QCOUNT) {halt_sampling(ERR_QUEUE);return 0;}
  uint32_t raw_hash;
  packet_t *p=&queue[qhead%QCOUNT];
  uint32_t length=encode_adc(pending,pending_n,p->data+HEADER,&raw_hash);
  p->len=make_header(p->data,1,qhead,pending_first,pending_n,length,raw_hash,
                     irq_cycles[processed&1u],pending_hits);
  __DMB();++qhead;
  if(qhead-qtail>queue_high) queue_high=qhead-qtail;
  pending_n=pending_hits=0;pump_tx();
  return !stream_error;
}

static int emit_block(void *context,uint64_t first,const uint16_t *data,uint32_t hits) {
  (void)context;
  if(pending_n && (first!=pending_first+pending_n || pending_n+SELECT_BLOCK>PACKET_SAMPLES)) {
    if(!flush_pending())return 0;
  }
  if(!pending_n)pending_first=first;
  memcpy(pending+pending_n,data,SELECT_BLOCK*2u);
  pending_n+=SELECT_BLOCK;pending_hits+=hits;
  return 1;
}

static void pump_adc(void) {
  uint32_t ready=completed;
  if(processed==ready) return;
  if(stream_error) {processed=ready;return;}
  if(ready!=processed+1u) {
    halt_sampling(ERR_DEADLINE); processed=ready;return;
  }
  uint32_t half=processed&1u, now=DWT->CYCCNT;
  for(uint32_t offset=0;offset<BLOCK;offset+=SELECT_BLOCK) {
    if(!selector_feed(&selector,(const uint16_t*)(samples+half*BLOCK+offset),emit_block,0)) break;
  }
  if(!stream_error)flush_pending();
  uint32_t enc=DWT->CYCCNT-now;
  if(enc>encode_max) encode_max=enc;
  __DMB();
  /* DMA starts overwriting this half at the NEXT half interrupt. No invalid
   * run may be accepted even if some frames were already queued. */
  uint32_t pos=(SAMPLE_COUNT-dma_data_number_get(DMA1_CHANNEL1))%SAMPLE_COUNT;
  if(completed!=ready || (sampling && pos/BLOCK==half)) {
    halt_sampling(ERR_DEADLINE);processed=completed;return;
  }
  if(enc>encode_max) encode_max=enc;
  ++processed;
}

static void pump_end(void) {
  if(sampling || end_queued || processed!=completed || qhead!=qtail || tx_active) return;
  uint32_t missing_tail=selector.have_window && selector.keep_until>=selector.blocks
      ? (selector.keep_until-selector.blocks+1u)*SELECT_BLOCK : 0;
  int n=snprintf((char*)terminal+HEADER,sizeof(terminal)-HEADER-1,
    "{\"type\":\"end\",\"fw\":\"%s\",\"session\":%lu,\"errors\":%lu,"
    "\"completed_blocks\":%lu,\"scanned_blocks\":%lu,\"packet_count\":%lu,\"selected_samples\":%lu,"
    "\"sample_rate_hz\":4000000,\"dma_block_samples\":4096,\"block_samples\":64,"
    "\"candidate_blocks\":%lu,\"clipped_blocks\":%lu,\"selection_threshold\":%lu,"
    "\"startup_unsearched_samples\":0,\"missing_post_context_samples\":%lu,"
    "\"tail_samples_excluded\":%lu,\"queue_high\":%lu,"
    "\"scan_block_max_cycles\":%lu,\"process_max_cycles\":%lu,\"irq_delta_min\":%lu,\"irq_delta_max\":%lu,"
    "\"span_cycles_mod32\":%lu,\"duration_ms\":%lu,\"adc_overrun\":%lu}",
    FW_VERSION,(unsigned long)session_id,(unsigned long)stream_error,
    (unsigned long)completed,(unsigned long)selector.blocks,(unsigned long)qhead,(unsigned long)(selector.emitted*SELECT_BLOCK),
    (unsigned long)selector.candidates,(unsigned long)selector.clipped_blocks,(unsigned long)selection_threshold,
    (unsigned long)missing_tail,(unsigned long)tail_samples,
    (unsigned long)queue_high,(unsigned long)selector.scan_max_cycles,(unsigned long)encode_max,
    (unsigned long)(completed>1?irq_delta_min:0),(unsigned long)irq_delta_max,
    (unsigned long)(last_irq-session_start_cycles),(unsigned long)(tick_ms-start_ms),
    (unsigned long)ADC1->sts_bit.occo);
  if(n<0 || (unsigned)n>=sizeof(terminal)-HEADER-1) {
    halt_sampling(ERR_INPUT);stream_active=0;return;
  }
  uint32_t len=make_header(terminal,2,qhead,(uint64_t)completed*BLOCK,0,(uint32_t)n,0,last_irq,0);
  send_bytes(terminal,len);end_queued=1;stream_active=0;
}

static void info(void) {
  snprintf(reply,sizeof(reply),
    "{\"type\":\"info\",\"board\":\"Aster MCA Nano AT32 v0.3\",\"mcu\":\"AT32F423CCT7\","
    "\"fw\":\"%s\",\"method\":\"continuous_dma_sparse\",\"core_hz\":%lu,"
    "\"adc_hz\":72000000,\"sample_rate_hz\":4000000,\"timer_ticks\":36,"
    "\"sample_cycles_x2\":5,\"block_samples\":64,\"dma_samples\":8192,\"selection_threshold\":%lu,"
    "\"codec\":\"delta4_escape12\",\"adc_on\":%lu,\"adc_fault\":%lu,"
    "\"xtest\":%lu,\"session\":%lu,\"last_errors\":%lu,\"uptime_ms\":%lu,\"led_edges\":%lu,\"clock_fault\":%lu,\"selector_fault\":%lu}\r\n",
    FW_VERSION,(unsigned long)system_core_clock,(unsigned long)selection_threshold,(unsigned long)adc_enabled,
    (unsigned long)adc_fault,(unsigned long)ADC1->misc_bit.xtest,(unsigned long)session_id,
    (unsigned long)stream_error,(unsigned long)tick_ms,(unsigned long)led_edges,(unsigned long)clock_fault,(unsigned long)selector_fault);
  send_text(reply);
}

static void command(const char *cmd) {
  if(stream_active) {
    if(!strcmp(cmd,"STOP")) stop_request=1;
    return; /* Never interleave ASCII responses with a binary stream. */
  }
  if(!strcmp(cmd,"INFO")) info();
  else if(!strcmp(cmd,"PING")) send_text("PONG\r\n");
  else if(!strncmp(cmd,"STREAM ",7)) {
    uint32_t ms=0;const char *s=cmd+7;
    if(!*s) { send_text("ERR STREAM_MS\r\n");return; }
    while(*s) {
      if(*s<'0'||*s>'9'||ms>360000u) { send_text("ERR STREAM_MS\r\n");return; }
      ms=ms*10u+(uint32_t)(*s++-'0');
    }
    if(ms>3600000u) { send_text("ERR STREAM_MS\r\n");return; }
    if(!adc_enabled||adc_fault||clock_fault||selector_fault) { send_text("ERR ADC_OR_CLOCK_FAULT\r\n");return; }
    send_text("OK STREAM\r\n");
    if(!begin_stream(ms)) send_text("ERR START\r\n");
  } else if(!strncmp(cmd,"THRESHOLD ",10)) {
    uint32_t threshold=0;const char *s=cmd+10;
    while(*s) {
      if(*s<'0'||*s>'9'||threshold>4095u) {send_text("ERR THRESHOLD\r\n");return;}
      threshold=threshold*10u+(uint32_t)(*s++-'0');
    }
    if(threshold<1 || threshold>2048) {send_text("ERR THRESHOLD\r\n");return;}
    selection_threshold=threshold;info();
  } else if(!strcmp(cmd,"ADC OFF")) { adc_enable(ADC1,FALSE);adc_enabled=0;info(); }
  else if(!strcmp(cmd,"ADC ON")) { init_adc();info(); }
  else if(!strcmp(cmd,"REBOOT")) {send_text("OK REBOOT\r\n");usb_delay_ms(50);NVIC_SystemReset();}
  else if(!strcmp(cmd,"STOP")) send_text("OK IDLE\r\n");
  else if(!strcmp(cmd,"HELP")) send_text("INFO PING STREAM milliseconds(0=until_STOP) STOP ADC OFF ADC ON REBOOT\r\n");
  else send_text("ERR UNKNOWN_COMMAND\r\n");
}

/* Test the actual ARM SIMD implementation before allowing acquisition.
 * Runs with DMA disabled and leaves the selector reset at stream start. */
static void selector_selftest(void) {
  for(uint32_t trial=0;trial<12;trial++) {
    uint32_t lo=4095,hi=0;
    for(uint32_t i=0;i<SELECT_BLOCK;i++) {
      uint32_t v=(i*73u+trial*157u)&4095u;
      if(trial==0)v=2048;
      if(trial==1)v=(i&1)?4095:0;
      if(trial==2)v=(i&1)?0:4095;
      if(trial==3)v=i==SELECT_BLOCK/2-1?1900:2048;
      samples[i]=(uint16_t)v;
      if(v<lo)lo=v;
      if(v>hi)hi=v;
    }
    selector_init(&selector,20);
    uint32_t hit=selector_scan(&selector,(const uint16_t*)samples);
    if(hit!=(hi-lo>=20) || selector.history_max[0]!=hi || selector.history_min[0]!=lo ||
       selector.clipped_blocks!=(lo==0||hi==4095))selector_fault|=1u<<trial;
    for(uint32_t i=0;i<SELECT_BLOCK;i++)
      if(selector.history[0][i]!=samples[i])selector_fault|=1u<<trial;
  }
}

int main(void) {
  init_clock_gpio_usb();usb_delay_ms(200);init_adc();init_acquisition();selector_selftest();
  uint8_t rx[64];char line[64];unsigned used=0;int overflow=0;
  for(;;) {
    if(!connected()) {
      if(stream_active) halt_sampling(ERR_USB);
      stream_active=0;qhead=qtail=tx_active=0;used=0;overflow=0;
      continue;
    }
    if(stream_active) {
      pump_tx();pump_adc();pump_end();pump_tx();
      if(sampling && tick_ms-irq_ms[(completed-1u)&1u]>20 && completed) halt_sampling(ERR_TIMEOUT);
      if(sampling && !completed && tick_ms-start_ms>20) halt_sampling(ERR_TIMEOUT);
    }
    uint16_t n=usb_vcp_get_rxdata(&usb.dev,rx);
    for(unsigned i=0;i<n;i++) {
      char c=(char)rx[i];
      if(c=='\n'||c=='\r') {
        if(overflow) { if(stream_active) halt_sampling(ERR_INPUT);else send_text("ERR LINE_TOO_LONG\r\n"); }
        else if(used) {line[used]=0;command(line);}
        used=0;overflow=0;
      } else if(!overflow) {
        if(used<sizeof(line)-1) line[used++]=c;else overflow=1;
      }
    }
  }
}
