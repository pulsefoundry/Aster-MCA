/* Aster Nano AT32 v0.6.3: 4 MS/s continuous DMA, 2048-bin on-board spectrum.
 * Acquisition has no bulk IN transfers; send the frozen result only at end.
 * Clock and analog configuration are unchanged from verified v0.5.0. */
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
#include "engine.h"
#define SAMPLE_COUNT 8192u
#define BLOCK 4096u
#define FW_VERSION "0.6.3"
static otg_core_type usb;
static volatile uint32_t tick_ms,led_edges;
static volatile uint16_t samples[SAMPLE_COUNT] __attribute__((aligned(4)));
static struct {uint32_t before;uint16_t data[BLOCK];uint32_t after;} snapshot_storage __attribute__((aligned(4)));
#define snapshot snapshot_storage.data
static histogram_t hist;
static char reply[2048];
static uint8_t tx_packet[64] __attribute__((aligned(4)));
static uint32_t adc_fault,adc_enabled,clock_fault,bist_fault,bist_max_cycles;
static uint32_t copy_bist_cycles;
static adc_sampletime_select_type sample_setting=ADC_SAMPLETIME_2_5;
extern cdc_struct_type cdc_struct;
#include "platform.inc"
enum {ERR_DMA=1,ERR_ADC=2,ERR_IRQ=4,ERR_DEADLINE=8,ERR_ENGINE=16,
      ERR_USB=32,ERR_INPUT=64,ERR_TIMEOUT=128};
static volatile uint32_t sampling,completed,stop_request,errors,tail_samples;
static volatile uint32_t last_irq,irq_min,irq_max,stop_ms,stop_cycles;
static uint32_t processed,active,has_result,session,requested_ms,limit_blocks;
static uint32_t start_ms,start_cycles,process_max,latency_max;
static uint32_t peak_fine_blocks,peak_candidates;
static uint32_t copy_max,copy_end_max;

static FAST void halt_sampling(uint32_t error) {
  uint32_t mask=__get_PRIMASK();__disable_irq();
  TMR3->ctrl1_bit.tmren=FALSE;ADC1->ctrl2_bit.ocete=ADC_ORDINARY_TRIG_EDGE_NONE;
  dma_channel_enable(DMA1_CHANNEL1,FALSE);
  if(sampling) {
    uint32_t pos=(SAMPLE_COUNT-dma_data_number_get(DMA1_CHANNEL1))%SAMPLE_COUNT;
    tail_samples=(pos-(completed&1u)*BLOCK+SAMPLE_COUNT)%SAMPLE_COUNT;
    stop_ms=tick_ms;stop_cycles=DWT->CYCCNT;
  }
  errors|=error;sampling=0;dma_flag_clear(DMA1_GL1_FLAG);
  __DMB();__set_PRIMASK(mask);
}

FAST void DMA1_Channel1_IRQHandler(void) {
  uint32_t flags=DMA1->sts,expected=(completed&1u)?DMA1_FDT1_FLAG:DMA1_HDT1_FLAG;
  if(!sampling) {dma_flag_clear(DMA1_GL1_FLAG);return;}
  if(flags&DMA1_DTERR1_FLAG) {halt_sampling(ERR_DMA);return;}
  if(ADC1->sts_bit.occo) {halt_sampling(ERR_ADC);return;}
  if((flags&(DMA1_HDT1_FLAG|DMA1_FDT1_FLAG))!=expected) {halt_sampling(ERR_IRQ);return;}
  dma_flag_clear(expected);uint32_t now=DWT->CYCCNT;
  if(completed) {uint32_t dt=now-last_irq;if(dt<irq_min)irq_min=dt;if(dt>irq_max)irq_max=dt;}
  last_irq=now;__DMB();++completed;
  if(stop_request || completed>=limit_blocks)halt_sampling(0);
}

