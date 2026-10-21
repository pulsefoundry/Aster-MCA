import ctypes as c
import csv
import json
import math
import os
from pathlib import Path
import pty
import random
import select
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import zlib
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"at32-histogram"))
from capture import run
from protocol import validate_result, validate_info

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def info(session=0,has_result=0):
    return dict(type='info',board='Aster MCA Nano AT32 v0.3',mcu='AT32F423CCT7',fw='0.6.0',
        method='onboard_histogram',core_hz=144000000,adc_hz=72000000,sample_rate_hz=4000000,
        timer_ticks=36,sample_cycles_x2=5,channels=2048,dma_samples=8192,ldo_mv=1300,
        adc_on=1,adc_fault=0,clock_fault=0,bist_fault=0,xtest=9,session=session,last_errors=0,
        has_result=has_result,bist_max_cycles=80000)

def result(ms=10,stop=False):
    bins=[0]*2048;bins[474]=7;raw=struct.pack('<2048I',*bins)
    blocks=(ms*4000+4095)//4096
    if stop:blocks=min(2,blocks)
    h=dict(type='spectrum',fw='0.6.0',method='mcu-area8-4M-v0.1',session=1,requested_ms=ms,
        threshold_codes=20,channels=2048,sample_rate_hz=4000000,core_hz=144000000,bin_width_code_us=1,
        blocks=blocks,processed_blocks=blocks,engine_blocks=blocks*64,fine_blocks=2,errors=0,
        adc_overrun=0,tail_samples_excluded=1,stop_user=int(stop),acquisition_ms=round(blocks*1.024),
        span_cycles_mod32=(blocks*4096*36+80)&0xffffffff,irq_delta_min=147450,irq_delta_max=147462,
        process_max_cycles=80000,latency_max_cycles=500,candidates=8,accepted=7,rejected=1,
        underflow=0,overflow=0,pending_excluded=0,rejection_flags=[1,0,0,0,0],minimum=1800,maximum=2060,
        histogram_crc32=zlib.crc32(raw))
    return h,raw

class Event(c.Structure):
    _fields_=[('trigger',c.c_uint64),*[(x,c.c_double) for x in ['baseline','peak','area4','area8','area16','pre_rms']],('flags',c.c_uint32),('half_width',c.c_uint32)]

