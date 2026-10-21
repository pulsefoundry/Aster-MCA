"""Strict continuous-stream decoder. A missing/corrupt block invalidates a run."""
import ctypes
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE=Path(__file__).resolve().parent
MAGIC=b'ASTC03\r\n'
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
        elif not LIBPATH.exists() or LIBPATH.stat().st_mtime<max((HERE/p).stat().st_mtime for p in ['codec.h','host_codec.c']):
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
        self.done=False;self.end=None;self.wire_bytes=0;self.irq_previous=None
        self.irq_intervals=[];self.payload_bytes=0

    def feed(self,data):
        if self.done and data:raise ValueError('Bytes after terminal packet')
        self.buf.extend(data); blocks=[]
        while len(self.buf)>=HEADER:
            header=bytes(self.buf[:HEADER])
            if header[:8]!=MAGIC:raise ValueError('Stream magic mismatch; no silent resynchronization')
            w=WORDS.unpack(header[8:])
            if self.codec.hash(header[:-4])!=w[17]:raise ValueError('Header checksum mismatch')
            version,kind,session,seq,lo,hi,n,rate,size,encoding,rawhash,payloadhash,flags,completed,cycles,enc,ms,_=w
            if version!=1 or kind not in (1,2) or rate!=1000000 or size>4096:
                raise ValueError('Unexpected stream header')
            wire=HEADER+size;wire+=int(wire%64==0)
            if len(self.buf)<wire:break
            payload=bytes(self.buf[HEADER:HEADER+size])
            if self.codec.hash(payload)!=payloadhash:raise ValueError('Payload checksum mismatch')
            if wire>HEADER+size and self.buf[wire-1]!=0:raise ValueError('Bad transport padding')
            if self.session is None:self.session=session
            if session!=self.session:raise ValueError('Session changed')
            first=lo|(hi<<32)
            if kind==1:
                if seq!=self.sequence or first!=self.sequence*2048:
                    raise ValueError('Missing or duplicated samples')
                if n!=2048 or encoding!=1 or flags:raise ValueError('Faulted data block')
                if completed<seq+1:raise ValueError('Invalid DMA completion counter')
                raw=self.codec.decode(payload,n,rawhash)
                if self.irq_previous is not None:self.irq_intervals.append((cycles-self.irq_previous)&0xffffffff)
                self.irq_previous=cycles
                blocks.append(({'sequence':seq,'first_sample':first,'n':n,'irq_cycles':cycles,
                                'encode_cycles':enc,'payload_bytes':size,'elapsed_ms':ms},raw))
                self.sequence+=1;self.payload_bytes+=size
            else:
                if n or encoding:raise ValueError('Invalid terminal packet')
                self.end=json.loads(payload)
                self.done=True
                if (flags or self.end['errors'] or self.end['adc_overrun'] or
                    self.end['completed_blocks']!=self.sequence or
                    self.end['encoded_blocks']!=self.sequence or seq!=self.sequence or
                    first!=self.sequence*2048 or self.end['session']!=self.session):
                    raise ValueError('Run ended with acquisition/transport loss: '+json.dumps(self.end))
            del self.buf[:wire];self.wire_bytes+=wire
            if self.done:
                if self.buf:raise ValueError('Trailing bytes after terminal packet')
                break
        return blocks
