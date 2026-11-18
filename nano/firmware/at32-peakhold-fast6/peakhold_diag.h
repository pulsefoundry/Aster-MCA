/* Fixed-generator bench diagnostic. Not an event-pretrigger DMA MCA. */
#define PH_MAX 128u
typedef struct {
  uint32_t id, baseline, baseline_min, baseline_max, release_pedestal, dummy;
  uint32_t peak[4], first_read_cycles, last_read_cycles, reset_peak;
  uint32_t flags, wait_cycles, hold_level;
} ph_record;
_Static_assert(sizeof(ph_record)==64, "host frame size");
static ph_record ph_records[PH_MAX];
static volatile uint32_t ph_done, ph_hold_cycle, ph_retrigger;
static volatile uint32_t ph_fault;
static uint32_t ph_selftest, ph_dac_code, ph_base, ph_idle_peak;
static uint32_t ph_threshold_offset=40;
static uint32_t ph_ticks_us;
#define PH_RING_N 256u
#define PH_STEP ph_raw_step
static volatile uint16_t ph_ring[PH_RING_N] __attribute__((aligned(4)));
static volatile uint32_t ph_streaming,ph_stream_pos,ph_stream_stop_cycle,ph_hold_age;
static uint32_t ph_last_channel=255;
static volatile uint32_t ph_snapshot,ph_snapshot_done,ph_snapshot_end;
static uint32_t ph_snapshot_begin;
static uint32_t ph_previous_trigger,ph_have_previous,ph_busy_n,ph_busy_sum,ph_busy_min,ph_busy_max;
static uint32_t ph_stop_early=0;
static volatile uint32_t ph_trigger_hits,ph_trigger_ignored;
static uint32_t ph_stop_n,ph_stop_before_irq_n;
static int32_t ph_stop_min,ph_stop_max,ph_stop_sum;
static void ph_stream_stop(void);
static void ph_stream_start(void);

static void ph_idle(void) {
  tmr_sub_mode_select(TMR3,TMR_SUB_MODE_DIABLE);
  tmr_counter_enable(TMR3,FALSE);
  tmr_interrupt_enable(TMR3,TMR_C1_INT|TMR_TRIGGER_INT|TMR_C2_INT,FALSE);
  /* HOLD high before RESET high, including every error/timeout path. */
  tmr_output_channel_mode_select(TMR3,TMR_SELECT_CHANNEL_2,TMR_OUTPUT_CONTROL_FORCE_HIGH);
  __DSB();
  ph_stream_stop();
  gpio_bits_set(GPIOB,GPIO_PINS_0);
}

__attribute__((section(".ramfunc"))) void TMR3_GLOBAL_IRQHandler(void) {
  if(tmr_interrupt_flag_get(TMR3,TMR_C2_FLAG)==SET) {
    ph_hold_cycle=DWT->CYCCNT;
    ph_hold_age=tmr_counter_value_get(TMR3);
    ph_stream_stop();
    ph_retrigger=(tmr_flag_get(TMR3,TMR_C1_RECAPTURE_FLAG)==SET);
    tmr_interrupt_enable(TMR3,TMR_C1_INT|TMR_TRIGGER_INT|TMR_C2_INT,FALSE);
    tmr_sub_mode_select(TMR3,TMR_SUB_MODE_DIABLE);
    tmr_counter_enable(TMR3,FALSE);
    tmr_flag_clear(TMR3,TMR_C2_FLAG);
    __DMB(); ph_done=1;
  } else if(tmr_interrupt_flag_get(TMR3,TMR_TRIGGER_FLAG)==SET) {
    ++ph_trigger_hits;
    /* TRGIN event starts the slave timer; do not depend on C1 capture
     * interrupt, which was never observed in fast.3. Guard stale events. */
    if(!TMR3->ctrl1_bit.tmren) {
      ++ph_trigger_ignored;
      tmr_flag_clear(TMR3,TMR_TRIGGER_FLAG);
      return;
    }
    tmr_interrupt_enable(TMR3,TMR_TRIGGER_INT,FALSE);
    tmr_flag_clear(TMR3,TMR_TRIGGER_FLAG);
    ph_stream_stop();
    /* Preselect PEAK while TMR3 independently finishes the capture window. */
    if(!ph_fault) {
      adc_ordinary_channel_set(ADC1,ADC_CHANNEL_0,1,ph_peak_sample);
      ph_last_channel=0;
    }
  }
}

