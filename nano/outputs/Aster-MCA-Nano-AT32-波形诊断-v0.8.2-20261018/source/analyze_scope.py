"""Offline diagnostics of verified finite snapshots; never concatenate gaps."""
import argparse
import csv
import ctypes as c
import json
import math
from pathlib import Path
import subprocess

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from scope_capture import N, RATE, validate_raw, validate_raw_info

HERE = Path(__file__).resolve().parent


class Event(c.Structure):
    _fields_ = [('trigger', c.c_uint64), *[(x, c.c_double) for x in
        ['baseline', 'peak', 'area4', 'area8', 'area16', 'pre_rms']],
        ('flags', c.c_uint32), ('half_width', c.c_uint32)]


def analyze(folder, out):
    folder, out = Path(folder), Path(out)
    record = json.loads((folder/'capture.json').read_text())
    assert record['completed'] and record['acquisition_mode'] == 'diagnostic_snapshot'
    validate_raw_info(record['initial_info']); validate_raw_info(record['final_info'])
    metadata = [json.loads(line) for line in (folder/'blocks.jsonl').read_text().splitlines()]
    raw = (folder/'samples.u16').read_bytes()
    assert len(metadata) == record['blocks'] and len(raw) == len(metadata)*N*2
    expected = record['initial_info']['raw_capture_id']+1
    for index, header in enumerate(metadata):
        assert header['segment_index'] == index and header['stored_sample_offset'] == index*N
        validate_raw(header, raw[index*N*2:(index+1)*N*2], expected+index)
    assert record['final_info']['raw_capture_id'] == expected+len(metadata)-1
    y = np.frombuffer(raw, dtype='<u2').reshape(-1, N)

    # Existing reference processor has event diagnostics and exactly the same
    # frozen-baseline/quality rules as the MCU engine. Compare their histograms.
    for source, name in [(HERE/'host_engine.c', 'libasterhist'),
                         (HERE.parent/'at32-burst/host_dsp.c', 'libreference')]:
        subprocess.run(['cc', '-O3', '-Wall', '-Wextra', '-Werror', '-dynamiclib',
            str(source), '-o', str(HERE/f'build/{name}.dylib')], check=True)
    ref = c.CDLL(str(HERE/'build/libreference.dylib'))
    ref.processor_new.argtypes = [c.c_double]; ref.processor_new.restype = c.c_void_p
    ref.processor_free.argtypes = [c.c_void_p]
    ref.processor_pending.argtypes = [c.c_void_p]
    ref.processor_feed.argtypes = [c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(Event)]
    ref.processor_feed.restype = c.c_size_t
    engine = c.CDLL(str(HERE/'build/libasterhist.dylib'))
    engine.engine_new.argtypes = [c.c_uint]; engine.engine_new.restype = c.c_void_p
    engine.engine_feed.argtypes = [c.c_void_p, c.c_void_p, c.c_uint]
    engine.engine_counts.argtypes = engine.engine_stats.argtypes = [c.c_void_p, c.c_void_p]
    engine.engine_free.argtypes = [c.c_void_p]
    events, totals, histogram = [], np.zeros(16, dtype=np.int64), np.zeros(2048, dtype=np.int64)
    for segment, values in enumerate(y):
        p, q = ref.processor_new(20), engine.engine_new(20)
        assert p and q
        try:
            buf = values.ctypes.data_as(c.c_void_p)
            output = (Event*(N//59+2))()
            count = ref.processor_feed(p, buf, N, output)
            engine.engine_feed(q, buf, N)
            bins, stats = (c.c_uint32*2048)(), (c.c_uint32*16)()
            engine.engine_counts(q, bins); engine.engine_stats(q, stats)
            expected_bins = np.zeros(2048, dtype=np.int64)
            for e in output[:count]:
                row = dict(segment=segment, trigger=int(e.trigger), baseline_code=e.baseline,
                    peak_code=e.peak, nominal_peak_mv=e.peak*3300/4096,
                    pre_rms_code=e.pre_rms, half_height_width_us=e.half_width/RATE*1e6,
                    area4_code_us=e.area4, area8_code_us=e.area8,
                    flags=int(e.flags))
                events.append(row)
                if e.flags == 0 and 0 <= e.peak < 2048: expected_bins[math.floor(e.peak)] += 1
            assert np.array_equal(expected_bins, np.array(bins))
            assert count == stats[0] and ref.processor_pending(p) == stats[5] and stats[6] == 0
            totals += np.array(stats); histogram += expected_bins
        finally:
            ref.processor_free(p); engine.engine_free(q)

    accepted = [e for e in events if e['flags'] == 0]
    # Fixed 64-sample (16 us) windows; quiet candidates exclude large excursions.
    windows = y.reshape(-1, 64).astype(float)
    quiet = windows[np.ptp(windows, axis=1) < 20]
    rms = quiet.std(axis=1) if len(quiet) else np.array([])

    def distribution(values):
        v = np.asarray(values, dtype=float)
        return dict(n=len(v), median=float(np.median(v)), p10=float(np.quantile(v, .1)),
            p90=float(np.quantile(v, .9))) if len(v) else dict(n=0)

    result = dict(input_record=str(folder.resolve()), input_state=record['input'],
        firmware=record['initial_info']['fw'], diagnostic_only=True,
        integrity_rechecked=True, engine_histogram_exact_match=True,
        segment_samples=N, sample_rate_hz=RATE, segment_us=N/RATE*1e6,
        snapshots=len(y), verified_sampled_seconds=len(y)*N/RATE,
        wall_seconds=record['wall_seconds'], minimum_code=int(y.min()), maximum_code=int(y.max()),
        segment_mean=distribution(y.mean(axis=1)), quiet_window_rms_code=distribution(rms),
        quiet_window_rms_nominal_mv=distribution(rms*3300/4096),
        quiet_windows=len(quiet), total_windows=len(windows),
        candidates=int(totals[0]), accepted=int(totals[1]), rejected=int(totals[2]),
        boundary_pending_excluded=int(totals[5]), rejection_flags=totals[11:].tolist(),
        accepted_peak_code=distribution([e['peak_code'] for e in accepted]),
        accepted_pre_rms_code=distribution([e['pre_rms_code'] for e in accepted]),
        accepted_half_height_width_us=distribution([e['half_height_width_us'] for e in accepted]),
        amplitude_60_to_100_code_events=sum(60 <= e['peak_code'] <= 100 for e in accepted),
        limitations=['Independent 1.024 ms snapshots with unsampled upload gaps; no absolute detector rate.',
            'Quiet-window RMS selects 16 us windows with range below 20 ADC codes and removes each window mean. This can suppress slow drift and exclude noise outliers.',
            'Voltages assume a nominal 3.3 V ADC reference, not a measured reference.',
            'Half-height width is counted on 0.25 us samples, not an analog bandwidth measurement.',
            '60..100 ADC codes is an illustrative amplitude range from the prior spectrum, not tagged photopeak events.',
            'No resolution fit, energy calibration, gain change or proof against out-of-band oscillation.'])
    out.mkdir(parents=True, exist_ok=False)
    (out/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    if events:
        with (out/'events.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(events[0])); writer.writeheader(); writer.writerows(events)
    np.savetxt(out/'snapshot-peak-histogram.csv', np.c_[np.arange(2048), histogram], fmt='%d',
        delimiter=',', header='channel_adc_code,counts', comments='')

    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10,
        'axes.spines.top':False, 'axes.spines.right':False})
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout='constrained')
    representative = accepted[len(accepted)//2] if accepted else None
    segment = representative['segment'] if representative else 0
    axes[0, 0].plot(np.arange(N)/RATE*1e6, y[segment], lw=.7, color='#26718f')
    axes[0, 0].set(title=f'Unsmoothed ADC snapshot #{segment}', xlabel='Time within snapshot (us)', ylabel='ADC code')
    if len(quiet):
        quiet_residuals = (quiet-quiet.mean(axis=1, keepdims=True)).ravel()
        axes[0, 1].hist(quiet_residuals, bins=np.arange(-20, 20.01, .5), color='#728b98')
        axes[0, 1].set(title=f'Quiet-window residuals; median RMS {np.median(rms):.2f} codes',
            xlabel='ADC code minus 16 us window mean', ylabel='Samples', xlim=(-12, 12))
    selected = sorted(accepted, key=lambda e:e['peak_code'])
    if selected:
        indices = sorted(set(np.round(np.linspace(0, len(selected)-1, min(6, len(selected)))).astype(int)))
        for index in indices:
            e = selected[index]; trigger = e['trigger']; segment = e['segment']
            lo, hi = max(0, trigger-20), min(N, trigger+64)
            axes[1, 0].plot((np.arange(lo, hi)-trigger)/RATE*1e6,
                y[segment, lo:hi]-e['baseline_code'], '.-', markersize=2, lw=.8,
                label=f"{e['peak_code']:.0f} codes")
        axes[1, 0].legend(frameon=False, fontsize=8)
    axes[1, 0].set(title='Accepted pulses spanning observed amplitude ranks',
        xlabel='Time from threshold crossing (us)', ylabel='ADC code minus frozen baseline', xlim=(-5, 16))
    if accepted:
        axes[1, 1].hist([e['peak_code'] for e in accepted], bins=np.arange(0, 514, 2), color='#26718f')
    axes[1, 1].set(title=f'Diagnostic events: {len(accepted)} accepted; no resolution fit',
        xlabel='Sampled peak above frozen baseline (ADC codes)', ylabel='Events / 2 codes', xlim=(0, 260))
    for ax in axes.ravel(): ax.grid(alpha=.15)
    fig.suptitle(f'Aster Nano AT32 v{result["firmware"]} | finite raw waveform diagnostics', fontsize=14)
    fig.supxlabel(f'{len(y)} snapshots; {len(y)*N/RATE:.4f} s sampled; gaps excluded; no energy calibration', fontsize=9)
    fig.savefig(out/'waveform-diagnostics.png', dpi=170); plt.close(fig)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('record', type=Path); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); analyze(a.record, a.out)
