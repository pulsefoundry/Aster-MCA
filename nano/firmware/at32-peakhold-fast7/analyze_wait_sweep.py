"""Replay completed fast.7 experiment and compare complete spectra, offline only."""
from pathlib import Path
import argparse
import json
import math
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
from capture_spectrum import decode_batch,add_events,FW
# Reuse the established peak fitter; import the fast.7 decoder first so the
# fitter's unused legacy run-loader cannot shadow this experiment's decoder.
sys.path.insert(0,str(ROOT/'work/peakhold-detector-20261118'))
from analyze_long_run import np,plt,fit_peak
from scipy.stats import t as student_t


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);args=p.parse_args()
    plan=json.loads((args.run/'progress.json').read_text());assert plan['completed'] and not plan.get('error')
    assert FW=='0.4.1-fast.7'
    output=args.run/'analysis';output.mkdir(exist_ok=False)
    groups={};blocks=[]
    for index,item in enumerate(plan['blocks'],1):
        path=args.run/item['path'];data=json.loads((path/'spectrum.json').read_text())
        assert data['completed'] and not data.get('error')
        limit=item['wait_us'];counts=[0]*2048;safe=[0]*2048
        received=0;timing={k:0 for k in data['internal_timing_sums']};rejected=0
        for line in (path/'batches.jsonl').read_text().splitlines():
            batch=json.loads(line);head=batch['header']
            rows=decode_batch(head,(path/batch['file']).read_bytes(),wait_limit_us=limit)
            assert add_events(counts,rows)==batch['selection'];received+=len(rows)
            for k in timing:timing[k]+=head[k]
            for row in rows:
                amp=row['amplitude_code'];maximum=max(row[f'peak{i}'] for i in range(1,5))
                if row['flags'] or maximum>=4090 or not 0<=amp<4096:continue
                if maximum>=2048:rejected+=1
                else:safe[math.floor(amp/2)]+=1
        assert counts==data['counts'] and sum(counts)==data['totals']['binned']
        assert timing==data['internal_timing_sums'] and received==data['totals']['received']
        assert sum(safe)+rejected==sum(counts)
        block=dict(index=index,path=item['path'],wait_us=limit,wall_seconds=data['wall_seconds'],
                   selected=sum(safe),received=received,analog_high_excluded=rejected,verified=True)
        if plan['phase']=='source':block['fit']=fit_peak(safe)[0]
        blocks.append(block)
        g=groups.setdefault(str(limit),dict(wait_us=limit,counts=[0]*2048,wall_seconds=0,
                received=0,selected=0,analog_high_excluded=0,totals={},timing={k:0 for k in timing},blocks=[]))
        g['counts']=[a+b for a,b in zip(g['counts'],safe)]
        for k in ['wall_seconds','received','selected','analog_high_excluded']:g[k]+=block[k]
        for k,v in data['totals'].items():g['totals'][k]=g['totals'].get(k,0)+v
        for k,v in timing.items():g['timing'][k]+=v
        g['blocks'].append(index)
    for g in groups.values():
        g['selected_per_wall_second']=g['selected']/g['wall_seconds']
        g['armed_observed_seconds']=g['timing']['armed_observed_cycles']/144000000
        g['armed_observed_fraction_of_wall']=g['armed_observed_seconds']/g['wall_seconds']
        if plan['phase']=='source':
            g['primary_fit']=fit_peak(g['counts'])[0]
            g['roi_sensitivity']=[fit_peak(g['counts'],lo,hi)[0] for lo,hi in [(115,185),(125,175),(130,170)]]
    pairs=[]
    if plan['phase']=='source':
        ref=[blocks[i-1]['fit'] for i in groups['10000']['blocks']]
        for key,g in groups.items():
            if key=='10000':continue
            other=[blocks[i-1]['fit'] for i in g['blocks']]
            if len(ref)==len(other) and len(ref)>1 and all(f['success'] for f in ref+other):
                delta=np.array([a['apparent_fwhm_percent']-b['apparent_fwhm_percent'] for a,b in zip(other,ref)])
                se=float(delta.std(ddof=1)/np.sqrt(len(delta)));mean=float(delta.mean())
                half=float(student_t.ppf(.975,len(delta)-1))*se
                pairs.append(dict(wait_us=g['wait_us'],reference_wait_us=10000,
                    mean_difference_pp=mean,approximate_95_interval_pp=[mean-half,mean+half],
                    note='Repeated-round scatter only; fit-model systematic uncertainty excluded.'))
        fig,axes=plt.subplots(1,3,figsize=(15,4.6),constrained_layout=True)
        for g in groups.values():
            counts=np.array(g['counts']);label=f"{g['wait_us']/1000:g}ms cutoff"
            axes[0].step(np.arange(2048)+.5,counts/g['wall_seconds'],where='mid',label=label)
            axes[1].step(np.arange(2048)+.5,counts/max(1,counts[120:180].sum()),where='mid',label=label)
            yy=[blocks[i-1]['fit']['apparent_fwhm_percent'] for i in g['blocks']]
            err=[blocks[i-1]['fit']['apparent_fwhm_statistical_se_pp'] for i in g['blocks']]
            axes[2].errorbar(g['blocks'],yy,yerr=err,fmt='o-',label=label)
        axes[0].set(xlim=(100,200),xlabel='Channel',ylabel='Counts / wall second')
        axes[1].set(xlim=(110,190),xlabel='Channel',ylabel='Counts / ROI integral')
        axes[2].set(xlabel='Balanced block index',ylabel='Apparent FWHM / centroid (%)')
        for ax in axes:ax.grid(alpha=.25);ax.legend(fontsize=8)
        fig.suptitle('Complete fresh spectra: waiting-deadline/reset comparison')
        fig.savefig(output/'wait-deadline-comparison.png',dpi=170);plt.close(fig)
    result=dict(phase=plan['phase'],experiment=plan,groups=groups,blocks=blocks,paired_comparisons=pairs,
        all_frames_histograms_and_timing_sums_verified=True,
        limitations=['No energy-dependent waiting-time subset is selected: each group uses its complete fresh acquisition.',
                     'Armed-observed time includes capture/IRQ latency and is not validated true live time.',
                     'Wall time includes USB/host gaps; prepare/armed timing sums overlap and must not be added.',
                     'Apparent FWHM/centroid is uncalibrated and has fit-window/model dependence.',
                     'Shorter wait deadlines can reduce counting efficiency; narrowness alone is insufficient.'])
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    for g in groups.values():
        print(json.dumps(dict(wait_us=g['wait_us'],received=g['received'],selected=g['selected'],
            selected_per_wall_second=g['selected_per_wall_second'],armed_observed_fraction_of_wall=g['armed_observed_fraction_of_wall'],
            primary_fit=g.get('primary_fit'))),flush=True)


if __name__=='__main__':main()
