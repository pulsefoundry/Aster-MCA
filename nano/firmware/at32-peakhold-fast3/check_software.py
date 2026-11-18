"""Host protocol checks with fake transport; never opens a board."""
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import io
import json
import os
import struct
import sys
import zlib

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('read_timing',HERE/'read_timing.py')
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
profiles={72:(4000000,36),36:(2000000,72),24:(1000000,144),12:(500000,288)}
raw=struct.pack('<16I',0,770,769,771,774,1131,1130,1129,1129,1128,1100,1700,770,0,5000,1)

class Fake:
    def __init__(self,port):self.fd=os.open(os.devnull,os.O_RDONLY);self.part=0
    def command(self,c):
        if c=='PING':return 'PONG'
        if c.startswith('PHCAP '):return json.dumps(head)
        return json.dumps(info)
    def exact(self,n):
        self.part+=1
        data=raw if self.part==1 else b'\r\n'
        assert n==len(data)
        return data

reader.transport.Serial=Fake
reader.glob.glob=lambda pattern:['/fake/board']
checks=0
with TemporaryDirectory() as tmp:
    for adc,(rate,step) in profiles.items():
        # External trigger spacing >=18 ADC clocks; all timer divisions exact.
        assert 144000000//step==rate and adc*1000000>=rate*18
        # The baseline window is valid even for a stop before the HOLD ISR.
        for phase in range(step):
            for stop_age in [200,1200,4800]:
                hold_age=5000
                age=(hold_age+((stop_age-hold_age)&0xffffffff))&0xffffffff
                assert age==stop_age
                post=(age+step-1)//step
                pos=(phase+post)%256
                end=(pos-post-8)%256
                assert end==(phase-8)%256
        for sample in [49,95,185,495]:
            for early in [False,True]:
                mode='trigger' if early else 'hold'
                info=dict(type='phinfo',fw='0.4.1-fast.3',fault=0,selftest=15,timer_hz=144000000,
                          adc_hz=adc*1000000,raw_rate_hz=rate,raw_timer_ticks=step,
                          peak_sample_cycles_x2=sample,clock_fault=0,hold=1,reset=1,raw_stop_phase=mode)
                head=dict(type='phcapture',fw=info['fw'],words=16,bytes=64,n=1,requested=1,
                          baseline_method='dma_pretrigger_mean32_guard8',adc_hz=info['adc_hz'],
                          raw_rate_hz=rate,core_hz=144000000,peak_sample_cycles_x2=sample,raw_stop_phase=mode,
                          dma_stop_n=1,baseline_rejects=0,timeouts=0,c1_irq_n=int(early),c1_ignored_n=0,
                          dma_stop_before_hold_irq_n=int(early),dma_stop_minus_hold_irq_min_cycles=-500 if early else 500,
                          dma_stop_minus_hold_irq_max_cycles=-500 if early else 500,
                          dma_stop_minus_hold_irq_mean_cycles=-500 if early else 500,fault=0,selftest=15,
                          within_batch_busy_min_cycles=0,within_batch_busy_mean_cycles=0,
                          within_batch_busy_max_cycles=0,crc32=zlib.crc32(raw))
                for bad in [None,'crc','rate']:
                    out=Path(tmp)/str(checks)
                    sys.argv=['read_timing.py','--events','1','--expect-events','--adc-mhz',str(adc),
                              '--peak-sample-x2',str(sample),'--stop-phase','early' if early else 'late','--output',str(out)]
                    if bad=='crc':head['crc32']^=1
                    if bad=='rate':head['raw_rate_hz']+=1
                    try:
                        with redirect_stdout(io.StringIO()):reader.main()
                        assert bad is None,'Invalid transport metadata accepted'
                        assert json.loads((out/'result.json').read_text())['completed']
                    except AssertionError:
                        if bad is None:raise
                        assert not json.loads((out/'result.json').read_text())['completed']
                    finally:
                        head['crc32']=zlib.crc32(raw);head['raw_rate_hz']=rate
                    checks+=1
print(f'PASS: {checks} host cases; all ADC/profile combinations, signed stop timing, CRC/rate rejection; index model at all timer phases')
