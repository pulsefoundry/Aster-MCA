"""Read one bounded peak-hold diagnostic batch; keep raw records and CRC."""
from pathlib import Path
import argparse
import datetime
import glob
import importlib.util
import json
import math
import os
import statistics
import struct
import zlib

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('baseline_transport',HERE.parent/'at32-bringup/read_baseline.py')
transport=importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
FIELDS=['id','baseline','baseline_min','baseline_max','release_pedestal','dummy',
        'peak1','peak2','peak3','peak4','first_read_cycles','last_read_cycles',
        'reset_peak','flags','wait_cycles','hold_level']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--events',type=int,default=64)
    p.add_argument('--window-us',type=int,default=6)
    p.add_argument('--delay-us',type=int,default=1)
    p.add_argument('--adc-mhz',type=int,choices=[72,36,24,12])
    p.add_argument('--raw-ksa',type=int,choices=[4000,2000,1000,500,250,125])
    p.add_argument('--peak-sample-x2',type=int,choices=[49,95,185,495])
    p.add_argument('--stop-phase',choices=['early','late'])
    p.add_argument('--wait-us',type=int,choices=[500,1000,2000,10000])
    p.add_argument('--expect-empty',action='store_true')
    p.add_argument('--expect-events',action='store_true')
    args=p.parse_args()
    assert 1<=args.events<=128 and 2<=args.window_us<=32 and 0<=args.delay_us<=200
    assert not(args.expect_empty and args.expect_events)
    ports=glob.glob('/dev/cu.usbmodem*');assert len(ports)==1
    args.output.mkdir(parents=True,exist_ok=False)
    result={'completed':False,'started':datetime.datetime.now().astimezone().isoformat(),
            'port':ports[0],'input_condition':'operator supplied; see bench notes', 'record_fields':FIELDS}
    serial=None
    try:
        serial=transport.Serial(ports[0])
        assert serial.command('PING')=='PONG'
        # Clock changes reset/calibrate the ADC while idle, never per event.
        for command in ([f'PHADC {args.adc_mhz}'] if args.adc_mhz else []) + \
                       ([f'PHRATE {args.raw_ksa}'] if args.raw_ksa else []) + \
                       ([f'PHPK {args.peak_sample_x2}'] if args.peak_sample_x2 else []) + \
                       ([f'PHSTOP {args.stop_phase.upper()}'] if args.stop_phase else []) + \
                       ([f'PHWAIT {args.wait_us}'] if args.wait_us else []):
            state=json.loads(serial.command(command))
            assert state['fw']=='0.4.1-fast.7' and state['fault']==0
        initial=json.loads(serial.command('PHINFO'));result['initial']=initial
        assert initial['fw']=='0.4.1-fast.7'
        assert initial['fault']==0 and initial['selftest']==15
        assert initial['adc_hz'] in [72000000,36000000,24000000,12000000]
        rate=initial['raw_rate_hz'];step=144000000//rate
        assert rate in [4000000,2000000,1000000,500000,250000,125000]
        assert rate*18<=initial['adc_hz'] and step*rate==144000000
        assert initial['timer_hz']==144000000 and initial['clock_fault']==0
        assert initial['raw_rate_hz']==rate and initial['raw_timer_ticks']==step
        assert initial['peak_sample_cycles_x2'] in [49,95,185,495]
        if args.adc_mhz:assert initial['adc_hz']==args.adc_mhz*1000000
        if args.raw_ksa:assert rate==args.raw_ksa*1000
        if args.peak_sample_x2:assert initial['peak_sample_cycles_x2']==args.peak_sample_x2
        if args.stop_phase:assert initial['raw_stop_phase']=={'early':'trigger','late':'hold'}[args.stop_phase]
        if args.wait_us:assert initial['wait_limit_us']==args.wait_us
        assert initial['hold']==1 and initial['reset']==1
        head=json.loads(serial.command(f'PHCAP {args.events} {args.window_us} {args.delay_us}'))
        result['header']=head
        assert head['type']=='phcapture' and head['words']==16
        assert head['baseline_method']=='dma_pretrigger_mean32_guard8'
        assert head['adc_hz']==initial['adc_hz'] and head['raw_rate_hz']==rate
        assert head['core_hz']==144000000 and head['peak_sample_cycles_x2']==initial['peak_sample_cycles_x2']
        assert head['raw_stop_phase']==initial['raw_stop_phase']
        assert head.get('wait_limit_us')==initial.get('wait_limit_us')
        assert head['dma_stop_n']==head['n']+head['baseline_rejects']
        assert 0<=head['trigger_ignored_n']<=head['trigger_irq_n']
        assert 0<=head['dma_stop_before_hold_irq_n']<=head['dma_stop_n']
        if head['dma_stop_n']:
            assert head['dma_stop_minus_hold_irq_min_cycles']<=head['dma_stop_minus_hold_irq_mean_cycles']<=head['dma_stop_minus_hold_irq_max_cycles']
        assert head['fault']==0 and head['selftest']==15
        assert head['bytes']==64*head['n'] and 0<=head['n']<=args.events
        raw=serial.exact(head['bytes'])
        (args.output/'records.bin').write_bytes(raw)
        assert serial.exact(2)==b'\r\n'
        assert zlib.crc32(raw)==head['crc32']
        rows=[dict(zip(FIELDS,v)) for v in struct.iter_unpack('<16I',raw)]
        assert len(rows)==head['n']
        for r in rows:
            assert all(0<=r[k]<=4095 for k in FIELDS[1:10]+['reset_peak'])
            assert r['hold_level']==1
            assert r['last_read_cycles']>=r['first_read_cycles']
            r['peak_mean_code']=statistics.mean(r['peak'+str(i)] for i in range(1,5))
            r['amplitude_code']=r['peak_mean_code']-r['baseline']
            r['first_read_us_after_hold_irq']=r['first_read_cycles']/head['core_hz']*1e6
            r['last_read_us_after_hold_irq']=r['last_read_cycles']/head['core_hz']*1e6
            r['reset_minus_baseline_code']=r['reset_peak']-r['baseline']
        result['records']=rows
        result['within_batch_busy_us']={k:head[k]/head['core_hz']*1e6 for k in ['within_batch_busy_min_cycles','within_batch_busy_mean_cycles','within_batch_busy_max_cycles']}
        result['raw_crc_verified']=True
        if rows:
            amps=[r['amplitude_code'] for r in rows]
            sigma=statistics.pstdev(amps)
            result['summary']={
                'n':len(rows),'amplitude_mean_code':statistics.mean(amps),
                'amplitude_sigma_code':sigma,'amplitude_min_code':min(amps),'amplitude_max_code':max(amps),
                'flagged_records':sum(r['flags']!=0 for r in rows),
                'mean_reset_minus_baseline_code':statistics.mean(r['reset_minus_baseline_code'] for r in rows),
                'first_read_us_range':[min(r['first_read_us_after_hold_irq'] for r in rows),max(r['first_read_us_after_hold_irq'] for r in rows)],
                'last_read_us_range':[min(r['last_read_us_after_hold_irq'] for r in rows),max(r['last_read_us_after_hold_irq'] for r in rows)]}
        final=json.loads(serial.command('PHINFO'));result['final']=final
        assert final['hold']==1 and final['reset']==1 and final['fault']==0
        if args.expect_empty:assert head['n']==0, 'Unexpected triggers with output off'
        if args.expect_events:assert head['n']>0, 'No accepted events'
        result['completed']=True
        print(json.dumps({k:v for k,v in result.items() if k in ('initial','header','summary','within_batch_busy_us','final','raw_crc_verified','completed')},indent=2),flush=True)
    except Exception as e:
        result['error']=repr(e)
        raise
    finally:
        if serial is not None:os.close(serial.fd)
        (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    main()
