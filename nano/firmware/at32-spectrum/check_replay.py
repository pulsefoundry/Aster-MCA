"""Numerical checks for the experimental replay, independent of real spectra."""
import unittest
import zlib
import numpy as np
from replay import extract, verify_frame


class ReplayChecks(unittest.TestCase):
    def test_known_peak_and_signed_area(self):
        y=np.full(512,2048.)
        y[200:205]-=[100,80,40,10,0]
        e=extract(y)
        self.assertEqual(len(e),1)
        self.assertTrue(e[0]['accepted'])
        self.assertEqual(e[0]['peak_codes'],100)
        self.assertEqual(e[0]['area4_code_us'],220)
        self.assertEqual(e[0]['area8_code_us'],230)
        self.assertEqual(e[0]['half_height_samples'],2)

    def test_offset_invariance(self):
        y=np.full(512,1900.)
        y[200:204]-=[100,80,40,10]
        e,f=extract(y)[0],extract(y+300)[0]
        for k in ('peak_codes','area4_code_us','area8_code_us','area16_code_us'):
            self.assertEqual(e[k],f[k])

    def test_positive_tail_is_signed(self):
        y=np.full(512,2048.)
        y[200:203]-=[100,80,40]
        y[203:207]+=10
        e=extract(y)[0]
        self.assertTrue(e['accepted'])
        self.assertEqual(e['area8_code_us'],180)

    def test_neighbour_and_clipping_flags(self):
        y=np.full(512,2048.)
        y[200:202]-=[100,40]
        y[210:212]-=[100,40]
        e=extract(y)
        self.assertEqual(len(e),2)
        self.assertTrue(all('nearby_candidate' in x['flags'] for x in e))
        y=np.full(512,2048.);y[200]=0
        self.assertIn('sampled_clipping',extract(y)[0]['flags'])

    def test_guard_regions_and_quiet_input(self):
        self.assertEqual(extract(np.full(512,2048.)),[])
        y=np.full(512,2048.);y[0]=1000;y[-1]=1000
        self.assertEqual(extract(y),[])

    def test_step_near_search_end_is_not_a_short_pulse(self):
        y=np.full(512,2048.);y[492:]-=100
        e=extract(y)
        self.assertEqual(len(e),1)
        self.assertIn('not_recovered',e[0]['flags'])

    def test_corruption_and_dma_fault_rejected(self):
        y=np.full(8192,2048,dtype='<u2');raw=y.tobytes()
        s=dict(n=len(y),crc32=zlib.crc32(raw),min=2048,max=2048,
               sum=len(y)*2048,sum_sq=len(y)*2048**2,
               method='timer_dma',sample_rate_hz=1000000,core_hz=48000000,
               timer_ticks=48,nominal_span_cycles=(len(y)-1)*48,
               elapsed_cycles=len(y)*48+180,dma_remaining=0,dma_error=0,adc_overrun=0)
        verify_frame(raw,s)
        with self.assertRaises(AssertionError):verify_frame(bytes([0])+raw[1:-1]+b'\0',s)
        with self.assertRaises(AssertionError):verify_frame(raw,dict(s,adc_overrun=1))


if __name__=='__main__':unittest.main()
