/* Aster Nano AT32 v0.7.1: raw event windows and 500000 B/s ADC/USB benchmark. */
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
#include "frame.h"
#define SAMPLE_COUNT 8192u
#define BLOCK 4096u
#define FW_VERSION "0.7.1"
static otg_core_type usb;
static volatile uint32_t tick_ms,led_edges;
static volatile uint16_t samples[SAMPLE_COUNT] __attribute__((aligned(4)));
static struct {uint32_t before;uint16_t data[BLOCK];uint32_t after;} snapshot_storage __attribute__((aligned(4)));
#define snapshot snapshot_storage.data
static event_engine engine;
/* Command replies and the final frame never overlap: the stream is drained
 * before send_end, and incoming commands are handled in the same main loop. */
static char reply[2048] __attribute__((aligned(4)));
#define terminal ((uint8_t *)reply)
static uint8_t tx_packet[64] __attribute__((aligned(4)));
static uint32_t adc_fault,adc_enabled,clock_fault,bist_fault,bist_max_cycles,copy_bist_cycles,packet_bist_cycles;
static adc_sampletime_select_type sample_setting=ADC_SAMPLETIME_2_5;
extern cdc_struct_type cdc_struct;
#include "platform.inc"
enum {ERR_DMA=1,ERR_ADC=2,ERR_IRQ=4,ERR_DEADLINE=8,ERR_QUEUE=16,ERR_USB=32,ERR_INPUT=64,ERR_TIMEOUT=128,ERR_ENGINE=256};
#define QCOUNT 8u
#define HEADER 64u
#define FRAME_CAPACITY (HEADER+EVENT_N*2u+4u)
typedef struct {uint32_t len;uint8_t data[FRAME_CAPACITY];} packet_t;
static packet_t queue[QCOUNT];
static uint32_t qhead,qtail,queue_high,tx_active,tx_started_ms,wire_bytes,payload_bytes;
static volatile uint32_t sampling,completed,stop_request,errors,tail_samples;
static volatile uint32_t last_irq,irq_min,irq_max,stop_ms,stop_cycles;
static uint32_t processed,active,has_result,session,requested_ms,limit_blocks,mode;
static uint32_t start_ms,start_cycles,process_max,latency_max,copy_max,copy_end_max;

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
  event_init(&engine,threshold);requested_ms=ms;
  qhead=qtail=queue_high=tx_active=wire_bytes=payload_bytes=0;
  limit_blocks=(uint32_t)(((uint64_t)ms*4000u+BLOCK-1u)/BLOCK);
  completed=processed=stop_request=errors=tail_samples=process_max=latency_max=irq_max=0;
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

