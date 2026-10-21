"""PC-side streaming pulse extraction and uncalibrated histograms."""
import csv
import ctypes as c
import json
from pathlib import Path
from protocol import Codec

class Event(c.Structure):
    _fields_=[('trigger',c.c_uint64),*[(x,c.c_double) for x in
        ['baseline','peak','area4','area8','area16','pre_rms']],('flags',c.c_uint32),('half_width',c.c_uint32)]

class Spectrum:
    def __init__(self,out,threshold=20,on_event=None):
        self.out=Path(out);self.codec=Codec();lib=self.codec.lib
        lib.processor_new.argtypes=[c.c_double];lib.processor_new.restype=c.c_void_p
        lib.processor_feed.argtypes=[c.c_void_p,c.c_char_p,c.c_size_t,c.POINTER(Event)]
        lib.processor_feed.restype=c.c_size_t
        lib.processor_pending.argtypes=[c.c_void_p];lib.processor_pending.restype=c.c_int
        lib.processor_free.argtypes=[c.c_void_p]
        self.state=lib.processor_new(threshold)
        if not self.state:raise MemoryError()
        self.threshold=threshold;self.n=0;self.total=self.accepted=0
        self.on_event=on_event
        self.reasons=[0]*5;self.peak=[0]*4096;self.area=[0]*4096
        self.peak_outside=self.area_outside=0;self.closed=False
        self.file=(self.out/'events.csv').open('w',newline='')
        self.writer=csv.writer(self.file)
        self.writer.writerow(['trigger_sample','time_s','baseline_code','peak_code','area4_code_us',
                              'area8_code_us','area16_code_us','pre_rms_code','flags','half_height_samples'])
    def feed(self,raw):
        n=len(raw)//2
        events=(Event*(n//14+2))()
        count=self.codec.lib.processor_feed(self.state,raw,n,events)
        self.n+=n
        for e in events[:count]:
            self.total+=1
            self.writer.writerow([e.trigger,e.trigger/1e6,e.baseline,e.peak,e.area4,e.area8,
                                  e.area16,e.pre_rms,e.flags,e.half_width])
            for i in range(5):self.reasons[i]+=bool(e.flags&(1<<i))
            if not e.flags:
                self.accepted+=1;p=int(e.peak);a=int(e.area8//4)
                if self.on_event:self.on_event(e.peak,e.area8)
                if 0<=p<4096:self.peak[p]+=1
                else:self.peak_outside+=1
                if 0<=a<4096:self.area[a]+=1
                else:self.area_outside+=1
    def finish(self,valid):
        if self.closed:return
        self.file.close()
        pending=self.codec.lib.processor_pending(self.state)
        self.codec.lib.processor_free(self.state);self.closed=True
        with (self.out/'spectrum.csv').open('w',newline='') as f:
            w=csv.writer(f);w.writerow(['channel','peak_counts','area8_div4_counts'])
            w.writerows((i,self.peak[i],self.area[i]) for i in range(4096))
        result={'method':'host-pulse-v0.1','valid_continuous_run':valid,'samples':self.n,
                'sampled_seconds':self.n/1e6,'threshold_codes':self.threshold,'candidates':self.total,
                'accepted':self.accepted,'rejection_flags':dict(zip(
                    ['pretrigger_unsettled','resolved_pileup','sampled_clipping','long_or_late','not_recovered'],self.reasons)),
                'terminal_partial_event_excluded':pending,'peak_outside_histogram':self.peak_outside,
                'area8_outside_histogram':self.area_outside,'peak_bin_code_width':1,'area8_bin_code_us_width':4,
                'nominal_vdda_v':3.3,'calibration':None,
                'limitations':['Uncalibrated; no isotope identification or energy-resolution claim.',
                               '1 MS/s can undersample pulse peaks. Close pile-up remains unresolved.',
                               'Cuts and trigger holdoff bias event acceptance; sample time is not MCA live time.']}
        (self.out/'spectrum-summary.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
