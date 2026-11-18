"""Verify one guarded 4096-sample RAW DMA snapshot at the reported profile."""
from pathlib import Path
import argparse
import glob
import importlib.util
import json
import math
import os
import struct
import zlib

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('transport',HERE.parent/'at32-bringup/read_baseline.py')
transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    ports=glob.glob('/dev/cu.usbmodem*');assert len(ports)==1
    args.output.mkdir(parents=True,exist_ok=False)
    result={'completed':False,'port':ports[0]};ser=None
    try:
        ser=transport.Serial(ports[0])
        info=json.loads(ser.command('PHINFO'));result['initial']=info
        assert info['fw']=='0.4.1-fast.4' and info['fault']==0 and info['selftest']==15
        head=json.loads(ser.command('PHRAW'));result['header']=head
        assert head['type']=='phraw' and head['n']==4096 and head['channel']=='RAW'
        assert head['fault']==0 and head['core_hz']==144000000
        profiles={72000000:(4000000,36),36000000:(2000000,72),24000000:(1000000,144),12000000:(500000,288)}
        rate,step=profiles[info['adc_hz']]
        assert head['adc_hz']==info['adc_hz'] and head['sample_rate_hz']==rate and head['timer_ticks']==step
        raw=ser.exact(head['n']*2);(args.output/'raw.bin').write_bytes(raw)
        assert ser.exact(2)==b'\r\n'
        data=struct.unpack('<4096H',raw)
        calculated={'min':min(data),'max':max(data),'sum':sum(data),
                    'sum_sq':sum(x*x for x in data),'crc32':zlib.crc32(raw)}
        assert all(head[k]==v for k,v in calculated.items()) and max(data)<=4095
        nominal=head['n']*head['timer_ticks']
        error=(head['elapsed_cycles']-nominal)/nominal
        assert abs(error)<.01
        mean=sum(data)/len(data)
        result['summary']={'mean_code':mean,'rms_code':math.sqrt(sum(x*x for x in data)/len(data)-mean**2),
                           'crc_and_statistics_verified':True,'duration_error_percent':error*100,
                           'configured_rate_hz':head['sample_rate_hz'],
                           'mcu_duration_based_rate_hz':len(data)*head['core_hz']/head['elapsed_cycles']}
        final=json.loads(ser.command('PHINFO'));result['final']=final
        assert final['hold']==1 and final['reset']==1 and final['fault']==0
        result['completed']=True
        print(json.dumps(result,indent=2),flush=True)
    except Exception as e:
        result['error']=repr(e);raise
    finally:
        if ser is not None:os.close(ser.fd)
        (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