static inline __attribute__((always_inline)) uint16_t ph_adc(unsigned ch) {
  if(ph_fault || adc_fault || !adc_enabled) return 0xffff;
  if(ph_last_channel!=ch) {
    adc_ordinary_channel_set(ADC1,ch,1,ph_peak_sample);
    ph_last_channel=ch;
  }
  ADC1->sts=~(ADC_OCCE_FLAG|ADC_OCCO_FLAG);
  ADC1->ctrl2_bit.ocswtrg=TRUE;
  uint32_t begin=DWT->CYCCNT;
  while(!(ADC1->sts&ADC_OCCE_FLAG)) {
    if((uint32_t)(DWT->CYCCNT-begin)>system_core_clock/1000u) {
      ph_fault|=1; return 0xffff;
    }
  }
  return (uint16_t)ADC1->odt;
}

/* TMR2 is independent of the TMR3 HOLD gate. Default:144 ticks =1us.
 * DMA ring IRQs stay disabled; only its most recent pretrigger window is used. */
static void ph_stream_stop(void) {
  if(!ph_streaming)return;
  TMR2->ctrl1_bit.tmren=FALSE;
  ADC1->ctrl2_bit.ocete=ADC_ORDINARY_TRIG_EDGE_NONE;
  ADC1->ctrl2_bit.adabrt=TRUE;
  uint32_t t=DWT->CYCCNT;
  while(ADC1->ctrl2_bit.adabrt) {
    if(DWT->CYCCNT-t>system_core_clock/10000u) {ph_fault|=32;break;}
  }
  dma_channel_enable(DMA1_CHANNEL1,FALSE);
  ph_stream_pos=(PH_RING_N-dma_data_number_get(DMA1_CHANNEL1))&(PH_RING_N-1);
  ph_stream_stop_cycle=DWT->CYCCNT;
  if((DMA1->sts&DMA1_DTERR1_FLAG) || ADC1->sts_bit.occo)ph_fault|=64;
  adc_dma_mode_enable(ADC1,FALSE);
  dma_flag_clear(DMA1_GL1_FLAG);
  ph_streaming=0;ph_last_channel=255;
}

static int ph_dma_begin(volatile uint16_t *buffer,unsigned n,int circular,int snapshot) {
  TMR2->ctrl1_bit.tmren=FALSE;
  ADC1->ctrl2_bit.ocete=ADC_ORDINARY_TRIG_EDGE_NONE;
  ADC1->ctrl2_bit.adabrt=TRUE;
  uint32_t t=DWT->CYCCNT;
  while(ADC1->ctrl2_bit.adabrt) {
    if(DWT->CYCCNT-t>system_core_clock/10000u) {ph_fault|=32;return 0;}
  }
  dma_reset(DMA1_CHANNEL1);NVIC_ClearPendingIRQ(DMA1_Channel1_IRQn);
  dma_init_type cfg;dma_default_para_init(&cfg);
  cfg.buffer_size=n;cfg.direction=DMA_DIR_PERIPHERAL_TO_MEMORY;
  cfg.memory_base_addr=(uint32_t)buffer;cfg.memory_data_width=DMA_MEMORY_DATA_WIDTH_HALFWORD;
  cfg.memory_inc_enable=TRUE;cfg.peripheral_base_addr=(uint32_t)&ADC1->odt;
  cfg.peripheral_data_width=DMA_PERIPHERAL_DATA_WIDTH_HALFWORD;
  cfg.peripheral_inc_enable=FALSE;cfg.priority=DMA_PRIORITY_VERY_HIGH;
  cfg.loop_mode_enable=circular?TRUE:FALSE;
  dma_init(DMA1_CHANNEL1,&cfg);dma_flag_clear(DMA1_GL1_FLAG);
  dma_interrupt_enable(DMA1_CHANNEL1,DMA_HDT_INT|DMA_FDT_INT|DMA_DTERR_INT,FALSE);
  if(snapshot)dma_interrupt_enable(DMA1_CHANNEL1,DMA_HDT_INT|DMA_DTERR_INT,TRUE);
  adc_ordinary_channel_set(ADC1,ADC_CHANNEL_1,1,ADC_SAMPLETIME_2_5);
  ph_last_channel=255;
  adc_dma_mode_enable(ADC1,TRUE);adc_dma_request_repeat_enable(ADC1,TRUE);
  tmr_primary_mode_select(TMR2,TMR_PRIMARY_SEL_RESET);
  tmr_base_init(TMR2,PH_STEP-1,0);tmr_counter_value_set(TMR2,0);
  tmr_flag_clear(TMR2,TMR_OVF_FLAG);
  tmr_primary_mode_select(TMR2,TMR_PRIMARY_SEL_OVERFLOW);
  (void)ADC1->odt;ADC1->sts=~(ADC_OCCE_FLAG|ADC_OCCO_FLAG);
  adc_ordinary_conversion_trigger_set(ADC1,ADC_ORDINARY_TRIG_TMR2TRGOUT,ADC_ORDINARY_TRIG_EDGE_RISING);
  dma_channel_enable(DMA1_CHANNEL1,TRUE);
  __DMB();
  ph_snapshot_begin=DWT->CYCCNT;
  TMR2->ctrl1_bit.tmren=TRUE;
  return 1;
}

