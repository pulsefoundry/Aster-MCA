"""Offline fixed-pulse analysis; never opens a USB/serial device."""
from pathlib import Path
import argparse
import csv
import json
import math
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'firmware/at32-peakhold-fast7'))
from capture_spectrum import decode_batch, add_events, validate_info


def describe(values):
    a = np.asarray(values, dtype=float)
    if not len(a):
        return {'n': 0}
    return dict(n=len(a), mean=float(a.mean()), median=float(np.median(a)),
                sigma_population=float(a.std()), minimum=float(a.min()),
                maximum=float(a.max()),
                percentiles_1_5_50_95_99=np.percentile(a, [1, 5, 50, 95, 99]).tolist())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--nominal-mvpp', type=float, help='Operator-confirmed generator setting, not a measured voltage')
    args = p.parse_args()
    spectrum = json.loads((args.capture / 'spectrum.json').read_text())
    assert spectrum['completed']
    validate_info(spectrum['final'], True, spectrum['peak_sample_cycles_x2'], spectrum['wait_limit_us'])
    counts, all_counts, rows = [0] * 2048, [0] * 2048, []
    sums = {k: 0 for k in spectrum['internal_timing_sums']}
    totals = dict(received=0, binned=0, flagged=0, clipped=0, underflow=0, overflow=0)
    batches = [json.loads(s) for s in (args.capture / 'batches.jsonl').read_text().splitlines()]
    for b in batches:
        decoded = decode_batch(b['header'], (args.capture / b['file']).read_bytes(),
                               window_us=spectrum['capture_window_us'],
                               peak_sample_x2=spectrum['peak_sample_cycles_x2'],
                               wait_limit_us=spectrum['wait_limit_us'])
        selected = add_events(counts, decoded)
        assert selected == b['selection']
        for k in totals:
            totals[k] += selected[k]
        for k in sums:
            sums[k] += b['header'][k]
        for r in decoded:
            r['batch'] = b['batch']
            if 0 <= r['amplitude_code'] < 4096:
                all_counts[math.floor(r['amplitude_code'] / 2)] += 1
        rows.extend(decoded)
    assert counts == spectrum['counts'] and all_counts == spectrum['all_received_counts']
    assert all(totals[k] == spectrum['totals'][k] for k in totals)
    assert sums == spectrum['internal_timing_sums']
    assert len(batches) == spectrum['totals']['batches']
    safe = [r for r in rows if not r['flags'] and max(r[f'peak{i}'] for i in range(1, 5)) < 2048
            and 0 <= r['amplitude_code'] < 4096]
    result = dict(capture=str(args.capture.resolve()), raw_crc_metadata_histogram_verified=True,
                  nominal_generator_mvpp=args.nominal_mvpp,
                  wall_seconds=spectrum['wall_seconds'], totals=spectrum['totals'],
                  safe_n=len(safe), safe_wall_cps=len(safe)/spectrum['wall_seconds'],
                  analog_high_n=sum(max(r[f'peak{i}'] for i in range(1, 5)) >= 2048 for r in rows),
                  amplitude_all_codes=describe([r['amplitude_code'] for r in rows]),
                  amplitude_safe_codes=describe([r['amplitude_code'] for r in safe]),
                  amplitude_safe_channels=describe([r['amplitude_code']/2 for r in safe]),
                  baseline_codes=describe([r['baseline'] for r in rows]),
                  read_span_codes=describe([max(r[f'peak{i}'] for i in range(1, 5))-
                                            min(r[f'peak{i}'] for i in range(1, 5)) for r in rows]),
                  reset_minus_baseline_codes=describe([r['reset_peak']-r['baseline'] for r in rows]),
                  assumptions=['Generator settings are nominal and operator controlled.',
                               'Codes use the recorded ADC values; no energy calibration or Gaussian fit.',
                               'Safe selection: flags=0, max PEAK<2048, amplitude in [0,4096).',
                               'Wall count rate is not absolute trigger efficiency or true live-time rate.'])
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    if rows:
        with (args.output / 'events.csv').open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        fig, ax = plt.subplots(2, 2, figsize=(11, 7.5), constrained_layout=True)
        x = np.asarray([r['amplitude_code']/2 for r in rows])
        low, high = math.floor(x.min()), math.ceil(x.max()) + 1
        edges = np.arange(low, max(low+2, high)+1)
        ax[0, 0].hist(x, bins=edges, histtype='step', label='All received')
        ax[0, 0].hist([r['amplitude_code']/2 for r in safe], bins=edges, histtype='step', label='Quality + analog guard')
        title = f'{args.nominal_mvpp:g} mVpp nominal fixed input' if args.nominal_mvpp is not None else 'Fixed input pulse'
        ax[0, 0].set(xlabel='Amplitude channel (2 ADC codes / channel)', ylabel='Events', title=title)
        ax[0, 0].legend()
        ax[0, 1].plot(x, '.', ms=2)
        ax[0, 1].set(xlabel='Received event index', ylabel='Amplitude channel', title='All events in acquisition order')
        ax[1, 0].plot([r['baseline'] for r in rows], '.', ms=2, label='RAW baseline')
        ax[1, 0].plot([r['reset_peak'] for r in rows], '.', ms=2, label='Reset PEAK')
        ax[1, 0].set(xlabel='Received event index', ylabel='ADC code', title='Baseline / reset reference')
        ax[1, 0].legend()
        ax[1, 1].scatter([r['wait_cycles']/144 for r in rows], x, s=4)
        ax[1, 1].set(xlabel='Firmware wait_cycles / CPU (us)', ylabel='Amplitude channel', title='Amplitude versus recorded wait')
        for a in ax.flat:
            a.grid(alpha=.25)
        fig.savefig(args.output/'fixed-pulse.png', dpi=160)
        plt.close(fig)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
