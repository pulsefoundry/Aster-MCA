"""Host-binned 2048-channel spectrum using the existing fast.6 batches.

This does not implement timed onboard histogramming or measure true live time.
No device is opened until main() is explicitly called.
"""
from pathlib import Path
import argparse
import datetime
import glob
import json
import math
import os
import struct
import time
import zlib

from read_timing import FIELDS, transport

FW='0.4.1-fast.6'

def require(condition,message):
    if not condition:raise ValueError(message)

def validate_info(info,configured=False,peak_sample_x2=49):
    require(info.get('fw')==FW,'Expected fast.6 peak-hold firmware')
    require(info.get('fault')==0 and info.get('clock_fault')==0 and info.get('selftest')==15,'Board fault or selftest failure')
    require(info.get('timer_hz')==144000000 and info.get('adc_hz')==72000000,'Unexpected CPU/ADC clock')
    require(info.get('hold')==info.get('reset')==1,'Board is not idle/reset')
    if configured:
        require(info.get('raw_rate_hz')==500000 and info.get('raw_timer_ticks')==288 and info.get('peak_sample_cycles_x2')==peak_sample_x2 and info.get('raw_stop_phase')=='trigger','Unexpected RAW rate, PEAK sample time, or stop phase')

def decode_batch(head,raw,*,window_us=6,peak_sample_x2=49):
    require(head.get('type')=='phcapture' and head.get('fw')==FW,'Unexpected batch header')
    require(head.get('words')==16 and head.get('bytes')==len(raw)==64*head.get('n',-1),'Batch length mismatch')
    require(zlib.crc32(raw)==head.get('crc32'),'Batch CRC mismatch')
    require(head.get('fault')==0 and head.get('selftest')==15,'Capture fault')
    require((head.get('core_hz'),head.get('adc_hz'),head.get('raw_rate_hz'),head.get('peak_sample_cycles_x2'),head.get('raw_stop_phase'),head.get('window_us'))==(144000000,72000000,500000,peak_sample_x2,'trigger',window_us),'Capture settings changed')
    require(head.get('extra_delay_us')==1,'Readout delay changed')
    require(head.get('baseline_method')=='dma_pretrigger_mean32_guard8','Unexpected baseline method')
    require(0<=head['n']<=head['requested']<=128,'Invalid record count')
    require(head['n']+head['baseline_rejects']+head['timeouts']==head['requested'],'Attempt accounting mismatch')
    require(head['dma_stop_n']==head['n']+head['baseline_rejects'],'DMA-stop accounting mismatch')
    require(0<=head['trigger_ignored_n']<=head['trigger_irq_n'],'Invalid trigger counters')
    require(0<=head['dma_stop_before_hold_irq_n']<=head['dma_stop_n'],'Invalid stop-phase counters')
    rows=[]
    for values in struct.iter_unpack('<16I',raw):
        r=dict(zip(FIELDS,values))
        require(all(0<=r[k]<=4095 for k in FIELDS[1:10]+['reset_peak']),'ADC value outside 12-bit range')
        require(r['hold_level']==1,'HOLD was not high at readout')
        require(r['last_read_cycles']>=r['first_read_cycles'],'Invalid read timing')
        r['amplitude_code']=sum(values[6:10])/4-values[1]
        rows.append(r)
    return rows

