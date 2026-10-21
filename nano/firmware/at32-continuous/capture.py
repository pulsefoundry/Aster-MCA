"""Capture continuous 1 MS/s lossless ADC and process spectra on the PC.

Stores original wire stream, decoded u16 samples, event list, spectra and status.
An interrupted or faulted run is explicitly invalid. No flashing or reset.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import select
import sys
import time
import tty
from protocol import Decoder
from spectrum import Spectrum

def line(fd,timeout=3):
    b=bytearray();deadline=time.monotonic()+timeout
    while b'\n' not in b:
        if not select.select([fd],[],[],max(0,deadline-time.monotonic()))[0]:raise TimeoutError('No command response')
        piece=os.read(fd,1)
        if not piece:raise EOFError('USB disconnected')
        b.extend(piece)
    return bytes(b).decode().strip()

def stop_and_drain(fd,out):
    """Preserve failure evidence and return the device to idle.

    Drained bytes are diagnostic only: never resynchronize them into a valid run.
    Keep the port open while STOP and queued USB packets finish.
    """
    result={'diagnostic_only':True,'drained_bytes':0}
    try:
        os.write(fd,b'STOP\n')
        deadline=time.monotonic()+3
        with (out/'failure-drain.bin').open('wb') as f:
            while time.monotonic()<deadline:
                if not select.select([fd],[],[],min(.3,max(0,deadline-time.monotonic())))[0]:break
                b=os.read(fd,65536)
                if not b:raise EOFError('USB disconnected during recovery')
                f.write(b);result['drained_bytes']+=len(b)
        os.write(fd,b'INFO\n')
        result['idle_info']=json.loads(line(fd,1))
    except Exception as e:
        result['recovery_error']=repr(e)
    return result

def run(port,out,seconds,input_condition,threshold=20,stall_seconds=0,
        stop_event=None,on_progress=None,on_event=None,quiet=False):
    if not .01<=seconds<=3600 or not 1<=threshold<=2048:
        raise ValueError('seconds=.01..3600; threshold=1..2048')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    decoder=Decoder();spectrum=Spectrum(out,threshold,on_event=on_event)
    record={'started':datetime.datetime.now().astimezone().isoformat(),'port':port,
            'input':input_condition,'requested_seconds':seconds,'completed':False,
            'host_processing':'All pulse extraction and histogramming on PC; MCU losslessly compresses every ADC sample.'}
    fd=None;started=False;stop_sent=False;t0=time.monotonic();last_progress=t0
    try:
        fd=os.open(port,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK);tty.setraw(fd)
        os.write(fd,b'INFO\n');info=json.loads(line(fd));record['initial_info']=info
        if info.get('fw')!='0.3.1' or info.get('board')!='Aster MCA Nano AT32 v0.3' or info['adc_fault'] or info.get('clock_fault',0):
            raise ValueError('Unexpected firmware/board state')
        os.write(fd,f'STREAM {round(seconds*1000)}\n'.encode())
        if line(fd)!='OK STREAM':raise ValueError('Stream not acknowledged')
        started=True;t0=time.monotonic();deadline=t0+seconds+8;last=t0
        if stall_seconds:time.sleep(stall_seconds)
        with (out/'stream.astc').open('wb') as wire,(out/'samples.u16').open('wb') as rawfile,(out/'blocks.jsonl').open('w') as headers:
            while not decoder.done:
                if stop_event is not None and stop_event.is_set() and not stop_sent:
                    os.write(fd,b'STOP\n');stop_sent=True
                    deadline=min(deadline,time.monotonic()+8)
                if time.monotonic()>deadline:raise TimeoutError('Stream terminal packet not received')
                if not select.select([fd],[],[],1)[0]:continue
                b=os.read(fd,65536)
                if not b:raise EOFError('USB disconnected')
                wire.write(b)
                for meta,raw in decoder.feed(b):
                    rawfile.write(raw);headers.write(json.dumps(meta)+'\n');spectrum.feed(raw)
                if on_progress and time.monotonic()-last_progress>=.25:
                    on_progress({'samples':spectrum.n,'seconds':spectrum.n/1e6,
                                 'candidates':spectrum.total,'accepted':spectrum.accepted,
                                 'threshold_codes':threshold,'blocks':decoder.sequence})
                    last_progress=time.monotonic()
                if not quiet and time.monotonic()-last>5:
                    print(json.dumps({'sampled_s':decoder.sequence*2048/1e6,'candidates':spectrum.total,
                                      'accepted':spectrum.accepted,'verified_blocks':decoder.sequence}),flush=True)
                    last=time.monotonic()
        if decoder.buf:raise ValueError('Incomplete terminal data')
        expected=(round(seconds*1000)*1000+2047)//2048
        if (not stop_sent and decoder.sequence!=expected) or (stop_sent and not 1<=decoder.sequence<=expected):
            raise ValueError('Unexpected run length')
        record['completed']=True
        record['stop_reason']='user_stop' if stop_sent else 'duration'
    except BaseException as e:
        record['error']=repr(e)
        if started:
            record['failure_recovery']=stop_and_drain(fd,out)
        raise
    finally:
        record.update(finished=datetime.datetime.now().astimezone().isoformat(),
                      wall_seconds=time.monotonic()-t0,blocks=decoder.sequence,
                      verified_sampled_seconds=decoder.sequence*2048/1e6,wire_bytes=decoder.wire_bytes,
                      payload_bytes=decoder.payload_bytes,terminal=decoder.end,
                      spectrum=spectrum.finish(record['completed']))
        raw_path=out/'samples.u16'
        record['stored_raw_samples']=raw_path.stat().st_size//2 if raw_path.exists() else 0
        if decoder.irq_intervals:
            record['irq_interval_cycles_min_max']=[min(decoder.irq_intervals),max(decoder.irq_intervals)]
        (out/'capture.json').write_text(json.dumps(record,indent=2)+'\n')
        if fd is not None:os.close(fd)
        if not quiet:print(json.dumps({k:v for k,v in record.items() if k not in ('spectrum','initial_info')},indent=2),flush=True)
    return record

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=10);p.add_argument('--input',required=True)
    p.add_argument('--threshold',type=float,default=20)
    a=p.parse_args()
    if not .01<=a.seconds<=3600 or not 1<=a.threshold<=2048:p.error('seconds=.01..3600; threshold=1..2048')
    run(a.port,a.out,a.seconds,a.input,a.threshold)
if __name__=='__main__':main()
