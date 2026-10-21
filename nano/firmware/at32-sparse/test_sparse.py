import ctypes as c
import csv
import json
from pathlib import Path
import random
import struct
import tempfile
import unittest
from protocol import Codec,Decoder,MAGIC,WORDS
from spectrum import Spectrum

CALLBACK=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_uint64,c.POINTER(c.c_uint16),c.c_uint32)

class Checks(unittest.TestCase):
    def setUp(self):
        self.codec=Codec();self.lib=self.codec.lib
        self.lib.host_encode.argtypes=[c.POINTER(c.c_uint16),c.c_size_t,c.c_void_p,c.POINTER(c.c_uint32)]
        self.lib.host_encode.restype=c.c_size_t
        self.lib.selector_new.argtypes=[c.c_uint32];self.lib.selector_new.restype=c.c_void_p
        self.lib.selector_host_feed.argtypes=[c.c_void_p,c.POINTER(c.c_uint16),CALLBACK]
        self.lib.selector_host_feed.restype=c.c_int
        self.lib.selector_free.argtypes=[c.c_void_p]
        self.lib.selector_trigger_count.argtypes=[c.c_void_p];self.lib.selector_trigger_count.restype=c.c_uint32
    def select(self,values,threshold=20):
        out=[];state=self.lib.selector_new(threshold)
        @CALLBACK
        def emit(_,first,raw,hits):out.append((first,bytes(raw[:64] and c.string_at(raw,128)),hits));return 1
        try:
            for i in range(0,len(values),64):
                self.assertEqual(self.lib.selector_host_feed(state,(c.c_uint16*64)(*values[i:i+64]),emit),1)
            return out,self.lib.selector_trigger_count(state)
        finally:self.lib.selector_free(state)
    def encode(self,v):
        raw=(c.c_uint16*len(v))(*v);b=c.create_string_buffer(len(v)*2);h=c.c_uint32()
        n=self.lib.host_encode(raw,len(v),b,c.byref(h));return b.raw[:n],h.value
    def packet(self,first,seq=0,hits=0,values=None):
        payload,h=self.encode(values or [2048]*256)
        w=[1,1,1,seq,first&0xffffffff,first>>32,len(values) if values is not None else 256,4000000,len(payload),1,h,
           self.codec.hash(payload),0,first//4096+1,147456,hits,1,0]
        return self.frame(w,payload)
    def frame(self,w,payload):
        w[-1]=self.codec.hash((MAGIC+WORDS.pack(*w))[:-4]);b=MAGIC+WORDS.pack(*w)+payload
        return b+b'\0'*(len(b)%64==0)
    def end(self,packets=2,hits=0,errors=0,completed=4,tail=0,selected=None):
        e={'fw':'0.4.4','errors':errors,'adc_overrun':0,'completed_blocks':completed,
           'scanned_blocks':completed*64,'packet_count':packets,'selected_samples':packets*256 if selected is None else selected,'candidate_blocks':hits,
           'session':1,'sample_rate_hz':4000000,'dma_block_samples':4096,'block_samples':64,'tail_samples_excluded':tail}
        payload=json.dumps(e).encode();w=[1,2,1,packets,completed*4096,0,0,4000000,len(payload),0,0,
            self.codec.hash(payload),errors,completed,0,0,4,0];return self.frame(w,payload)
    def test_codec_full_adc_range(self):
        rng=random.Random(43)
        for values in [list(range(4096)),[0,4095]*128,[2048]*256,[rng.randrange(4096) for _ in range(256)]]:
            p,h=self.encode(values);self.assertEqual(self.codec.decode(p,len(values),h),struct.pack('<'+'H'*len(values),*values))
    def test_selector_all_block_positions_and_edges(self):
        for pos in [272,511,512,767,768,1023,1024,4095,4096,4097,8191,8192,12000,16383]:
            v=[2048]*16384;v[pos]=1900
            out,hits=self.select(v);self.assertEqual(hits,1)
            indices=[i//64 for i,_,_ in out];b=pos//64
            expected=set(range(7))|set(range(max(0,b-5),min(256,b+2)))
            self.assertEqual(indices,sorted(expected));self.assertEqual(sum(h for _,_,h in out),hits)
            for first,raw,_ in out:self.assertEqual(raw,struct.pack('<64H',*v[first:first+64]))
    def test_selector_merges_overlaps_without_duplicates(self):
        v=[2048]*16384
        for pos in (3000,3100,3300,3400,6000):v[pos:pos+4]=[1900]*4
        out,h=self.select(v);self.assertEqual(h,5);self.assertEqual(sum(x[2] for x in out),h)
        idx=[x[0] for x in out];self.assertEqual(idx,sorted(set(idx)))
    def test_conservative_gate_preserves_all_host_crossings(self):
        rng=random.Random(18);v=[2048+rng.randrange(-10,11) for _ in range(16384)]
        for k in range(800,16300,700):v[k:k+16]=[1900]*16
        for t in (1,19,20,21,100):
            out,h=self.select(v,t);sent={first//64 for first,_,_ in out}
            self.assertEqual(sum(x[2] for x in out),h)
            for k in range(272,len(v)):
                d=sum(v[k-272:k-16])/256-v[k]
                if d>=t:
                    b=k//64
                    for q in range(max(0,b-5),min(len(v)//64,b+2)):
                        self.assertIn(q,sent)
    def test_selector_periodic_baseline(self):
        out,h=self.select([2048]*(62510*64))
        self.assertEqual(h,0);self.assertEqual([x[0]//64 for x in out],list(range(7))+list(range(62500,62507)))
    def test_selector_backpressure_fails_explicitly(self):
        state=self.lib.selector_new(20)
        @CALLBACK
        def fail(*args):return 0
        try:
            raw=(c.c_uint16*64)(*[2048]*64)
            for _ in range(5):self.assertEqual(self.lib.selector_host_feed(state,raw,fail),1)
            self.assertEqual(self.lib.selector_host_feed(state,raw,fail),0)
        finally:self.lib.selector_free(state)
    def test_intentional_time_gaps_and_fragmentation(self):
        b=self.packet(0)+self.packet(8192,1)+self.end();d=Decoder();out=[]
        for i in range(0,len(b),13):out.extend(d.feed(b[i:i+13]))
        self.assertTrue(d.done);self.assertFalse(d.buf);self.assertEqual(out[1][0]['gap_samples'],7936)
        self.assertEqual(out[1][0]['stored_sample_offset'],256)
    def test_variable_merged_packets_keep_exact_sample_counts(self):
        frames=[self.packet(0,0,values=[2048]*256),self.packet(256,1,values=[2049]*64),
                self.packet(384,2,values=[2050]*448),self.packet(832,3,values=[2051]*512)]
        d=Decoder();blocks=d.feed(b''.join(frames)+self.end(packets=4,selected=1280))
        self.assertTrue(d.done);self.assertEqual([x[0]['n'] for x in blocks],[256,64,448,512])
        self.assertEqual(d.selected_samples,1280);self.assertEqual(blocks[2][0]['gap_samples'],64)
    def test_stop_tail_is_explicitly_outside_reported_exposure(self):
        d=Decoder();d.feed(self.packet(0)+self.packet(8192,1)+self.end(tail=8))
        self.assertTrue(d.done);self.assertEqual(d.end['tail_samples_excluded'],8)
        d=Decoder();d.feed(self.packet(0)+self.packet(8192,1))
        with self.assertRaises(ValueError):d.feed(self.end(tail=4096))
    def test_packet_loss_duplicate_overlap_corruption_rejected(self):
        for bad in (self.packet(8192,2),self.packet(0,1),self.packet(257,1)):
            d=Decoder();d.feed(self.packet(0))
            with self.assertRaises(ValueError):d.feed(bad)
        for offset in (24,100):
            b=bytearray(self.packet(0));b[offset]^=1
            with self.assertRaises(ValueError):Decoder().feed(b)
    def test_terminal_candidate_and_overrun_integrity(self):
        for end in (self.end(hits=1),self.end(errors=16),self.end(packets=3)):
            d=Decoder();d.feed(self.packet(0)+self.packet(8192,1))
            with self.assertRaises(ValueError):d.feed(end)
    def test_physical_integrals_and_sparse_absolute_time(self):
        v=[2048]*16384
        for k in (4095,12000):v[k:k+16]=[1948]*16 # 4 us, 100-code rectangle
        raw=struct.pack('<16384H',*v);out,hits=self.select(v)
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            full=Spectrum(a);full.feed(raw,0);sf=full.finish(True,len(v))
            sparse=Spectrum(b)
            for first,chunk,_ in out:sparse.feed(chunk,first)
            ss=sparse.finish(True,len(v))
            with (Path(b)/'events.csv').open() as f:rows=list(csv.DictReader(f))
            self.assertEqual(ss['accepted'],2);self.assertEqual(sf['accepted'],2)
            self.assertEqual((Path(a)/'events.csv').read_bytes(),(Path(b)/'events.csv').read_bytes())
            self.assertEqual([int(r['trigger_sample']) for r in rows],[4095,12000])
            self.assertEqual(float(rows[0]['time_s']),4095/4e6)
            self.assertEqual(float(rows[0]['area8_code_us']),400)
            self.assertEqual(float(rows[0]['area4_code_us']),300)
            self.assertEqual(int(rows[0]['half_height_samples']),16)
    def test_no_stitching_across_sparse_gap(self):
        with tempfile.TemporaryDirectory() as a:
            s=Spectrum(a);v=[2048]*1024;v[-1]=1900
            s.feed(struct.pack('<1024H',*v),0);s.feed(struct.pack('<1024H',*[2048]*1024),10000)
            result=s.finish(True,16384)
            self.assertEqual(result['accepted'],0);self.assertEqual(result['gap_partial_events_excluded'],1)

if __name__=='__main__':unittest.main()
