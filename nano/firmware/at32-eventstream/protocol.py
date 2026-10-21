"""Strict, non-resynchronizing event-window protocol. No spectrum claims."""
import json
import struct
import importlib.util
from pathlib import Path
_spec=importlib.util.spec_from_file_location('aster_histogram_wire',Path(__file__).resolve().parents[1]/'at32-histogram/protocol.py')
_wire=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wire)
Serial = _wire.Serial

MAGIC=b'ASTW07\r\n'
HEADER=64
RATE=4_000_000
FIRMWARES=('0.7.0','0.7.1')

def fnv(data):
    h=2166136261
    for b in data:h=((h^b)*16777619)&0xffffffff
    return h

def validate_info(i):
    if i.get('fw') not in FIRMWARES:raise ValueError('Unsupported firmware')
    expected=dict(type='info',board='Aster MCA Nano AT32 v0.3',mcu='AT32F423CCT7',
        core_hz=144000000,adc_hz=72000000,sample_rate_hz=RATE,ldo_mv=1300,
        dma_samples=8192,snapshot_samples=4096,event_samples=512,pre_samples=320,
        holdoff_samples=64,queue_slots=8,bench_payload_bps=500000,
        adc_on=1,adc_fault=0,clock_fault=0,bist_fault=0,xtest=9)
    for k,v in expected.items():
        if i.get(k)!=v:raise ValueError(f'Unexpected device configuration: {k}={i.get(k)!r}')
    if type(i.get('session')) is not int or i['session']<0:raise ValueError('Bad session')
    if i['fw']=='0.7.1' and not 0<i.get('packet_bist_cycles',0)<147456:
        raise ValueError('Packet-processing self-test did not pass its deadline')

def header(data):
    if len(data)!=64 or data[:8]!=MAGIC:raise ValueError('Bad frame signature')
    keys=('version','kind','session','seq','first','trigger','samples','rate','length',
          'baseline_sum','threshold','errors','payload_hash','header_hash')
    h=dict(zip(keys,struct.unpack('<14I',data[8:])))
    if fnv(data[:60])!=h['header_hash']:raise ValueError('Header checksum mismatch')
    if h['version']!=1 or h['kind'] not in (1,2,3) or h['rate']!=RATE:raise ValueError('Unsupported frame')
    if h['length']>1976 or (h['kind']!=3 and (h['length']!=1024 or h['samples']!=512)):
        raise ValueError('Invalid payload size')
    if h['kind']==3 and h['samples']:raise ValueError('Terminal sample count')
    return h

def decode(raw_header,payload,trailer):
    h=header(raw_header)
    size=64+h['length']+4;pad=1 if size%64==0 else 0
    if len(payload)!=h['length'] or len(trailer)!=4+pad:raise ValueError('Frame size mismatch')
    if fnv(payload)!=h['payload_hash'] or struct.unpack('<I',trailer[:4])[0]!=(~h['payload_hash']&0xffffffff):
        raise ValueError('Payload checksum mismatch')
    if pad and trailer[4:]!=b'\0':raise ValueError('Bad padding')
    return h