static int begin_acquire(uint32_t ms,uint32_t threshold) {
  if(!adc_enabled||adc_fault||clock_fault||bist_fault)return 0;
  halt_sampling(0);adc_conversion_stop(ADC1);uint32_t t=tick_ms;
  while(adc_conversion_stop_status_get(ADC1))if(tick_ms-t>100) {adc_fault=4;return 0;}
  dma_reset(DMA1_CHANNEL1);NVIC_ClearPendingIRQ(DMA1_Channel1_IRQn);
  dma_init_type cfg;dma_default_para_init(&cfg);
  cfg.buffer_size=SAMPLE_COUNT;cfg.direction=DMA_DIR_PERIPHERAL_TO_MEMORY;
  cfg.memory_base_addr=(uint32_t)samples;cfg.memory_data_width=DMA_MEMORY_DATA_WIDTH_HALFWORD;
  cfg.memory_inc_enable=TRUE;cfg.peripheral_base_addr=(uint32_t)&ADC1->odt;
  cfg.peripheral_data_width=DMA_PERIPHERAL_DATA_WIDTH_HALFWORD;cfg.peripheral_inc_enable=FALSE;
  cfg.priority=DMA_PRIORITY_VERY_HIGH;cfg.loop_mode_enable=TRUE;
  dma_init(DMA1_CHANNEL1,&cfg);dma_flag_clear(DMA1_GL1_FLAG);
  dma_interrupt_enable(DMA1_CHANNEL1,DMA_HDT_INT|DMA_FDT_INT|DMA_DTERR_INT,TRUE);
  tmr_primary_mode_select(TMR3,TMR_PRIMARY_SEL_RESET);tmr_base_init(TMR3,35,0);
  tmr_counter_value_set(TMR3,0);tmr_flag_clear(TMR3,TMR_OVF_FLAG);
  tmr_primary_mode_select(TMR3,TMR_PRIMARY_SEL_OVERFLOW);
  adc_enable(ADC1,FALSE);(void)adc_ordinary_conversion_data_get(ADC1);
  adc_flag_clear(ADC1,ADC_OCCE_FLAG|ADC_OCCO_FLAG|ADC_RDY_FLAG);adc_enable(ADC1,TRUE);t=tick_ms;
  while(adc_flag_get(ADC1,ADC_RDY_FLAG)==RESET)if(tick_ms-t>100) {adc_fault=1;return 0;}
  histogram_init(&hist,threshold);requested_ms=ms;
  limit_blocks=(uint32_t)(((uint64_t)ms*4000u+BLOCK-1u)/BLOCK);
  completed=processed=stop_request=errors=tail_samples=process_max=latency_max=irq_max=0;
  peak_fine_blocks=peak_candidates=0;
  copy_max=copy_end_max=0;
  irq_min=UINT32_MAX;has_result=0;++session;active=sampling=1;
  dma_channel_enable(DMA1_CHANNEL1,TRUE);
  adc_ordinary_conversion_trigger_set(ADC1,ADC_ORDINARY_TRIG_TMR3TRGOUT,ADC_ORDINARY_TRIG_EDGE_RISING);
  start_ms=tick_ms;start_cycles=DWT->CYCCNT;__DMB();TMR3->ctrl1_bit.tmren=TRUE;return 1;
}

/* Fixed-size, word-aligned SRAM copy. Prevent the compiler from replacing a
 * C loop with the byte-at-a-time Flash-resident nano-libc memcpy. Interrupts
 * remain enabled; the caller checks DMA ownership after the copy. */
static FAST void snapshot_copy(const volatile uint16_t *source) {
  uint16_t *destination=snapshot;
  uint32_t chunks=BLOCK/8u;
  __asm__ volatile(
    "1:\n\t"
    "ldmia %[source]!, {r2, r3, r4, r5}\n\t"
    "stmia %[destination]!, {r2, r3, r4, r5}\n\t"
    "subs %[chunks], %[chunks], #1\n\t"
    "bne 1b\n\t"
    : [source] "+&r"(source),[destination] "+&r"(destination),[chunks] "+&r"(chunks)
    : : "r2","r3","r4","r5","cc","memory");
}

