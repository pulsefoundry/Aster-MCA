import csv
import json
import os
from pathlib import Path
import pty
import select
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib
from capture import run
from protocol import N, RATE, CORE, validate_frame, validate_info
from spectrum import Spectrum


def waveform(start=1000):
    values = [2048]*N
    pulse = [25,50,75,100,125,150,175,200,175,150,125,100,75,50,25,0]
    for i, height in enumerate(pulse):
        if start+i < N: values[start+i] -= height
    return struct.pack('<8192H', *values)


def info(identity=0):
    return dict(type='info', board='Aster MCA Nano AT32 v0.3', mcu='AT32F423CCT7',
                fw='0.5.0', method='burst_dma', core_hz=CORE, adc_hz=72000000,
                sample_rate_hz=RATE, timer_ticks=36, sample_cycles_x2=5, n=N,
                adc_on=1, adc_fault=0, clock_fault=0, xtest=9, ldo_mv=1300,
                capture_id=identity)


def header(raw, identity=1):
    values = struct.unpack('<8192H', raw)
    return dict(type='stats', method='burst_dma', fw='0.5.0', id=identity, n=N,
                capture_start_ms=identity*40, sample_rate_hz=RATE, timer_ticks=36,
                core_hz=CORE, nominal_span_cycles=(N-1)*36, elapsed_cycles=N*36+100,
                dma_remaining=0, dma_error=0, adc_overrun=0,
                min=min(values), max=max(values), sum=sum(values),
                sum_sq=sum(v*v for v in values), crc32=zlib.crc32(raw))


class FrameTests(unittest.TestCase):
    def test_corruption_counter_timing_and_overrun_rejected(self):
        raw = waveform(); h = header(raw)
        validate_info(info()); validate_frame(h, raw, 1)
        for key, bad in [('id',2),('n',8191),('sample_rate_hz',1000000),
                         ('adc_overrun',1),('dma_remaining',1),('dma_error',1),
                         ('elapsed_cycles',N*36+2000),('sum',h['sum']+1),('crc32',0)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_frame({**h,key:bad},raw,1)
        corrupt = bytearray(raw); corrupt[2000] ^= 1
        with self.assertRaises(ValueError): validate_frame(h,corrupt,1)
        with self.assertRaises(ValueError): validate_info({**info(),'xtest':0})
        with self.assertRaises(ValueError): validate_frame(h,raw[:-2],1)

    def test_pulse_area_peak_and_segment_local_times(self):
        with tempfile.TemporaryDirectory() as p:
            s = Spectrum(p,20); s.feed(waveform(),37); s.feed(waveform(),38)
            result = s.finish(True)
            with (Path(p)/'events.csv').open() as f: rows = list(csv.DictReader(f))
            self.assertEqual(result['accepted'],2)
            self.assertEqual(result['samples'],N*2)
            self.assertEqual(result['analysis_window_seconds'],2*(N-272-59)/RATE)
            self.assertEqual([r['segment_id'] for r in rows],['37','38'])
            self.assertEqual([int(r['trigger_sample_in_segment']) for r in rows],[1000,1000])
            self.assertEqual([float(r['peak_code']) for r in rows],[200,200])
            self.assertEqual([float(r['area8_code_us']) for r in rows],[400,400])
            self.assertEqual(int(rows[1]['stored_sample_offset']),N+1000)

    def test_truncated_pulses_do_not_cross_gap(self):
        with tempfile.TemporaryDirectory() as p:
            s = Spectrum(p,20); s.feed(waveform(N-2),1); s.feed(waveform(10),2)
            result=s.finish(True)
            self.assertEqual(result['accepted'],0)
            self.assertEqual(result['boundary_partial_events_excluded'],1)


class CaptureTests(unittest.TestCase):
    def test_disconnect_during_frame_is_invalid(self):
        class Disconnected:
            def __init__(self,*args):pass
            def command(self,command):
                return json.dumps(info() if command=='INFO' else header(waveform()))
            def exact(self,n):raise EOFError('USB disconnected mid-frame')
            def close(self):pass
        with tempfile.TemporaryDirectory() as p, patch('capture.Serial',Disconnected):
            out=Path(p)/'disconnect'
            with self.assertRaises(EOFError):run('fake',out,1,'synthetic',quiet=True)
            record=json.loads((out/'capture.json').read_text())
            self.assertFalse(record['completed']);self.assertEqual(record['verified_sampled_seconds'],0)
            self.assertEqual(record['stored_raw_samples'],0)

    def emulate(self, folder, bad=False, stop=False):
        master,slave=pty.openpty(); port=os.ttyname(slave)
        end=threading.Event(); stop_event=threading.Event(); errors=[]
        def device():
            buf=b''; identity=0
            try:
                while not end.is_set():
                    if not select.select([master],[],[],.05)[0]: continue
                    buf+=os.read(master,4096)
                    while b'\n' in buf:
                        command,buf=buf.split(b'\n',1)
                        if command==b'INFO': data=json.dumps(info(identity)).encode()+b'\r\n'
                        elif command==b'RAW':
                            identity+=1;raw=waveform();h=header(raw,identity)
                            if bad:h['crc32']+=1
                            data=json.dumps(h).encode()+b'\r\n'+raw+b'\r\n'
                        else: raise AssertionError(command)
                        # Fragmented delivery must not change waveform boundaries.
                        for offset in range(0,len(data),701):
                            part=memoryview(data[offset:offset+701])
                            while part:
                                n=os.write(master,part);part=part[n:]
            except BaseException as e: errors.append(e)
        thread=threading.Thread(target=device);thread.start()
        try:
            return run(port,folder,2 if stop else .04,'synthetic test',20,
                       stop_event=stop_event,
                       on_progress=(lambda _:stop_event.set()) if stop else None,quiet=True)
        finally:
            end.set();thread.join(2);os.close(master);os.close(slave)
            self.assertFalse(thread.is_alive());self.assertFalse(errors)

    def test_complete_bursts_and_separate_wall_time(self):
        with tempfile.TemporaryDirectory() as p:
            out=Path(p)/'run';r=self.emulate(out)
            self.assertTrue(r['completed']);self.assertGreater(r['blocks'],0)
            self.assertEqual(r['stored_raw_samples'],r['blocks']*N)
            self.assertEqual(r['spectrum']['accepted'],r['blocks'])
            self.assertEqual((out/'samples.u16').stat().st_size,r['blocks']*N*2)
            self.assertEqual(r['duration_basis'],'wall_time')
            self.assertEqual(r['verified_sampled_seconds'],r['blocks']*N/RATE)

    def test_bad_crc_preserves_diagnostics_but_invalidates_run(self):
        with tempfile.TemporaryDirectory() as p:
            out=Path(p)/'bad'
            with self.assertRaises(ValueError):self.emulate(out,bad=True)
            r=json.loads((out/'capture.json').read_text())
            self.assertFalse(r['completed']);self.assertEqual(r['verified_sampled_seconds'],0)
            self.assertFalse(r['spectrum']['valid_burst_run'])
            self.assertGreater((out/'wire.bin').stat().st_size,N*2)

    def test_stop_finishes_current_frame(self):
        with tempfile.TemporaryDirectory() as p:
            r=self.emulate(Path(p)/'stopped',stop=True)
            self.assertTrue(r['completed']);self.assertEqual(r['stop_reason'],'user_stop')
            self.assertLess(r['wall_seconds'],2)


if __name__=='__main__':unittest.main()