static void ph_stream_start(void) {
  if(!ph_dma_begin(ph_ring,PH_RING_N,1,0))return;
  ph_streaming=1;
  uint32_t t=DWT->CYCCNT;
  /* Prime >=96 samples. At4M:24us; at125k:768us. Baseline always uses
   * 32samples with an8sample guard; its time span changes with RAW rate. */
  while(PH_RING_N-dma_data_number_get(DMA1_CHANNEL1)<96) {
    if(DWT->CYCCNT-t>system_core_clock/1000u) {ph_fault|=128;ph_stream_stop();return;}
  }
}

__attribute__((section(".ramfunc"))) void DMA1_Channel1_IRQHandler(void) {
  if(!ph_snapshot) {dma_flag_clear(DMA1_GL1_FLAG);return;}
  TMR2->ctrl1_bit.tmren=FALSE;
  ph_snapshot_end=DWT->CYCCNT;
  ADC1->ctrl2_bit.ocete=ADC_ORDINARY_TRIG_EDGE_NONE;
  if(DMA1->sts&DMA1_DTERR1_FLAG)ph_fault|=64;
  if(!(DMA1->sts&DMA1_HDT1_FLAG))ph_fault|=128;
  dma_interrupt_enable(DMA1_CHANNEL1,DMA_HDT_INT|DMA_DTERR_INT,FALSE);
  dma_flag_clear(DMA1_GL1_FLAG);
  /* Late conversion may drain into the unused second half, never first half. */
  __DMB();ph_snapshot_done=1;
}

static void ph_pretrigger(ph_record *r) {
  uint32_t age=ph_hold_age+(ph_stream_stop_cycle-ph_hold_cycle);
  uint32_t post=(age+PH_STEP-1)/PH_STEP;
  uint32_t end=(ph_stream_pos-post-8)&(PH_RING_N-1);
  uint32_t total=0,lo=4095,hi=0;
  for(unsigned i=0;i<32;++i) {
    uint32_t v=ph_ring[(end-32+i)&(PH_RING_N-1)];total+=v;
    if(v<lo)lo=v;
    if(v>hi)hi=v;
  }
  r->baseline=(total+16)/32;r->baseline_min=lo;r->baseline_max=hi;
}

static uint32_t ph_mean(unsigned ch,unsigned n,uint32_t *lo,uint32_t *hi) {
  (void)ph_adc(ch); /* discard after each channel switch */
  uint32_t s=0,l=4095,h=0;
  for(unsigned i=0;i<n;++i) {
    uint32_t x=ph_adc(ch);s+=x;if(x<l)l=x;if(x>h)h=x;
  }
  if(lo)*lo=l;
  if(hi)*hi=h;
  return (s+n/2)/n;
}

static void ph_threshold(void) {
  ph_dac_code=ph_base+ph_threshold_offset;
  if(ph_dac_code<300)ph_dac_code=300;
  if(ph_dac_code>2000)ph_dac_code=2000;
  dac_1_data_set(DAC1_12BIT_RIGHT,(uint16_t)ph_dac_code);
  /* R113/C104 settle at least 1 ms after updating threshold. */
  usb_delay_ms(2);
}

static int ph_wait_trigger_low(uint32_t timeout_cycles) {
  uint32_t started=DWT->CYCCNT;
  for(;;) {
    /* Consume the low observation once. A separate post-loop GPIO read can
     * see the next pulse and falsely classify that new edge as stuck high. */
    if(gpio_input_data_bit_read(GPIOA,GPIO_PINS_6)==RESET)return 1;
    if((uint32_t)(DWT->CYCCNT-started)>=timeout_cycles)return 0;
  }
}

