/* Verified v0.5.0 board/clock/ADC/USB setup, unchanged. */
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

