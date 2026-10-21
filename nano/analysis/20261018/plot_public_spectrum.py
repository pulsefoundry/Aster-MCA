"""Plot the archived 2048-channel gross-source spectrum without changing it."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'outputs/Aster-MCA-Nano-AT32-增益5倍实测-20261018'
OUT = ROOT / 'docs/at32/cs137-60s-spectrum.png'


def main():
    with (DATA/'Cs-source-60s-2048ch.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    meta = json.loads((DATA/'Cs-source-60s-2048ch-metadata.json').read_text())
    fit = json.loads((DATA/'gain-peak-fit-comparison.json').read_text())['after']
    channels = np.array([int(row['channel']) for row in rows])
    counts = np.array([int(row['counts']) for row in rows])
    background = np.array([float(row['background_scaled_counts']) for row in rows])
    assert np.array_equal(channels, np.arange(2048)) and counts.sum() == 17611
    assert meta['sampled_seconds'] == 60.000256 and meta['threshold_codes'] == 100
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), layout='constrained',
                             gridspec_kw={'width_ratios': [1, 1.35]})
    for ax, limit, title in zip(axes, (2048, 650), ('Full 2048-channel histogram', 'Detail: channels 0-650')):
        edges = np.arange(2049)
        ax.stairs(background, edges, color='#a6adb4', lw=.9, alpha=.8,
                  label='Background scaled to source sampled time')
        ax.stairs(counts, edges, color='#246b8e', lw=1.0, label='Gross-source counts')
        ax.axvline(100, color='#777777', lw=.8, ls='--', label='Trigger threshold: 100 codes')
        ax.set(xlim=(0, limit), ylim=(0, max(counts.max(), background.max())*1.13),
               xlabel='Pulse-height channel (ADC codes; not energy-calibrated)',
               ylabel='Counts per native 1-code bin', title=title)
        ax.grid(axis='y', alpha=.16)
    axes[1].annotate(f"Archived peak fit: centroid {fit['centroid_adc_code']:.2f}\n"
                     f"FWHM/centroid {fit['apparent_fwhm_percent']:.2f}%",
                     xy=(fit['centroid_adc_code'], counts[409]), xycoords='data',
                     xytext=(.53, .87), textcoords='axes fraction', fontsize=9,
                     arrowprops={'arrowstyle': '-', 'color': '#555555'})
    axes[0].legend(loc='upper right', fontsize=7.5, frameon=False)
    fig.suptitle('Cs-137 source | AT32 v0.8.2 | 4 MS/s | 60.000256 s sampled | 17,611 accepted', fontsize=12)
    fig.supxlabel('Gain rework: R21=40.2 kohm, R22=10 kohm. Unsmoothed counts; no background subtraction or dead-time correction.', fontsize=9)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=170)
    print(f'Wrote {OUT.relative_to(ROOT)} from archived native histogram; accepted counts={counts.sum()}')


if __name__ == '__main__':
    main()