static inline uint32_t frame(uint8_t *data,uint32_t kind,uint32_t seq,uint32_t first,
                      uint32_t trigger,uint32_t baseline,uint32_t length) {
  return wire_frame(data,kind,session,seq,first,trigger,baseline,length,engine.threshold,errors);
}
static FAST void pump_tx(void) {
  if(tx_active) {
    if(!cdc_struct.g_tx_completed) {
      if(tick_ms-tx_started_ms>1000)halt_sampling(ERR_USB);
      return;
    }
    wire_bytes+=queue[qtail%QCOUNT].len;payload_bytes+=EVENT_N*2u;
    ++qtail;tx_active=0;
  }
  if(qtail<qhead) {
    packet_t *p=&queue[qtail%QCOUNT];
    if(usb_vcp_send_data(&usb.dev,p->data,(uint16_t)p->len)!=SUCCESS)halt_sampling(ERR_USB);
    else {tx_active=1;tx_started_ms=tick_ms;}
  }
}
static FAST void prepare_packet(packet_t *p,uint32_t kind,uint32_t seq,
    uint32_t first,uint32_t trigger,uint32_t baseline,const uint16_t *data,uint32_t ring_first) {
  uint16_t *dest=(uint16_t *)(void *)(p->data+HEADER);
  if(kind==1)for(unsigned i=0;i<EVENT_N;i++)dest[i]=data[(ring_first+i)&1023u];
  else for(unsigned i=0;i<EVENT_N;i++)dest[i]=data[i];
  p->len=frame(p->data,kind,seq,first,trigger,baseline,EVENT_N*2u);
}
static FAST int enqueue(uint32_t kind,uint32_t first,uint32_t trigger,uint32_t baseline,
                   const uint16_t *data,uint32_t ring_first) {
  pump_tx();if(qhead-qtail>=QCOUNT) {halt_sampling(ERR_QUEUE);return 0;}
  packet_t *p=&queue[qhead%QCOUNT];
  prepare_packet(p,kind,qhead,first,trigger,baseline,data,ring_first);
  __DMB();++qhead;if(qhead-qtail>queue_high)queue_high=qhead-qtail;
  pump_tx();return !errors;
}
static FAST int emit_event(void *unused,uint32_t trigger,uint32_t baseline,
                       const uint16_t *ring,uint32_t ring_first) {
  (void)unused;return enqueue(1,trigger-EVENT_PRE,trigger,baseline,ring,ring_first);
}
static FAST void pump_adc(void) {
  uint32_t ready=completed;if(processed==ready)return;
  if(errors) {processed=ready;return;}
  if(ready!=processed+1u) {halt_sampling(ERR_DEADLINE);processed=ready;return;}
  uint32_t half=processed&1u,irq=last_irq,begin=DWT->CYCCNT,latency=begin-irq;
  if(latency>latency_max)latency_max=latency;
  snapshot_copy(samples+half*BLOCK);
  __DMB();uint32_t copied=DWT->CYCCNT,copy_cycles=copied-begin,copy_end=copied-irq;
  if(copy_cycles>copy_max)copy_max=copy_cycles;
  if(copy_end>copy_end_max)copy_end_max=copy_end;
  uint32_t pos=(SAMPLE_COUNT-dma_data_number_get(DMA1_CHANNEL1))%SAMPLE_COUNT;
  if(completed!=ready || copy_end>=BLOCK*36u || (sampling && pos/BLOCK==half)) {
    halt_sampling(ERR_DEADLINE);processed=completed;return;
  }
  for(unsigned off=0;off<BLOCK;off+=64) {
    if(mode==1) { /* deliberate 6.25% window coverage; no event selection */
      event_copy(&engine,snapshot+off);++engine.blocks;
    } else if(!event_feed(&engine,snapshot+off,emit_event,0)) {halt_sampling(ERR_ENGINE);break;}
    pump_tx();
    if(errors)break;
  }
  if(mode==1 && !(processed&1u) && !errors)
    enqueue(2,processed*BLOCK,UINT32_MAX,0,snapshot,0);
  if(engine.fault)halt_sampling(ERR_ENGINE);
  uint32_t cycles=DWT->CYCCNT-begin;if(cycles>process_max)process_max=cycles;
  ++processed;
}
static void send_end(void) {
  int n=snprintf((char*)terminal+HEADER,sizeof(reply)-HEADER-8,
    "{\"type\":\"end\",\"fw\":\"0.7.1\",\"session\":%lu,\"mode\":%lu,\"errors\":%lu,"
    "\"requested_ms\":%lu,\"blocks\":%lu,\"processed_blocks\":%lu,\"engine_blocks\":%lu,"
    "\"fine_blocks\":%lu,\"packets\":%lu,\"payload_bytes\":%lu,\"wire_bytes\":%lu,"
    "\"candidates\":%lu,\"emitted\":%lu,\"pending_excluded\":%lu,\"holdoff_crossings\":%lu,"
    "\"queue_high\":%lu,\"threshold\":%lu,\"minimum\":%lu,\"maximum\":%lu,"
    "\"process_max_cycles\":%lu,\"copy_max_cycles\":%lu,\"copy_end_max_cycles\":%lu,"
    "\"latency_max_cycles\":%lu,\"irq_min\":%lu,\"irq_max\":%lu,\"span_cycles_mod32\":%lu,"
    "\"acquisition_ms\":%lu,\"tail_samples_excluded\":%lu,\"stop_user\":%lu,\"adc_overrun\":%lu}",
    (unsigned long)session,(unsigned long)mode,(unsigned long)errors,(unsigned long)requested_ms,
    (unsigned long)completed,(unsigned long)processed,(unsigned long)engine.blocks,(unsigned long)engine.fine_blocks,
    (unsigned long)qtail,(unsigned long)payload_bytes,(unsigned long)wire_bytes,
    (unsigned long)engine.candidates,(unsigned long)engine.emitted,(unsigned long)(engine.head-engine.tail),
    (unsigned long)engine.holdoff_crossings,(unsigned long)queue_high,(unsigned long)engine.threshold,
    (unsigned long)engine.minimum,(unsigned long)engine.maximum,(unsigned long)process_max,
    (unsigned long)copy_max,(unsigned long)copy_end_max,(unsigned long)latency_max,
    (unsigned long)(completed>1?irq_min:0),(unsigned long)irq_max,(unsigned long)(last_irq-start_cycles),
    (unsigned long)(stop_ms-start_ms),(unsigned long)tail_samples,(unsigned long)stop_request,
    (unsigned long)ADC1->sts_bit.occo);
  if(n<0 || (unsigned)n>=sizeof(reply)-HEADER-8) {send_text("ERR END_SIZE\r\n");return;}
  uint32_t length=frame(terminal,3,qtail,completed*BLOCK,UINT32_MAX,0,(uint32_t)n);
  send_bytes(terminal,length);
}
static void info(void) {
  snprintf(reply,sizeof(reply),
    "{\"type\":\"info\",\"fw\":\"0.7.1\",\"board\":\"Aster MCA Nano AT32 v0.3\","
    "\"mcu\":\"AT32F423CCT7\",\"core_hz\":%lu,\"adc_hz\":72000000,\"sample_rate_hz\":4000000,"
    "\"ldo_mv\":1300,\"dma_samples\":8192,\"snapshot_samples\":4096,\"event_samples\":512,"
    "\"pre_samples\":320,\"holdoff_samples\":64,\"queue_slots\":8,\"bench_payload_bps\":500000,"
    "\"adc_on\":%lu,\"adc_fault\":%lu,\"clock_fault\":%lu,\"bist_fault\":%lu,\"xtest\":%lu,"
    "\"session\":%lu,\"last_errors\":%lu,\"has_result\":%lu,\"bist_max_cycles\":%lu,\"copy_bist_cycles\":%lu,\"packet_bist_cycles\":%lu}\r\n",
    (unsigned long)system_core_clock,(unsigned long)adc_enabled,(unsigned long)adc_fault,
    (unsigned long)clock_fault,(unsigned long)bist_fault,(unsigned long)ADC1->misc_bit.xtest,
    (unsigned long)session,(unsigned long)errors,(unsigned long)has_result,
    (unsigned long)bist_max_cycles,(unsigned long)copy_bist_cycles,(unsigned long)packet_bist_cycles);
  send_text(reply);
}
static void command(const char *cmd) {
  if(active) {if(!strcmp(cmd,"STOP"))stop_request=1;return;}
  if(!strcmp(cmd,"INFO"))info();
  else if(!strncmp(cmd,"STREAM ",7)||!strncmp(cmd,"BENCH ",6)) {
    uint32_t fields[2]={0,0};unsigned field=0,digits=0;int invalid=0;
    uint32_t requested_mode=!strncmp(cmd,"BENCH ",6)?1:2;
    for(const char *p=cmd+(requested_mode==1?6:7);*p;p++) {
      if(*p==' ' && field==0 && digits) {field=1;digits=0;continue;}
      if(*p<'0'||*p>'9'||fields[field]>600000u) {invalid=1;break;}
      fields[field]=fields[field]*10u+(uint32_t)(*p-'0');++digits;
    }
    uint32_t ms=fields[0],threshold=fields[1];
    if(invalid||field!=1||!digits||ms<1||ms>600000||threshold<1||threshold>2048) {
      send_text("ERR PARAMETERS\r\n");return;
    }
    if(!adc_enabled||adc_fault||clock_fault||bist_fault) {send_text("ERR DEVICE_FAULT\r\n");return;}
    mode=requested_mode;
    snprintf(reply,sizeof(reply),"OK %s %lu %lu\r\n",mode==1?"BENCH":"STREAM",(unsigned long)ms,(unsigned long)(session+1));send_text(reply);
    if(!begin_acquire(ms,threshold))send_text("ERR START\r\n");
  } else if(!strcmp(cmd,"STOP")) {}
  else send_text("ERR UNKNOWN_COMMAND\r\n");
}
static uint32_t test_emitted;
static int test_emit(void *unused,uint32_t trigger,uint32_t baseline,const uint16_t *ring,uint32_t first) {
  (void)unused;++test_emitted;
  if(baseline!=2048u*256u || ring[(first+EVENT_PRE)&1023u]!=2000 || trigger<320)bist_fault|=4;
  return 1;
}
static int test_packet_emit(void *unused,uint32_t trigger,uint32_t baseline,const uint16_t *ring,uint32_t first) {
  (void)unused;
  packet_t *p=&queue[test_emitted%QCOUNT];
  prepare_packet(p,1,test_emitted,trigger-EVENT_PRE,trigger,baseline,ring,first);
  ++test_emitted;
  return 1;
}
static void selftest(void) {
  for(unsigned trial=0;trial<4;trial++) {
    for(unsigned i=0;i<SAMPLE_COUNT;i++)samples[i]=(i*73u+trial*137u)&4095u;
    snapshot_storage.before=0x1234abcd;snapshot_storage.after=0x9876fedc;
    const volatile uint16_t *source=samples+(trial&1u)*BLOCK;
    uint32_t begin=DWT->CYCCNT;snapshot_copy(source);uint32_t elapsed=DWT->CYCCNT-begin;
    if(elapsed>copy_bist_cycles)copy_bist_cycles=elapsed;
    for(unsigned i=0;i<BLOCK;i++)if(snapshot[i]!=source[i])bist_fault|=8;
    if(snapshot_storage.before!=0x1234abcd||snapshot_storage.after!=0x9876fedc)bist_fault|=8;
  }
  for(unsigned trial=0;trial<12;trial++) {
    uint32_t lo=4095,hi=0;
    for(unsigned i=0;i<64;i++) {uint16_t v=(i*73u+trial*157u)&4095u;
      if(trial==0)v=2048;
      if(trial==1)v=(i&1u)?4095:0;
      if(trial==2)v=(i&1u)?0:4095;
      samples[i]=v;if(v<lo)lo=v;if(v>hi)hi=v;}
    event_init(&engine,20);uint32_t hit=event_copy(&engine,(const uint16_t*)samples);
    if(hit!=(hi-lo>=20)||engine.minimum!=lo||engine.maximum!=hi)bist_fault|=1;
    for(unsigned i=0;i<64;i++)if(engine.ring[i]!=samples[i])bist_fault|=2;
  }
  for(unsigned trial=0;trial<2;trial++) {
    for(unsigned i=0;i<BLOCK;i++)samples[i]=2048;
    if(trial)for(unsigned p=512;p<3072;p+=1024) {
      samples[p]=2000;samples[p+1]=1900;samples[p+2]=1800;samples[p+3]=1900;samples[p+4]=2000;
    }
    event_init(&engine,20);test_emitted=0;uint32_t begin=DWT->CYCCNT;
    for(unsigned i=0;i<BLOCK;i+=64)event_feed(&engine,(const uint16_t*)(samples+i),test_emit,0);
    uint32_t elapsed=DWT->CYCCNT-begin;if(elapsed>bist_max_cycles)bist_max_cycles=elapsed;
    if(engine.candidates!=(trial?3u:0u)||test_emitted!=(trial?3u:0u)||engine.fault)bist_fault|=4;
  }
  /* Exercise real copies, header packing and checksums for four pulses in
   * one 1.024 ms block. USB interrupt load still requires an on-board run. */
  for(unsigned i=0;i<BLOCK;i++)samples[i]=2048;
  for(unsigned p=512;p<BLOCK-192;p+=1024) {
    samples[p]=2000;samples[p+1]=1900;samples[p+2]=1800;samples[p+3]=1900;samples[p+4]=2000;
  }
  event_init(&engine,20);test_emitted=0;uint32_t begin=DWT->CYCCNT;
  for(unsigned i=0;i<BLOCK;i+=64)event_feed(&engine,(const uint16_t*)(samples+i),test_packet_emit,0);
  packet_bist_cycles=DWT->CYCCNT-begin;
  if(test_emitted!=4 || engine.fault || packet_bist_cycles>=BLOCK*36u)bist_fault|=16;
  for(unsigned q=0;q<4;q++) {
    const uint16_t *dest=(const uint16_t *)(const void *)(queue[q].data+HEADER);
    if(queue[q].len!=1092 || dest[EVENT_PRE]!=2000)bist_fault|=16;
    for(unsigned i=0;i<EVENT_N;i++)if(dest[i]!=samples[192+q*1024+i])bist_fault|=16;
  }
  if(hash_bytes("hello",5)!=0x4f9f2cabu)bist_fault|=16;
  event_init(&engine,20);
}
int main(void) {
  init_clock_gpio_usb();usb_delay_ms(200);if(!clock_fault)init_adc();init_acquisition();selftest();
  uint8_t rx[64];char line[64];unsigned used=0;int overflow=0;
  uint32_t observed=0,seen_ms=0;
  for(;;) {
    if(!connected()) {if(active)halt_sampling(ERR_USB);used=0;overflow=0;continue;}
    if(active) {
      pump_adc();pump_tx();
      if(sampling&&!completed&&tick_ms-start_ms>20)halt_sampling(ERR_TIMEOUT);
      if(completed!=observed||!completed) {observed=completed;seen_ms=tick_ms;}
      else if(sampling&&tick_ms-seen_ms>20)halt_sampling(ERR_TIMEOUT);
      if(!sampling&&processed==completed&&qhead==qtail&&!tx_active) {
        active=0;has_result=1;send_end();
      }
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
