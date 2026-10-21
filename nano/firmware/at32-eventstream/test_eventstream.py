import copy
import ctypes as c
import json
from pathlib import Path
import random
import struct
import subprocess
import os
import pty
import tempfile
import threading
import time
import contextlib
import io
import unittest
from protocol import fnv,header,decode,Validator

HERE=Path(__file__).resolve().parent

class Event(c.Structure):
    _fields_=[('trigger',c.c_uint32),('baseline',c.c_uint32),('samples',c.c_uint16*512)]

def buildlib():
    (HERE/'build').mkdir(exist_ok=True)
    libpath=HERE/'build/libeventengine.dylib'
    subprocess.run(['cc','-shared','-fPIC','-O2',str(HERE/'host_engine.c'),'-o',str(libpath)],check=True)
    lib=c.CDLL(str(libpath))
    lib.event_new.argtypes=[c.c_uint32];lib.event_new.restype=c.c_void_p
    lib.event_free.argtypes=[c.c_void_p]
    lib.event_run.argtypes=[c.c_void_p,c.POINTER(c.c_uint16),c.c_uint32,c.POINTER(Event),c.c_uint32]
    lib.event_run.restype=c.c_uint32
    lib.event_counter.argtypes=[c.c_void_p,c.c_uint32];lib.event_counter.restype=c.c_uint32
    lib.host_frame.argtypes=[c.c_void_p]+[c.c_uint32]*9;lib.host_frame.restype=c.c_uint32
    return lib

def oracle(data,threshold=20):
    prefix=[0]
    for x in data:prefix.append(prefix[-1]+x)
    armed=True;next_allowed=0;found=[];suppressed=0
    for k in range(320,len(data)):
        base=prefix[k-16]-prefix[k-272];delta=base-data[k]*256
        if delta<threshold*128:armed=True
        if armed and delta>=threshold*256:
            armed=False
            if k>=next_allowed:found.append((k,base));next_allowed=k+64
            else:suppressed+=1
    return found,suppressed