static void ph_prepare(unsigned window,int external,uint32_t *pedestal) {
  ph_idle();
  /* Every attempt owns a new completion flag, including failed preparation. */
  ph_done=ph_retrigger=0;
  usb_delay_us(2);
  gpio_bits_reset(GPIOB,GPIO_PINS_0); /* release reset, HOLD still high */
  usb_delay_us(1);
  if(pedestal) { (void)ph_adc(0); *pedestal=ph_adc(0); }
  if(external) {
    ph_stream_start();
    if(!ph_fault && !ph_wait_trigger_low(system_core_clock/100u))ph_fault|=256;
    if(ph_fault) {ph_idle();return;}
  }
  tmr_period_value_set(TMR3,(window+2)*ph_ticks_us-1);
  tmr_channel_value_set(TMR3,TMR_SELECT_CHANNEL_2,window*ph_ticks_us);
  tmr_counter_value_set(TMR3,0);
  tmr_flag_clear(TMR3,0xffff);
  NVIC_ClearPendingIRQ(TMR3_GLOBAL_IRQn);
  ph_done=ph_retrigger=0;
  tmr_interrupt_enable(TMR3,TMR_C2_INT,TRUE);
  /* Force low once, then latch HIGH on the compare match. Unlike PWM, it
   * stays high at wrap/stop; later input edges cannot reopen capture. */
  tmr_output_channel_mode_select(TMR3,TMR_SELECT_CHANNEL_2,TMR_OUTPUT_CONTROL_FORCE_LOW);
  tmr_output_channel_mode_select(TMR3,TMR_SELECT_CHANNEL_2,TMR_OUTPUT_CONTROL_HIGH);
  if(external) {
    tmr_sub_mode_select(TMR3,TMR_SUB_TRIGGER_MODE);
    if(ph_stop_early)tmr_interrupt_enable(TMR3,TMR_TRIGGER_INT,TRUE);
    uint32_t armed=DWT->CYCCNT;
    if(ph_have_previous) {
      uint32_t busy=armed-ph_previous_trigger;
      if(!ph_busy_n || busy<ph_busy_min)ph_busy_min=busy;
      if(busy>ph_busy_max)ph_busy_max=busy;
      ph_busy_sum+=busy;++ph_busy_n;ph_have_previous=0;
    }
  }
  else tmr_counter_enable(TMR3,TRUE);
}

static void ph_init(void) {
  ph_ticks_us=system_core_clock/1000000u;
  if(clock_fault)ph_fault|=1024;
  crm_periph_clock_enable(CRM_TMR2_PERIPH_CLOCK,TRUE);
  crm_periph_clock_enable(CRM_DMA1_PERIPH_CLOCK,TRUE);
  tmr_reset(TMR2);tmr_cnt_dir_set(TMR2,TMR_COUNT_UP);
  dmamux_enable(DMA1,TRUE);dmamux_init(DMA1MUX_CHANNEL1,DMAMUX_DMAREQ_ID_ADC1);
  nvic_irq_enable(DMA1_Channel1_IRQn,0,0);
  crm_periph_clock_enable(CRM_TMR3_PERIPH_CLOCK,TRUE);
  tmr_reset(TMR3);
  tmr_base_init(TMR3,65535,0);
  tmr_cnt_dir_set(TMR3,TMR_COUNT_UP);
  tmr_clock_source_div_set(TMR3,TMR_CLOCK_DIV1);
  tmr_output_config_type oc;tmr_output_default_para_init(&oc);
  oc.oc_mode=TMR_OUTPUT_CONTROL_FORCE_HIGH;
  oc.oc_polarity=TMR_OUTPUT_ACTIVE_HIGH;oc.oc_output_state=TRUE;
  tmr_output_channel_config(TMR3,TMR_SELECT_CHANNEL_2,&oc);
  tmr_output_channel_buffer_enable(TMR3,TMR_SELECT_CHANNEL_2,FALSE);
  tmr_input_config_type ic;tmr_input_default_para_init(&ic);
  ic.input_channel_select=TMR_SELECT_CHANNEL_1;
  ic.input_mapped_select=TMR_CC_CHANNEL_MAPPED_DIRECT;
  ic.input_polarity_select=TMR_INPUT_RISING_EDGE;ic.input_filter_value=0;
  tmr_input_channel_init(TMR3,&ic,TMR_CHANNEL_INPUT_DIV_1);
  tmr_trigger_input_select(TMR3,TMR_SUB_INPUT_SEL_C1DF1);
  tmr_one_cycle_mode_enable(TMR3,TRUE);
  gpio_pin_mux_config(GPIOA,GPIO_PINS_SOURCE6,GPIO_MUX_2);
  gpio_pin_mux_config(GPIOA,GPIO_PINS_SOURCE7,GPIO_MUX_2);
  gpio_init_type pin;gpio_default_para_init(&pin);
  pin.gpio_pins=GPIO_PINS_6|GPIO_PINS_7;pin.gpio_mode=GPIO_MODE_MUX;
  pin.gpio_out_type=GPIO_OUTPUT_PUSH_PULL;pin.gpio_pull=GPIO_PULL_NONE;
  gpio_init(GPIOA,&pin);
  nvic_irq_enable(TMR3_GLOBAL_IRQn,0,0); /* preempts USB priority 1 */
  ph_idle();
  crm_clocks_freq_type clocks;crm_clocks_freq_get(&clocks);
  uint32_t tmr_hz=clocks.apb1_freq;
  if(clocks.apb1_freq!=clocks.ahb_freq)tmr_hz*=2;
  if(tmr_hz!=system_core_clock)ph_fault|=2;
  /* At boot, output is requested off. Test the actual HOLD pin's timer
   * low-to-high transition, with reset released before taking HOLD low. */
  if(gpio_input_data_bit_read(GPIOA,GPIO_PINS_7)==SET)ph_selftest|=1;
  ph_prepare(32,0,0);
  if(gpio_input_data_bit_read(GPIOA,GPIO_PINS_7)==RESET)ph_selftest|=2;
  uint32_t t=DWT->CYCCNT;
  while(!ph_done && (uint32_t)(DWT->CYCCNT-t)<system_core_clock/1000u){}
  if(ph_done)ph_selftest|=4;
  if(gpio_input_data_bit_read(GPIOA,GPIO_PINS_7)==SET)ph_selftest|=8;
  ph_idle();
  if(ph_selftest!=15)ph_fault|=4;
  crm_periph_clock_enable(CRM_DAC_PERIPH_CLOCK,TRUE);
  dac_trigger_enable(DAC1_SELECT,FALSE);
  dac_wave_generate(DAC1_SELECT,DAC_WAVE_GENERATE_NONE);
  dac_output_buffer_enable(DAC1_SELECT,TRUE);
  dac_1_data_set(DAC1_12BIT_RIGHT,900);
  dac_enable(DAC1_SELECT,TRUE);
  ph_base=ph_mean(2,8,0,0);ph_idle_peak=ph_mean(0,8,0,0);
  if(ph_base<400 || ph_base>1600)ph_fault|=8;
  ph_threshold();
}

