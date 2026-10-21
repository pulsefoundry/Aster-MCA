import csv
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib
from histogram_adapter import get_capture
from gui_model import Model,read_record,compatible
get_capture()
from aster_histogram.protocol import validate_result,histogram_snapshot

def fixture(folder,fw='0.6.0'):
    info=dict(type='info',board='Aster MCA Nano AT32 v0.3',mcu='AT32F423CCT7',fw=fw,method='onboard_histogram',
        core_hz=144000000,adc_hz=72000000,sample_rate_hz=4000000,timer_ticks=36,sample_cycles_x2=5,channels=2048,
        dma_samples=8192,ldo_mv=1300,adc_on=1,adc_fault=0,clock_fault=0,bist_fault=0,xtest=9,session=0,snapshot_samples=4096)
    counts=[0]*2048;counts[474]=7;raw=struct.pack('<2048I',*counts)
    h=dict(type='spectrum',fw=fw,method='mcu-area8-4M-v0.1',session=1,requested_ms=1000,
        threshold_codes=20,channels=2048,sample_rate_hz=4000000,core_hz=144000000,bin_width_code_us=1,
        blocks=977,processed_blocks=977,engine_blocks=977*64,fine_blocks=5,errors=0,adc_overrun=0,
        tail_samples_excluded=1,stop_user=0,acquisition_ms=1000,span_cycles_mod32=977*4096*36+80,
        irq_delta_min=147450,irq_delta_max=147460,process_max_cycles=80000,latency_max_cycles=500,
        candidates=8,accepted=7,rejected=1,underflow=0,overflow=0,pending_excluded=0,rejection_flags=[1,0,0,0,0],
        minimum=1900,maximum=2060,histogram_crc32=zlib.crc32(raw),snapshot_samples=4096,copy_max_cycles=10000,copy_end_max_cycles=10500)
    summary=validate_result(h,raw,1,1000,20)
    capture=dict(completed=True,initial_info=info,device_result=h,requested_seconds=1,input='SIMULATED GUI TEST',started='test',
        acquisition_mode='histogram',stop_reason='duration',wall_seconds=1.1,duty_cycle=summary['sampled_seconds']/1.1,
        verified_sampled_seconds=summary['sampled_seconds'],spectrum=summary,histogram=histogram_snapshot(counts,h))
    folder=Path(folder);folder.mkdir(exist_ok=True)
    (folder/'capture.json').write_text(json.dumps(capture));(folder/'spectrum-summary.json').write_text(json.dumps(summary))
    (folder/'histogram.u32').write_bytes(raw)
    return capture

class HistogramGUI(unittest.TestCase):
    def test_native_bins_history_export_and_no_fake_4096(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture(folder);r=read_record(folder)
            self.assertEqual(r['histogram']['master_channels'],2048)
            self.assertEqual(r['histogram']['counts']['area8'][474],7)
            self.assertTrue(compatible(r,r));self.assertFalse(compatible(r,{**r,'method':'host-pulse-4M-burst-v0.1'}))
            m=Model.__new__(Model);m.lock=threading.RLock();m.phase='idle';m.current=r;m.background=None
            for n in [512,1024,2048]:
                path=Path(m.export('area8',n,r['name']))
                with path.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
                self.assertEqual(len(rows),n);self.assertEqual(sum(int(x['counts']) for x in rows),7)
                self.assertEqual(json.loads(path.with_suffix('.json').read_text())['mapping_version'],'mcu-area8-2048-v1')
            for mode,n in [('area8',4096),('peak',2048)]:
                with self.assertRaises(ValueError):m.export(mode,n,r['name'])
            raw=bytearray((Path(folder)/'histogram.u32').read_bytes());raw[0]^=1;(Path(folder)/'histogram.u32').write_bytes(raw)
            with self.assertRaises(ValueError):read_record(folder)

    def test_waiting_has_no_invented_counts_then_final_histogram(self):
        with tempfile.TemporaryDirectory() as folder,patch('gui_model.RECORD_ROOT',Path(folder)):
            def fake_capture(port,out,seconds,condition,threshold,**kwargs):
                kwargs['on_progress']({'awaiting_result':True,'remaining_seconds':.5,'accepted':None,'samples':0,'seconds':0})
                self.assertIsNone(model.current['accepted']);self.assertTrue(model.current['awaiting_result'])
                return fixture(out,fw='0.6.3')
            model=Model();model.connected={'port':'fake','info':{'fw':'0.6.3'}}
            with patch('gui_model.get_histogram_capture',return_value=fake_capture):
                model.start(1,20,'SIMULATED GUI TEST');model.worker.join(3)
            self.assertEqual(model.phase,'complete',model.error);self.assertFalse(model.current['awaiting_result'])
            self.assertEqual(model.current['histogram']['counts']['area8'][474],7)
            self.assertEqual(model.current['histogram']['master_channels'],2048)
            self.assertEqual(read_record(model.current['path'])['histogram']['counts']['area8'][474],7)
            with self.assertRaises(ValueError):model.start(1,20.1,'invalid threshold')

if __name__=='__main__':unittest.main()