class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.lib=buildlib()
    def check_data(self,data,chunk=4096):
        found,suppressed=oracle(data)
        expected=[(k,b) for k,b in found if k+192<=len(data)]
        state=self.lib.event_new(20);got=[]
        try:
            for start in range(0,len(data),chunk):
                block=data[start:start+chunk];buf=(c.c_uint16*len(block))(*block)
                events=(Event*(len(block)//64+8))()
                count=self.lib.event_run(state,buf,len(block),events,len(events))
                self.assertNotEqual(count,0xffffffff)
                for e in events[:count]:
                    got.append((e.trigger,e.baseline))
                    self.assertEqual(list(e.samples),data[e.trigger-320:e.trigger+192])
            self.assertEqual(got,expected)
            self.assertEqual(self.lib.event_counter(state,0),len(found))
            self.assertEqual(self.lib.event_counter(state,2),len(found)-len(expected))
            self.assertEqual(self.lib.event_counter(state,3),suppressed)
            self.assertEqual(self.lib.event_counter(state,4),0)
        finally:self.lib.event_free(state)
    def test_flat_and_threshold_noise(self):
        self.check_data([2048]*8192)
        rng=random.Random(423)
        self.check_data([2048+rng.randrange(-4,5) for _ in range(32768)])
    def test_ring_chunk_and_dma_boundaries(self):
        data=[2048]*16384
        for k in (320,511,512,1023,4095,4096+80,8191,16192,16320):
            for j,v in enumerate((2000,1900,1800,1900,2000)):
                if k+j<len(data):data[k+j]=v
        self.check_data(data,64)
        self.check_data(data,4096)
    def test_overlapping_and_holdoff_events(self):
        data=[2048]*8192
        for k in range(512,4096,40):data[k]=1900
        self.check_data(data)
    def test_large_baseline_steps_and_random_pulses(self):
        rng=random.Random(70);data=[]
        for k in range(65536):data.append(2000+(k//2048)%3*30+rng.randrange(-12,13))
        for k in range(511,65000,257):
            for j in range(12):data[k+j]-=int(120*(1-abs(j-5)/7))
        self.check_data(data)
    def test_firmware_frame_packer_matches_independent_python_bytes(self):
        rng=random.Random(71)
        for kind,length in [(1,1024),(2,1024)]+[(3,n) for n in (1,59,60,61,63,64,65,124,1000,1976)]:
            for seq in range(5):
                data=(c.c_uint32*514)(*[0xdeadbeef]*514)
                payload=bytes(rng.randrange(256) for _ in range(length))
                c.memmove(c.addressof(data)+64,payload,length)
                n=self.lib.host_frame(data,kind,17,seq,10240,10560,524288,length,20,0)
                words=[1,kind,17,seq,10240,10560,0 if kind==3 else 512,4_000_000,length,524288,20,0,fnv(payload)]
                h=b'ASTW07\r\n'+struct.pack('<13I',*words);h+=struct.pack('<I',fnv(h))
                expected=h+payload+struct.pack('<I',~fnv(payload)&0xffffffff)
                if len(expected)%64==0:expected+=b'\0'
                actual=c.string_at(c.addressof(data),n)
                self.assertEqual(actual,expected);decode(actual[:64],payload,actual[64+length:])
                self.assertEqual(c.string_at(c.addressof(data)+n,4),bytes.fromhex('efbeadde')[(n%4):]+bytes.fromhex('efbeadde')[:n%4])

def packet(kind=2,seq=0,first=0,trigger=0xffffffff,baseline=0,values=None):
    payload=struct.pack('<512H',*(values if values is not None else [2048]*512))
    words=[1,kind,1,seq,first,trigger,512,4_000_000,len(payload),baseline,20,0,fnv(payload)]
    h=b'ASTW07\r\n'+struct.pack('<13I',*words);h+=struct.pack('<I',fnv(h))
    return h,payload,struct.pack('<I',~fnv(payload)&0xffffffff)

def end_data():
    return dict(type='end',fw='0.7.0',session=1,mode=1,errors=0,requested_ms=2,
        blocks=2,processed_blocks=2,engine_blocks=128,fine_blocks=0,packets=1,payload_bytes=1024,wire_bytes=1092,
        candidates=0,emitted=0,pending_excluded=0,holdoff_crossings=0,queue_high=1,threshold=20,minimum=2048,maximum=2048,
        process_max_cycles=70000,copy_max_cycles=8500,copy_end_max_cycles=9000,latency_max_cycles=500,
        irq_min=147456,irq_max=147456,span_cycles_mod32=2*147456+100,acquisition_ms=2,
        tail_samples_excluded=6,stop_user=0,adc_overrun=0)

class ProtocolTests(unittest.TestCase):
    def test_valid_benchmark(self):
        h,p,t=packet();v=Validator(1,1,2,20)
        v.accept(decode(h,p,t),p);v.finish(end_data())
    def test_corruption(self):
        h,p,t=packet()
        for i in (0,20,60):
            bad=bytearray(h);bad[i]^=1
            with self.assertRaises(ValueError):decode(bytes(bad),p,t)
        with self.assertRaises(ValueError):decode(h,b'\x01'+p[1:],t)
        with self.assertRaises(ValueError):decode(h,p,b'\0'*4)
    def test_sequence_and_benchmark_cadence(self):
        for kwargs in (dict(seq=1),dict(first=8192),dict(trigger=320)):
            h,p,t=packet(**kwargs)
            with self.assertRaises(ValueError):Validator(1,1,2,20).accept(decode(h,p,t),p)
    def test_end_rejects_missing_samples_errors_timing(self):
        h,p,t=packet()
        for key,value in dict(errors=8,processed_blocks=1,engine_blocks=127,packets=2,
            copy_end_max_cycles=147456,latency_max_cycles=147456,span_cycles_mod32=0,
            queue_high=9,adc_overrun=1,payload_bytes=0).items():
            v=Validator(1,1,2,20);v.accept(decode(h,p,t),p);d=end_data();d[key]=value
            with self.assertRaises(ValueError,msg=key):v.finish(d)
    def test_event_baseline_and_overlap(self):
        data=[2048]*640;data[320]=1800;data[384]=1850
        v=Validator(1,2,2,20)
        for seq,k in enumerate((320,384)):
            values=data[k-320:k+192]
            h,p,t=packet(1,seq,k-320,k,sum(values[48:304]),values)
            v.accept(decode(h,p,t),p)
        values=data[128:640];values[100]=2000;values[320]=1800
        h,p,t=packet(1,2,128,448,sum(values[48:304]),values)
        with self.assertRaises(ValueError):v.accept(decode(h,p,t),p)

class CaptureTests(unittest.TestCase):
    def test_fragmented_terminal_and_saved_raw_record(self):
        from capture import run
        from protocol import validate_info
        # PTY emulates transport only. This is not a USB or hardware benchmark.
        master,slave=pty.openpty();failures=[]
        info=dict(type='info',fw='0.7.1',board='Aster MCA Nano AT32 v0.3',mcu='AT32F423CCT7',
            core_hz=144000000,adc_hz=72000000,sample_rate_hz=4_000_000,ldo_mv=1300,
            dma_samples=8192,snapshot_samples=4096,event_samples=512,pre_samples=320,
            holdoff_samples=64,queue_slots=8,bench_payload_bps=500000,adc_on=1,
            adc_fault=0,clock_fault=0,bist_fault=0,xtest=9,session=0,last_errors=0,has_result=0,packet_bist_cycles=100000)
        def line():
            data=b''
            while not data.endswith(b'\n'):data+=os.read(master,1)
            return data.strip()
        def write(data):
            for i in range(0,len(data),37):
                piece=data[i:i+37]
                while piece:piece=piece[os.write(master,piece):]
        def server():
            try:
                self.assertEqual(line(),b'INFO');write(json.dumps(info).encode()+b'\r\n')
                self.assertEqual(line(),b'BENCH 2 20');write(b'OK BENCH 2 1\r\n')
                h,p,t=packet();write(h+p+t)
                payload=json.dumps(dict(end_data(),fw='0.7.1')).encode()
                words=[1,3,1,1,8192,0xffffffff,0,4_000_000,len(payload),0,20,0,fnv(payload)]
                h=b'ASTW07\r\n'+struct.pack('<13I',*words);h+=struct.pack('<I',fnv(h))
                frame=h+payload+struct.pack('<I',~fnv(payload)&0xffffffff)
                if len(frame)%64==0:frame+=b'\0'
                write(frame)
                self.assertEqual(line(),b'INFO');write(json.dumps(dict(info,session=1,has_result=1)).encode()+b'\r\n')
            except Exception as exc:failures.append(exc)
        worker=threading.Thread(target=server,daemon=True);worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()):
                out=Path(directory)/'capture'
                result=run(os.ttyname(slave),out,.002,'bench','PTY test only')
                self.assertTrue(result['completed']);self.assertEqual(result['stored_raw_samples'],512)
                self.assertEqual((out/'windows.u16').stat().st_size,1024)
                self.assertEqual(result['payload_Bps_per_device_second'],500000)
                self.assertTrue(json.loads((out/'capture.json').read_text())['completed'])
            worker.join(2);self.assertFalse(worker.is_alive());self.assertEqual(failures,[])
        finally:os.close(master);os.close(slave)

if __name__=='__main__':unittest.main()
