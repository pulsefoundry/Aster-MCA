"""Offline CRC-checked RAW pulse/noise analysis; no hardware access."""
from pathlib import Path
import argparse
import json
import zlib

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def stats(x):
    a = np.asarray(x, dtype=float)
    return dict(n=len(a), median=float(np.median(a)), mean=float(a.mean()),
                sigma_population=float(a.std()), minimum=float(a.min()), maximum=float(a.max()),
                percentiles_5_95=np.percentile(a, [5, 95]).tolist())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--mode', choices=['signal', 'off'], required=True)
    p.add_argument('--peak-summary', type=Path)
    args = p.parse_args()
    run = json.loads((args.capture/'result.json').read_text())
    assert run['completed'] and run['original_profile_restored']
    assert run['final']['fault'] == 0 and run['final']['hold'] == run['final']['reset'] == 1
    rows, signals = [], []
    for record in run['snapshots']:
        h = json.loads((args.capture/record['header_file']).read_text())
        raw = (args.capture/record['file']).read_bytes()
        u = np.frombuffer(raw, dtype='<u2')
        assert h['n'] == len(u) == 4096 and h['crc32'] == zlib.crc32(raw)
        assert h['min'] == int(u.min()) and h['max'] == int(u.max()) <= 4095
        assert h['sum'] == int(u.sum()) and h['sum_sq'] == int((u.astype(np.uint64)**2).sum())
        assert h['fault'] == 0 and h['channel'] == 'RAW' and 0 < h['guard_remaining'] <= 4096
        assert (h['core_hz'], h['adc_hz'], h['sample_rate_hz'], h['timer_ticks'], h['sample_cycles_x2']) == (144000000, 72000000, 4000000, 36, 5)
        assert abs(h['elapsed_cycles']/(h['n']*h['timer_ticks'])-1) < .01
        a = u.astype(float)
        baseline = float(np.median(a))
        i = int(np.argmax(a))
        row = dict(file=record['file'], baseline_global_median_code=baseline,
                   whole_record_sigma_code=float(a.std()), minimum_code=float(a.min()),
                   maximum_code=float(a.max()), max_minus_global_median_code=float(a.max()-baseline),
                   peak_index=i, samples_above_baseline_plus10=int(np.sum(a > baseline+10)),
                   pulse_roi_complete=False)
        # Local waveform statistics require an intact ROI. Global amplitudes above keep every record.
        if args.mode == 'signal' and i >= 60 and i+80 < len(a):
            b = float(a[i-60:i-20].mean())
            aligned = a[i-60:i+81]-b
            row.update(pulse_roi_complete=True, baseline_local_mean_code=b,
                       peak_minus_local_baseline_code=float(a[i]-b),
                       signed_area_minus4_to_plus12us_code_us=float((a[i-16:i+49]-b).sum()*.25))
            signals.append(aligned)
        rows.append(row)
    assert len(rows) == len(run['snapshots'])
    result = dict(capture=str(args.capture.resolve()), mode=args.mode,
                  nominal_generator_mvpp=run['nominal_generator_mvpp'],
                  crc_statistics_guard_rate_verified=True, snapshots=len(rows),
                  sample_rate_hz=4000000, sampled_duration_seconds=len(rows)*4096/4000000,
                  raw_global_amplitude_code=stats([r['max_minus_global_median_code'] for r in rows]),
                  baseline_global_median_code=stats([r['baseline_global_median_code'] for r in rows]),
                  record_sigma_code=stats([r['whole_record_sigma_code'] for r in rows]), records=rows,
                  notes=['Discontinuous snapshots; sampled duration is not wall time or true live time.',
                         'Global RAW amplitude is maximum ADC sample minus whole-record median; includes noise and sampling-phase effects.',
                         'Local pulse peak/area requires a complete -15us..+20us ROI,without wrapping the record.',
                         'RAW and earlier PEAK aggregates are different acquisition modes and are not same-event measurements.',
                         'Generator voltage is nominal; no independent input voltage or ADC reference calibration.'])
    if signals:
        good = [r for r in rows if r['pulse_roi_complete']]
        result['local_peak_amplitude_code'] = stats([r['peak_minus_local_baseline_code'] for r in good])
        result['local_signed_area_code_us'] = stats([r['signed_area_minus4_to_plus12us_code_us'] for r in good])
    if args.peak_summary:
        peak = json.loads(args.peak_summary.read_text())
        assert peak['raw_crc_metadata_histogram_verified']
        result['earlier_peak_capture'] = str(args.peak_summary.resolve())
        result['earlier_peak_amplitude_code'] = peak['amplitude_safe_codes']
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.4), layout='constrained')
    first = np.frombuffer((args.capture/run['snapshots'][0]['file']).read_bytes(), dtype='<u2')
    ax[0].plot(np.arange(len(first))*.25, first, lw=.7)
    ax[0].set(xlabel='Time within snapshot (us)', ylabel='RAW ADC code', title='First complete 1.024 ms record')
    if signals:
        t = np.arange(-60, 81)*.25
        for a in signals:
            ax[1].plot(t, a, alpha=.3, lw=.8)
        ax[1].plot(t, np.median(signals, axis=0), color='black', lw=1.5, label='Median of peak-aligned samples')
        if args.peak_summary:
            ax[1].axhline(peak['amplitude_safe_codes']['median'], color='#d35400', ls='--',
                          label='Earlier PEAK amplitude median (separate events)')
        ax[1].set(xlim=(-5, 12), xlabel='Time from maximum sample (us)',
                  ylabel='RAW code minus local pre-pulse baseline', title=f'{len(signals)} complete pulse ROIs')
        ax[1].legend(fontsize=8)
    else:
        ax[1].hist(np.concatenate([np.frombuffer((args.capture/r['file']).read_bytes(), dtype='<u2') for r in rows]),
                   bins=np.arange(min(r['minimum_code'] for r in rows), max(r['maximum_code'] for r in rows)+2)-.5)
        ax[1].set(xlabel='RAW ADC code', ylabel='Samples', title='Output-off sample distribution')
    for a in ax:
        a.grid(alpha=.2)
    fig.suptitle(f"RAW diagnostic: {run['nominal_generator_mvpp']:g} mVpp nominal, mode={args.mode}, 4 MSa/s")
    fig.savefig(args.output/'waveforms.png', dpi=160)
    plt.close(fig)
    print(json.dumps({k:v for k,v in result.items() if k != 'records'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
