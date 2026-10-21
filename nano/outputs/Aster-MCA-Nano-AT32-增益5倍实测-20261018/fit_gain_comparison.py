"""Offline gross-source peak fits before/after R21/R22 rework. No device access."""
from pathlib import Path
import json
import sys
import math
import numpy as np
from scipy.optimize import least_squares
from scipy.special import ndtr, xlogy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'outputs/Aster-MCA-Nano-AT32-增益5倍实测-20261018'
sys.path.insert(0, str(ROOT/'firmware/at32-continuous'))
from gui_model import read_record, compatible


def fit(counts, gain=1., lo=62, hi=102, step=1, initial=None):
    low = math.floor(round(lo*gain)/step)*step
    high = math.ceil(round(hi*gain)/step)*step
    observed = counts[low:high].reshape(-1, step).sum(axis=1)
    adc_edges = np.arange(low, high+step*.1, step)
    edges = adc_edges/gain
    centers = (edges[:-1]+edges[1:])/2
    def model(p):
        n, mu, sigma, left, right = p
        continuum = (left+(right-left)*(centers-edges[0])/(edges[-1]-edges[0]))*np.diff(edges)
        return n*np.diff(ndtr((edges-mu)/sigma))+continuum
    def residual(p):
        expected = np.maximum(model(p), 1e-12)
        return np.sign(observed-expected)*np.sqrt(np.maximum(0, 2*(xlogy(observed, observed/expected)-observed+expected)))
    lower = np.array([0, 70, 1, 0, 0.]); upper = np.array([20000, 88, 16, 500, 500.])
    starts = [initial] if initial is not None else [[3000, 78, sigma, 50, 5] for sigma in (4,6,8)]
    fits = [least_squares(residual, np.clip(p, lower+1e-7, upper-1e-7),
        bounds=(lower, upper), max_nfev=1000, x_scale='jac') for p in starts]
    opt = min(fits, key=lambda v:np.dot(v.fun, v.fun)); n, mu, sigma, left, right = opt.x
    bound = bool(n<1 or mu<70.01 or mu>87.99 or sigma<1.01 or sigma>15.99)
    result = dict(success=bool(opt.success and not bound),bound_warning=bound,
        window_adc_codes=[low, high],bin_width_adc_codes=step,centroid_adc_code=float(mu*gain),
        sigma_adc_codes=float(sigma*gain),fwhm_adc_codes=float(2.354820045*sigma*gain),
        apparent_fwhm_percent=float(235.4820045*sigma/mu),fitted_peak_events=float(n),
        observed_roi_counts=int(observed.sum()),deviance=float(np.dot(opt.fun,opt.fun)),
        dof=len(observed)-5,parameters_in_nominal_pre_gain_codes=opt.x.tolist())
    return result, adc_edges, observed, model(opt.x)