class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (HERE/'build').mkdir(exist_ok=True)
        for src,name in [(HERE/'host_engine.c','libasterhist'),(HERE.parent/'at32-burst/host_dsp.c','libreference')]:
            subprocess.run(['cc','-O3','-Wall','-Wextra','-Werror','-dynamiclib',str(src),'-o',str(HERE/f'build/{name}.dylib')],check=True)
        cls.lib=c.CDLL(str(HERE/'build/libasterhist.dylib'));lib=cls.lib
        lib.engine_new.argtypes=[c.c_uint];lib.engine_new.restype=c.c_void_p
        lib.engine_free.argtypes=[c.c_void_p];lib.engine_feed.argtypes=[c.c_void_p,c.c_void_p,c.c_uint]
        lib.engine_counts.argtypes=lib.engine_stats.argtypes=[c.c_void_p,c.c_void_p]
        cls.ref=c.CDLL(str(HERE/'build/libreference.dylib'));ref=cls.ref
        ref.processor_new.argtypes=[c.c_double];ref.processor_new.restype=c.c_void_p
        ref.processor_free.argtypes=[c.c_void_p];ref.processor_pending.argtypes=[c.c_void_p]
        ref.processor_feed.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(Event)];ref.processor_feed.restype=c.c_size_t

    def compare(self,values,threshold=20):
        raw=(c.c_uint16*len(values))(*values);s=self.lib.engine_new(threshold);r=self.ref.processor_new(threshold)
        try:
            # Exercise state across DMA and ring boundaries, not just a single call.
            for off in range(0,len(values),64):self.lib.engine_feed(s,c.byref(raw,off*2),64)
            counts=(c.c_uint32*2048)();stats=(c.c_uint32*16)()
            self.lib.engine_counts(s,counts);self.lib.engine_stats(s,stats)
            es=(Event*(len(values)//59+2))();n=self.ref.processor_feed(r,raw,len(values),es)
            expected=[0]*2048;accepted=under=over=0;reasons=[0]*5
            for e in es[:n]:
                for bit in range(5):reasons[bit]+=bool(e.flags&(1<<bit))
                if not e.flags:
                    accepted+=1;index=math.floor(e.peak)
                    if index<0:under+=1
                    elif index>=2048:over+=1
                    else:expected[index]+=1
            self.assertEqual(list(counts),expected)
            self.assertEqual(list(stats[:7]),[n,accepted,n-accepted,under,over,self.ref.processor_pending(r),0])
            self.assertEqual(list(stats[11:]),reasons)
            return list(counts),list(stats)
        finally:self.lib.engine_free(s);self.ref.processor_free(r)

    def test_pulse_positions_ring_dma_and_end_boundaries(self):
        for pos in [270,271,272,273,319,511,512,4094,4095,4096,8191,16320,16324,16383]:
            y=[2048]*16384
            for i,v in enumerate([2000,1900,1800,1900,2000]):
                if pos+i<len(y):y[pos+i]=v
            self.compare(y)

    def test_baseline_noise_pileup_clipping_and_recovery(self):
        rng=random.Random(423)
        for threshold in [1,20,63,2048]:
            y=[2048+rng.randrange(-12,13) for _ in range(32768)]
            for pos in range(300,32000,277):
                a=rng.choice([10,30,100,300,1000,2100])
                for k in range(24):y[pos+k]=max(0,2048-round(a*math.exp(-k/4)))
            y[15000:15500]=[4095]*500;y[20000:20040]=[0]*40
            self.compare(y,threshold)

    def test_selftest_known_peak_and_histogram_limits(self):
        y=[2048]*4096
        for p in [512,1536,2560]:y[p:p+5]=[2000,1900,1800,1900,2000]
        bins,stats=self.compare(y);self.assertEqual(bins[248],3);self.assertEqual(stats[1],3)

    def test_long_continuous_skipped_blocks(self):
        # Exercise continuous state through millions of samples and a change
        # from mostly skipped blocks to dense fine processing.
        y=[2048]*(2**21+4096)
        for p in range(512,len(y)-64,4096):y[p:p+5]=[2000,1900,1800,1900,2000]
        rng=random.Random(601)
        for p in range(2**21-2048,len(y)):y[p]=2048+rng.randrange(-12,13)
        for p in [2**21-273,2**21-1,2**21+511,2**21+2048]:
            y[p:p+5]=[2000,1900,1800,1900,2000]
        self.compare(y)

    def test_saved_source_and_background_exact_histogram(self):
        evidence={}
        for folder in ['capture-20261015-001908-112177','capture-20261015-001338-073683']:
            p=ROOT/'work/at32-gui-recordings'/folder
            if not (p/'samples.u16').exists():self.skipTest('Saved bench data unavailable')
            expected=[0]*2048;actual=[0]*2048;totals=[0]*16
            with (p/'events.csv').open() as events:
                for e in csv.DictReader(events):
                    if int(e['flags'])==0 and 0<=float(e['peak_code'])<2048:expected[math.floor(float(e['peak_code']))]+=1
            with (p/'samples.u16').open('rb') as f:
                while raw:=f.read(16384):
                    s=self.lib.engine_new(20);self.lib.engine_feed(s,c.c_char_p(raw),8192)
                    bins=(c.c_uint32*2048)();stats=(c.c_uint32*16)();self.lib.engine_counts(s,bins);self.lib.engine_stats(s,stats);self.lib.engine_free(s)
                    actual=[a+b for a,b in zip(actual,bins)];totals=[a+b for a,b in zip(totals,stats)]
            self.assertEqual(actual,expected)
            summary=json.loads((p/'spectrum-summary.json').read_text())
            self.assertEqual(totals[:3],[summary['candidates'],summary['accepted'],summary['candidates']-summary['accepted']])
            self.assertEqual(totals[5],summary['boundary_partial_events_excluded'])
            evidence[folder]=dict(histogram_exact=True,candidates=totals[0],accepted=totals[1],rejected=totals[2],
                underflow=totals[3],overflow=totals[4],in_range=sum(actual),scan_blocks=totals[7],fine_blocks=totals[8],
                scope='Native execution of the same integer engine; ARM timing/SIMD require device self-test and acquisition validation.')
        (HERE/'build/replay-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')

class ProtocolTests(unittest.TestCase):
    def test_result_conservation_and_long_duration_counter_wrap(self):
        for ms in [1,10,1000,180000,3600000]:
            h,raw=result(ms);s=validate_result(h,raw,1,ms,20);self.assertEqual(s['samples'],h['blocks']*4096)
    def test_reject_crc_counters_deadline_and_early_finish(self):
        h,raw=result()
        for key,value in [('histogram_crc32',0),('blocks',1),('errors',8),('accepted',8),('processed_blocks',0),('adc_overrun',1),('span_cycles_mod32',0),('process_max_cycles',147456),('stop_user',1)]:
            with self.subTest(key=key),self.assertRaises(ValueError):validate_result({**h,key:value},raw,1,10,20)
        bad=bytearray(raw);bad[0]^=1
        with self.assertRaises(ValueError):validate_result(h,bytes(bad),1,10,20)
    def test_device_fault_rejected(self):
        for fw in ['0.6.0','0.6.1','0.6.2','0.6.3']:
            validate_info({**info(),'fw':fw,'snapshot_samples':4096})
            h,raw=result();validate_result({**h,'fw':fw,'snapshot_samples':4096,'copy_max_cycles':10000,'copy_end_max_cycles':10500},raw,1,10,20)
        for key in ['bist_fault','clock_fault','adc_fault']:
            with self.assertRaises(ValueError):validate_info({**info(),key:1})
        with self.assertRaises(ValueError):validate_info({**info(),'fw':'0.6.4'})

    def test_snapshot_allows_processing_burst_but_rejects_overwritten_input(self):
        h,raw=result()
        h.update(fw='0.6.2',snapshot_samples=4096,copy_max_cycles=16000,
                 copy_end_max_cycles=60000,process_max_cycles=190000,latency_max_cycles=44000)
        validate_result(h,raw,1,10,20)
        for key,value in [('copy_end_max_cycles',147456),('copy_max_cycles',147456),
                          ('snapshot_samples',8192),('copy_end_max_cycles',0),
                          ('latency_max_cycles',147456),('errors',8),('processed_blocks',0)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_result({**h,key:value},raw,1,10,20)
        with self.assertRaises(ValueError):validate_result({**h,'fw':'0.6.1'},raw,1,10,20)

    def simulate(self,stop=False,corrupt=False):
        master,slave=pty.openpty();port=os.ttyname(slave);quit=threading.Event();request=threading.Event();failures=[];sent_at=[]
        def device():
            buf=b'';active=False;sent=False;ms=10;when=0
            try:
                while not quit.is_set():
                    userstop=False
                    if select.select([master],[],[],.005)[0]:buf+=os.read(master,4096)
                    while b'\n' in buf:
                        cmd,buf=buf.split(b'\n',1)
                        if cmd==b'INFO':os.write(master,json.dumps(info(int(sent),int(sent))).encode()+b'\r\n')
                        elif cmd.startswith(b'ACQUIRE '):
                            ms=int(cmd.split()[1]);active=True;when=time.monotonic()+.08
                            os.write(master,f'OK ACQUIRE {ms} 1\r\n'.encode())
                        elif cmd==b'STOP' and active:userstop=True
                    if active and ((not stop and time.monotonic()>=when) or userstop):
                        h,raw=result(ms,userstop);line=json.dumps(h).encode()+b'\r\n';crc=zlib.crc32(line)^(1 if corrupt else 0)
                        packet=line+raw+f'\r\nEND {crc:08x}\r\n'.encode();sent_at.append(time.monotonic())
                        for i in range(0,len(packet),31):os.write(master,packet[i:i+31])
                        active=False;sent=True
            except BaseException as e:failures.append(e)
        thread=threading.Thread(target=device);thread.start();updates=[]
        def progress(u):
            updates.append(u)
            if stop:request.set()
        try:
            with tempfile.TemporaryDirectory() as folder:
                out=Path(folder)/'record'
                if corrupt:
                    with self.assertRaises(ValueError):run(port,out,.01,'simulated device',stop_event=request,on_progress=progress,quiet=True)
                    self.assertFalse(json.loads((out/'capture.json').read_text())['completed'])
                else:
                    r=run(port,out,1 if stop else .01,'simulated device',stop_event=request,on_progress=progress,quiet=True)
                    self.assertTrue(r['completed']);self.assertEqual(r['stop_reason'],'user_stop' if stop else 'duration')
                    self.assertEqual(r['histogram']['counts']['peak' if r['initial_info']['fw']=='0.8.0' else 'area8'][474],7)
                    self.assertFalse((out/'events.csv').exists());self.assertFalse((out/'samples.u16').exists())
                    self.assertTrue(updates);self.assertTrue(all(u['accepted'] is None and u['seconds']==0 for u in updates))
        finally:quit.set();thread.join(2);os.close(master);os.close(slave)
        self.assertFalse(failures)
    def test_fragmented_final_result_after_silence(self):self.simulate()
    def test_manual_stop_returns_partial_spectrum(self):self.simulate(stop=True)
    def test_metadata_checksum_failure_invalidates_record(self):self.simulate(corrupt=True)

LEGACY_INFO=info
LEGACY_RESULT=result

class PeakProtocolTests(unittest.TestCase):
    def peak_info(self, session=0, has_result=0):
        return dict(LEGACY_INFO(session,has_result),fw='0.8.0',snapshot_samples=4096,
                    energy_estimator='sampled_peak',bin_width_adc_codes=1)

    def peak_result(self,ms=10,stop=False):
        header,raw=LEGACY_RESULT(ms,stop)
        del header['bin_width_code_us']
        header.update(fw='0.8.0',method='mcu-peak-4M-v0.1',snapshot_samples=4096,
                      energy_estimator='sampled_peak',bin_width_adc_codes=1,
                      copy_max_cycles=10000,copy_end_max_cycles=10500)
        return header,raw

    def test_peak_units_and_method_are_strict(self):
        validate_info(self.peak_info())
        h,raw=self.peak_result();summary=validate_result(h,raw,1,10,20)
        self.assertEqual(summary['method'],'mcu-peak-4M-v0.1')
        for key,value in [('method','mcu-area8-4M-v0.1'),('bin_width_adc_codes',2),
                          ('energy_estimator','area8'),('bin_width_code_us',1),
                          ('copy_end_max_cycles',147456),('errors',8)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_result({**h,key:value},raw,1,10,20)

    def test_peak_info_requires_correct_units(self):
        for key in ('energy_estimator','bin_width_adc_codes','snapshot_samples'):
            bad=self.peak_info();del bad[key]
            with self.subTest(key=key),self.assertRaises(ValueError):validate_info(bad)

    def test_timed_peak_capture_with_fragmented_result(self):
        from unittest.mock import patch
        with patch(__name__+'.info',self.peak_info),patch(__name__+'.result',self.peak_result):
            ProtocolTests.simulate(self)

if __name__=='__main__':unittest.main()
