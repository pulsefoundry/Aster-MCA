"""Saved v0.8.0 source/background spectra only. No device access."""
from pathlib import Path
import json
import sys
import numpy as np
from scipy.optimize import least_squares
from scipy.special import ndtr, xlogy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[2]
WORK=Path(__file__).resolve().parent
OUT=ROOT/'outputs/Aster-MCA-Nano-AT32-取峰-v0.8.0-20261018'
SOURCE=ROOT/'work/at32-gui-recordings/capture-20261018-173943-644509'
BACKGROUND=Path((WORK/'latest-background-path.txt').read_text().strip())
sys.path.insert(0,str(ROOT/'firmware/at32-continuous'))
from gui_model import read_record,compatible


def fit(counts,lo=62,hi=102,step=1,initial=None):
    y=counts[lo:hi].reshape(-1,step).sum(axis=1)
    edges=np.arange(lo,hi+.1,step);centers=(edges[:-1]+edges[1:])/2
    def model(p):
        n,mu,sigma,left,right=p
        return n*np.diff(ndtr((edges-mu)/sigma))+(left+(right-left)*(centers-lo)/(hi-lo))*np.diff(edges)
    def residual(p):
        m=np.maximum(model(p),1e-12)
        return np.sign(y-m)*np.sqrt(np.maximum(0,2*(xlogy(y,y/m)-y+m)))
    lower=np.array([0,70,1,0,0.]);upper=np.array([20000,88,16,500,500.])
    starts=[initial] if initial is not None else [[3000,78,s,50,5] for s in (4,6,8)]
    opts=[least_squares(residual,np.clip(p,lower+1e-7,upper-1e-7),bounds=(lower,upper),
                        max_nfev=1000,x_scale='jac') for p in starts]
    opt=min(opts,key=lambda x:np.dot(x.fun,x.fun));n,mu,sigma,left,right=opt.x
    warning=bool(n<1 or mu<70.01 or mu>87.99 or sigma<1.01 or sigma>15.99)
    return dict(success=bool(opt.success and not warning),bound_warning=warning,
        window=[lo,hi],bin_width_adc_codes=step,centroid_channel=float(mu),sigma_channels=float(sigma),
        fwhm_channels=float(2.354820045*sigma),apparent_fwhm_percent=float(235.4820045*sigma/mu),
        fitted_peak_events=float(n),events_in_window=int(y.sum()),deviance=float(np.dot(opt.fun,opt.fun)),
        dof=len(y)-5,parameters=opt.x.tolist()),edges,y,model(opt.x)