def main():
    old_path = ROOT/'work/at32-gui-recordings/capture-20261018-173943-644509'
    new_path = Path((HERE/'latest-source-60s-path.txt').read_text().strip())
    new_background_path = Path((HERE/'latest-background-path.txt').read_text().strip())
    old = read_record(old_path); new = read_record(new_path); background = read_record(new_background_path)
    assert old['valid'] and new['valid'] and background['valid'] and compatible(new,background)
    assert old['method'] == new['method'] == 'mcu-peak-4M-v0.1'
    old_counts = np.array(old['histogram']['counts']['peak'])
    new_counts = np.array(new['histogram']['counts']['peak'])
    old_fit, old_edges, old_y, old_expected = fit(old_counts)
    new_fit, new_edges, new_y, new_expected = fit(new_counts, 5.02)
    assert old_fit['success'] and new_fit['success']
    archived = json.loads((ROOT/'outputs/Aster-MCA-Nano-AT32-取峰-v0.8.0-20261018/cs-source-60s-fit.json').read_text())
    assert abs(old_fit['apparent_fwhm_percent']-archived['primary']['apparent_fwhm_percent']) < 1e-6
    sensitivity = [fit(new_counts,5.02,lo,hi)[0] for lo,hi in ((58,106),(66,98))]
    sensitivity += [fit(new_counts,5.02,step=step)[0] for step in (5,10)]
    rng = np.random.default_rng(20261018502); boot_old=[]; boot_new=[]
    for _ in range(300):
        values=[]
        for counts,gain,primary,expected in [(old_counts,1.,old_fit,old_expected),(new_counts,5.02,new_fit,new_expected)]:
            simulated=counts.copy();lo,hi=primary['window_adc_codes'];simulated[lo:hi]=rng.poisson(expected)
            result=fit(simulated,gain,initial=primary['parameters_in_nominal_pre_gain_codes'])[0]
            values.append(result['apparent_fwhm_percent'] if result['success'] else np.nan)
        if np.isfinite(values).all():boot_old.append(values[0]);boot_new.append(values[1])
    assert len(boot_new)>=270
    difference=np.asarray(boot_new)-np.asarray(boot_old)
    def interval(v):return np.quantile(v,[.025,.975]).tolist()
    result=dict(firmware_before=json.loads((old_path/'capture.json').read_text())['initial_info']['fw'],
        firmware_after=json.loads((new_path/'capture.json').read_text())['initial_info']['fw'],
        source_before=str(old_path),source_after=str(new_path),background_after=str(new_background_path),
        sampled_seconds_before=old['seconds'],sampled_seconds_after=new['seconds'],
        accepted_before=old['accepted'],accepted_after=new['accepted'],
        threshold_before=20,threshold_after=100,nominal_opamp_gain_before=1.,nominal_opamp_gain_after=5.02,
        native_channels=2048,unchanged_integer_peak_engine=True,
        before=old_fit,after=new_fit,after_sensitivity=sensitivity,
        centroid_ratio=new_fit['centroid_adc_code']/old_fit['centroid_adc_code'],
        after_nominal_peak_mv=new_fit['centroid_adc_code']*3300/4096,
        after_minus_before_percentage_points=new_fit['apparent_fwhm_percent']-old_fit['apparent_fwhm_percent'],
        bootstrap=dict(method='Independent parametric Poisson resampling of each fitted gross-source ROI, conditional on its Gaussian + linear-continuum model; no systematic errors',
            seed=20261018502,successful=len(boot_new),before_fwhm_percent_95=interval(boot_old),after_fwhm_percent_95=interval(boot_new),
            difference_percentage_points_95=interval(difference)),
        limitations=['Apparent FWHM/centroid assumes negligible energy offset and linear response; no multipoint energy calibration.',
            'Fit is bin-integrated Gaussian plus nonnegative linear continuum on unsmoothed gross-source counts, not background-subtracted counts.',
            'Nominal gain ratio5.02 determines scaled fit ROI and numerical units, not the fitted centroid ratio.',
            'Native1-code fits are primary;5/10-code regrouping and ROI changes are sensitivity checks.',
            'The detector HV/gain and source placement were user-confirmed unchanged, but source was physically removed/replaced and the runs were taken at different times.',
            'The peak engine is unchanged but firmware differs0.8.0/0.8.2. Trigger threshold changes20/100 and baseline quality cuts remain fixed in ADC units.',
            'Statistical bootstrap intervals exclude model/window, drift, source positioning, analog behavior and quality-selection systematic errors.',
            'This is one short before/after experiment, not a detector or hardware resolution limit.'])
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'gain-peak-fit-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(11,4.7),layout='constrained')
    for ax,primary,edges,observed,expected,color,title in [
        (axes[0],old_fit,old_edges,old_y,old_expected,'#7a8797','Before: op amp gain1; threshold20'),
        (axes[1],new_fit,new_edges,new_y,new_expected,'#236f91','After: nominal op amp gain5.02; threshold100')]:
        centers=(edges[:-1]+edges[1:])/2
        ax.stairs(observed,edges,color=color,lw=1.1,label='Gross-source counts, 60 s')
        ax.plot(centers,expected,color='#ba5d3c',lw=1.5,label='Gaussian + linear continuum')
        mu=primary['centroid_adc_code'];width=primary['fwhm_adc_codes']
        ax.axvspan(mu-width/2,mu+width/2,color='#ba5d3c',alpha=.1)
        ax.set(xlabel='ADC channel (one ADC code per native bin)',ylabel='Counts / native bin',
            title=f'{title}\nApparent FWHM/centroid: {primary["apparent_fwhm_percent"]:.2f}%\nCentroid {mu:.2f}; FWHM {width:.2f} codes')
        ax.legend(frameon=False,fontsize=8);ax.grid(alpha=.15)
    fig.suptitle('Aster Nano AT32 | R21/R22 analog gain comparison',fontsize=14)
    fig.supxlabel('Unsmoothed gross-source fits; no energy calibration. Window/model and drift uncertainty are additional.',fontsize=8)
    fig.savefig(OUT/'gain-peak-fit-comparison.png',dpi=180);plt.close(fig)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
