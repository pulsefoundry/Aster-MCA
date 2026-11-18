"""Compare saved nominal generator levels; no hardware access or energy calibration."""
from pathlib import Path
import argparse
import csv
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--levels', type=int, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    levels = sorted(args.levels)
    assert len(set(levels)) == len(levels) and 500 in levels
    summaries, spectra, points, large_events = {}, {}, [], []
    for mv in levels:
        a = json.loads((args.run/f'analysis-{mv}mv/summary.json').read_text())
        s = json.loads((args.run/f'pulse-{mv}mv/spectrum.json').read_text())
        assert a['raw_crc_metadata_histogram_verified'] and s['completed']
        assert s['final']['fault'] == 0 and s['final']['hold'] == s['final']['reset'] == 1
        assert a['totals'] == s['totals']
        summaries[mv], spectra[mv] = a, s
        if mv != levels[0]:
            first = spectra[levels[0]]
            for k in ['capture_window_us', 'extra_read_delay_us', 'peak_sample_cycles_x2',
                      'wait_limit_us', 'bins', 'adc_codes_per_channel']:
                assert s[k] == first[k], k
            for k in ['fw', 'timer_hz', 'adc_hz', 'raw_rate_hz', 'raw_stop_phase',
                      'peak_sample_cycles_x2', 'wait_limit_us']:
                assert s['configured'][k] == first['configured'][k], k
        point = dict(nominal_mvpp=mv, nominal_offset_mv=-mv/2,
                     wall_seconds=a['wall_seconds'], received=a['totals']['received'],
                     selected=a['safe_n'], flagged=a['totals']['flagged'],
                     selected_median_channel=a['amplitude_safe_channels']['median'],
                     all_received_median_channel=a['amplitude_all_codes']['median']/2,
                     selected_percentiles_channel=a['amplitude_safe_channels']['percentiles_1_5_50_95_99'])
        points.append(point)
        rows = list(csv.DictReader((args.run/f'analysis-{mv}mv/events.csv').open()))
        # This descriptive criterion identifies large excursions; it is never a spectrum cut.
        for i, r in enumerate(rows):
            if float(r['amplitude_code']) > 2*a['amplitude_all_codes']['median']:
                large_events.append(dict(nominal_mvpp=mv, event_index_1_based=i+1,
                                         channel=float(r['amplitude_code'])/2,
                                         prepare_to_hold_irq_us=int(r['wait_cycles'])/144,
                                         flags=int(r['flags']),
                                         peak_codes=[int(r[f'peak{k}']) for k in range(1, 5)],
                                         batch=int(r['batch']), attempt_id=int(r['id'])))
    anchor = summaries[500]['amplitude_safe_channels']['median']
    for point in points:
        ref = anchor*point['nominal_mvpp']/500
        point['zero_intercept_reference_channel'] = ref
        point['difference_from_reference_channel'] = point['selected_median_channel']-ref
        point['relative_difference_from_reference'] = point['selected_median_channel']/ref-1
    slopes = [dict(from_mvpp=a['nominal_mvpp'], to_mvpp=b['nominal_mvpp'],
                   channel_per_nominal_mv=(b['selected_median_channel']-a['selected_median_channel'])/
                                         (b['nominal_mvpp']-a['nominal_mvpp']))
              for a, b in zip(points, points[1:])]
    result = dict(created=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                  configuration_equality_verified=True, points=points, adjacent_secant_slopes=slopes,
                  large_event_criterion='Amplitude > twice the all-received median at each level; descriptive only, no removal.',
                  large_events=large_events,
                  timing_definition='wait_cycles measures ph_prepare entry to HOLD IRQ; includes preparation, priming, capture and IRQ latency, not physical interarrival time.',
                  notes=['Nominal operator-controlled generator voltage; not independently measured.',
                         'Fixed periodic source and gates can phase-select; wall rates are not absolute trigger efficiency.',
                         'No energy calibration or Gaussian resolution fit applied.',
                         'These nominal voltage points do not identify the physical cause of offset or curvature.',
                         'Large excursions remain in all primary statistics and native spectra.'])
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    fig, ax = plt.subplots(1, 2, figsize=(11, 5.0), layout='constrained')
    palette = plt.get_cmap('tab10').colors
    for i, mv in enumerate(levels):
        color = palette[i % len(palette)]
        c = np.array(spectra[mv]['counts'])
        ax[0].stairs(c/c.sum(), np.arange(2049), color=color, linewidth=1.6,
                     label=f'{mv} mVpp: {int(c.sum())} in native spectrum')
    upper_channel = int(np.ceil(max(a['selected_percentiles_channel'][-1] for a in points)/10)*10+5)
    ax[0].set(xlim=(10, upper_channel), ylim=(0, .78), xlabel='Amplitude channel (2 ADC codes/channel)',
              ylabel='Fraction per native channel', title='Native spectra, central region')
    outside = sum(sum(spectra[mv]['counts'][upper_channel:]) for mv in levels)
    ax[0].text(.03, .95, f'{outside} events above zoom; retained in original spectra.',
               transform=ax[0].transAxes, va='top', fontsize=8,
               bbox=dict(facecolor='white', edgecolor='none', alpha=.9))
    ax[0].legend(loc='upper center', bbox_to_anchor=(.5, -.20), ncol=2, fontsize=8)
    x = np.linspace(0, max(levels)*1.1, 100)
    ax[1].plot(x, x*anchor/500, '--', color='gray', label='Zero-intercept reference anchored at 500 mV')
    ax[1].plot(levels, [a['selected_median_channel'] for a in points], 'o', color='#2471a3',
               label='Measured median; no calibration applied')
    for point in points:
        x0, y0 = point['nominal_mvpp'], point['selected_median_channel']
        dx, dy = (-190, 6) if x0 == max(levels) else (-80, -12)
        ax[1].annotate(f'{x0} mV: {y0:.3f} ch', xy=(x0, y0), xytext=(x0+dx, y0+dy),
                       arrowprops=dict(arrowstyle='->'), fontsize=9)
    ax[1].set(xlim=(0, max(levels)*1.13), ylim=(0, max(p['selected_median_channel'] for p in points)*1.3),
              xlabel='Nominal generator amplitude (mVpp)', ylabel='Median amplitude channel',
              title='Amplitude response: nominal voltage settings')
    ax[1].legend(loc='upper left', fontsize=8)
    for a in ax:
        a.grid(alpha=.2)
    fig.suptitle('Negative 4 µs waveform · 976.5625 Hz · PHWAIT 500 µs · about 5 s per point')
    fig.savefig(args.output/'comparison.png', dpi=160)
    plt.close(fig)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
