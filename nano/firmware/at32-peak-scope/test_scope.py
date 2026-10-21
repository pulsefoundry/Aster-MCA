import json
import os
from pathlib import Path
import pty
import select
import struct
import tempfile
import threading
import unittest
import zlib

from scope_capture import run,validate_raw,validate_raw_info
from aster_histogram.protocol import validate_result,histogram_snapshot
from test_peak import LEGACY_INFO,LEGACY_RESULT


def info(raw_id=0):
    return dict(LEGACY_INFO(3,1),fw='0.8.2',snapshot_samples=4096,
        energy_estimator='sampled_peak',bin_width_adc_codes=1,
        supports_raw=1,raw_n=4096,raw_capture_id=raw_id,raw_last_errors=0)


def frame(cid=1,value=2048):
    values=[value]*4096
    values[1000:1005]=[value-x for x in (20,40,80,40,20)]
    raw=struct.pack('<4096H',*values)
    h=dict(type='raw',method='diagnostic_snapshot',fw='0.8.2',id=cid,n=4096,
        sample_rate_hz=4000000,core_hz=144000000,adc_hz=72000000,timer_ticks=36,
        sample_cycles_x2=5,nominal_span_cycles=147420,elapsed_cycles=147524,
        dma_buffer_samples=8192,guard_samples=4096,
        dma_remaining=4093,errors=0,adc_overrun=0,min=min(values),max=max(values),
        sum=sum(values),sum_sq=sum(x*x for x in values),crc32=zlib.crc32(raw))
    return h,raw


class ScopeTests(unittest.TestCase):
    def test_good_raw_including_64bit_square_sum(self):
        h,raw=frame(value=4095)
        self.assertGreater(h['sum_sq'],2**32)
        self.assertTrue(validate_raw(h,raw,1)['checksum_statistics_verified'])
        validate_raw_info(info())

    def test_reject_wrong_sample_count_clock_checksum_sequence_or_fault(self):
        h,raw=frame()
        for key,value in [('id',2),('n',4095),('sample_rate_hz',2000000),
                          ('crc32',0),('sum_sq',2),('elapsed_cycles',300000),
                          ('dma_remaining',1),('dma_remaining',4097),('guard_samples',0),
                          ('errors',1),('adc_overrun',1),('id',True)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_raw({**h,key:value},raw,1)
        with self.assertRaises(ValueError):validate_raw(h,raw[:-2],1)

    def test_peak_histogram_compatibility_in_new_firmware(self):
        h,raw=LEGACY_RESULT();del h['bin_width_code_us']
        h.update(fw='0.8.2',method='mcu-peak-4M-v0.1',energy_estimator='sampled_peak',
            bin_width_adc_codes=1,snapshot_samples=4096,copy_max_cycles=10000,copy_end_max_cycles=10500)
        self.assertEqual(validate_result(h,raw,1,10,20)['method'],'mcu-peak-4M-v0.1')
        self.assertEqual(histogram_snapshot([0]*2048,h)['ranges'],{'peak':2048.0})

    def simulate(self,corrupt=False,change_hist_state=False):
        master,slave=pty.openpty();port=os.ttyname(slave);stop=threading.Event();failures=[]
        def device():
            buf=b'';cid=0
            try:
                while not stop.is_set():
                    if not select.select([master],[],[],.01)[0]:continue
                    buf+=os.read(master,4096)
                    while b'\n' in buf:
                        command,buf=buf.split(b'\n',1)
                        if command==b'INFO':
                            payload=info(cid)
                            if change_hist_state and cid:payload['session']+=1
                            os.write(master,json.dumps(payload).encode()+b'\r\n')
                        elif command==b'RAW':
                            cid+=1;h,raw=frame(cid);line=json.dumps(h).encode()+b'\r\n'
                            checksum=zlib.crc32(line)^(1 if corrupt else 0)
                            packet=line+raw+f'\r\nEND {checksum:08x}\r\n'.encode()
                            for i in range(0,len(packet),47):os.write(master,packet[i:i+47])
            except BaseException as exc:failures.append(exc)
        worker=threading.Thread(target=device);worker.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                out=Path(folder)/'diagnostic'
                if corrupt or change_hist_state:
                    with self.assertRaises(ValueError):run(port,out,2,'SIMULATED',quiet=True)
                    self.assertFalse(json.loads((out/'capture.json').read_text())['completed'])
                else:
                    result=run(port,out,2,'SIMULATED',quiet=True)
                    self.assertTrue(result['completed']);self.assertEqual(result['blocks'],2)
                    self.assertEqual((out/'samples.u16').read_bytes(),frame()[1]*2)
                    self.assertEqual(result['initial_info']['session'],result['final_info']['session'])
                    self.assertFalse((out/'histogram.u32').exists())
        finally:
            stop.set();worker.join(2);os.close(master);os.close(slave)
        self.assertFalse(failures)

    def test_fragmented_raw_sequence_and_saved_exact_samples(self):self.simulate()
    def test_corrupt_metadata_invalidates_capture(self):self.simulate(corrupt=True)
    def test_unexpected_histogram_state_change_invalidates_capture(self):self.simulate(change_hist_state=True)


if __name__=='__main__':unittest.main()