def main():
    source=read_record(SOURCE);background=read_record(BACKGROUND)
    assert source['valid'] and background['valid'] and compatible(source,background)
    y=np.array(source['histogram']['counts']['peak']);b=np.array(background['histogram']['counts']['peak'])
    alpha=source['seconds']/background['seconds']
    primary,edges,counts,expected=fit(y)
    assert primary['success']
    windows=[fit(y,lo,hi)[0] for lo,hi in ((58,106),(66,98))]
    bins=[fit(y,step=2)[0]]
    # Conditional parametric bootstrap, preserving the primary spectral model.
    rng=np.random.default_rng(2026101808);replicates=[]
    for _ in range(300):
        simulated=y.copy();simulated[62:102]=rng.poisson(expected)
        result,_,_,_=fit(simulated,initial=primary['parameters'])
        if result['success']:replicates.append(result['apparent_fwhm_percent'])
    assert len(replicates)>=270
    result=dict(source=str(SOURCE),background=str(BACKGROUND),firmware='0.8.0',
        estimator='sampled peak above frozen baseline',channels=2048,bin_width_adc_codes=1,
        sampled_seconds=source['seconds'],accepted=source['accepted'],background_seconds=background['seconds'],
        background_accepted=background['accepted'],background_scale=alpha,
        source_selected_rate_per_sampled_s=source['accepted']/source['seconds'],
        background_selected_rate_per_sampled_s=background['accepted']/background['seconds'],
        background_subtracted_counts=float(y.sum()-alpha*b.sum()),primary=primary,
        window_sensitivity=windows,bin_sensitivity=bins,
        bootstrap=dict(method='Parametric Poisson resampling of primary fitted gross-source ROI; conditional on fixed model/window',
            seed=2026101808,repeats=300,successful=len(replicates),
            apparent_width_95_percent=np.quantile(replicates,[.025,.975]).tolist(),
            apparent_width_sd_percentage_points=float(np.std(replicates,ddof=1))),
        roi_selection='After observing the full source/background spectrum, a clear source-related candidate peak near channel78 was selected; ROI/window sensitivity disclosed, not a blind pre-registered peak selection.',
        nominal_3v3_adc_peak_amplitude_mv=primary['centroid_channel']*3300/4096,
        nominal_adc_full_scale_fraction=primary['centroid_channel']/4096,
        limitations=['Gross-source histogram is fitted directly with bin-integrated Gaussian plus nonnegative linear continuum. No histogram smoothing or fit to subtracted counts.',
            'FWHM/centroid assumes a negligible energy offset and linear response; not a multipoint energy calibration or detector specification.',
            'Statistical interval excludes ROI/model, analog, calibration and background-model systematic uncertainty.',
            'Only final spectra retained, no current pulse waveforms. Cannot redo baseline/shaping per event from these files.',
            'Source/background share current firmware, threshold and user-confirmed settings. Historical integral and r11 results have different sampling/units/conditions; no direct improvement claim.',
            'Rates use sampled clock duration and accepted events; not dead-time or quality-cut corrected detector rates.'])
    (OUT/'cs-source-60s-fit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
    e=np.arange(0,162,2);centers=(e[:-1]+e[1:])/2
    axes[0].stairs(y[:160].reshape(-1,2).sum(axis=1),e,label='Cs present, 60 s',color='#246b9a',lw=1.5)
    axes[0].stairs(b[:160].reshape(-1,2).sum(axis=1)*alpha,e,label='Background, scaled to 60 s',color='#9aa2a8')
    axes[0].set(xlabel='Channel (1 ADC code / channel)',ylabel='Counts / 2-channel bin',xlim=(10,130),title='Same peak-mode firmware, threshold and settings')
    axes[0].legend(frameon=False,fontsize=8);axes[0].grid(alpha=.15)
    c=(edges[:-1]+edges[1:])/2
    axes[1].stairs(counts,edges,label='Unsmoothed source counts',color='#246b9a')
    axes[1].plot(c,expected,label='Gaussian + linear continuum',color='#b95440',lw=1.8)
    mu=primary['centroid_channel'];width=primary['fwhm_channels']
    axes[1].axvspan(mu-width/2,mu+width/2,color='#b95440',alpha=.1,label='Gaussian FWHM interval')
    axes[1].set(xlabel='Channel (1 ADC code / channel)',ylabel='Counts / channel',
        title=f'Apparent FWHM / centroid: {primary["apparent_fwhm_percent"]:.2f}%\nCentroid {mu:.2f}; FWHM {width:.2f} channels',xlim=(58,106))
    axes[1].legend(frameon=False,fontsize=8);axes[1].grid(alpha=.15)
    fig.suptitle('Aster Nano AT32 | v0.8.0 sampled peak | Cs-source test',fontsize=14)
    fig.supxlabel('No energy calibration. Current 60 s test only; no claim of improvement over a historical run.',fontsize=8)
    fig.savefig(OUT/'cs-source-60s-fit.png',dpi=180);plt.close(fig)
    (WORK/'latest-source-path.txt').write_text(str(SOURCE)+'\n')
    status=json.loads((WORK/'status.json').read_text());status['source_record']=str(SOURCE)
    (WORK/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