static void ph_info(void) {
  snprintf(reply,sizeof(reply),
    "{\"type\":\"phinfo\",\"fw\":\"%s\",\"fault\":%lu,\"selftest\":%lu,"
    "\"base_code\":%lu,\"idle_peak_code\":%lu,\"dac_code\":%lu,\"threshold_offset\":%lu,"
    "\"hold\":%u,\"reset\":%u,\"trig\":%u,\"timer_hz\":%lu,\"adc_hz\":%lu,"
    "\"raw_rate_hz\":%lu,\"clock_fault\":%lu,\"ldo_mv\":1300,\"raw_stop_phase\":\"%s\","
    "\"peak_sample_cycles_x2\":%lu,\"raw_timer_ticks\":%lu}\r\n",
    FW_VERSION,(unsigned long)ph_fault,(unsigned long)ph_selftest,
    (unsigned long)ph_base,(unsigned long)ph_idle_peak,(unsigned long)ph_dac_code,
    (unsigned long)ph_threshold_offset,(unsigned)gpio_input_data_bit_read(GPIOA,GPIO_PINS_7),
    (unsigned)gpio_output_data_bit_read(GPIOB,GPIO_PINS_0),
    (unsigned)gpio_input_data_bit_read(GPIOA,GPIO_PINS_6),
    (unsigned long)system_core_clock,(unsigned long)ph_adc_hz,(unsigned long)ph_raw_hz,(unsigned long)clock_fault,
    ph_stop_early?"trigger":"hold",(unsigned long)ph_peak_sample_x2,(unsigned long)PH_STEP);
  send_text(reply);
}

