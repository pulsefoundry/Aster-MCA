"""Experimental negative-pulse replay for verified AT32 1 MS/s RAW captures.

No board access. Outputs sampled peak and signed finite-window area, NOT keV.
Gaps between frames are never joined. Cuts are diagnostic and can bias spectra.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import zlib

import numpy as np

SCALE = 3300.0 / 4096
PRE = 64
GUARD = 4
TAIL = 16
THRESHOLD = 20


def verify_frame(raw, s):
    y = np.frombuffer(raw, dtype='<u2').astype(np.int64)
    assert len(raw) == s['n'] * 2, 'sample length'
    actual = dict(crc32=zlib.crc32(raw), min=int(y.min()), max=int(y.max()),
                  sum=int(y.sum()), sum_sq=int((y * y).sum()))
    assert all(s[k] == v for k, v in actual.items()), 'frame checksum/statistics'
    assert y.min() >= 0 and y.max() <= 4095, '12-bit data'
    assert s['method'] == 'timer_dma' and s['sample_rate_hz'] == 1000000
    assert s['core_hz'] == s['sample_rate_hz'] * s['timer_ticks']
    assert s['nominal_span_cycles'] == (s['n'] - 1) * s['timer_ticks']
    assert not any(s[k] for k in ('dma_remaining', 'dma_error', 'adc_overrun'))
    assert abs(s['elapsed_cycles'] / (s['n'] * s['timer_ticks']) - 1) < .01
    return y.astype(float)


def extract(y):
    """Local negative trigger, frozen pretrigger median, separate quality flags.

    Search baseline is the mean of 64 preceding samples with a 4-sample gap.
    Final baseline is their median. A 16-sample tail is required in this frame.
    Adjacent threshold runs <=3 samples apart merge; unresolved pile-up remains.
    """
    n = len(y)
    cs = np.r_[0., np.cumsum(y)]
    starts = np.arange(PRE + GUARD, n - TAIL)
    search_base = (cs[starts-GUARD] - cs[starts-GUARD-PRE]) / PRE
    hit = starts[(search_base - y[starts]) >= THRESHOLD]
    groups = np.split(hit, np.flatnonzero(np.diff(hit) > 3) + 1) if hit.size else []
    events = []
    for k, g in enumerate(groups):
        t = int(g[0])
        pre = y[t-GUARD-PRE:t-GUARD]
        b = float(np.median(pre))
        peak = int(g[np.argmax(b-y[g])])
        amp = b-y[peak]
        width = int(g[-1]-g[0]+1)
        rms = float(np.sqrt(np.mean((pre-b)**2)))
        slope = float(np.median(pre[-16:])-np.median(pre[:16]))
        flags = []
        if rms > 8 or abs(slope) > 4:
            flags.append('unsettled_pretrigger')
        if amp < THRESHOLD:
            flags.append('below_local_threshold')
        if width > 8:
            flags.append('long_excursion')
        if peak-t > 4:
            flags.append('late_peak')
        # This rejects resolvable neighbours; it cannot identify merged pulses.
        if ((k and t-int(groups[k-1][-1]) <= PRE+GUARD) or
                (k+1 < len(groups) and int(groups[k+1][0])-t < TAIL)):
            flags.append('nearby_candidate')
        seg = y[t-1:t+TAIL-1]
        if np.any((seg <= 0) | (seg >= 4095)):
            flags.append('sampled_clipping')
        if b-float(np.median(y[t+TAIL-3:t+TAIL])) >= THRESHOLD:
            flags.append('not_recovered')
        left = right = peak
        while left > 0 and b-y[left-1] >= amp/2:
            left -= 1
        while right+1 < n and b-y[right+1] >= amp/2:
            right += 1
        row = dict(trigger_index=t, peak_index=peak, baseline_code=b,
                   pretrigger_rms_codes=rms, pretrigger_drift_codes=slope,
                   peak_codes=float(amp), peak_mv=float(amp*SCALE),
                   half_height_samples=right-left+1,
                   threshold_span_samples=width,
                   accepted=not flags, flags=';'.join(flags))
        for gate in (4, 8, 16):
            # Includes one pretrigger sample; signed sum, never rectified.
            row[f'area{gate}_code_us'] = float(np.sum(b-y[t-1:t+gate-1]))
            row[f'area{gate}_mv_us'] = row[f'area{gate}_code_us']*SCALE
        row['post_overshoot_mv'] = float(max(0, y[t:t+TAIL].max()-b)*SCALE)
        events.append(row)
    return events


def process(directory, label, out):
    record = json.loads((directory/'result.json').read_text())
    events, hashes, rms, frames = [], {}, [], []
    for st in record['captures']:
        raw = (directory/(st['file']+'.bin')).read_bytes()
        y = verify_frame(raw, st)
        hashes[st['file']] = hashlib.sha256(raw).hexdigest()
        for event in extract(y):
            event.update(dataset=label, frame=st['file'])
            events.append(event)
        rms.append(float(np.std(y)))
        frames.append(dict(file=st['file'], n=len(y), baseline_code=float(np.median(y)),
                           rms_codes=float(np.std(y)), min=int(y.min()), max=int(y.max())))
    accepted = [e for e in events if e['accepted']]
    eligible = sum((f['n']-PRE-GUARD-TAIL)/1e6 for f in frames)
    sampled = sum(f['n']/1e6 for f in frames)
    reasons = Counter(flag for e in events for flag in e['flags'].split(';') if flag)
    meta = dict(label=label, source_directory=str(directory.resolve()), input=record['input'],
                frames=len(frames), sampled_seconds=sampled,
                eligible_trigger_window_seconds=eligible,
                wall_seconds=record['host_duration_seconds'],
                sampling_duty_fraction=sampled/record['host_duration_seconds'],
                candidates=len(events), accepted=len(accepted),
                accepted_per_sampled_second=len(accepted)/sampled,
                rejection_flags=dict(reasons),
                accepted_half_height_samples=dict(Counter(e['half_height_samples'] for e in accepted)),
                median_frame_rms_mv=float(np.median(rms)*SCALE),
                sampled_min_code=min(f['min'] for f in frames),
                sampled_max_code=max(f['max'] for f in frames),
                all_frames_revalidated=True, raw_sha256=hashes)
    if accepted:
        p = np.array([e['peak_mv'] for e in accepted])
        a = np.array([e['area8_mv_us'] for e in accepted])
        meta.update(peak_q50_q95_mv=np.quantile(p,[.5,.95]).tolist(),
                    area8_q50_q95_mv_us=np.quantile(a,[.5,.95]).tolist(),
                    area8_over_peak_us_q05_q50_q95=np.quantile(a/p,[.05,.5,.95]).tolist())
    (out/f'{label}-summary.json').write_text(json.dumps(meta,indent=2)+'\n')
    with (out/f'{label}-events.csv').open('w',newline='') as f:
        if events:
            writer=csv.DictWriter(f,fieldnames=list(events[0]))
            writer.writeheader();writer.writerows(events)
        else:
            f.write('dataset,frame,trigger_index,peak_mv,area8_mv_us,accepted,flags\n')
    return meta, events


def plot_and_export(results, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    colors={'source':'#d65e27','removed':'#206caa','before':'#339780','open':'#777777'}
    fig, axes=plt.subplots(2,2,figsize=(12.6,8.5),layout='constrained')
    histogram_rows=[]
    for label,(meta,events) in results.items():
        a=[e for e in events if e['accepted']]
        for key,ax,edges in [('peak_mv',axes[0,0],np.arange(0,804,4)),
                             ('area8_mv_us',axes[0,1],np.arange(-200,2001,10))]:
            vals=np.array([e[key] for e in a])
            counts,_=np.histogram(vals,edges)
            rate=counts/meta['sampled_seconds']
            ax.stairs(rate,edges,label=f'{label} ({len(a)} accepted)',color=colors.get(label),lw=1.1)
            for lo,hi,n,r in zip(edges[:-1],edges[1:],counts,rate):
                histogram_rows.append(dict(dataset=label,estimator=key,bin_low=lo,bin_high=hi,
                                            counts=int(n),per_sampled_second=float(r)))
            # Explicit overflow accounting preserves all accepted events.
            meta[key+'_hist_underflow']=int(np.sum(vals<edges[0]))
            meta[key+'_hist_overflow']=int(np.sum(vals>edges[-1]))
        if label=='source' and a:
            p=np.array([e['peak_mv'] for e in a])
            area=np.array([e['area8_mv_us'] for e in a])
            axes[1,0].scatter(p,area,s=3,alpha=.22,color=colors[label],rasterized=True)
            axes[1,0].set(xlabel='Sampled peak (mV)',ylabel='Signed 8 us area (mV us)',
                          title='Same source events: area versus peak')
            # A representative clean event near the median amplitude.
            e=min(a,key=lambda e:abs(e['peak_mv']-float(np.median(p))))
            y=np.fromfile(Path(meta['source_directory'])/(e['frame']+'.bin'),dtype='<u2').astype(float)
            t=e['trigger_index']; indices=np.arange(t-10,t+30)
            axes[1,1].plot(indices-t,(e['baseline_code']-y[indices])*SCALE,'.-',color=colors[label])
            for lo,hi,col,txt in [(-1,3,'#b0d8f0','first 4 us'),(3,7,'#d3e9b6','extend to 8 us'),(7,15,'#eee4bd','extend to 16 us')]:
                axes[1,1].axvspan(lo,hi,color=col,alpha=.55,label=txt)
            axes[1,1].axhline(0,color='gray',lw=.7)
            axes[1,1].set(xlabel='Time from threshold crossing (us)',ylabel='Baseline - ADC (mV)',
                          title=f"Actual samples: {e['frame']} @ {t}")
            axes[1,1].legend(fontsize=8)
    for ax in axes.flat: ax.grid(alpha=.2)
    for ax,title,xlabel in [(axes[0,0],'Sampled peak distribution','Peak at ADC (mV)'),
                            (axes[0,1],'Finite-window area distribution','Signed 8 us area at ADC (mV us)')]:
        ax.set(title=title,xlabel=xlabel,ylabel='Accepted / sampled second / bin',yscale='symlog',ylim=(0,None))
        ax.legend(fontsize=8)
    fig.suptitle('Aster AT32: experimental offline spectrum replay at 1 MS/s',fontsize=15)
    fig.supxlabel('Uncalibrated; cuts can bias distributions. Sample windows have USB gaps. Lines do not resolve between-sample peaks.',fontsize=9)
    fig.savefig(out/'AT32-spectrum-replay.png',dpi=170)
    plt.close(fig)
    with (out/'spectra.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(histogram_rows[0]));w.writeheader();w.writerows(histogram_rows)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset',action='append',required=True,help='label=/capture/directory')
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    results={}
    for item in args.dataset:
        label,path=item.split('=',1)
        if not label.replace('_','').isalnum() or label in results:
            raise ValueError('Labels must be unique alphanumeric names')
        results[label]=process(Path(path),label,args.out)
    plot_and_export(results,args.out)
    summary={'algorithm':'experimental-replay-0.1',
             'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'sample_rate_hz':1000000,
             'threshold_codes':THRESHOLD,'nominal_vdda_v':3.3,
             'pre_samples':PRE,'guard_samples':GUARD,'post_samples':TAIL,
             'integration':'Signed sum from trigger-1; gates 4, 8, 16 samples at 1 MS/s',
             'data':[r[0] for r in results.values()],
             'limitations':['No keV calibration, energy-resolution claim or validated detector CPS.',
                            'Sub-sample pulse shape and merged pile-up remain unresolved.',
                            'Selection cuts may reject physical events and bias distributions.',
                            'N/fs describes sampled coverage, not total MCA live time.',
                            'No connection between frames; their USB gaps are unobserved.',
                            'Signed area is an estimator, not charge in coulombs.']}
    (args.out/'replay-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps([{k:v for k,v in r[0].items() if k!='raw_sha256'} for r in results.values()],indent=2))


if __name__=='__main__': main()
