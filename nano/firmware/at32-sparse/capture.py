"""Capture selected 4 MS/s raw waveform contexts and process spectra on the PC.

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
try:
    from .protocol import Decoder
    from .spectrum import Spectrum
except ImportError:
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

def run(port,out,seconds,input_condition,threshold=64,stall_seconds=0,
        stop_event=None,on_progress=None,on_event=None,quiet=False):
    if not .01<=seconds<=3600 or not 1<=threshold<=2048 or threshold!=int(threshold):
        raise ValueError('seconds=.01..3600; threshold=integer 1..2048')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    decoder=Decoder();spectrum=Spectrum(out,threshold,on_event=on_event)
    record={'started':datetime.datetime.now().astimezone().isoformat(),'port':port,
            'input':input_condition,'requested_seconds':seconds,'completed':False,
            'host_processing':'MCU continuously samples 4 MS/s and selects negative pulse contexts plus periodic baselines. Selected raw samples are lossless; energy extraction and histogramming run on PC. This is NOT a complete raw stream.'}
    fd=None;started=False;stop_sent=False;t0=time.monotonic();last_progress=t0
    try:
        fd=os.open(port,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK);tty.setraw(fd)
        os.write(fd,b'INFO\n');info=json.loads(line(fd));record['initial_info']=info
        if info.get('fw')!='0.4.4' or info.get('board')!='Aster MCA Nano AT32 v0.3' or info['adc_fault'] or info.get('clock_fault',0) or info.get('selector_fault',1):
            raise ValueError('Unexpected firmware/board state')
        os.write(fd,f'THRESHOLD {int(threshold)}\n'.encode())
        selected=json.loads(line(fd));record['selection_info']=selected
        if selected['selection_threshold']!=int(threshold) or selected['sample_rate_hz']!=4000000:
            raise ValueError('Wrong selector/rate configuration')
        os.write(fd,f'STREAM {round(seconds*1000)}\n'.encode())
        if line(fd)!='OK STREAM':raise ValueError('Stream not acknowledged')
        started=True;t0=time.monotonic();deadline=t0+seconds+8;last=t0
        if stall_seconds:time.sleep(stall_seconds)
        with (out/'stream.asts').open('wb') as wire,(out/'selected-samples.u16').open('wb') as rawfile,(out/'blocks.jsonl').open('w') as headers:
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
                    rawfile.write(raw);headers.write(json.dumps(meta)+'\n');spectrum.feed(raw,meta['first_sample'])
                if on_progress and time.monotonic()-last_progress>=.25:
                    on_progress({'samples':decoder.completed*4096,'seconds':decoder.completed*4096/4e6,
                                 'candidates':spectrum.total,'accepted':spectrum.accepted,
                                 'threshold_codes':threshold,'blocks':decoder.sequence})
                    last_progress=time.monotonic()
                if not quiet and time.monotonic()-last>5:
                    print(json.dumps({'sampled_s':decoder.completed*4096/4e6,'candidates':spectrum.total,
                                      'accepted':spectrum.accepted,'verified_blocks':decoder.sequence}),flush=True)
                    last=time.monotonic()
        if decoder.buf:raise ValueError('Incomplete terminal data')
        expected=(round(seconds*1000)*4000+4095)//4096
        if (not stop_sent and decoder.completed!=expected) or (stop_sent and not 1<=decoder.completed<=expected):
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
                      verified_sampled_seconds=decoder.completed*4096/4e6 if record['completed'] else 0,
                      observed_dma_seconds=decoder.completed*4096/4e6,wire_bytes=decoder.wire_bytes,
                      payload_bytes=decoder.payload_bytes,terminal=decoder.end,
                      spectrum=spectrum.finish(record['completed'],decoder.completed*4096))
        raw_path=out/'selected-samples.u16'
        record['stored_raw_samples']=raw_path.stat().st_size//2 if raw_path.exists() else 0
        record['selected_sample_fraction']=decoder.selected_samples/(decoder.completed*4096) if decoder.completed else None
        (out/'capture.json').write_text(json.dumps(record,indent=2)+'\n')
        if fd is not None:os.close(fd)
        if not quiet:print(json.dumps({k:v for k,v in record.items() if k not in ('spectrum','initial_info')},indent=2),flush=True)
    return record

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=10);p.add_argument('--input',required=True)
    p.add_argument('--threshold',type=float,default=64)
    a=p.parse_args()
    if not .01<=a.seconds<=3600 or not 1<=a.threshold<=2048:p.error('seconds=.01..3600; threshold=integer 1..2048')
    run(a.port,a.out,a.seconds,a.input,a.threshold)
if __name__=='__main__':main()
