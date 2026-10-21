"""Strict sparse-window decoder. Intentional time gaps are allowed; packet loss is not."""
import ctypes
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
MAGIC=b'ASTS04\r\n'
HEADER=80
WORDS=struct.Struct('<18I')
LIBPATH=HERE/'build/libastercodec.dylib'


def build_codec():
    LIBPATH.parent.mkdir(exist_ok=True)
    subprocess.run(['cc','-O3','-Wall','-Wextra','-Werror','-dynamiclib',
                    str(HERE/'host_codec.c'),'-o',str(LIBPATH)],check=True)


class Codec:
    def __init__(self):
        if getattr(sys, 'frozen', False):
            if not LIBPATH.is_file(): raise RuntimeError('应用缺少采集处理库，请重新安装完整应用')
        elif not LIBPATH.exists() or LIBPATH.stat().st_mtime<max((HERE/p).stat().st_mtime for p in ['codec.h','host_codec.c','selector.h']):
            build_codec()
        self.lib=ctypes.CDLL(str(LIBPATH))
        self.lib.host_hash.argtypes=[ctypes.c_char_p,ctypes.c_size_t]
        self.lib.host_hash.restype=ctypes.c_uint32
        self.lib.host_decode.argtypes=[ctypes.c_char_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_uint16),ctypes.c_size_t,ctypes.POINTER(ctypes.c_uint32)]
        self.lib.host_decode.restype=ctypes.c_int

    def hash(self,b):return self.lib.host_hash(b,len(b))

    def decode(self,payload,n,expected):
        values=(ctypes.c_uint16*n)(); h=ctypes.c_uint32()
        rc=self.lib.host_decode(payload,len(payload),values,n,ctypes.byref(h))
        if rc:raise ValueError(f'Invalid compressed ADC payload ({rc})')
        if h.value!=expected:raise ValueError('Decoded sample checksum mismatch')
        return bytes(values)


class Decoder:
    def __init__(self):
        self.codec=Codec();self.buf=bytearray();self.sequence=0;self.session=None
        self.done=False;self.end=None;self.wire_bytes=0;self.payload_bytes=0
        self.next_sample=0;self.selected_samples=0;self.candidate_blocks=0
        self.completed=0

    def feed(self,data):
        if self.done and data:raise ValueError('Bytes after terminal packet')
        self.buf.extend(data);blocks=[]
        while len(self.buf)>=HEADER:
            header=bytes(self.buf[:HEADER])
            if header[:8]!=MAGIC:raise ValueError('Stream magic mismatch; no silent resynchronization')
            w=WORDS.unpack(header[8:])
            if self.codec.hash(header[:-4])!=w[17]:raise ValueError('Header checksum mismatch')
            version,kind,session,seq,lo,hi,n,rate,size,encoding,rawhash,payloadhash,flags,completed,cycles,hits,ms,_=w
            if version!=1 or kind not in (1,2) or rate!=4000000 or size>1120:
                raise ValueError('Unexpected stream header')
            wire=HEADER+size;wire+=int(wire%64==0)
            if len(self.buf)<wire:break
            payload=bytes(self.buf[HEADER:HEADER+size])
            if self.codec.hash(payload)!=payloadhash:raise ValueError('Payload checksum mismatch')
            if wire>HEADER+size and self.buf[wire-1]!=0:raise ValueError('Bad transport padding')
            if self.session is None:self.session=session
            if session!=self.session:raise ValueError('Session changed')
            if seq!=self.sequence:raise ValueError('Missing or duplicated transport packet')
            first=lo|(hi<<32)
            if completed<self.completed:raise ValueError('DMA counter went backwards')
            self.completed=completed
            if kind==1:
                if first%64 or first<self.next_sample or (seq==0 and first!=0):
                    raise ValueError('Overlapping/unordered/missing initial waveform context')
                if not (64<=n<=512 and n%64==0) or encoding!=1 or flags or hits>n//64:raise ValueError('Faulted data block')
                if first+n>completed*4096:raise ValueError('Samples ahead of DMA completion')
                raw=self.codec.decode(payload,n,rawhash)
                blocks.append(({'sequence':seq,'first_sample':first,'n':n,'irq_cycles':cycles,
                    'candidate_blocks':hits,'payload_bytes':size,'elapsed_ms':ms,
                    'gap_samples':first-self.next_sample,'stored_sample_offset':self.selected_samples},raw))
                self.next_sample=first+n;self.selected_samples+=n;self.candidate_blocks+=hits
                self.sequence+=1;self.payload_bytes+=size
            else:
                if n or encoding:raise ValueError('Invalid terminal packet')
                self.end=json.loads(payload);self.done=True;e=self.end
                if (flags or e['errors'] or e['adc_overrun'] or e['fw']!='0.4.4' or
                    e['completed_blocks']!=completed or e['scanned_blocks']!=completed*64 or
                    e['packet_count']!=self.sequence or first!=completed*4096 or
                    first<self.next_sample or e['candidate_blocks']!=self.candidate_blocks or
                    e['session']!=self.session or e['sample_rate_hz']!=4000000 or
                    e['dma_block_samples']!=4096 or e['block_samples']!=64 or e['selected_samples']!=self.selected_samples or
                    not 0<=e['tail_samples_excluded']<4096):
                    raise ValueError('Run ended with acquisition/transport loss: '+json.dumps(e))
            del self.buf[:wire];self.wire_bytes+=wire
            if self.done:
                if self.buf:raise ValueError('Trailing bytes after terminal packet')
                break
        return blocks