static FAST void pump_adc(void) {
  uint32_t ready=completed;
  if(processed==ready)return;
  if(errors) {processed=ready;return;}
  if(ready!=processed+1u) {halt_sampling(ERR_DEADLINE);processed=ready;return;}
  uint32_t half=processed&1u,irq=last_irq,begin=DWT->CYCCNT,latency=begin-irq;
  uint32_t fine_before=hist.fine_blocks,candidates_before=hist.candidates;
  if(latency>latency_max)latency_max=latency;
  /* Only this copy must finish before DMA overwrites the completed half.
   * Processing owns a stable snapshot and can use slack in the following
   * half-period. A backlog of two completed halves remains a hard error. */
  snapshot_copy(samples+half*BLOCK);
  __DMB();uint32_t copied=DWT->CYCCNT,copy_cycles=copied-begin,copy_end=copied-irq;
  if(copy_cycles>copy_max)copy_max=copy_cycles;
  if(copy_end>copy_end_max)copy_end_max=copy_end;
  uint32_t pos=(SAMPLE_COUNT-dma_data_number_get(DMA1_CHANNEL1))%SAMPLE_COUNT;
  if(completed!=ready || copy_end>=BLOCK*36u || (sampling && pos/BLOCK==half)) {
    halt_sampling(ERR_DEADLINE);processed=completed;return;
  }
  for(unsigned off=0;off<BLOCK;off+=64)histogram_feed(&hist,snapshot+off);
  uint32_t cycles=DWT->CYCCNT-begin;if(cycles>process_max) {
    process_max=cycles;peak_fine_blocks=hist.fine_blocks-fine_before;
    peak_candidates=hist.candidates-candidates_before;
  }
  ++processed;if(hist.fault)halt_sampling(ERR_ENGINE);
}

static uint32_t crc32(const void *p,uint32_t n) {
  const uint8_t *b=p;uint32_t crc=~0u;
  while(n--) {crc^=*b++;for(unsigned i=0;i<8;i++)crc=(crc>>1)^(0xedb88320u&(0u-(crc&1u)));}
  return ~crc;
}
static void send_result(void) {
  int n=snprintf(reply,sizeof(reply),
    "{\"type\":\"spectrum\",\"fw\":\"0.6.3\",\"method\":\"mcu-area8-4M-v0.1\","
    "\"session\":%lu,\"requested_ms\":%lu,\"threshold_codes\":%lu,\"channels\":2048,"
    "\"sample_rate_hz\":4000000,\"core_hz\":144000000,\"bin_width_code_us\":1,"
    "\"blocks\":%lu,\"processed_blocks\":%lu,\"engine_blocks\":%lu,\"fine_blocks\":%lu,"
    "\"errors\":%lu,\"adc_overrun\":%lu,\"tail_samples_excluded\":%lu,\"stop_user\":%lu,"
    "\"acquisition_ms\":%lu,\"span_cycles_mod32\":%lu,\"irq_delta_min\":%lu,\"irq_delta_max\":%lu,"
    "\"process_max_cycles\":%lu,\"latency_max_cycles\":%lu,\"candidates\":%lu,\"accepted\":%lu,"
    "\"peak_fine_blocks\":%lu,\"peak_candidates\":%lu,"
    "\"snapshot_samples\":4096,\"copy_max_cycles\":%lu,\"copy_end_max_cycles\":%lu,"
    "\"rejected\":%lu,\"underflow\":%lu,\"overflow\":%lu,\"pending_excluded\":%lu,"
    "\"rejection_flags\":[%lu,%lu,%lu,%lu,%lu],\"minimum\":%lu,\"maximum\":%lu,\"histogram_crc32\":%lu}\r\n",
    (unsigned long)session,(unsigned long)requested_ms,(unsigned long)hist.threshold,
    (unsigned long)completed,(unsigned long)processed,(unsigned long)hist.blocks,(unsigned long)hist.fine_blocks,
    (unsigned long)errors,(unsigned long)ADC1->sts_bit.occo,(unsigned long)tail_samples,(unsigned long)stop_request,
    (unsigned long)(stop_ms-start_ms),(unsigned long)(last_irq-start_cycles),
    (unsigned long)(completed>1?irq_min:0),(unsigned long)irq_max,
    (unsigned long)process_max,(unsigned long)latency_max,(unsigned long)hist.candidates,(unsigned long)hist.accepted,
    (unsigned long)peak_fine_blocks,(unsigned long)peak_candidates,
    (unsigned long)copy_max,(unsigned long)copy_end_max,
    (unsigned long)hist.rejected,(unsigned long)hist.underflow,(unsigned long)hist.overflow,(unsigned long)hist.active,
    (unsigned long)hist.reasons[0],(unsigned long)hist.reasons[1],(unsigned long)hist.reasons[2],
    (unsigned long)hist.reasons[3],(unsigned long)hist.reasons[4],(unsigned long)hist.minimum,(unsigned long)hist.maximum,
    (unsigned long)crc32(hist.histogram,sizeof(hist.histogram)));
  if(n<0 || (unsigned)n>=sizeof(reply)) {send_text("ERR RESULT_SIZE\r\n");return;}
  uint32_t header_crc=crc32(reply,(uint32_t)n);
  if(!send_bytes(reply,(uint32_t)n) || !send_bytes(hist.histogram,sizeof(hist.histogram)))return;
  snprintf(reply,sizeof(reply),"\r\nEND %08lx\r\n",(unsigned long)header_crc);send_text(reply);
}

