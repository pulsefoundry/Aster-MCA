"""Small libusb binding for the previously verified OWON5345:1234 protocol.

Importing this module opens no device. No USB reset or firmware update is used.
"""
from pathlib import Path
import ctypes as C
import struct


class OwonUSB:
    def __init__(self):
        self.lib=C.CDLL('/opt/homebrew/lib/libusb-1.0.dylib')
        declarations={
            'libusb_init':([C.POINTER(C.c_void_p)],C.c_int),
            'libusb_exit':([C.c_void_p],None),
            'libusb_get_device_list':([C.c_void_p,C.POINTER(C.POINTER(C.c_void_p))],C.c_ssize_t),
            'libusb_free_device_list':([C.POINTER(C.c_void_p),C.c_int],None),
            'libusb_get_device_descriptor':([C.c_void_p,C.c_void_p],C.c_int),
            'libusb_open':([C.c_void_p,C.POINTER(C.c_void_p)],C.c_int),
            'libusb_close':([C.c_void_p],None),
            'libusb_get_configuration':([C.c_void_p,C.POINTER(C.c_int)],C.c_int),
            'libusb_claim_interface':([C.c_void_p,C.c_int],C.c_int),
            'libusb_release_interface':([C.c_void_p,C.c_int],C.c_int),
            'libusb_control_transfer':([C.c_void_p,C.c_uint8,C.c_uint8,C.c_uint16,C.c_uint16,C.c_void_p,C.c_uint16,C.c_uint],C.c_int),
            'libusb_bulk_transfer':([C.c_void_p,C.c_uint8,C.c_void_p,C.c_int,C.POINTER(C.c_int),C.c_uint],C.c_int),
            'libusb_error_name':([C.c_int],C.c_char_p),
        }
        for name,(args,ret) in declarations.items():
            fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=ret
        self.ctx=C.c_void_p();self.handle=C.c_void_p();self.interface=None;self.buffer=bytearray()
        self.check(self.lib.libusb_init(C.byref(self.ctx)),'init')
        devices=C.POINTER(C.c_void_p)()
        try:
            n=self.lib.libusb_get_device_list(self.ctx,C.byref(devices));self.check(n,'enumerate')
            matches=[]
            for i in range(n):
                desc=C.create_string_buffer(18)
                if self.lib.libusb_get_device_descriptor(devices[i],desc)==0:
                    if struct.unpack_from('<HH',desc.raw,8)==(0x5345,0x1234):matches.append(devices[i])
            if len(matches)!=1:raise RuntimeError(f'Expected exactly one OWON5345:1234; found{len(matches)}')
            self.check(self.lib.libusb_open(matches[0],C.byref(self.handle)),'open OWON')
            config=C.c_int();self.check(self.lib.libusb_get_configuration(self.handle,C.byref(config)),'read configuration')
            if config.value==0:raise RuntimeError('OWON has no active USB configuration; reconnect before retrying')
            raw=C.create_string_buffer(4096)
            size=self.lib.libusb_control_transfer(self.handle,0x80,6,0x0200,0,raw,len(raw),2000)
            self.check(size,'read configuration descriptor');blob=raw.raw[:size]
            if len(blob)<9 or blob[5]!=config.value:raise RuntimeError('Unexpected OWON configuration descriptor')
            pairs={};current=None;offset=0
            while offset+2<=len(blob):
                length,kind=blob[offset:offset+2]
                if length<2 or offset+length>len(blob):raise RuntimeError('Malformed USB descriptor')
                item=blob[offset:offset+length]
                if kind==4 and length>=9:
                    current=item[2] if item[3]==0 else None
                    if current is not None:pairs.setdefault(current,[])
                elif kind==5 and length>=7 and current is not None and item[3]&3==2:
                    pairs[current].append(item[2])
                offset+=length
            usable=[(i,e) for i,e in pairs.items() if len([x for x in e if x&0x80])==1 and len([x for x in e if not x&0x80])==1]
            if len(usable)!=1:raise RuntimeError('Expected one bulk interface with one IN/OUT endpoint')
            interface,endpoints=usable[0]
            self.check(self.lib.libusb_claim_interface(self.handle,interface),'claim OWON interface')
            self.interface=interface
            self.endpoint_in=next(x for x in endpoints if x&0x80)
            self.endpoint_out=next(x for x in endpoints if not x&0x80)
            self.descriptor=dict(vid='5345',pid='1234',configuration=config.value,interface=interface,
                                 endpoint_in=hex(self.endpoint_in),endpoint_out=hex(self.endpoint_out))
        except BaseException:
            if devices:
                self.lib.libusb_free_device_list(devices,1)
                devices=C.POINTER(C.c_void_p)()
            self.close();raise
        finally:
            if devices:self.lib.libusb_free_device_list(devices,1)

    def check(self,result,operation):
        if result<0:
            raise RuntimeError(operation+': '+self.lib.libusb_error_name(result).decode())
        return result

    def write(self,data,timeout=3000):
        data=bytes(data);buf=C.create_string_buffer(data);done=C.c_int()
        result=self.lib.libusb_bulk_transfer(self.handle,self.endpoint_out,buf,len(data),C.byref(done),timeout)
        self.check(result,'OWON bulk OUT')
        if done.value!=len(data):raise RuntimeError('Incomplete OWON write')

    def packet(self,timeout=3000):
        buf=C.create_string_buffer(65536);done=C.c_int()
        result=self.lib.libusb_bulk_transfer(self.handle,self.endpoint_in,buf,len(buf),C.byref(done),timeout)
        self.check(result,'OWON bulk IN')
        if not done.value:raise RuntimeError('Empty OWON response')
        return buf.raw[:done.value]

    def command(self,text):
        if self.buffer:raise RuntimeError('Unread binary bytes before text command')
        self.write(text.encode('ascii'))
        result=self.packet().decode('ascii').strip('\x00\r\n ')
        if not(result.startswith('{') and result.endswith('}')):raise RuntimeError('Invalid OWON text response')
        return result

    def exact(self,n):
        while len(self.buffer)<n:self.buffer.extend(self.packet())
        result=bytes(self.buffer[:n]);del self.buffer[:n];return result

    def close(self):
        if self.handle:
            if self.interface is not None:self.lib.libusb_release_interface(self.handle,self.interface)
            self.lib.libusb_close(self.handle);self.handle=C.c_void_p()
        if self.ctx:self.lib.libusb_exit(self.ctx);self.ctx=C.c_void_p()
