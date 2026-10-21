"""Plot verified continuous-run spectra; no automatic energy calibration."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',action='append',required=True,help='label=/capture/path')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();fig,axes=plt.subplots(1,2,figsize=(12,4.7),layout='constrained')
    for item in a.run:
        label,path=item.split('=',1);folder=Path(path)
        status=json.loads((folder/'capture.json').read_text())
        summary=json.loads((folder/'spectrum-summary.json').read_text())
        if not status['completed'] or not summary['valid_continuous_run']:
            raise ValueError(f'{label}: incomplete or faulted acquisition')
        rows=list(csv.DictReader((folder/'spectrum.csv').open()))
        seconds=summary['sampled_seconds']
        for ax,key,mult in zip(axes,['peak_counts','area8_div4_counts'],[3300/4096,4*3300/4096]):
            # Rebin four native bins for display only; CSV keeps all bins.
            counts=np.array([int(r[key]) for r in rows]).reshape(-1,4).sum(axis=1)
            edges=np.arange(0,4097,4)*mult
            ax.stairs(counts/seconds,edges,label=f'{label}: {seconds:.2f} sampled s',lw=1.2)
            ax.set(yscale='symlog',ylim=(0,None),ylabel='Accepted / sampled second / displayed bin')
            ax.grid(alpha=.2);ax.legend(fontsize=8)
    axes[0].set(title='Sampled peak spectrum',xlabel='ADC peak (mV)',xlim=(0,1000))
    axes[1].set(title='Fixed 8 us signed-area spectrum',xlabel='ADC area (mV us)',xlim=(0,2000))
    fig.suptitle('Aster AT32 - continuous 1 MS/s, host-side pulse processing',fontsize=14)
    fig.supxlabel('Uncalibrated; 1 MS/s peak sampling and event cuts limit interpretation. Not a calibrated detector count rate.',fontsize=9)
    a.out.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.out,dpi=160)
if __name__=='__main__':main()
