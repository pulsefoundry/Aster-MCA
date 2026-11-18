"""Reproduce the 2026-11-16 fixed-pulse speed/repeatability comparison."""
from pathlib import Path
import hashlib
import json
import statistics as st
import struct
import zlib

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
FAST = ROOT / 'work/peakhold-fast-20261116'
OLD = ROOT / 'work/peakhold-timing-20261116'
OUT = ROOT / 'outputs/Aster-MCA-Nano-144M-4MSa-读出对照-20261116'
OUT.mkdir(parents=True, exist_ok=True)
groups = {
    '48 MHz / timing.1': [OLD / f'pulse-300mv-{i:02d}/result.json' for i in range(1, 4)],
    '144 MHz / fast.1': [FAST / x / 'result.json' for x in ['pulse-300mv-01', 'pulse-300mv-repeat-02']],
    '144 MHz / fast.2 LATE': [FAST / f'fast2-pulse-300mv-late-{i:02d}/result.json' for i in range(1, 4)],
    '144 MHz / fast.2 EARLY': [FAST / f'fast2-pulse-300mv-early-{i:02d}/result.json' for i in range(2, 5)],
}
summary = {}
loaded = {}
for name, paths in groups.items():
    batches = [json.loads(p.read_text()) for p in paths]
    rows = []
    for p, d in zip(paths, batches):
        assert d['completed'] and d['raw_crc_verified'] and d['header']['fault'] == 0
        raw = (p.parent / 'records.bin').read_bytes()
        assert zlib.crc32(raw) == d['header']['crc32']
        binary_rows = list(struct.iter_unpack('<16I', raw))
        assert len(binary_rows) == len(d['records']) == d['header']['n']
        for words, r in zip(binary_rows, d['records']):
            assert list(words) == [r[k] for k in d['record_fields']]
            assert r['amplitude_code'] == st.mean(words[6:10]) - words[1]
        rows += d['records']
    amp = [r['amplitude_code'] for r in rows]
    mean, sigma = st.mean(amp), st.pstdev(amp)
    n = len(rows)
    # Within-batch spread is shown separately so changes of batch mean remain visible.
    within_sigma = (sum(len(d['records']) * st.pvariance(r['amplitude_code'] for r in d['records'])
                        for d in batches) / n) ** 0.5
    busy_n = sum(d['header'].get('within_batch_busy_n', 0) for d in batches)
    busy_sum_us = sum(d['header'].get('within_batch_busy_mean_cycles', 0) *
                      d['header'].get('within_batch_busy_n', 0) / d['header']['core_hz'] * 1e6
                      for d in batches)
    summary[name] = {
        'files': [str(p.relative_to(ROOT)) for p in paths], 'n': n,
        'requested': sum(d['header']['requested'] for d in batches),
        'timeouts': sum(d['header']['timeouts'] for d in batches),
        'baseline_rejects': sum(d['header']['baseline_rejects'] for d in batches),
        'flagged_records': sum(r['flags'] != 0 for r in rows),
        'mean_code': mean, 'sigma_code': sigma, 'relative_rms_percent': sigma / mean * 100,
        'within_batch_sigma_code': within_sigma,
        'batch_means_code': [d['summary']['amplitude_mean_code'] for d in batches],
        'first_read_us_range': [min(r['first_read_us_after_hold_irq'] for r in rows),
                                max(r['first_read_us_after_hold_irq'] for r in rows)],
        'last_read_us_range': [min(r['last_read_us_after_hold_irq'] for r in rows),
                               max(r['last_read_us_after_hold_irq'] for r in rows)],
        'within_batch_busy_mean_us': busy_sum_us / busy_n if busy_n else None,
        'source_sha256': [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths],
    }
    loaded[name] = (batches, rows)

result = {'condition': 'AG1022 N61116A.bin, nominal 300mVpp / -150mV / 976.56Hz / High Z',
          'amplitude_definition': 'mean(peak1..peak4) - baseline; no outlier removal',
          'early_mode_execution_verified': False,
          'comparability': '48MHz vs 144MHz also changes ADC clock and baseline method; measurements were not interleaved across firmware.',
          'scope': 'Fixed electrical pulse repeatability, not detector energy resolution. Read timing is relative to HOLD IRQ entry; busy excludes batch upload and waiting for host.',
          'groups': summary}
(OUT / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')

fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), layout='constrained')
colors = ['#607d8b', '#db9644', '#228c8c', '#9065b0']
for (name, (batches, rows)), color in zip(loaded.items(), colors):
    axes[0].hist([r['last_read_us_after_hold_irq'] for r in rows], bins=22,
                 density=True, histtype='step', linewidth=1.7, label=name, color=color)
    deviations = [r['amplitude_code'] - st.mean(x['amplitude_code'] for x in d['records'])
                  for d in batches for r in d['records']]
    axes[1].hist(deviations, bins=list(range(-40, 42, 2)), density=True,
                 histtype='step', linewidth=1.7, label=name, color=color)
for name, color in zip(list(loaded)[2:], colors[2:]):
    values = summary[name]['batch_means_code']
    axes[2].plot(range(1, 4), values, 'o-', color=color, label=name.split(' / ')[1])
axes[0].set(xlabel='Fourth read after HOLD IRQ (us)', ylabel='Probability density (1/us)', title='Readout completion')
axes[1].set(xlabel='Amplitude minus its batch mean (ADC codes)', ylabel='Probability density (1/code)', title='Within-batch spread; all events included')
axes[2].set(xlabel='Alternating pair', ylabel='Mean amplitude (ADC codes)', title='fast.2 batch means; n=128 each', xticks=[1, 2, 3])
for ax in axes:
    ax.grid(alpha=.2)
    ax.legend(fontsize=8)
fig.suptitle('Aster MCA Nano peak hold — fixed 300 mV negative pulse, 2026-11-16')
fig.savefig(OUT / 'readout-comparison.png', dpi=170)
print(json.dumps(summary, indent=2))