static void info(void) {
  snprintf(reply,sizeof(reply),"{\"type\":\"info\",\"board\":\"Aster MCA Nano AT32 v0.3\","
    "\"mcu\":\"AT32F423CCT7\",\"fw\":\"0.6.3\",\"method\":\"onboard_histogram\","
    "\"core_hz\":%lu,\"adc_hz\":72000000,\"sample_rate_hz\":4000000,\"timer_ticks\":36,"
    "\"sample_cycles_x2\":5,\"channels\":2048,\"dma_samples\":8192,\"snapshot_samples\":4096,\"ldo_mv\":1300,"
    "\"adc_on\":%lu,\"adc_fault\":%lu,\"clock_fault\":%lu,\"bist_fault\":%lu,\"xtest\":%lu,"
    "\"session\":%lu,\"last_errors\":%lu,\"bist_max_cycles\":%lu,\"has_result\":%lu,\"copy_bist_cycles\":%lu}\r\n",
    (unsigned long)system_core_clock,(unsigned long)adc_enabled,(unsigned long)adc_fault,
    (unsigned long)clock_fault,(unsigned long)bist_fault,(unsigned long)ADC1->misc_bit.xtest,
    (unsigned long)session,(unsigned long)errors,(unsigned long)bist_max_cycles,(unsigned long)has_result,(unsigned long)copy_bist_cycles);
  send_text(reply);
}
static void command(const char *cmd) {
  if(active) {if(!strcmp(cmd,"STOP"))stop_request=1;return;}
  if(!strcmp(cmd,"INFO"))info();
  else if(!strcmp(cmd,"PING"))send_text("PONG\r\n");
  else if(!strncmp(cmd,"ACQUIRE ",8)) {
    uint32_t fields[2]={0,0};unsigned field=0,digits=0;int invalid=0;
    for(const char *p=cmd+8;*p;p++) {
      if(*p==' ' && field==0 && digits) {field=1;digits=0;continue;}
      if(*p<'0'||*p>'9'||fields[field]>360000u) {invalid=1;break;}
      fields[field]=fields[field]*10u+(uint32_t)(*p-'0');++digits;
    }
    uint32_t ms=fields[0],threshold=fields[1];
    if(invalid || field!=1 || !digits || ms<1 || ms>3600000 || threshold<1 || threshold>2048) {
      send_text("ERR ACQUIRE_MS_THRESHOLD\r\n");return;
    }
    if(!adc_enabled||adc_fault||clock_fault||bist_fault) {send_text("ERR DEVICE_FAULT\r\n");return;}
    snprintf(reply,sizeof(reply),"OK ACQUIRE %lu %lu\r\n",(unsigned long)ms,(unsigned long)(session+1u));send_text(reply);
    if(!begin_acquire((uint32_t)ms,(uint32_t)threshold))send_text("ERR START\r\n");
  } else if(!strcmp(cmd,"RESULT")) {if(has_result)send_result();else send_text("ERR NO_RESULT\r\n");}
  else if(!strcmp(cmd,"STOP")) { /* A late STOP must not append text to a completed result. */ }
  else if(!strcmp(cmd,"REBOOT")) {send_text("OK REBOOT\r\n");usb_delay_ms(50);NVIC_SystemReset();}
  else send_text("ERR UNKNOWN_COMMAND\r\n");
}