class Validator:
    def __init__(self,session,mode,milliseconds,threshold,firmware='0.7.0'):
        if firmware not in FIRMWARES:raise ValueError('Unsupported firmware')
        self.firmware=firmware
        self.session,self.mode,self.ms,self.threshold=session,mode,milliseconds,threshold
        self.packets=self.payload_bytes=self.wire_bytes=0
        self.last=None
    def accept(self,h,payload):
        if h['errors']:raise ValueError(f'Device frame error {h["errors"]}')
        if (h['session'],h['seq'],h['threshold'])!=(self.session,self.packets,self.threshold):
            raise ValueError('Session, sequence or threshold mismatch')
        if h['kind']==3:
            d=json.loads(payload)
            self.finish(d)
            if h['first']!=d['blocks']*4096 or h['trigger']!=0xffffffff or h['baseline_sum']!=0:
                raise ValueError('Terminal header mismatch')
            return d
        if h['kind']!=(2 if self.mode==1 else 1):raise ValueError('Mixed acquisition modes')
        values=struct.unpack('<512H',payload)
        if max(values)>4095:raise ValueError('ADC value out of range')
        if self.mode==1:
            if h['first']!=self.packets*8192 or h['trigger']!=0xffffffff or h['baseline_sum']:
                raise ValueError('Benchmark sampling cadence mismatch')
        else:
            if h['trigger']<320 or h['first']+320!=h['trigger']:raise ValueError('Event alignment')
            if not 0<=h['baseline_sum']<=4095*256:raise ValueError('Baseline range')
            if sum(values[48:304])!=h['baseline_sum']:raise ValueError('Pretrigger baseline does not match waveform')
            delta=h['baseline_sum']-values[320]*256
            if delta<self.threshold*256:raise ValueError('Trigger waveform does not cross threshold')
            if self.last:
                before,old=self.last;shift=h['first']-before
                if shift<64:raise ValueError('Trigger ordering/holdoff')
                if shift<512 and old[shift:]!=values[:512-shift]:raise ValueError('Overlapping windows disagree')
            self.last=h['first'],values
        self.packets+=1;self.payload_bytes+=len(payload);self.wire_bytes+=1092
        return None
    def finish(self,d):
        checks=dict(type='end',fw=self.firmware,session=self.session,mode=self.mode,errors=0,
            requested_ms=self.ms,threshold=self.threshold,packets=self.packets,
            payload_bytes=self.payload_bytes,wire_bytes=self.wire_bytes,stop_user=0,adc_overrun=0)
        for k,v in checks.items():
            if d.get(k)!=v:raise ValueError(f'Invalid final counter {k}={d.get(k)!r}, expected {v}')
        numeric=['blocks','processed_blocks','engine_blocks','fine_blocks','candidates','emitted','pending_excluded',
            'holdoff_crossings','queue_high','minimum','maximum','process_max_cycles','copy_max_cycles',
            'copy_end_max_cycles','latency_max_cycles','irq_min','irq_max','span_cycles_mod32','acquisition_ms','tail_samples_excluded']
        if any(type(d.get(k)) is not int or not 0<=d[k]<=0xffffffff for k in numeric):raise ValueError('Invalid end metadata')
        b=(self.ms*4000+4095)//4096
        if d['blocks']!=b or d['processed_blocks']!=b or d['engine_blocks']!=b*64:raise ValueError('Missing ADC/DMA blocks')
        if not 0<d['copy_max_cycles']<=d['copy_end_max_cycles']<147456 or not d['latency_max_cycles']<147456:
            raise ValueError('DMA snapshot deadline violation')
        if d['copy_max_cycles']>d['process_max_cycles'] or d['fine_blocks']>b*64:raise ValueError('Processing metadata')
        if b>1 and not 146016<=d['irq_min']<=d['irq_max']<=148896:raise ValueError('ADC timing interval')
        if (d['span_cycles_mod32']-b*4096*36)&0xffffffff>1440:raise ValueError('ADC cycle duration')
        if abs(d['acquisition_ms']-b*1.024)>3:raise ValueError('ADC millisecond duration')
        if not 0<=d['minimum']<=d['maximum']<=4095 or d['tail_samples_excluded']>=4096:raise ValueError('ADC extrema/tail')
        if not 0<=d['queue_high']<=8 or (self.packets and not d['queue_high']):raise ValueError('Queue metadata')
        if self.mode==1:
            if self.packets!=(b+1)//2 or any(d[k] for k in ('candidates','emitted','pending_excluded','holdoff_crossings')):
                raise ValueError('Benchmark counter mismatch')
        elif d['emitted']!=self.packets or d['candidates']!=d['emitted']+d['pending_excluded'] or d['pending_excluded']>8:
            raise ValueError('Trigger conservation failure')
