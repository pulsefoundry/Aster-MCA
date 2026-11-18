"""Offline spectrum/peak/drift analysis. Never opens a device.

Run with work/usb-bringup-2026-10-13/wave-plot-env/bin/python.
The primary Gaussian + linear continuum ROI (channels120..180) is fixed from
the preceding one-minute spectrum; alternative windows are sensitivity checks.
"""
from pathlib import Path
import argparse
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'firmware/at32-peakhold-fast7'))
import numpy as np
from scipy.optimize import least_squares
from scipy.special import ndtr, xlogy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from capture_spectrum import decode_batch as _decode_batch, add_events

def decode_batch(head, raw):
    return _decode_batch(head, raw, wait_limit_us=head["wait_limit_us"])

FWHM_FACTOR = 2 * np.sqrt(2 * np.log(2))


def fit_peak(counts, lo=120, hi=180, initial=None, bin_width=1):
    assert (hi-lo) % bin_width == 0
    observed = np.asarray(counts[lo:hi], dtype=float).reshape(-1, bin_width).sum(axis=1)
    edges = np.arange(lo, hi + bin_width*.1, bin_width, dtype=float)
    centers = (edges[:-1] + edges[1:]) / 2
    t = (centers - lo) / (hi - lo)
    lower = np.array([0, max(lo + 2, 125), 1, 0, 0.])
    upper = np.array([max(100, observed.sum() * 20), min(hi - 2, 165), 20,
                      max(10, observed.sum()), max(10, observed.sum())])

    def components(p):
        area, mu, sigma, left, right = p
        peak = area * np.diff(ndtr((edges - mu) / sigma))
        background = (left + (right - left) * t) * np.diff(edges)
        return peak, background

    def model(p):
        peak, background = components(p)
        return np.maximum(peak + background, 1e-12)

    def residual(p):
        expected = model(p)
        deviance = 2 * (xlogy(observed, observed / expected) - observed + expected)
        return np.sign(observed - expected) * np.sqrt(np.maximum(0, deviance))

    tail_bins = max(1, 5//bin_width)
    left = max(.01, np.mean(observed[:tail_bins]) / bin_width)
    right = max(.01, np.mean(observed[-tail_bins:]) / bin_width)
    if initial is None:
        starts = [[max(10, observed.sum() * .3), mu, sigma, left, right]
                  for mu in [142, 148] for sigma in [4, 7, 11]]
    else:
        starts = [initial]
    fits = [least_squares(residual, np.clip(p, lower + 1e-7, upper - 1e-7),
                          bounds=(lower, upper), max_nfev=800, x_scale='jac') for p in starts]
    optimum = min(fits, key=lambda f: np.dot(f.fun, f.fun))
    area, mu, sigma, left, right = optimum.x
    cov = np.linalg.pinv(optimum.jac.T @ optimum.jac)
    gradient = np.array([0, -100 * FWHM_FACTOR * sigma / mu**2,
                         100 * FWHM_FACTOR / mu, 0, 0])
    ratio_error = math.sqrt(max(0, float(gradient @ cov @ gradient)))
    area_se = float(np.sqrt(max(0, cov[0, 0])))
    area_snr = float(area / area_se) if area_se > 0 else 0.
    bound = bool(area < 1 or mu < lower[1] + .01 or mu > upper[1] - .01 or
                 sigma < 1.01 or sigma > 19.99)
    peak, background = components(optimum.x)
    result = dict(success=bool(optimum.success and not bound and area_snr >= 5), bound_warning=bound,
                  roi_channels=[lo, hi], centroid_channel=float(mu),
                  bin_width_channels=bin_width, bin_width_adc_codes=2*bin_width,
                  centroid_statistical_se=float(np.sqrt(max(0, cov[1, 1]))),
                  sigma_channels=float(sigma), fwhm_channels=float(FWHM_FACTOR * sigma),
                  apparent_fwhm_percent=float(100 * FWHM_FACTOR * sigma / mu),
                  apparent_fwhm_statistical_se_pp=ratio_error,
                  fitted_gaussian_events=float(area), observed_roi_counts=int(observed.sum()),
                  fitted_area_statistical_se=area_se, fitted_area_signal_to_stat_noise=area_snr,
                  deviance=float(np.dot(optimum.fun, optimum.fun)), dof=len(observed) - 5,
                  model_parameters=optimum.x.tolist())
    result['deviance_per_dof'] = result['deviance'] / result['dof']
    result['model_misfit_warning'] = result['deviance_per_dof'] > 2
    return result, dict(edges=edges, observed=observed, expected=model(optimum.x),
                        peak=peak, background=background, residual=optimum.fun)


def load_run(run, allow_incomplete=False):
    data = json.loads((run / 'spectrum.json').read_text())
    if not allow_incomplete and not data['completed']:
        raise ValueError('Run is incomplete')
    if data.get('error'):
        raise ValueError('Run has capture error: ' + data['error'])
    n = data['totals']['batches']
    lines = (run / 'batches.jsonl').read_text().splitlines()[:n]
    if len(lines) != n:
        raise ValueError('Snapshot/log mismatch')
    batches = [json.loads(line) for line in lines]
    durations = np.array([b['host_roundtrip_seconds'] for b in batches])
    wall = data['wall_seconds']
    ends = np.cumsum(durations) * wall / durations.sum()
    starts = np.r_[0, ends[:-1]]
    nsegments = max(1, math.ceil((wall - .02) / 60))
    segments = np.zeros((nsegments, 2048), dtype=np.int64)
    counts = [0] * 2048
    all_counts = [0] * 2048
    selected_per_segment = np.zeros(nsegments, dtype=np.int64)
    max_peak = 0
    above_1p65v = 0
    high_records = []
    received = 0
    baseline = np.zeros((nsegments, 4), dtype=float)
    for b, start, end in zip(batches, starts, ends):
        rows = decode_batch(b['header'], (run / b['file']).read_bytes())
        received += len(rows)
        selection = add_events(counts, rows)
        if selection != b['selection']:
            raise ValueError('Selection accounting mismatch')
        segment = min(nsegments - 1, int((start + end) / 2 // 60))
        selected_per_segment[segment] += selection['binned']
        add_events(segments[segment], rows)
        for row in rows:
            amp = row['amplitude_code']
            if 0 <= amp < 4096:
                all_counts[int(amp // 2)] += 1
            pk = max(row[f'peak{i}'] for i in range(1, 5))
            max_peak = max(max_peak, pk)
            above_1p65v += pk * 3.3 / 4095 >= 1.65
            if pk * 3.3 / 4095 >= 1.65 and len(high_records) < 1000:
                high_records.append(dict(file=b['file'], record_id=row['id'],
                    peak_code=pk, nominal_peak_v=pk*3.3/4095,
                    amplitude_channel=row['amplitude_code']/2, flags=row['flags']))
            if not row['flags'] and pk < 4090 and 0 <= amp < 4096:
                baseline[segment] += [1, row['baseline'], row['baseline']**2,
                                      row['reset_peak']-row['baseline']]
    assert counts == data['counts'] and all_counts == data['all_received_counts']
    assert received == data['totals']['received'] and sum(counts) == data['totals']['binned']
    assert np.array_equal(segments.sum(axis=0), counts)
    for total, header in [('attempts', 'requested'), ('firmware_timeouts', 'timeouts'),
                          ('firmware_baseline_rejects', 'baseline_rejects'),
                          ('trigger_irq_n', 'trigger_irq_n'), ('trigger_ignored_n', 'trigger_ignored_n'),
                          ('dma_stop_n', 'dma_stop_n'),
                          ('dma_stop_before_hold_irq_n', 'dma_stop_before_hold_irq_n')]:
        assert sum(b['header'][header] for b in batches) == data['totals'][total]
    baseline_checks = [dict(segment=i, selected=int(n), mean_baseline_code=float(s/n),
                            baseline_rms_code=float(np.sqrt(max(0, q/n-(s/n)**2))),
                            mean_reset_minus_baseline_code=float(r/n))
                       for i, (n,s,q,r) in enumerate(baseline) if n]
    quality = dict(all_payload_crcs_and_histograms_verified=True, received=received,
                   selected=int(sum(counts)), batches=n, max_peak_code=max_peak,
                   max_peak_nominal_v=max_peak * 3.3 / 4095,
                   records_above_nominal_1p65v=int(above_1p65v),
                   analog_high_records=high_records,
                   mcu_batch_seconds=sum(b['header']['elapsed_ms'] for b in batches) / 1000,
                   longest_approx_batch_seconds=float(np.max(ends - starts)),
                   baseline_by_segment=baseline_checks)
    return data, segments, selected_per_segment, quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--bootstrap', type=int, default=300)
    parser.add_argument('--allow-incomplete', action='store_true')
    args = parser.parse_args()
    data, histograms, selected_per_segment, quality = load_run(args.run, args.allow_incomplete)
    counts = np.asarray(data['counts'])
    primary, model = fit_peak(counts)
    sensitivity = [fit_peak(counts, lo, hi)[0] for lo, hi in [(115, 185), (125, 175), (130, 170)]]
    regrouping = [fit_peak(counts, bin_width=w)[0] for w in [2,3,4]]
    all_trigger_fit = fit_peak(data['all_received_counts'])[0]
    segments = []
    for i, h in enumerate(histograms):
        if h.sum() < 100:
            continue
        result, _ = fit_peak(h)
        start, end = i * 60, min((i + 1) * 60, data['wall_seconds'])
        result.update(segment=i, approximate_start_seconds=start, approximate_end_seconds=end,
                      selected=int(selected_per_segment[i]), wall_selected_cps=int(h.sum()) / (end - start))
        segments.append(result)
    rng = np.random.default_rng(20261118)
    bootstrap = []
    if primary['success']:
        lo, hi = primary['roi_channels']
        for _ in range(args.bootstrap):
            synthetic = counts.copy()
            synthetic[lo:hi] = rng.poisson(model['expected'])
            fit, _ = fit_peak(synthetic, initial=primary['model_parameters'])
            if fit['success']:
                bootstrap.append(fit['apparent_fwhm_percent'])
    good = [s for s in segments if s['success']]
    drift = None
    if len(good) >= 3:
        mu = np.array([s['centroid_channel'] for s in good])
        t = np.array([(s['approximate_start_seconds'] + s['approximate_end_seconds']) / 120 for s in good])
        err = np.maximum([s['centroid_statistical_se'] for s in good], 1e-6)
        design = np.c_[np.ones(len(t)), t]
        cov = np.linalg.pinv((design / err[:, None]).T @ (design / err[:, None]))
        beta = cov @ design.T @ (mu / err**2)
        drift = dict(centroid_min=float(mu.min()), centroid_max=float(mu.max()),
                     centroid_range_percent_of_mean=float(np.ptp(mu) / mu.mean() * 100),
                     weighted_linear_slope_channel_per_minute=float(beta[1]),
                     slope_statistical_se=float(np.sqrt(cov[1, 1])),
                     first_to_last_percent=float((mu[-1] - mu[0]) / mu[0] * 100),
                     segment_fwhm_percent_range=[float(min(s['apparent_fwhm_percent'] for s in good)),
                                                 float(max(s['apparent_fwhm_percent'] for s in good))])
    report = dict(source=str(args.run), capture_completed=data['completed'], wall_seconds=data['wall_seconds'],
                  totals=data['totals'], quality=quality, primary=primary, window_sensitivity=sensitivity,
                  regrouping_sensitivity=regrouping,
                  all_trigger_fit=all_trigger_fit, segments=segments, drift=drift,
                  bootstrap=dict(requested=args.bootstrap, successful=len(bootstrap), seed=20261118,
                      method='Parametric Poisson resampling conditional on fitted Gaussian+linear continuum; excludes systematic errors.',
                      apparent_fwhm_percent_95=np.quantile(bootstrap, [.025, .975]).tolist() if len(bootstrap)>=.9*max(1,args.bootstrap) else None),
                  limitations=['FWHM/centroid is an apparent channel-domain ratio, assuming negligible energy intercept and linear response; no multipoint energy calibration.',
                    'Fit uses unsmoothed gross-source counts with a bin-integrated Gaussian and nonnegative linear continuum. No source-removed detector background measured in this configuration.',
                    'Fit-window sensitivity and deviance indicate model dependence; bootstrap intervals do not include it.',
                    'Adjacent-bin regrouping is a fit sensitivity check with Gaussian bin integration, not smoothing or an improved detector resolution. Native histogram is unchanged.',
                    'Minute boundaries approximate wall time by normalizing cumulative batch roundtrip durations; events within a boundary batch are assigned together. This is not live time.',
                    'Whole-chain drift does not identify detector versus MCA causes. R10510k/C101100pF pulse response remains experimental.'])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'analysis.json').write_text(json.dumps(report, indent=2)+'\n')
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), layout='constrained')
    axes[0].stairs(counts, np.arange(2049), color='#238b8b')
    axes[0].set(xlim=(0, 230), xlabel='Channel (2 ADC codes/channel)', ylabel='Counts', title='Unsmoothed source spectrum')
    centers = (model['edges'][:-1] + model['edges'][1:]) / 2
    axes[1].stairs(model['observed'], model['edges'], color='#238b8b', label='Observed')
    axes[1].plot(centers, model['expected'], color='#bc4f36', label='Gaussian + linear continuum')
    axes[1].plot(centers, model['background'], '--', color='#888888', label='Fitted continuum')
    mu, width = primary['centroid_channel'], primary['fwhm_channels']
    axes[1].axvspan(mu-width/2, mu+width/2, color='#bc4f36', alpha=.1)
    qualifier = ' (model dependent)' if primary['model_misfit_warning'] else ''
    axes[1].set(xlabel='Channel', ylabel='Counts', title=f'Approx. FWHM/centroid: {primary["apparent_fwhm_percent"]:.1f}%{qualifier}\nCentroid {mu:.1f}, FWHM {width:.1f} channels')
    axes[1].legend(fontsize=8)
    for ax in axes:ax.grid(alpha=.2)
    status = 'Completed' if data['completed'] else 'PARTIAL snapshot'
    fig.suptitle(f'{status}: {data["wall_seconds"]:.1f}s wall, {data["totals"]["binned"]} selected | uncalibrated')
    fig.savefig(args.out/'spectrum-and-fit.png', dpi=170)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 3.8), layout='constrained')
    ax.axhline(0, color='gray', lw=.6)
    ax.plot(centers, model['residual'], '.-', ms=3)
    ax.set(xlabel='Channel', ylabel='Signed Poisson deviance residual',
           title=f'Gaussian + linear continuum | deviance/dof={primary["deviance_per_dof"]:.2f}')
    ax.grid(alpha=.2);fig.savefig(args.out/'fit-residuals.png', dpi=160);plt.close(fig)
    if good:
        time = [(s['approximate_start_seconds'] + s['approximate_end_seconds']) / 120 for s in good]
        fig, axes = plt.subplots(3, 1, figsize=(10, 8), layout='constrained', sharex=True)
        axes[0].errorbar(time, [s['centroid_channel'] for s in good], yerr=[1.96*s['centroid_statistical_se'] for s in good], fmt='o-', ms=4)
        axes[0].set_ylabel('Peak centroid (channel)')
        axes[1].errorbar(time, [s['apparent_fwhm_percent'] for s in good], yerr=[1.96*s['apparent_fwhm_statistical_se_pp'] for s in good], fmt='o-', ms=4)
        axes[1].set_ylabel('Apparent FWHM (%)')
        axes[2].plot(time, [s['wall_selected_cps'] for s in good], 'o-', ms=4)
        axes[2].set(xlabel='Approximate wall time (minutes)', ylabel='Selected counts / wall s')
        for ax in axes:ax.grid(alpha=.2)
        fig.suptitle('Per-minute checks | model-conditional 95% statistical error bars; no live-time correction')
        fig.savefig(args.out/'drift.png', dpi=160);plt.close(fig)
    print(json.dumps({k:report[k] for k in ['capture_completed','wall_seconds','quality','primary','drift','bootstrap']},indent=2))


if __name__ == '__main__':
    main()