def add_events(counts,rows):
    totals=dict(received=len(rows),binned=0,flagged=0,clipped=0,underflow=0,overflow=0)
    for r in rows:
        amp=r['amplitude_code']
        if r['flags']:totals['flagged']+=1
        elif max(r[f'peak{i}'] for i in range(1,5))>=4090:totals['clipped']+=1
        elif amp<0:totals['underflow']+=1
        elif amp>=4096:totals['overflow']+=1
        else:counts[math.floor(amp/2)]+=1;totals['binned']+=1
    return totals

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=60)
    parser.add_argument('--label',default='detector-background')
    parser.add_argument('--window-us',type=int,choices=range(2,33),default=6)
    parser.add_argument('--peak-sample-x2',type=int,choices=[49,95,185,495],default=49)
    parser.add_argument('--condition',required=True,help='Operator-confirmed detector/source conditions')
    parser.add_argument('--port')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    require(0<args.seconds<=3600,'Choose duration within (0,3600]seconds')
    ports=[args.port] if args.port else glob.glob('/dev/cu.usbmodem*')
    require(len(ports)==1,'Expected exactly one Nano serial port')
    args.output.mkdir(parents=True,exist_ok=False)
    result=dict(completed=False,label=args.label,input_condition=args.condition,port=ports[0],
                started=datetime.datetime.now().astimezone().isoformat(),requested_wall_seconds=args.seconds,
                capture_window_us=args.window_us,extra_read_delay_us=1,peak_sample_cycles_x2=args.peak_sample_x2,
                mode=f'host histogram from {FW} batches;not timed onboard histogram',
                bins=2048,adc_codes_per_channel=2,energy_calibrated=False,
                amplitude_definition='mean(PEAK1..4)-RAW pretrigger baseline',record_fields=FIELDS,
                counts=[0]*2048,all_received_counts=[0]*2048,
                histogram_note='counts applies flag/clipping/range selection;all_received_counts includes every in-range trigger amplitude',
                totals=dict(received=0,binned=0,flagged=0,clipped=0,underflow=0,overflow=0,
                                         firmware_timeouts=0,firmware_baseline_rejects=0,attempts=0,batches=0,
                                         trigger_irq_n=0,trigger_ignored_n=0,dma_stop_n=0,dma_stop_before_hold_irq_n=0),
                mcu_batch_elapsed_ms_sum=0,wall_seconds=0,
                live_time_note='True live time unavailable;wall time includes upload/host gaps;MCU batch time includes event busy periods')
    ser=None;begin=None
    def save():
        if begin is not None:result['wall_seconds']=time.monotonic()-begin
        result['wall_rate_cps']=result['totals']['binned']/result['wall_seconds'] if result['wall_seconds'] else 0
        temp=args.output/'spectrum.json.tmp';temp.write_text(json.dumps(result,indent=2)+'\n');temp.replace(args.output/'spectrum.json')
    try:
        ser=transport.Serial(ports[0]);require(ser.command('PING')=='PONG','No PONG from Nano')
        result['initial']=json.loads(ser.command('PHINFO'));validate_info(result['initial'])
        for command in ['PHRATE 500',f'PHPK {args.peak_sample_x2}','PHSTOP EARLY']:
            info=json.loads(ser.command(command));validate_info(info)
        result['configured']=json.loads(ser.command('PHINFO'));validate_info(result['configured'],True,args.peak_sample_x2)
        begin=time.monotonic();deadline=begin+args.seconds
        with (args.output/'batches.jsonl').open('w') as log:
            while deadline-time.monotonic()>=.01:
                remaining=deadline-time.monotonic()
                attempts=min(128,max(1,int(remaining/.01)))
                index=result['totals']['batches']+1;t0=time.monotonic()
                head=json.loads(ser.command(f'PHCAP {attempts} {args.window_us} 1'))
                require(head.get('bytes',-1) in range(0,8193),'Invalid byte count')
                raw=ser.exact(head['bytes']);filename=f'batch-{index:06d}.bin'
                (args.output/filename).write_bytes(raw)
                try:
                    require(ser.exact(2)==b'\r\n','Missing frame terminator')
                    rows=decode_batch(head,raw,window_us=args.window_us,peak_sample_x2=args.peak_sample_x2)
                except Exception as error:
                    failed=dict(batch=index,file=filename,header=head,
                                validation_error=str(error),host_roundtrip_seconds=time.monotonic()-t0)
                    log.write(json.dumps(failed)+'\n');log.flush()
                    result['failed_batch']=failed;save()
                    raise
                for row in rows:
                    if 0<=row['amplitude_code']<4096:result['all_received_counts'][math.floor(row['amplitude_code']/2)]+=1
                selection=add_events(result['counts'],rows)
                for key,value in selection.items():result['totals'][key]+=value
                for key,source in [('firmware_timeouts','timeouts'),('firmware_baseline_rejects','baseline_rejects'),('attempts','requested'),('trigger_irq_n','trigger_irq_n'),('trigger_ignored_n','trigger_ignored_n'),('dma_stop_n','dma_stop_n'),('dma_stop_before_hold_irq_n','dma_stop_before_hold_irq_n')]:result['totals'][key]+=head[source]
                result['totals']['batches']+=1;result['mcu_batch_elapsed_ms_sum']+=head['elapsed_ms']
                log.write(json.dumps(dict(batch=index,file=filename,header=head,selection=selection,host_roundtrip_seconds=time.monotonic()-t0))+'\n');log.flush();save()
        result['final']=json.loads(ser.command('PHINFO'));validate_info(result['final'],True,args.peak_sample_x2)
        require(sum(result['counts'])==result['totals']['binned'],'Histogram accounting mismatch')
        result['completed']=True;save()
        print(json.dumps({k:v for k,v in result.items() if k not in ['counts','all_received_counts','record_fields']},indent=2))
    except BaseException as e:
        result['error']=repr(e);raise
    finally:
        if ser is not None:os.close(ser.fd)
        save()

if __name__=='__main__':main()