static void selftest(void) {
  for(unsigned trial=0;trial<4;trial++) {
    for(unsigned i=0;i<SAMPLE_COUNT;i++)samples[i]=(i*73u+trial*137u)&4095u;
    snapshot_storage.before=0x1234abcd;snapshot_storage.after=0x9876fedc;
    const volatile uint16_t *source=samples+(trial&1u)*BLOCK;
    uint32_t begin=DWT->CYCCNT;snapshot_copy(source);uint32_t elapsed=DWT->CYCCNT-begin;
    if(elapsed>copy_bist_cycles)copy_bist_cycles=elapsed;
    for(unsigned i=0;i<BLOCK;i++)if(snapshot[i]!=source[i])bist_fault|=8u;
    if(snapshot_storage.before!=0x1234abcd || snapshot_storage.after!=0x9876fedc)bist_fault|=8u;
  }
  for(unsigned trial=0;trial<12;trial++) {
    uint32_t lo=4095,hi=0;
    for(unsigned i=0;i<64;i++) {uint16_t v=(i*73u+trial*157u)&4095u;
      if(trial==0)v=2048;
      if(trial==1)v=(i&1u)?4095:0;
      if(trial==2)v=(i&1u)?0:4095;
      samples[i]=v;if(v<lo)lo=v;if(v>hi)hi=v;}
    histogram_init(&hist,20);uint32_t hit=histogram_copy(&hist,(const uint16_t*)samples);
    if(hit!=(hi-lo>=20)||hist.minimum!=lo||hist.maximum!=hi)bist_fault|=1u;
    for(unsigned i=0;i<64;i++)if(hist.ring[i]!=samples[i])bist_fault|=2u;
  }
  for(unsigned trial=0;trial<2;trial++) {
    for(unsigned i=0;i<BLOCK;i++)samples[i]=2048;
    if(trial)for(unsigned p=512;p<3072;p+=1024) {
      samples[p]=2000;samples[p+1]=1900;samples[p+2]=1800;samples[p+3]=1900;samples[p+4]=2000;
    }
    histogram_init(&hist,20);uint32_t begin=DWT->CYCCNT;
    for(unsigned i=0;i<BLOCK;i+=64)histogram_feed(&hist,(const uint16_t*)(samples+i));
    uint32_t elapsed=DWT->CYCCNT-begin;if(elapsed>bist_max_cycles)bist_max_cycles=elapsed;
    if(hist.candidates!=(trial?3u:0u)||hist.accepted!=(trial?3u:0u)||hist.histogram[160]!=(trial?3u:0u)||hist.fault)bist_fault|=4u;
  }
  histogram_init(&hist,20);
}
int main(void) {
  init_clock_gpio_usb();usb_delay_ms(200);if(!clock_fault)init_adc();init_acquisition();selftest();
  uint8_t rx[64];char line[64];unsigned used=0;int overflow=0;
  for(;;) {
    if(!connected()) {if(active)halt_sampling(ERR_USB);used=0;overflow=0;continue;}
    if(active) {
      pump_adc();
      if(sampling && !completed && tick_ms-start_ms>20)halt_sampling(ERR_TIMEOUT);
      /* Millisecond watchdog independent of the requested acquisition length. */
      static uint32_t observed=0,seen_ms=0;
      if(completed!=observed || !completed) {observed=completed;seen_ms=tick_ms;}
      else if(sampling && tick_ms-seen_ms>20)halt_sampling(ERR_TIMEOUT);
      if(!sampling && processed==completed) {active=0;has_result=1;send_result();}
    }
    uint16_t n=usb_vcp_get_rxdata(&usb.dev,rx);
    for(unsigned i=0;i<n;i++) {char c=(char)rx[i];
      if(c=='\n'||c=='\r') {
        if(overflow) {if(active)halt_sampling(ERR_INPUT);else send_text("ERR LINE_TOO_LONG\r\n");}
        else if(used) {line[used]=0;command(line);}
        used=0;overflow=0;
      } else if(!overflow) {if(used<sizeof(line)-1)line[used++]=c;else overflow=1;}
    }
  }
}
