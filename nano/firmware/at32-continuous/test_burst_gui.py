import csv
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from burst_adapter import get_capture
from gui_model import Model, read_record, compatible


class BurstGUI(unittest.TestCase):
    def test_burst_record_export_and_background_isolation(self):
        get_capture()
        from aster_burst.spectrum import Spectrum
        import struct
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            s=Spectrum(p);y=[2048]*8192
            y[1000:1016]=[2048-v for v in [25,50,75,100,125,150,175,200,175,150,125,100,75,50,25,0]]
            s.feed(struct.pack('<8192H',*y),1);s.finish(True)
            capture=dict(completed=True,initial_info=dict(fw='0.5.0',sample_rate_hz=4000000),
                         acquisition_mode='burst',wall_seconds=.1,duty_cycle=.02048,input='test',started='test')
            (p/'capture.json').write_text(json.dumps(capture))
            r=read_record(p)
            self.assertEqual(r['seconds'],.002048);self.assertEqual(r['wall_seconds'],.1)
            self.assertTrue(compatible(r,r))
            self.assertFalse(compatible(r,{**r,'method':'host-pulse-4M-v0.2'}))
            self.assertEqual(sum(r['histogram']['counts']['area8']),1)
            model=Model.__new__(Model);model.lock=threading.RLock();model.phase='idle'
            model.current=r;model.background=None
            path=Path(model.export('area8',1024,r['name']))
            meta=json.loads(path.with_suffix('.json').read_text())
            self.assertEqual(meta['acquisition_mode'],'burst');self.assertEqual(meta['wall_seconds'],.1)
            self.assertEqual(meta['sampled_seconds'],.002048)
            capture['completed']=False;(p/'capture.json').write_text(json.dumps(capture))
            with self.assertRaises(ValueError):read_record(p)

    def test_mode_dispatch_and_failure_not_exportable(self):
        with tempfile.TemporaryDirectory() as folder, patch('gui_model.RECORD_ROOT',Path(folder)), \
             patch('gui_model.get_burst_capture',return_value=lambda *a,**k: (_ for _ in ()).throw(ValueError('CRC failure'))):
            model=Model();model.connected={'port':'fake','info':{'fw':'0.5.0'}}
            model.start(1,20,'test');model.worker.join(2)
            self.assertEqual(model.current['acquisition_mode'],'burst')
            self.assertEqual(model.phase,'error');self.assertFalse(model.current['valid'])
            with self.assertRaises(ValueError):model.export('peak',1024,model.current['name'])


if __name__=='__main__':unittest.main()
