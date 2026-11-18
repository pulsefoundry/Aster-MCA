"""Execute the real C prepare/capture functions against injected trigger faults.

No board access. The archived fast.5 must reproduce its stale-record bug;
fast.6 must reject that record and handle a low-to-high GPIO race and wrap.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def function(source, name):
    match = re.search(r'static (?:void|int) ' + name + r'\([^)]*\)\s*\{', source)
    assert match, name
    start = match.start()
    # Remove strings/comments for brace counting, preserving byte offsets.
    clean = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*',
                   lambda m: ' ' * len(m[0]), source, flags=re.S)
    opening = source.index('{', match.start())
    depth = 0
    for index in range(opening, len(source)):
        if clean[index] == '{':
            depth += 1
        elif clean[index] == '}':
            depth -= 1
            if not depth:
                return source[start:index + 1]
    raise AssertionError('Unclosed function: ' + name)


PREAMBLE = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define SET 1
#define RESET 0
#define TRUE 1
#define FALSE 0
#define GPIOA 0
#define GPIOB 1
#define GPIO_PINS_0 0
#define GPIO_PINS_6 6
#define GPIO_PINS_7 7
#define TMR3 3
#define TMR_SELECT_CHANNEL_2 2
#define TMR_C2_INT 4
#define TMR_TRIGGER_INT 8
#define TMR_C2_FLAG 4
#define TMR3_GLOBAL_IRQn 3
#define TMR_OUTPUT_CONTROL_FORCE_LOW 0
#define TMR_OUTPUT_CONTROL_HIGH 1
#define TMR_SUB_TRIGGER_MODE 1
#define ADC1 1
#define ADC_SAMPLETIME_640_5 640
#define FW_VERSION "native-guard-test"
static uint32_t system_core_clock=144000000, tick_ms, ph_raw_step=288;
static uint32_t ph_adc_hz=72000000, ph_raw_hz=500000, ph_peak_sample_x2=49;
static uint32_t adc_fault, adc_enabled=1, selected_channel, period_us, sample_cycles_x2;
static char reply[4096];
static struct { uint32_t CYCCNT; } clock_state;
static uint32_t clock_step=1000;
static void *unused_pointer;
static __typeof__(clock_state) *clock_read(void) {
  clock_state.CYCCNT+=clock_step;tick_ms=clock_state.CYCCNT/144000;
  return &clock_state;
}
#define DWT clock_read()
'''

STUBS = r'''
static unsigned stage, gpio_mode_test, gpio_reads, injected_dma_fault;
static unsigned hold_level=1, reset_level=1, arm_calls, post_fault_adc_reads, payload_bytes, event_valid;
static void ph_idle(void) {hold_level=reset_level=1;stage=event_valid=0;}
static void ph_stream_start(void) {stage=1;if(injected_dma_fault)ph_fault|=32;}
static void usb_delay_us(unsigned value) {(void)value;}
static void gpio_bits_reset(unsigned port,unsigned pin) {(void)port;(void)pin;reset_level=0;}
static unsigned gpio_input_data_bit_read(unsigned port,unsigned pin) {
  (void)port;
  if(pin==GPIO_PINS_7)return hold_level;
  ++gpio_reads;
  if(gpio_mode_test==1)return gpio_reads==1?RESET:SET;
  if(gpio_mode_test==2)return SET;
  if(gpio_mode_test==3)return RESET;
  return stage?SET:RESET;
}
static uint16_t ph_adc(unsigned ch) {(void)ch;if(ph_fault){++post_fault_adc_reads;return 65535;}return event_valid?1130:770;}
static uint32_t ph_mean(unsigned ch,unsigned n,uint32_t *lo,uint32_t *hi) {
  (void)ch;(void)n;(void)lo;(void)hi;return 770;
}
static void ph_threshold(void) {}
static void ph_info(void) {}
static int connected(void) {return 1;}
static void ph_pretrigger(ph_record *r) {r->baseline=770;r->baseline_min=769;r->baseline_max=771;}
static void tmr_period_value_set(unsigned a,unsigned b) {(void)a;(void)b;}
static void tmr_channel_value_set(unsigned a,unsigned b,unsigned c) {(void)a;(void)b;(void)c;}
static void tmr_counter_value_set(unsigned a,unsigned b) {(void)a;(void)b;}
static void tmr_flag_clear(unsigned a,unsigned b) {(void)a;(void)b;}
static void NVIC_ClearPendingIRQ(unsigned a) {(void)a;}
static void tmr_interrupt_enable(unsigned a,unsigned b,unsigned c) {(void)a;(void)b;(void)c;}
static void tmr_output_channel_mode_select(unsigned a,unsigned b,unsigned c) {(void)a;(void)b;if(c==0)hold_level=0;}
static void tmr_sub_mode_select(unsigned a,unsigned b) {
  (void)a;
  if(b==TMR_SUB_TRIGGER_MODE) {
    ++arm_calls;
    if(gpio_mode_test==3) {
      event_valid=1;hold_level=1;ph_hold_cycle=DWT->CYCCNT;
      ph_hold_age=864;ph_stream_stop_cycle=ph_hold_cycle-570;
      ++ph_trigger_hits;ph_done=1;
    }
  }
}
static void tmr_counter_enable(unsigned a,unsigned b) {(void)a;(void)b;}
static void adc_ordinary_channel_set(unsigned a,unsigned b,unsigned c,unsigned d) {(void)a;(void)b;(void)c;(void)d;}
static void __DMB(void) {}
static uint32_t __get_PRIMASK(void) {return 0;}
static void __disable_irq(void) {}
static void __set_PRIMASK(uint32_t a) {(void)a;}
static uint32_t crc32(const void *p,unsigned n) {(void)p;(void)n;return 0;}
static void send_text(const char *p) {if(p[0]=='{')fputs(p,stdout);}
static void send_bytes(const void *p,unsigned n) {(void)p;payload_bytes+=n;}
'''

MAIN = r'''
int main(void) {
  ph_ticks_us=144;ph_selftest=15;ph_done=1;ph_hold_cycle=0;
  /* Outer idle check is low. Once DMA starts, TRIG is stuck high.
   * fast.5 retains its previous completion bit and emits 65535 ADC fields. */
  ph_capture(1,6,1);
  printf("{\"test\":\"failed_prepare\",\"fault\":%u,\"done\":%u,\"post_fault_reads\":%u,\"payload_bytes\":%u,\"hold\":%u,\"reset\":%u}\n",
    ph_fault,ph_done,post_fault_adc_reads,payload_bytes,hold_level,reset_level);
#if HAS_HELPER
  if(ph_fault!=256 || ph_done || post_fault_adc_reads || payload_bytes || hold_level!=1 || reset_level!=1)return 1;
  ph_fault=0;ph_done=1;injected_dma_fault=1;arm_calls=0;
  ph_prepare(6,1,0);
  if(ph_fault!=32 || ph_done || arm_calls || hold_level!=1 || reset_level!=1)return 2;
  ph_fault=0;injected_dma_fault=0;gpio_mode_test=1;gpio_reads=0;
  if(!ph_wait_trigger_low(10000) || gpio_reads!=1)return 3;
  /* The next sample is high, but must not invalidate the observed low. */
  if(gpio_input_data_bit_read(GPIOA,GPIO_PINS_6)!=SET)return 4;
  gpio_mode_test=2;gpio_reads=0;clock_state.CYCCNT=0xfffff000;
  if(ph_wait_trigger_low(10000) || !gpio_reads)return 5;
  puts("{\"test\":\"new_edge_dma_failure_and_clock_wrap\",\"passed\":true}");
  gpio_mode_test=3;gpio_reads=0;ph_fault=0;payload_bytes=0;
  ph_capture(1,6,1);
  if(ph_fault || payload_bytes!=64 || ph_records[0].peak[0]!=1130 || ph_records[0].reset_peak!=770)return 6;
  puts("{\"test\":\"normal_capture\",\"passed\":true}");
#endif
  return 0;
}
'''


def main():
    reports = []
    with TemporaryDirectory() as temp:
        for name, directory in [('fast5', HERE.parent / 'at32-peakhold-fast5'), ('fast6', HERE)]:
            source = (directory / 'peakhold_diag.h').read_text()
            has_helper = 'static int ph_wait_trigger_low(' in source
            prefix = source[:source.index('static void ph_stream_stop(void);')]
            functions = [function(source, n) for n in
                         (['ph_wait_trigger_low'] if has_helper else []) + ['ph_prepare', 'ph_capture']]
            text = PREAMBLE + prefix + STUBS + '\n'.join(functions) + MAIN
            cfile = Path(temp) / (name + '.c')
            binary = Path(temp) / name
            cfile.write_text(text)
            subprocess.run(['cc', '-std=gnu11', '-O2', '-DHAS_HELPER=' + str(int(has_helper)),
                            str(cfile), '-o', str(binary)], check=True, capture_output=True, text=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)
            rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            header = next(r for r in rows if r.get('type') == 'phcapture')
            fault = next(r for r in rows if r.get('test') == 'failed_prepare')
            if name == 'fast5':
                assert header['n'] == 1 and fault['post_fault_reads'] > 0 and fault['payload_bytes'] == 64
            else:
                assert header['n'] == 0 and fault['post_fault_reads'] == fault['payload_bytes'] == 0
                assert any(r.get('type')=='phcapture' and r['n']==1 and r['fault']==0 for r in rows)
                assert rows[-1]['passed']
            reports.append(dict(version=name, capture_n=header['n'], fault=header['fault'],
                                post_fault_adc_reads=fault['post_fault_reads'], cases=rows[1:]))
    print(json.dumps(dict(passed=True, reports=reports), indent=2))


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr, file=sys.stderr)
        raise
