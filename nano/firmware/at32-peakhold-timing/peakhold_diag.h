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
static uint32_t ph_fault, ph_selftest, ph_dac_code, ph_base, ph_idle_peak;
static uint32_t ph_threshold_offset=40;
static uint32_t ph_ticks_us;

static void ph_idle(void) {
  tmr_sub_mode_select(TMR3,TMR_SUB_MODE_DIABLE);
  tmr_counter_enable(TMR3,FALSE);
  tmr_interrupt_enable(TMR3,TMR_C2_INT,FALSE);
  /* HOLD high before RESET high, including every error/timeout path. */
  tmr_output_channel_mode_select(TMR3,TMR_SELECT_CHANNEL_2,TMR_OUTPUT_CONTROL_FORCE_HIGH);
  __DSB();
  gpio_bits_set(GPIOB,GPIO_PINS_0);
}

void TMR3_GLOBAL_IRQHandler(void) {
  if(tmr_interrupt_flag_get(TMR3,TMR_C2_FLAG)==SET) {
    ph_hold_cycle=DWT->CYCCNT;
    ph_retrigger=(tmr_flag_get(TMR3,TMR_C1_RECAPTURE_FLAG)==SET);
    tmr_interrupt_enable(TMR3,TMR_C2_INT,FALSE);
    tmr_sub_mode_select(TMR3,TMR_SUB_MODE_DIABLE);
    tmr_counter_enable(TMR3,FALSE);
    tmr_flag_clear(TMR3,TMR_C2_FLAG);
    __DMB(); ph_done=1;
  }
}

static uint16_t ph_adc(unsigned ch) {
  if(ph_fault || adc_fault || !adc_enabled) return 0xffff;
  adc_ordinary_channel_set(ADC1,ch,1,ADC_SAMPLETIME_24_5);
  adc_flag_clear(ADC1,ADC_OCCE_FLAG|ADC_OCCO_FLAG);
  adc_ordinary_software_trigger_enable(ADC1,TRUE);
  uint32_t begin=DWT->CYCCNT;
  while(adc_flag_get(ADC1,ADC_OCCE_FLAG)==RESET) {
    if((uint32_t)(DWT->CYCCNT-begin)>system_core_clock/1000u) {
      ph_fault|=1; return 0xffff;
    }
  }
  return adc_ordinary_conversion_data_get(ADC1);
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

static void ph_prepare(unsigned window,int external,uint32_t *pedestal) {
  ph_idle();
  usb_delay_us(2);
  gpio_bits_reset(GPIOB,GPIO_PINS_0); /* release reset, HOLD still high */
  usb_delay_us(1);
  if(pedestal) { (void)ph_adc(0); *pedestal=ph_adc(0); }
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
  if(external)tmr_sub_mode_select(TMR3,TMR_SUB_TRIGGER_MODE);
  else tmr_counter_enable(TMR3,TRUE);
}

static void ph_init(void) {
  ph_ticks_us=system_core_clock/1000000u;
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
    "\"hold\":%u,\"reset\":%u,\"trig\":%u,\"timer_hz\":%lu,\"adc_hz\":%lu}\r\n",
    FW_VERSION,(unsigned long)ph_fault,(unsigned long)ph_selftest,
    (unsigned long)ph_base,(unsigned long)ph_idle_peak,(unsigned long)ph_dac_code,
    (unsigned long)ph_threshold_offset,(unsigned)gpio_input_data_bit_read(GPIOA,GPIO_PINS_7),
    (unsigned)gpio_output_data_bit_read(GPIOB,GPIO_PINS_0),
    (unsigned)gpio_input_data_bit_read(GPIOA,GPIO_PINS_6),
    (unsigned long)system_core_clock,(unsigned long)(system_core_clock/4));
  send_text(reply);
}

static void ph_capture(unsigned requested,unsigned window,unsigned delay) {
  if(ph_fault || adc_fault || !adc_enabled) {send_text("ERR PH_FAULT\r\n");ph_info();return;}
  uint32_t used=0,timeouts=0,rejects=0,started=tick_ms;
  ph_idle();usb_delay_us(2);
  ph_base=ph_mean(2,8,0,0);ph_idle_peak=ph_mean(0,8,0,0);ph_threshold();
  for(unsigned attempt=0;attempt<requested && !ph_fault && connected();++attempt) {
    ph_record r;memset(&r,0,sizeof(r));r.id=attempt;
    r.baseline=ph_mean(1,8,&r.baseline_min,&r.baseline_max);
    if(r.baseline_max-r.baseline_min>24 ||
       (r.baseline>ph_base+32) || (ph_base>r.baseline+32)) {++rejects;continue;}
    uint32_t t=DWT->CYCCNT;
    while(gpio_input_data_bit_read(GPIOA,GPIO_PINS_6)==SET &&
          (uint32_t)(DWT->CYCCNT-t)<system_core_clock/100u){}
    if(gpio_input_data_bit_read(GPIOA,GPIO_PINS_6)==SET) {++timeouts;continue;}
    t=DWT->CYCCNT;ph_prepare(window,1,&r.release_pedestal);
    while(!ph_done && (uint32_t)(DWT->CYCCNT-t)<system_core_clock/100u){}
    if(!ph_done) {++timeouts;ph_idle();continue;}
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
    ph_records[used++]=r;
  }
  ph_idle();selected_channel=0;
  /* Keep the generic RAW/STATS diagnostics at their advertised slow setting. */
  adc_ordinary_channel_set(ADC1,selected_channel,1,ADC_SAMPLETIME_640_5);
  period_us=100;sample_cycles_x2=1281;
  uint32_t bytes=used*sizeof(ph_record);
  snprintf(reply,sizeof(reply),
    "{\"type\":\"phcapture\",\"fw\":\"%s\",\"n\":%lu,\"requested\":%u,"
    "\"words\":16,\"bytes\":%lu,\"crc32\":%lu,\"timeouts\":%lu,\"baseline_rejects\":%lu,"
    "\"fault\":%lu,\"selftest\":%lu,\"window_us\":%u,\"extra_delay_us\":%u,"
    "\"core_hz\":%lu,\"adc_hz\":%lu,\"base_code\":%lu,\"idle_peak_code\":%lu,"
    "\"dac_code\":%lu,\"elapsed_ms\":%lu,\"baseline_method\":\"mean8_before_arm\"}\r\n",
    FW_VERSION,(unsigned long)used,requested,(unsigned long)bytes,
    (unsigned long)crc32(ph_records,bytes),(unsigned long)timeouts,(unsigned long)rejects,
    (unsigned long)ph_fault,(unsigned long)ph_selftest,window,delay,
    (unsigned long)system_core_clock,(unsigned long)(system_core_clock/4),
    (unsigned long)ph_base,(unsigned long)ph_idle_peak,(unsigned long)ph_dac_code,
    (unsigned long)(tick_ms-started));
  send_text(reply);send_bytes(ph_records,bytes);send_text("\r\n");
}

static int ph_command(const char *s) {
  if(!strcmp(s,"PHINFO")) {ph_info();return 1;}
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