static void ph_raw(void) {
  if(ph_fault || adc_fault || !adc_enabled) {send_text("ERR PH_FAULT\r\n");ph_info();return;}
  ph_idle();ph_snapshot=1;ph_snapshot_done=0;
  if(!ph_dma_begin(samples,SAMPLE_COUNT,0,1)) {ph_snapshot=0;ph_info();return;}
  uint32_t t=tick_ms;
  while(!ph_snapshot_done && tick_ms-t<100){}
  TMR2->ctrl1_bit.tmren=FALSE;
  ADC1->ctrl2_bit.ocete=ADC_ORDINARY_TRIG_EDGE_NONE;
  ADC1->ctrl2_bit.adabrt=TRUE;
  uint32_t wait=DWT->CYCCNT;
  while(ADC1->ctrl2_bit.adabrt) {
    if(DWT->CYCCNT-wait>system_core_clock/10000u) {ph_fault|=32;break;}
  }
  dma_channel_enable(DMA1_CHANNEL1,FALSE);
  uint32_t remaining=dma_data_number_get(DMA1_CHANNEL1);
  if(!ph_snapshot_done || remaining>SAMPLE_COUNT/2 || remaining==0)ph_fault|=128;
  if((DMA1->sts&DMA1_DTERR1_FLAG)||ADC1->sts_bit.occo)ph_fault|=64;
  dma_interrupt_enable(DMA1_CHANNEL1,DMA_HDT_INT|DMA_DTERR_INT,FALSE);
  dma_flag_clear(DMA1_GL1_FLAG);adc_dma_mode_enable(ADC1,FALSE);
  ph_snapshot=0;ph_last_channel=255;
  uint32_t n=SAMPLE_COUNT/2,lo=4095,hi=0,total=0;uint64_t square=0;
  for(unsigned i=0;i<n;++i) {
    uint32_t v=samples[i];total+=v;square+=(uint64_t)v*v;
    if(v<lo)lo=v;
    if(v>hi)hi=v;
  }
  char digits[24];char *p=digits+sizeof(digits)-1;*p=0;
  do { *--p='0'+square%10;square/=10; } while(square);
  snprintf(reply,sizeof(reply),
    "{\"type\":\"phraw\",\"fw\":\"%s\",\"n\":%lu,\"channel\":\"RAW\","
    "\"sample_rate_hz\":%lu,\"core_hz\":%lu,\"adc_hz\":%lu,\"timer_ticks\":%lu,"
    "\"sample_cycles_x2\":5,\"elapsed_cycles\":%lu,\"fault\":%lu,"
    "\"guard_remaining\":%lu,\"min\":%lu,\"max\":%lu,\"sum\":%lu,\"sum_sq\":%s,\"crc32\":%lu}\r\n",
    FW_VERSION,(unsigned long)n,(unsigned long)ph_raw_hz,(unsigned long)system_core_clock,
    (unsigned long)ph_adc_hz,(unsigned long)PH_STEP,(unsigned long)(ph_snapshot_end-ph_snapshot_begin),
    (unsigned long)ph_fault,(unsigned long)remaining,(unsigned long)lo,(unsigned long)hi,
    (unsigned long)total,p,(unsigned long)crc32((const void *)samples,n*2));
  send_text(reply);send_bytes((const void *)samples,n*2);send_text("\r\n");
}

