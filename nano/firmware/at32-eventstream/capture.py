"""Capture 512-point event windows or the fixed 0.5 MB/s ADC stress mode."""
import argparse
import datetime
import json
import math
from pathlib import Path
import select
import time
from protocol import Serial,Validator,validate_info,header,decode

def run(port,out,seconds,mode,input_condition,threshold=20):
    if not math.isfinite(seconds) or not .001<=seconds<=600:raise ValueError('Duration must be .001 to 600 s')
    if mode not in ('bench','stream') or type(threshold) is not int or not 1<=threshold<=2048:raise ValueError('Bad mode/threshold')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    ms=round(seconds*1000);mode_id=1 if mode=='bench' else 2
    record=dict(started=datetime.datetime.now().astimezone().isoformat(),mode=mode,requested_seconds=ms/1000,
        input=input_condition,completed=False,stored_raw_samples=0,
        note='Benchmark deliberately transmits 512/8192 samples; event mode sends triggered windows only. Neither file is a contiguous waveform. No spectrum/energy calibration claimed.')
    serial=None;t0=None;begun=False;terminal=False;validator=None;last_progress=-30
    try:
        with (out/'wire.bin').open('wb') as wire,(out/'windows.u16').open('wb') as raw,(out/'windows.jsonl').open('w') as index:
            serial=Serial(port,wire);info=json.loads(serial.command('INFO'));validate_info(info);record['initial_info']=info
            session=info['session']+1
            ack=serial.command(f'{mode.upper()} {ms} {threshold}')
            if ack!=f'OK {mode.upper()} {ms} {session}':raise ValueError('Start acknowledgement mismatch: '+ack)
            begun=True;t0=time.monotonic();deadline=t0+ms/1000+10
            validator=Validator(session,mode_id,ms,threshold,info['fw'])
            while not terminal:
                while len(serial.buf)<64:
                    now=time.monotonic()
                    if now>=deadline:raise TimeoutError('No complete acquisition terminal frame')
                    if now-t0-last_progress>=30:
                        last_progress=now-t0
                        print(json.dumps(dict(elapsed_s=round(now-t0,3),packets=validator.packets,
                            payload_bytes=validator.payload_bytes,payload_Bps=round(validator.payload_bytes/max(now-t0,.001)))),flush=True)
                    if select.select([serial.fd],[],[],min(.1,deadline-now))[0]:serial.fill(deadline)
                raw_header=serial.exact(64);h=header(raw_header)
                payload=serial.exact(h['length']);size=64+h['length']+4
                trailer=serial.exact(4+(1 if size%64==0 else 0))
                h=decode(raw_header,payload,trailer)
                if h['kind']==3:
                    terminal=True;record['device_result']=json.loads(payload)
                result=validator.accept(h,payload)
                if terminal:break
                h['stored_sample_offset']=record['stored_raw_samples']
                raw.write(payload);index.write(json.dumps(h)+'\n');record['stored_raw_samples']+=512
            final=json.loads(serial.command('INFO'));validate_info(final);record['final_info']=final
            if final['fw']!=info['fw'] or final['session']!=session or final['last_errors'] or final['has_result']!=1:raise ValueError('Final state mismatch')
            record['completed']=True
    except BaseException as exc:
        record['error']=repr(exc)
        if serial is not None and begun and not terminal:
            try:
                with (out/'wire.bin').open('ab') as diagnostic_wire:
                    serial.wire=diagnostic_wire
                    serial.write('STOP')
                    # Preserve terminal diagnostics without resynchronizing or
                    # promoting a failed run to a valid acquisition.
                    until=time.monotonic()+3
                    while time.monotonic()<until:
                        rh=serial.exact(64,timeout=max(.01,until-time.monotonic()));dh=header(rh)
                        body=serial.exact(dh['length'],timeout=max(.01,until-time.monotonic()))
                        size=64+dh['length']+4
                        tail=serial.exact(4+(1 if size%64==0 else 0),timeout=max(.01,until-time.monotonic()))
                        decode(rh,body,tail)
                        if dh['kind']==3:
                            record['device_result']=json.loads(body);break
            except Exception as diagnostic_exc:record['diagnostic_error']=repr(diagnostic_exc)
            finally:serial.wire=None
        raise
    finally:
        if serial is not None:serial.close()
        wall=time.monotonic()-t0 if t0 is not None else 0
        record['wall_seconds']=wall;record['finished']=datetime.datetime.now().astimezone().isoformat()
        if validator:
            record.update(received_packets=validator.packets,payload_bytes=validator.payload_bytes,
                data_frame_bytes=validator.wire_bytes,payload_Bps=validator.payload_bytes/wall if wall else 0,
                data_frame_Bps=validator.wire_bytes/wall if wall else 0)
        if record['completed']:
            d=record['device_result'];record['nominal_sampled_seconds']=d['blocks']*4096/4e6
            record['payload_Bps_per_device_second']=validator.payload_bytes/record['nominal_sampled_seconds']
            record['copy_deadline_margin_us']=(147456-d['copy_end_max_cycles'])/144
        (out/'capture.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(record,ensure_ascii=False,indent=2),flush=True)
    return record

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True);p.add_argument('--out',required=True)
    p.add_argument('--seconds',type=float,required=True);p.add_argument('--mode',choices=['bench','stream'],required=True)
    p.add_argument('--condition',required=True);p.add_argument('--threshold',type=int,default=20)
    a=p.parse_args();run(a.port,a.out,a.seconds,a.mode,a.condition,a.threshold)
