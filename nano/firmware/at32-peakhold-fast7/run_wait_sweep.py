"""Bounded wait-deadline experiment. Start only after physical bench readiness.

Retains every frame; no spectrum-based stopping or parameter selection.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def save(path, obj):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj,indent=2)+'\n')
    temp.replace(path)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--condition',required=True)
    p.add_argument('--phase',choices=['empty','source'],required=True)
    p.add_argument('--seconds-per-block',type=float,default=30)
    args=p.parse_args()
    if not 2<=args.seconds_per_block<=60:p.error('Use2..60second bounded blocks')
    short=[10000,1000,500]
    order=[10000,1000,500,1000,500,10000,500,10000,1000,
           500,1000,10000,10000,500,1000,1000,10000,500]
    limits=short if args.phase=='empty' else order
    args.output.mkdir(parents=True,exist_ok=False)
    capture=HERE/'capture_spectrum.py'
    state=dict(completed=False,phase=args.phase,condition=args.condition,
               started=datetime.datetime.now().astimezone().isoformat(),
               seconds_per_block=args.seconds_per_block,plan_wait_us=limits,blocks=[],
               fixed=dict(window_us=6,peak_sample_cycles_x2=49,raw_rate_hz=500000,
                          core_hz=144000000,adc_hz=72000000,stop_phase='EARLY',delay_us=1),
               capture_script_sha256=hashlib.sha256(capture.read_bytes()).hexdigest(),
               live_time_note='Internal armed duration includes capture/IRQ latency and is not independently validated true live time.')
    save(args.output/'progress.json',state)
    try:
        for index,limit in enumerate(limits,1):
            name=f'block-{index:02d}-wait{limit}'
            state['active_block']=name;save(args.output/'progress.json',state)
            with (args.output/f'{name}.log').open('w') as log:
                result=subprocess.run([sys.executable,str(capture),'--seconds',str(args.seconds_per_block),
                    '--wait-us',str(limit),'--window-us','6','--peak-sample-x2','49',
                    '--label',f'{args.phase}-{name}','--condition',args.condition,
                    '--output',str(args.output/name)],stdout=log,stderr=subprocess.STDOUT,
                    timeout=args.seconds_per_block+20)
            if result.returncode:raise RuntimeError(f'{name} failed; frames/log preserved')
            record=json.loads((args.output/name/'spectrum.json').read_text())
            if not record['completed'] or record.get('error'):raise RuntimeError(f'{name} incomplete')
            item=dict(path=name,wait_us=limit,wall_seconds=record['wall_seconds'],
                      totals=record['totals'],internal_timing_sums=record['internal_timing_sums'])
            state['blocks'].append(item);state['active_block']=None;save(args.output/'progress.json',state)
            print(json.dumps(dict(block=index,of=len(limits),wait_us=limit,
                received=record['totals']['received'],selected=record['totals']['binned'],
                cancelled_pending=item['internal_timing_sums']['deadline_pending_n'],fault=record['final']['fault'])),flush=True)
        state['completed']=True
    except BaseException as e:
        state['error']=repr(e);raise
    finally:
        state['finished']=datetime.datetime.now().astimezone().isoformat()
        save(args.output/'progress.json',state)


if __name__=='__main__':main()