static void ph_capture(unsigned requested,unsigned window,unsigned delay) {
  if(ph_fault || adc_fault || !adc_enabled) {send_text("ERR PH_FAULT\r\n");ph_info();return;}
  uint32_t used=0,timeouts=0,rejects=0,started=tick_ms;
  ph_have_previous=ph_busy_n=ph_busy_sum=ph_busy_min=ph_busy_max=0;
  ph_trigger_hits=ph_trigger_ignored=ph_stop_n=ph_stop_before_irq_n=0;
  ph_stop_min=ph_stop_max=ph_stop_sum=0;
  ph_idle();usb_delay_us(2);
  ph_base=ph_mean(2,8,0,0);ph_idle_peak=ph_mean(0,8,0,0);ph_threshold();
  for(unsigned attempt=0;attempt<requested && !ph_fault && connected();++attempt) {
    ph_record r;memset(&r,0,sizeof(r));r.id=attempt;
    if(!ph_wait_trigger_low(system_core_clock/100u)) {++timeouts;continue;}
    uint32_t t=DWT->CYCCNT;ph_prepare(window,1,&r.release_pedestal);
    if(ph_fault) {ph_idle();break;}
    while(!ph_done && !ph_fault && (uint32_t)(DWT->CYCCNT-t)<system_core_clock/100u){}
    if(ph_fault) {ph_idle();break;}
    if(!ph_done) {++timeouts;ph_idle();continue;}
    /* ph_stream_stop records completion of the stop, including ADC abort and
     * DMA freeze. Negative delta proves completion before C2 IRQ entry;
     * it is not an externally measured offset from the hardware HOLD edge. */
    int32_t stop_delta=(int32_t)(ph_stream_stop_cycle-ph_hold_cycle);
    if(!ph_stop_n || stop_delta<ph_stop_min)ph_stop_min=stop_delta;
    if(!ph_stop_n || stop_delta>ph_stop_max)ph_stop_max=stop_delta;
    ph_stop_sum+=stop_delta;++ph_stop_n;
    if(stop_delta<0)++ph_stop_before_irq_n;
    ph_previous_trigger=ph_hold_cycle-ph_hold_age;ph_have_previous=1;
    r.wait_cycles=ph_hold_cycle-t;
    uint32_t saved=__get_PRIMASK();__disable_irq();
    uint32_t target=ph_hold_cycle+delay*ph_ticks_us;
    while((int32_t)(DWT->CYCCNT-target)<0){}
    r.hold_level=(gpio_input_data_bit_read(GPIOA,GPIO_PINS_7)==SET);
    r.dummy=ph_adc(0);
    for(unsigned i=0;i<4;++i) {
      r.peak[i]=ph_adc(0);
      uint32_t dt=DWT->CYCCNT-ph_hold_cycle;
      if(i==0)r.first_read_cycles=dt;
      if(i==3)r.last_read_cycles=dt;
    }
    r.flags=ph_retrigger?1:0;
    if(!r.hold_level) {r.flags|=2;ph_fault|=16;}
    ph_idle();usb_delay_us(2);
    (void)ph_adc(0);r.reset_peak=ph_adc(0);
    __set_PRIMASK(saved);
    if(ph_fault)break;
    ph_pretrigger(&r);
    if(r.baseline_max-r.baseline_min>24 ||
       r.baseline>ph_base+32 || ph_base>r.baseline+32) {++rejects;continue;}
    ph_records[used++]=r;
  }
  ph_idle();selected_channel=0;
  /* Keep the generic RAW/STATS diagnostics at their advertised slow setting. */
  adc_ordinary_channel_set(ADC1,selected_channel,1,ADC_SAMPLETIME_640_5);
  period_us=100;sample_cycles_x2=1281;
  ph_last_channel=255;
  uint32_t bytes=used*sizeof(ph_record);
  snprintf(reply,sizeof(reply),
    "{\"type\":\"phcapture\",\"fw\":\"%s\",\"n\":%lu,\"requested\":%u,"
    "\"words\":16,\"bytes\":%lu,\"crc32\":%lu,\"timeouts\":%lu,\"baseline_rejects\":%lu,"
    "\"fault\":%lu,\"selftest\":%lu,\"window_us\":%u,\"extra_delay_us\":%u,"
    "\"core_hz\":%lu,\"adc_hz\":%lu,\"base_code\":%lu,\"idle_peak_code\":%lu,"
    "\"dac_code\":%lu,\"elapsed_ms\":%lu,\"baseline_method\":\"dma_pretrigger_mean32_guard8\","
    "\"raw_rate_hz\":%lu,\"within_batch_busy_n\":%lu,\"within_batch_busy_min_cycles\":%lu,"
    "\"within_batch_busy_max_cycles\":%lu,\"within_batch_busy_mean_cycles\":%lu,\"raw_stop_phase\":\"%s\","
    "\"peak_sample_cycles_x2\":%lu,\"trigger_irq_n\":%lu,\"trigger_ignored_n\":%lu,\"dma_stop_n\":%lu,"
    "\"dma_stop_before_hold_irq_n\":%lu,\"dma_stop_minus_hold_irq_min_cycles\":%ld,"
    "\"dma_stop_minus_hold_irq_max_cycles\":%ld,\"dma_stop_minus_hold_irq_mean_cycles\":%ld}\r\n",
    FW_VERSION,(unsigned long)used,requested,(unsigned long)bytes,
    (unsigned long)crc32(ph_records,bytes),(unsigned long)timeouts,(unsigned long)rejects,
    (unsigned long)ph_fault,(unsigned long)ph_selftest,window,delay,
    (unsigned long)system_core_clock,(unsigned long)ph_adc_hz,
    (unsigned long)ph_base,(unsigned long)ph_idle_peak,(unsigned long)ph_dac_code,
    (unsigned long)(tick_ms-started),(unsigned long)ph_raw_hz,(unsigned long)ph_busy_n,(unsigned long)ph_busy_min,
    (unsigned long)ph_busy_max,(unsigned long)(ph_busy_n?ph_busy_sum/ph_busy_n:0),
    ph_stop_early?"trigger":"hold",(unsigned long)ph_peak_sample_x2,
    (unsigned long)ph_trigger_hits,(unsigned long)ph_trigger_ignored,(unsigned long)ph_stop_n,
    (unsigned long)ph_stop_before_irq_n,(long)ph_stop_min,(long)ph_stop_max,
    (long)(ph_stop_n?ph_stop_sum/(int32_t)ph_stop_n:0));
  send_text(reply);send_bytes(ph_records,bytes);send_text("\r\n");
}

