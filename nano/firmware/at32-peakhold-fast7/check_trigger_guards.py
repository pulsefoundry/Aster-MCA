"""Execute actual fast.7 C prepare/capture under injected deadline/trigger faults.
No board access. Also replay native-generated frames through the real decoder.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import re
import subprocess
import sys
import zlib

HERE = Path(__file__).resolve().parent

def function(source, name):
    match = re.search(r'static (?:void|int|uint32_t) ' + name + r'\([^)]*\)\s*\{', source)
    assert match, name
    clean = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*',
                   lambda m: ' ' * len(m[0]), source, flags=re.S)
    opening = source.index('{',match.start());depth=0
    for index in range(opening,len(source)):
        if clean[index]=='{':depth+=1
        elif clean[index]=='}':
            depth-=1
            if not depth:return source[match.start():index+1]
    raise AssertionError(name)

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
#define TMR_SELECT_CHANNEL_2 2
#define TMR_C2_INT 4
#define TMR_TRIGGER_INT 8
#define TMR_C2_FLAG 4
#define TMR_TRIGGER_FLAG 8
#define TMR3_GLOBAL_IRQn 3
#define TMR_OUTPUT_CONTROL_FORCE_LOW 0
#define TMR_OUTPUT_CONTROL_HIGH 1
#define TMR_SUB_TRIGGER_MODE 1
#define ADC1 1
#define ADC_SAMPLETIME_640_5 640
#define FW_VERSION "0.4.1-fast.7"
static struct {struct {unsigned tmren;} ctrl1_bit;unsigned flags;} fake_timer;
#define TMR3 (&fake_timer)
static uint32_t system_core_clock=144000000, tick_ms, ph_raw_step=288;
static uint32_t ph_adc_hz=72000000,ph_raw_hz=500000,ph_peak_sample_x2=49;
static uint32_t adc_fault,adc_enabled=1,selected_channel,period_us,sample_cycles_x2;
static char reply[3072];
static struct {uint32_t CYCCNT;} clock_state;
static uint64_t clock_total;
static void advance(unsigned cycles);
static __typeof__(clock_state) *clock_read(void) {advance(144);return &clock_state;}
#define DWT clock_read()
'''

STUBS = r'''
enum {BAD_PREPARE=1,EMPTY,NORMAL,DMA_FAILURE,INFLIGHT,COMPLETION_RACE,ADC_FAILURE,BASE_REJECT};
static unsigned mode,stage,hold_level=1,reset_level=1,event_valid,mask_irq;
static unsigned arm_calls,post_fault_reads,gpio_reads,low_high_race,race_done,payload_bytes;
static uint32_t scheduled,monotonic_arm;
static void complete(void) {
  event_valid=1;hold_level=1;ph_hold_cycle=clock_state.CYCCNT;
  ph_hold_age=864;ph_stream_stop_cycle=ph_hold_cycle-500;
  ++ph_trigger_hits;ph_done=1;fake_timer.ctrl1_bit.tmren=0;fake_timer.flags|=TMR_C2_FLAG;
}
static void advance(unsigned cycles) {
  clock_state.CYCCNT+=cycles;clock_total+=cycles;tick_ms=clock_total/144000;
  if(stage==2 && !ph_done && !mask_irq &&
     (mode==NORMAL || mode==ADC_FAILURE || mode==BASE_REJECT) &&
     (uint32_t)(clock_state.CYCCNT-scheduled)<0x80000000u)complete();
}
static void ph_idle(void) {hold_level=reset_level=1;stage=event_valid=0;fake_timer.ctrl1_bit.tmren=0;fake_timer.flags=0;}
static void ph_stream_start(void) {stage=1;advance(192*144);if(mode==DMA_FAILURE)ph_fault|=32;}
static void usb_delay_us(unsigned value) {advance(value*144);}
static void gpio_bits_reset(unsigned port,unsigned pin) {(void)port;(void)pin;reset_level=0;}
static unsigned gpio_input_data_bit_read(unsigned port,unsigned pin) {
  (void)port;if(pin==GPIO_PINS_7)return hold_level;
  ++gpio_reads;if(low_high_race)return gpio_reads==1?RESET:SET;
  return mode==BAD_PREPARE && stage?SET:RESET;
}
static uint16_t ph_adc(unsigned ch) {
  (void)ch;advance(72);
  if(ph_fault){++post_fault_reads;return 65535;}
  if(mode==ADC_FAILURE && event_valid){ph_fault|=1;return 65535;}
  return event_valid?1130:770;
}
static uint32_t ph_mean(unsigned ch,unsigned n,uint32_t *lo,uint32_t *hi) {
  (void)ch;(void)n;(void)lo;(void)hi;return 770;
}
static void ph_threshold(void) {ph_dac_code=810;advance(2000*144);}
static void ph_info(void) {}
static int connected(void) {return 1;}
static void ph_pretrigger(ph_record *r) {r->baseline=770;r->baseline_min=769;r->baseline_max=mode==BASE_REJECT?795:771;}
static void tmr_period_value_set(void *a,unsigned b) {(void)a;(void)b;}
static void tmr_channel_value_set(void *a,unsigned b,unsigned c) {(void)a;(void)b;(void)c;}
static void tmr_counter_value_set(void *a,unsigned b) {(void)a;(void)b;}
static void tmr_flag_clear(void *a,unsigned b) {(void)a;(void)b;fake_timer.flags=0;}
static void NVIC_ClearPendingIRQ(unsigned a) {(void)a;}
static void tmr_interrupt_enable(void *a,unsigned b,unsigned c) {(void)a;(void)b;(void)c;}
static unsigned tmr_interrupt_flag_get(void *a,unsigned flag) {(void)a;return (fake_timer.flags&flag)?SET:RESET;}
static void tmr_output_channel_mode_select(void *a,unsigned b,unsigned c) {(void)a;(void)b;if(c==0)hold_level=0;}
static void tmr_sub_mode_select(void *a,unsigned b) {
  (void)a;if(b==TMR_SUB_TRIGGER_MODE){++arm_calls;stage=2;scheduled=clock_state.CYCCNT+100*144;
    if(mode==INFLIGHT){fake_timer.ctrl1_bit.tmren=1;fake_timer.flags|=TMR_TRIGGER_FLAG;}}
}
static void tmr_counter_enable(void *a,unsigned b) {(void)a;(void)b;}
static void adc_ordinary_channel_set(unsigned a,unsigned b,unsigned c,unsigned d) {(void)a;(void)b;(void)c;(void)d;}
static void __DMB(void) {}
static uint32_t __get_PRIMASK(void) {return mask_irq;}
static void __disable_irq(void) {if(mode==COMPLETION_RACE && stage==2 && !ph_done && !race_done){race_done=1;advance(144);complete();}mask_irq=1;}
static void __set_PRIMASK(uint32_t a) {mask_irq=a;}
static void send_text(const char *p) {if(p[0]=='{')fputs(p,stdout);}
static void send_bytes(const void *p,unsigned n) {
  const unsigned char *b=p;payload_bytes+=n;
  printf("{\"raw_hex\":\"");for(unsigned i=0;i<n;++i)printf("%02x",b[i]);puts("\"}");
}
static void reset_case(unsigned m,unsigned limit,uint32_t clock_seed) {
  ph_idle();mode=m;mask_irq=0;ph_fault=adc_fault=0;adc_enabled=1;ph_selftest=15;ph_ticks_us=144;
  ph_done=1;ph_hold_cycle=0;ph_wait_limit_us=limit;ph_stop_early=1;
  arm_calls=post_fault_reads=gpio_reads=low_high_race=race_done=payload_bytes=0;
  clock_state.CYCCNT=clock_seed;clock_total=0;tick_ms=0;
}
static void check(int ok,unsigned line){if(!ok){fprintf(stderr,"failed line%u\n",line);exit(1);}}
#define CHECK(x) check((x),__LINE__)
'''
MAIN = r'''
int main(void) {
  unsigned limits[]={10000,2000,1000,500};
  for(unsigned i=0;i<4;++i){
    printf("{\"case\":\"empty_%u\"}\n",limits[i]);reset_case(EMPTY,limits[i],0);ph_capture(3,6,1);
    CHECK(!ph_fault && payload_bytes==0 && arm_calls==3 && hold_level==1 && reset_level==1 && !mask_irq);
    printf("{\"case\":\"normal_%u\"}\n",limits[i]);reset_case(NORMAL,limits[i],0);ph_capture(2,6,1);
    CHECK(!ph_fault && payload_bytes==128 && arm_calls==2 && ph_records[0].peak[0]==1130 && hold_level==1 && reset_level==1);
  }
  puts("{\"case\":\"failed_prepare\"}");reset_case(BAD_PREPARE,500,0);ph_capture(1,6,1);
  CHECK(ph_fault==256 && !ph_done && !payload_bytes && !post_fault_reads && hold_level==1 && reset_level==1);
  puts("{\"case\":\"dma_failure\"}");reset_case(DMA_FAILURE,500,0);ph_capture(1,6,1);
  CHECK(ph_fault==32 && !ph_done && !payload_bytes && !arm_calls && !post_fault_reads);
  puts("{\"case\":\"inflight_deadline\"}");reset_case(INFLIGHT,500,0);ph_capture(1,6,1);
  CHECK(!ph_fault && !payload_bytes && hold_level==1 && reset_level==1 && !mask_irq);
  puts("{\"case\":\"completion_race\"}");reset_case(COMPLETION_RACE,500,0);ph_capture(1,6,1);
  CHECK(!ph_fault && payload_bytes==64 && race_done && !mask_irq);
  puts("{\"case\":\"counter_wrap\"}");reset_case(NORMAL,500,0xffffe000);ph_capture(1,6,1);
  CHECK(!ph_fault && payload_bytes==64 && ph_records[0].wait_cycles<500*144);
  puts("{\"case\":\"baseline_reject\"}");reset_case(BASE_REJECT,500,0);ph_capture(1,6,1);
  CHECK(!ph_fault && !payload_bytes && hold_level==1 && reset_level==1);
  puts("{\"case\":\"adc_failure\"}");reset_case(ADC_FAILURE,500,0);ph_capture(1,6,1);
  CHECK(ph_fault==1 && !payload_bytes && hold_level==1 && reset_level==1);
  puts("{\"case\":\"max128\"}");reset_case(NORMAL,10000,0);ph_capture(128,6,1);
  CHECK(!ph_fault && payload_bytes==8192 && hold_level==1 && reset_level==1);
  reset_case(EMPTY,500,0);low_high_race=1;CHECK(ph_wait_trigger_low(10000) && gpio_reads==1);
  CHECK(gpio_input_data_bit_read(GPIOA,GPIO_PINS_6)==SET);
  puts("{\"low_high_race_checked\":true}");return 0;
}
'''


def main():
    source=(HERE/'peakhold_diag.h').read_text()
    prefix=source[:source.index('static void ph_stream_stop(void);')]
    funcs='\n'.join(function(source,n) for n in ['ph_wait_trigger_low','ph_prepare','ph_capture'])
    checksum=function((HERE/'main.c').read_text(),'crc32')
    with TemporaryDirectory() as temp:
        cfile=Path(temp)/'wait.c';binary=Path(temp)/'wait'
        cfile.write_text(PREAMBLE+prefix+checksum+STUBS+funcs+MAIN)
        build=subprocess.run(['cc','-std=gnu11','-O2','-Wall','-Wno-unused-variable','-Wno-unused-function',str(cfile),'-o',str(binary)],capture_output=True,text=True)
        if build.returncode:raise RuntimeError(build.stderr)
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
        if result.returncode:raise RuntimeError(result.stderr)
    rows=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    sys.path.insert(0,str(HERE))
    from capture_spectrum import decode_batch
    reports=[];case=None;header=None;valid=0;negative=0
    for row in rows:
        if 'case' in row:case=row['case']
        elif row.get('type')=='phcapture':
            header=row;assert header['bytes']==64*header['n']
            assert len(json.dumps(header))<3072
        elif 'raw_hex' in row:
            raw=bytes.fromhex(row['raw_hex']);assert zlib.crc32(raw)==header['crc32']
            if not header['fault']:
                decoded=decode_batch(header,raw,wait_limit_us=header['wait_limit_us']);valid+=1
                assert len(decoded)==header['n']
                if case.startswith('empty'):assert header['wait_timeouts']==3 and header['armed_attempts']==3
                if case=='inflight_deadline':assert header['deadline_pending_n']==header['wait_timeouts']==1
                if case=='completion_race':assert header['completed_over_limit_n']==1
                if case=='baseline_reject':assert header['baseline_rejects']==1
                for key in ['wait_limit_us','attempts_started','wait_timeouts','armed_observed_cycles','crc32']:
                    bad=dict(header);bad[key]+=1
                    if key=='armed_observed_cycles':bad[key]=header['batch_work_cycles']+1
                    try:decode_batch(bad,raw,wait_limit_us=header['wait_limit_us'])
                    except ValueError:negative+=1
                    else:raise AssertionError('Bad '+key+' accepted')
            else:
                assert not raw
                try:decode_batch(header,raw,wait_limit_us=header['wait_limit_us'])
                except ValueError:negative+=1
                else:raise AssertionError('Faulty frame accepted')
            reports.append(dict(case=case,n=header['n'],fault=header['fault'],timeouts=header['timeouts'],
                                pending=header['deadline_pending_n'],over_limit=header['completed_over_limit_n']))
    assert rows[-1]['low_high_race_checked']
    print(json.dumps(dict(passed=True,native_c_cases=len(reports),valid_frame_replays=valid,negative_decoder_cases=negative,cases=reports),indent=2))

if __name__=='__main__':main()
