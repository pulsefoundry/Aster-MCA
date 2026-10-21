"""Independent bursts; retain segment-local event times and reset all DSP state."""
import csv
import ctypes as c
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LIB = HERE/'build/libasterburst.dylib'
RATE = 4000000
WARM = 272
POST = 59


def build_dsp():
    LIB.parent.mkdir(exist_ok=True)
    subprocess.run(['cc', '-O3', '-Wall', '-Wextra', '-Werror', '-dynamiclib',
                    str(HERE/'host_dsp.c'), '-o', str(LIB)], check=True)


class Event(c.Structure):
    _fields_ = [('trigger', c.c_uint64), *[(x, c.c_double) for x in
                ['baseline', 'peak', 'area4', 'area8', 'area16', 'pre_rms']],
                ('flags', c.c_uint32), ('half_width', c.c_uint32)]


class Spectrum:
    def __init__(self, out, threshold=20, on_event=None):
        if not getattr(sys, 'frozen', False):
            if not LIB.exists() or LIB.stat().st_mtime < (HERE/'host_dsp.c').stat().st_mtime:
                build_dsp()
        self.lib = c.CDLL(str(LIB))
        self.lib.processor_new.argtypes = [c.c_double]
        self.lib.processor_new.restype = c.c_void_p
        self.lib.processor_feed.argtypes = [c.c_void_p, c.c_char_p, c.c_size_t, c.POINTER(Event)]
        self.lib.processor_feed.restype = c.c_size_t
        self.lib.processor_pending.argtypes = [c.c_void_p]
        self.lib.processor_pending.restype = c.c_int
        self.lib.processor_reset.argtypes = [c.c_void_p]
        self.lib.processor_free.argtypes = [c.c_void_p]
        self.state = self.lib.processor_new(threshold)
        if not self.state:
            raise MemoryError()
        self.out = Path(out); self.threshold = threshold; self.on_event = on_event
        self.n = self.total = self.accepted = self.segments = self.partial = self.analysis_samples = 0
        self.reasons = [0]*5; self.peak = [0]*4096; self.area = [0]*4096
        self.peak_outside = self.area_outside = 0; self.closed = False
        self.file = (self.out/'events.csv').open('w', newline='')
        self.writer = csv.writer(self.file)
        self.writer.writerow(['segment_id', 'trigger_sample_in_segment', 'time_in_segment_s',
                              'stored_sample_offset', 'baseline_code', 'peak_code',
                              'area4_code_us', 'area8_code_us', 'area16_code_us',
                              'pre_rms_code', 'flags', 'half_height_samples'])

    def feed(self, raw, segment_id):
        self.lib.processor_reset(self.state)
        n = len(raw)//2
        events = (Event*(n//59+2))()
        count = self.lib.processor_feed(self.state, raw, n, events)
        self.partial += self.lib.processor_pending(self.state)
        self.analysis_samples += max(0, n-WARM-POST)
        self.segments += 1
        for e in events[:count]:
            self.total += 1
            self.writer.writerow([segment_id, e.trigger, e.trigger/RATE, self.n+e.trigger,
                                  e.baseline, e.peak, e.area4, e.area8, e.area16,
                                  e.pre_rms, e.flags, e.half_width])
            for i in range(5):
                self.reasons[i] += bool(e.flags & (1 << i))
            if not e.flags:
                self.accepted += 1
                p = int(e.peak); a = int(e.area8//4)
                if self.on_event:
                    self.on_event(e.peak, e.area8)
                if 0 <= p < 4096: self.peak[p] += 1
                else: self.peak_outside += 1
                if 0 <= a < 4096: self.area[a] += 1
                else: self.area_outside += 1
        self.n += n

    def finish(self, valid):
        if self.closed:
            return
        self.file.close(); self.lib.processor_free(self.state); self.closed = True
        with (self.out/'spectrum.csv').open('w', newline='') as f:
            w = csv.writer(f); w.writerow(['channel', 'peak_counts', 'area8_div4_counts'])
            w.writerows((i, self.peak[i], self.area[i]) for i in range(4096))
        result = dict(method='host-pulse-4M-burst-v0.1', acquisition_mode='burst',
                      valid_burst_run=valid, sample_rate_hz=RATE, samples=self.n,
                      stored_samples=self.n, segments=self.segments, sampled_seconds=self.n/RATE,
                      analysis_window_seconds=self.analysis_samples/RATE,
                      excluded_start_samples_per_segment=WARM,
                      excluded_end_trigger_samples_per_segment=POST,
                      boundary_partial_events_excluded=self.partial,
                      threshold_codes=self.threshold, candidates=self.total, accepted=self.accepted,
                      rejection_flags=dict(zip(['pretrigger_unsettled', 'resolved_pileup',
                            'sampled_clipping', 'long_or_late', 'not_recovered'], self.reasons)),
                      peak_outside_histogram=self.peak_outside, area8_outside_histogram=self.area_outside,
                      peak_bin_code_width=1, area8_bin_code_us_width=4,
                      nominal_vdda_v=3.3, calibration=None,
                      limitations=['Finite bursts with unsampled USB/processing gaps.',
                        'Event time is local to its segment, not continuous wall time.',
                        'Trigger windows exclude 272 initial and 59 final samples per segment.',
                        'Sample time is not corrected MCA live time; trigger holdoff and quality cuts remain.',
                        'No calibrated energy, resolution or absolute count-rate claim.'])
        (self.out/'spectrum-summary.json').write_text(json.dumps(result, indent=2)+'\n')
        return result