static int ph_command(const char *s) {
  if(!strcmp(s,"PHINFO")) {ph_info();return 1;}
  if(!strcmp(s,"PHRAW")) {ph_raw();return 1;}
  if(!strncmp(s,"PHRATE ",7)) {
    /* Rate changes only alter TMR2 period for the next DMA start. ADC clock,
     * calibration, sample cycles, HOLD window and trigger threshold stay put. */
    uint32_t rate=0;
    if(!strcmp(s,"PHRATE 4000"))rate=4000000;
    if(!strcmp(s,"PHRATE 2000"))rate=2000000;
    if(!strcmp(s,"PHRATE 1000"))rate=1000000;
    if(!strcmp(s,"PHRATE 500"))rate=500000;
    if(!strcmp(s,"PHRATE 250"))rate=250000;
    if(!strcmp(s,"PHRATE 125"))rate=125000;
    if(!rate) {send_text("ERR PHRATE_4000_2000_1000_500_250_125\r\n");return 1;}
    if(rate*18u>ph_adc_hz) {send_text("ERR PHRATE_ADC_CLOCK\r\n");return 1;}
    ph_idle();ph_raw_hz=rate;ph_raw_step=system_core_clock/rate;
    ph_info();return 1;
  }
  if(!strncmp(s,"PHADC ",6)) {
    /* Reconfigure only between batches, with HOLD/RESET high. Reset and
     * recalibrate at each clock; no calibration is inserted per event. */
    uint32_t hz=0,rate=0;adc_div_type div=ADC_HCLK_DIV_2;
    if(!strcmp(s,"PHADC 72")) {hz=72000000;rate=4000000;div=ADC_HCLK_DIV_2;}
    if(!strcmp(s,"PHADC 36")) {hz=36000000;rate=2000000;div=ADC_HCLK_DIV_4;}
    if(!strcmp(s,"PHADC 24")) {hz=24000000;rate=1000000;div=ADC_HCLK_DIV_6;}
    if(!strcmp(s,"PHADC 12")) {hz=12000000;rate=500000;div=ADC_HCLK_DIV_12;}
    if(!hz) {send_text("ERR PHADC_72_36_24_12\r\n");return 1;}
    ph_idle();adc_enabled=0;
    ph_adc_hz=hz;ph_adc_div=div;
    /* Keep the independently selected rate unless a lower ADC clock cannot
     * sustain it; then clamp to this ADC profile's supported rate. */
    if(ph_raw_hz>rate)ph_raw_hz=rate;
    ph_raw_step=system_core_clock/ph_raw_hz;
    period_us=100;sample_cycles_x2=1281;
    if(!init_adc()) {ph_fault|=2048;ph_info();return 1;}
    ph_last_channel=255;
    ph_base=ph_mean(2,8,0,0);ph_idle_peak=ph_mean(0,8,0,0);
    if(ph_base<400 || ph_base>1600)ph_fault|=8;
    ph_threshold();ph_info();return 1;
  }
  if(!strncmp(s,"PHPK ",5)) {
    adc_sampletime_select_type sample=ADC_SAMPLETIME_24_5;uint32_t x2=0;
    if(!strcmp(s,"PHPK 49")) {sample=ADC_SAMPLETIME_24_5;x2=49;}
    if(!strcmp(s,"PHPK 95")) {sample=ADC_SAMPLETIME_47_5;x2=95;}
    if(!strcmp(s,"PHPK 185")) {sample=ADC_SAMPLETIME_92_5;x2=185;}
    if(!strcmp(s,"PHPK 495")) {sample=ADC_SAMPLETIME_247_5;x2=495;}
    if(!x2) {send_text("ERR PHPK_49_95_185_495\r\n");return 1;}
    ph_idle();ph_peak_sample=sample;ph_peak_sample_x2=x2;ph_last_channel=255;
    ph_info();return 1;
  }
  if(!strcmp(s,"PHSTOP EARLY") || !strcmp(s,"PHSTOP LATE")) {
    ph_idle();ph_stop_early=!strcmp(s,"PHSTOP EARLY");ph_info();return 1;
  }
  if(!strncmp(s,"PHCAP ",6)) {
    unsigned values[3]={0};const char *p=s+6;int valid=1;
    for(unsigned i=0;i<3;++i) {
      while(*p==' ')++p;
      unsigned digits=0;
      while(*p>='0' && *p<='9') {
        if(values[i]>10000)valid=0;
        if(valid)values[i]=values[i]*10+(unsigned)(*p-'0');
        ++digits;++p;
      }
      if(!digits || (*p && *p!=' '))valid=0;
    }
    while(*p==' ')++p;
    unsigned n=values[0],w=values[1],d=values[2];
    if(!valid || *p || n<1 || n>PH_MAX || w<2 || w>32 || d>200) {
      send_text("ERR PHCAP_N_WINDOW_DELAY\r\n");return 1;
    }
    ph_capture(n,w,d);return 1;
  }
  return 0;
}
