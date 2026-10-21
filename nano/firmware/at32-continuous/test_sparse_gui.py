import csv
import json
from pathlib import Path
import tempfile
import unittest
from gui_model import read_record,compatible,acquisition_error
from sparse_adapter import get_capture

class SparseGUI(unittest.TestCase):
    def test_overload_explanation_is_readable(self):
        message=acquisition_error(ValueError('Run ended with acquisition/transport loss: {"errors":16}'))
        self.assertIn('发送缓冲区已满',message);self.assertNotIn('{',message)
    def test_independent_codec_modules(self):
        import protocol
        continuous=protocol.Codec()
        self.assertEqual(get_capture().__module__,'aster_sparse.capture')
        from aster_sparse.protocol import Codec
        sparse=Codec()
        self.assertNotEqual(continuous.lib._name,sparse.lib._name)
    def test_sparse_record_and_background_separation(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            capture={'completed':True,'initial_info':{'fw':'0.4.4','sample_rate_hz':4000000},'input':'synthetic','started':'test'}
            summary={'valid_sparse_run':True,'samples':4000000,'sampled_seconds':1,'candidates':1,'accepted':1,
                     'method':'host-pulse-4M-v0.2','threshold_codes':20}
            (p/'capture.json').write_text(json.dumps(capture));(p/'spectrum-summary.json').write_text(json.dumps(summary))
            with (p/'events.csv').open('w') as f:
                w=csv.writer(f);w.writerow(['flags','peak_code','area8_code_us']);w.writerow([0,100,400])
            r=read_record(p);self.assertEqual(r['sample_rate_hz'],4000000)
            self.assertEqual(sum(r['histogram']['counts']['area8']),1)
            self.assertFalse(compatible(r,{**r,'method':'host-pulse-v0.1'}))
            summary['valid_sparse_run']=False;(p/'spectrum-summary.json').write_text(json.dumps(summary))
            with self.assertRaises(ValueError):read_record(p)
if __name__=='__main__':unittest.main()
