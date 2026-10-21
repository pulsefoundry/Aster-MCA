"""Idle-only 4096-point raw diagnostics. The second DMA half absorbs late conversions."""
import argparse
import datetime
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import time
import zlib

HERE=Path(__file__).resolve().parent
if 'aster_histogram' not in sys.modules:
    folder=HERE.parent/'at32-histogram'
    spec=importlib.util.spec_from_file_location('aster_histogram',folder/'__init__.py',submodule_search_locations=[str(folder)])
    module=importlib.util.module_from_spec(spec);sys.modules['aster_histogram']=module;spec.loader.exec_module(module)
from aster_histogram.protocol import Serial,validate_info

N=4096
RATE=4000000


def validate_raw_info(info):
    validate_info(info)
    if info.get('fw')!='0.8.2' or info.get('supports_raw')!=1 or info.get('raw_n')!=N:
        raise ValueError('需要支持短波形诊断的v0.8.2固件')
    if type(info.get('raw_capture_id')) is not int or not 0<=info['raw_capture_id']<=0xffffffff:
        raise ValueError('缺少原始波形采集序号')
    if info.get('raw_last_errors')!=0:raise ValueError('上次原始波形采集故障')


def validate_raw(header,raw,expected_id):
    expected=dict(type='raw',method='diagnostic_snapshot',fw='0.8.2',id=expected_id,
        n=N,sample_rate_hz=RATE,core_hz=144000000,adc_hz=72000000,timer_ticks=36,
        sample_cycles_x2=5,nominal_span_cycles=(N-1)*36,dma_buffer_samples=N*2,
        guard_samples=N,errors=0,adc_overrun=0)
    for key,value in expected.items():
        if type(header.get(key)) is not type(value) or header[key]!=value:
            raise ValueError(f'无效短波形字段：{key}={header.get(key)!r}')
    if len(raw)!=N*2:raise ValueError('原始波形长度不符')
    if type(header.get('dma_remaining')) is not int or not N-64<=header['dma_remaining']<=N:
        raise ValueError('DMA停止位置超出保护区')
    values=struct.unpack('<4096H',raw)
    if max(values)>4095:raise ValueError('ADC样本超出12位范围')
    for key,value in dict(crc32=zlib.crc32(raw),min=min(values),max=max(values),
                          sum=sum(values),sum_sq=sum(v*v for v in values)).items():
        if type(header.get(key)) is not int or header[key]!=value:raise ValueError('波形校验失败：'+key)
    elapsed=header.get('elapsed_cycles')
    if type(elapsed) is not int or not N*36<=elapsed<=N*36+1440:
        raise ValueError('短波形采样时长不符')
    mean=sum(values)/N
    return dict(mean_code=mean,rms_code=math.sqrt(max(0,sum(v*v for v in values)/N-mean*mean)),
                sampled_seconds=N/RATE,timing_overhead_cycles=elapsed-N*36,
                checksum_statistics_verified=True)


def run(port,out,segments,input_condition,quiet=False):
    if type(segments) is not int or not 1<=segments<=1000:raise ValueError('segments须为1..1000整数')
    if not str(input_condition).strip():raise ValueError('必须记录当前输入状态')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    record=dict(started=datetime.datetime.now().astimezone().isoformat(),port=port,
        input=input_condition,requested_segments=segments,acquisition_mode='diagnostic_snapshot',
        completed=False,blocks=0,stored_raw_samples=0,
        limitations=['Each 1.024 ms snapshot is followed by an unsampled transfer gap.',
            'No continuous coverage, absolute detector rate or calibrated energy claim.',
            'ADC-only diagnostics cannot rule out out-of-band oscillation.'])
    serial=None;t0=time.monotonic()
    try:
        with (out/'wire.bin').open('wb') as wire,(out/'samples.u16').open('wb') as samples,\
             (out/'blocks.jsonl').open('w') as meta:
            serial=Serial(port,wire)
            info=json.loads(serial.command('INFO'));validate_raw_info(info);record['initial_info']=info
            expected_id=info['raw_capture_id']+1
            for i in range(segments):
                line=serial.command('RAW')
                if line.startswith('ERR'):raise ValueError('设备拒绝短波形采集：'+line)
                header=json.loads(line)
                if header.get('type')!='raw' or header.get('n')!=N:raise ValueError('原始波形头格式错误')
                raw=serial.exact(N*2)
                if serial.exact(2)!=b'\r\n':raise ValueError('原始波形结束符错误')
                trailer=serial.line()
                if trailer!=f'END {zlib.crc32((line+chr(13)+chr(10)).encode()):08x}':
                    raise ValueError('原始波形元数据CRC错误')
                verified=validate_raw(header,raw,expected_id)
                meta.write(json.dumps(dict(header,**verified,segment_index=i,stored_sample_offset=i*N))+'\n')
                samples.write(raw);expected_id+=1;record['blocks']+=1
            final=json.loads(serial.command('INFO'));validate_raw_info(final);record['final_info']=final
            if final['raw_capture_id']!=expected_id-1:raise ValueError('波形序号不连续')
            for key in ('session','has_result','last_errors'):
                if final[key]!=info[key]:raise ValueError('诊断采集改变了原能谱状态：'+key)
            record['completed']=True
    except BaseException as exc:
        record['error']=repr(exc);raise
    finally:
        if serial is not None:serial.close()
        wall=time.monotonic()-t0;sampled=record['blocks']*N/RATE
        record.update(finished=datetime.datetime.now().astimezone().isoformat(),wall_seconds=wall,
            stored_raw_samples=record['blocks']*N,observed_sampled_seconds=sampled,
            verified_sampled_seconds=sampled if record['completed'] else 0,
            unsampled_wall_seconds=max(0,wall-sampled))
        (out/'capture.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        if not quiet:print(json.dumps({k:record[k] for k in ('completed','blocks','verified_sampled_seconds','wall_seconds')}),flush=True)
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--segments',type=int,default=100);parser.add_argument('--input',required=True)
    args=parser.parse_args();run(args.port,args.out,args.segments,args.input)
