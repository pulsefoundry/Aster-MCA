import ctypes as c
import json
from pathlib import Path
import random
import struct
import tempfile
import unittest
from protocol import Codec,Decoder,MAGIC,WORDS
from spectrum import Spectrum

def reference_decode(data,n):
    ns=[(v>>shift)&15 for v in data for shift in (0,4)];p=0;last=0;out=[]
    for _ in range(n):
        v=ns[p];p+=1
        if v==15:last=ns[p]|ns[p+1]<<4|ns[p+2]<<8;p+=3
        else:last+=v-7
        if not 0<=last<=4095:raise ValueError()
        out.append(last)
    return out

class Checks(unittest.TestCase):
    def setUp(self):
        self.codec=Codec();self.codec.lib.host_encode.argtypes=[c.POINTER(c.c_uint16),c.c_size_t,c.c_void_p,c.POINTER(c.c_uint32)]
        self.codec.lib.host_encode.restype=c.c_size_t
    def encode(self,values):
        a=(c.c_uint16*len(values))(*values);out=c.create_string_buffer(len(values)*2);h=c.c_uint32()
        n=self.codec.lib.host_encode(a,len(values),out,c.byref(h));return out.raw[:n],h.value
    def packet(self,values,seq=0):
        payload,h=self.encode(values);w=[1,1,1,seq,seq*2048,0,len(values),1000000,len(payload),1,h,
            self.codec.hash(payload),0,seq+1,(seq+1)*98304,20000,seq*2,0]
        pre=MAGIC+WORDS.pack(*w);w[-1]=self.codec.hash(pre[:-4])
        b=MAGIC+WORDS.pack(*w)+payload
        return b+b'\0'*(len(b)%64==0)
    def test_lossless_full_range_and_noise(self):
        rng=random.Random(123)
        for values in [list(range(4096)),list(range(4095,-1,-1)),[0,4095]*1024,
                       [2048]*2048,[rng.randrange(4096) for _ in range(2048)],
                       [round(rng.gauss(2048,2)) for _ in range(2048)]]:
            payload,h=self.encode(values)
            self.assertLessEqual(len(payload),len(values)*2)
            self.assertEqual(reference_decode(payload,len(values)),values)
            self.assertEqual(list(struct.unpack('<'+'H'*len(values),self.codec.decode(payload,len(values),h))),values)
    def test_fragmentation_and_contiguity(self):
        b=self.packet([2048]*2048)+self.packet([2049]*2048,1);d=Decoder();out=[]
        for i in range(0,len(b),13):out+=d.feed(b[i:i+13])
        self.assertEqual(len(out),2);self.assertEqual(d.sequence,2);self.assertFalse(d.buf)
        with self.assertRaises(ValueError):Decoder().feed(self.packet([2048]*2048,1))
    def test_corruption_and_invalid_samples_rejected(self):
        b=bytearray(self.packet([2048]*2048));b[100]^=1
        with self.assertRaises(ValueError):Decoder().feed(b)
        b=bytearray(self.packet([2048]*2048));b[20]^=1
        with self.assertRaises(ValueError):Decoder().feed(b)
        with self.assertRaises(ValueError):self.codec.decode(b'\0',1,0)
    def test_terminal_fault_and_missing_tail_rejected(self):
        for errors in (0,16):
            payload=json.dumps({'errors':errors,'adc_overrun':0,'completed_blocks':1,
                                'encoded_blocks':1,'session':1}).encode()
            w=[1,2,1,1,2048,0,0,1000000,len(payload),0,0,self.codec.hash(payload),errors,1,98304,0,2,0]
            header=MAGIC+WORDS.pack(*w);w[-1]=self.codec.hash(header[:-4])
            b=MAGIC+WORDS.pack(*w)+payload;b+=b'\0'*(len(b)%64==0)
            d=Decoder();d.feed(self.packet([2048]*2048))
            if errors:
                with self.assertRaises(ValueError):d.feed(b)
            else:
                d.feed(b);self.assertTrue(d.done);self.assertFalse(d.buf)
    def test_host_event_across_block_boundary(self):
        values=[2048]*4096;values[2047:2051]=[1948,1968,2008,2038]
        raw=struct.pack('<4096H',*values)
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            x=Spectrum(a);x.feed(raw);sa=x.finish(True)
            y=Spectrum(b)
            for i in range(0,len(raw),34):y.feed(raw[i:i+34])
            sb=y.finish(True)
            self.assertEqual(sa,sb);self.assertEqual(sa['accepted'],1)
            self.assertEqual((Path(a)/'events.csv').read_bytes(),(Path(b)/'events.csv').read_bytes())
            self.assertIn(',100.0,220.0,230.0,230.0,',(Path(a)/'events.csv').read_text())
    def test_positive_rebound_and_clipping(self):
        values=[2048]*1024;values[200:203]=[1948,1968,2008];values[203:207]=[2058]*4
        values[700]=0
        with tempfile.TemporaryDirectory() as a:
            x=Spectrum(a);x.feed(struct.pack('<1024H',*values));s=x.finish(True)
            self.assertEqual(s['candidates'],2);self.assertEqual(s['accepted'],1)
            self.assertEqual(s['rejection_flags']['sampled_clipping'],1)
            self.assertIn(',100.0,220.0,180.0,180.0,',(Path(a)/'events.csv').read_text())
    def test_no_join_between_independent_runs(self):
        with tempfile.TemporaryDirectory() as a:
            x=Spectrum(a);v=[2048]*100;v[-1]=1900;x.feed(struct.pack('<100H',*v))
            s=x.finish(True);self.assertEqual(s['accepted'],0);self.assertEqual(s['terminal_partial_event_excluded'],1)

if __name__=='__main__':unittest.main()
