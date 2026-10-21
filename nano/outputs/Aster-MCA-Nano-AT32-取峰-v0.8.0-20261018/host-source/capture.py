"""Timed, on-device 2048-channel acquisition; no spectra until the board stops."""
import datetime
import json
import math
from pathlib import Path
import select
import struct
import time
import zlib
try:
    from .protocol import Serial, validate_info, validate_result, histogram_snapshot
except ImportError:
    from protocol import Serial, validate_info, validate_result, histogram_snapshot


def run(port, out, seconds, input_condition, threshold=20, stop_event=None,
        on_progress=None, on_event=None, quiet=False):
    if not math.isfinite(seconds) or not .001 <= seconds <= 3600:
        raise ValueError('采集时长须为 0.001–3600 秒')
    if not math.isfinite(threshold) or threshold != int(threshold) or not 1 <= threshold <= 2048:
        raise ValueError('板上触发门限须为 1–2048 的整数')
    milliseconds=round(seconds*1000);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    record=dict(started=datetime.datetime.now().astimezone().isoformat(),port=port,input=input_condition,
        requested_seconds=milliseconds/1000,duration_basis='device_sample_clock',acquisition_mode='histogram',
        completed=False,stored_raw_samples=0,host_processing='MCU 8 us signed integration into 2048 bins; one final histogram; no waveform/event list stored.')
    serial=None;t0=None;summary=None;histogram=None;stop_sent=False;started=False;stopped=False
    try:
        with (out/'wire.bin').open('wb') as wire:
            serial=Serial(port,wire)
            info=json.loads(serial.command('INFO'));validate_info(info);record['initial_info']=info
            if info['fw']=='0.8.0':
                record['host_processing']='MCU frozen-baseline sampled pulse height into 2048 bins; one final histogram; no waveform/event list stored.'
            expected_session=info['session']+1
            ack=serial.command(f'ACQUIRE {milliseconds} {int(threshold)}')
            if ack!=f'OK ACQUIRE {milliseconds} {expected_session}':raise ValueError('设备未确认定时采集：'+ack)
            started=True;t0=time.monotonic();next_progress=0;deadline=t0+milliseconds/1000+10
            # Keep buffering a fragmented final header; no timed-out line is discarded.
            while b'\n' not in serial.buf:
                now=time.monotonic()
                if stop_event is not None and stop_event.is_set() and not stop_sent:
                    serial.write('STOP');stop_sent=True;deadline=min(deadline,now+10)
                if now>=deadline:raise TimeoutError('板上定时采集结束后未收到结果')
                if on_progress and now>=next_progress:
                    on_progress(dict(awaiting_result=True,wall_seconds=now-t0,
                        remaining_seconds=max(0,milliseconds/1000-(now-t0)),seconds=0,samples=0,
                        candidates=None,accepted=None))
                    next_progress=now+.25
                if select.select([serial.fd],[],[],min(.1,max(0,deadline-now)))[0]:serial.fill(deadline)
            line=serial.line()
            if line.startswith('ERR'):raise ValueError(line)
            header=json.loads(line);record['device_result']=header;stopped=True
            if header.get('fw')!=info['fw']:raise ValueError('采集中固件版本不一致')
            raw=serial.exact(8192)
            if serial.exact(2)!=b'\r\n':raise ValueError('能谱结束标记错误')
            trailer=serial.line()
            if trailer!=f'END {zlib.crc32((line+chr(13)+chr(10)).encode()):08x}':
                raise ValueError('能谱元数据校验失败')
            counts=list(struct.unpack('<2048I',raw));(out/'histogram.u32').write_bytes(raw)
            summary=validate_result(header,raw,expected_session,milliseconds,int(threshold),stop_sent)
            histogram=histogram_snapshot(counts,header)
            final=json.loads(serial.command('INFO'));validate_info(final);record['final_info']=final
            if final['session']!=expected_session or final['last_errors'] or final['has_result']!=1:
                raise ValueError('采集结束状态与返回谱不一致')
            (out/'histogram.json').write_text(json.dumps(histogram)+'\n')
            (out/'spectrum-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
            record['completed']=True
            record['stop_reason']='user_stop' if header['stop_user'] else 'duration'
    except BaseException as exc:
        record['error']=repr(exc)
        if serial is not None and started and not stopped:
            try:serial.write('STOP')
            except OSError:pass
        raise
    finally:
        if serial is not None:serial.close()
        wall=time.monotonic()-t0 if t0 is not None else 0
        sampled=summary['sampled_seconds'] if record['completed'] else 0
        record.update(finished=datetime.datetime.now().astimezone().isoformat(),wall_seconds=wall,
            verified_sampled_seconds=sampled,observed_sampled_seconds=sampled,
            duty_cycle=sampled/wall if wall else 0,spectrum=summary,histogram=histogram)
        (out/'capture.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        if not quiet:print(json.dumps({'completed':record['completed'],'sampled_seconds':sampled,'wall_seconds':wall}),flush=True)
    return record
