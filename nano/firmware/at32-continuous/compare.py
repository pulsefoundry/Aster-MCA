"""Compare two verified continuous captures using their recorded event cuts.

No energy calibration, smoothing, isotope identification or peak fitting.
Requires NumPy and Matplotlib; original channel counts stay in the output CSV.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def load_run(folder):
    folder = Path(folder).resolve()
    capture = json.loads((folder / 'capture.json').read_text())
    summary = json.loads((folder / 'spectrum-summary.json').read_text())
    if not capture['completed'] or not summary['valid_continuous_run']:
        raise ValueError('Only complete, validated runs may be compared')
    values = np.memmap(folder / 'samples.u16', dtype='<u2', mode='r')
    if len(values) != summary['samples'] or len(values) != capture['blocks'] * 2048:
        raise ValueError('Stored sample count mismatch')
    events = np.atleast_1d(np.genfromtxt(folder / 'events.csv', delimiter=',', names=True))
    accepted = events[events['flags'] == 0]
    spectrum = np.genfromtxt(folder / 'spectrum.csv', delimiter=',', names=True)
    seconds = summary['sampled_seconds']
    # DMA rounds the duration up slightly; retain events in that final fraction.
    time_edges = np.arange(0, seconds, 10)
    if len(time_edges) > 1 and seconds - time_edges[-1] < .01:
        time_edges = time_edges[:-1]
    time_edges = np.append(time_edges, seconds)
    time_counts = np.histogram(accepted['time_s'], bins=time_edges)[0]
    widths, numbers = np.unique(accepted['half_height_samples'].astype(int), return_counts=True)
    stats = {
        'directory': str(folder), 'condition': capture['input'],
        'seconds': seconds, 'samples': len(values),
        'candidates': summary['candidates'], 'accepted': summary['accepted'],
        'candidate_rate': summary['candidates'] / seconds,
        'accepted_rate': summary['accepted'] / seconds,
        'acceptance_fraction': summary['accepted'] / summary['candidates'] if summary['candidates'] else None,
        'rejection_flags_nonexclusive': summary['rejection_flags'],
        'half_height_samples_counts': dict(zip(widths.tolist(), numbers.tolist())),
        'adc_range_codes': [int(values.min()), int(values.max())],
        'rail_samples': int(np.count_nonzero((values == 0) | (values == 4095))),
        'negative_area8_events': int(np.count_nonzero(accepted['area8_code_us'] < 0)),
        'area8_outside_histogram': summary['area8_outside_histogram'],
        'accepted_peak_mv_percentiles_5_50_95': (np.percentile(accepted['peak_code'], [5, 50, 95]) * 3300 / 4096).tolist() if len(accepted) else [],
        'accepted_counts_per_10s': time_counts.tolist(),
        'time_bin_edges_seconds': time_edges.tolist(),
        'accepted_rates_per_time_bin': (time_counts / np.diff(time_edges)).tolist(),
    }
    return capture, summary, spectrum, stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--background', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    cb, sb, hb, b = load_run(args.background)
    cs, ss, hs, s = load_run(args.source)
    for key in ['method', 'threshold_codes', 'peak_bin_code_width', 'area8_bin_code_us_width', 'nominal_vdda_v']:
        if sb[key] != ss[key]: raise ValueError('Analysis settings differ: ' + key)
    for key in ['fw', 'sample_rate_hz', 'adc_hz', 'sample_cycles_x2']:
        if cb['initial_info'][key] != cs['initial_info'][key]: raise ValueError('Acquisition settings differ: ' + key)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    tb, ts = b['seconds'], s['seconds']
    result = {'background': b, 'source': s, 'method': sb['method'],
              'threshold_codes': sb['threshold_codes'], 'calibration': None,
              'accepted_rate_ratio': s['accepted_rate'] / b['accepted_rate'] if b['accepted_rate'] else None,
              'candidate_rate_ratio': s['candidate_rate'] / b['candidate_rate'] if b['candidate_rate'] else None,
              'net_accepted_rate': s['accepted_rate'] - b['accepted_rate'],
              'net_accepted_rate_poisson_standard_error': float(np.sqrt(s['accepted'] / ts**2 + b['accepted'] / tb**2)),
              'uncertainty_scope': 'Counting statistics only; excludes drift, efficiency, cuts and gain changes.'}
    (out / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with (out / 'spectrum-comparison.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['channel', 'background_peak_count', 'source_peak_count', 'net_peak_per_s', 'net_peak_sigma_per_s',
                    'background_area8_count', 'source_area8_count', 'net_area8_per_s', 'net_area8_sigma_per_s'])
        for i in range(4096):
            row = [i]
            for key in ['peak_counts', 'area8_div4_counts']:
                nb, ns = int(hb[key][i]), int(hs[key][i])
                row += [nb, ns, ns / ts - nb / tb, float(np.sqrt(ns / ts**2 + nb / tb**2))]
            w.writerow(row)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout='constrained')
    for col, key, multiplier, title, label, xmax in [
        (0, 'peak_counts', 3300 / 4096, 'Sampled peak height', 'ADC peak (mV)', 900),
        (1, 'area8_div4_counts', 4 * 3300 / 4096, 'Fixed 8 us signed area', 'ADC area (mV us)', 1800)]:
        nb = hb[key].reshape(-1, 8).sum(1); ns = hs[key].reshape(-1, 8).sum(1)
        edges = np.arange(0, 4097, 8) * multiplier
        top, bottom = axes[0, col], axes[1, col]
        top.stairs(nb / tb, edges, label='Detector background', color='#3182bd')
        top.stairs(ns / ts, edges, label='Cs source present', color='#e6550d')
        top.set(title=title, yscale='symlog', ylim=(0, None)); top.legend(fontsize=9)
        net = ns / ts - nb / tb; sigma = np.sqrt(ns / ts**2 + nb / tb**2)
        bottom.stairs(net, edges, color='#31a354', label='Source minus background')
        bottom.fill_between((edges[:-1] + edges[1:]) / 2, net - sigma, net + sigma,
                            alpha=.2, color='#31a354', label='Counting +/- 1 sigma')
        bottom.axhline(0, color='gray', lw=.7); bottom.legend(fontsize=9)
        for ax in [top, bottom]:
            ax.set(xlabel=label, ylabel='Events / sampled s / displayed bin', xlim=(0, xmax))
            ax.grid(alpha=.2)
    fig.suptitle('Aster AT32 | 1 MS/s continuous | Background and Cs, 60 s each', fontsize=14)
    fig.supxlabel('Uncalibrated; same 20-code threshold and event cuts. Display: 8 native bins combined.\nNegative net bins retained. Rates are accepted events per sampled second, not corrected MCA live-time rates.', fontsize=9)
    fig.savefig(out / 'background-vs-cs.png', dpi=160)
    manifest = {}
    for label, folder in [('background', args.background), ('cs-source', args.source)]:
        folder = folder.resolve(); target = out / label; target.mkdir()
        for name in ['capture.json', 'spectrum-summary.json', 'events.csv', 'spectrum.csv']:
            shutil.copy2(folder / name, target / name)
        files = {}
        for name in ['samples.u16', 'stream.astc', 'blocks.jsonl']:
            path = folder / name; h = hashlib.sha256()
            with path.open('rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
            files[name] = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': h.hexdigest()}
        manifest[label] = files
    (out / 'raw-data-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('OUTPUT', out)


if __name__ == '__main__':
    main()
