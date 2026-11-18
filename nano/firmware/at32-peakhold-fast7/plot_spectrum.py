"""Plot an uncalibrated host-binned spectrum without opening any device."""
from pathlib import Path
import argparse
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from capture_spectrum import decode_batch

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('spectrum',type=Path);args=p.parse_args()
    d=json.loads(args.spectrum.read_text());counts=np.asarray(d['counts']);edges=np.arange(len(counts)+1)
    assert len(counts)==2048 and counts.sum()==d['totals']['binned']
    if 'all_received_counts' in d:all_counts=np.asarray(d['all_received_counts'])
    else:
        all_counts=np.zeros(2048,dtype=np.int64)
        for line in (args.spectrum.parent/'batches.jsonl').read_text().splitlines():
            b=json.loads(line)
            for r in decode_batch(b['header'],(args.spectrum.parent/b['file']).read_bytes()):
                if 0<=r['amplitude_code']<4096:all_counts[int(r['amplitude_code']//2)]+=1
    fig,axes=plt.subplots(1,2,figsize=(12,4.6),layout='constrained')
    occupied=np.flatnonzero(all_counts);zoom=min(2048,max(128,int(occupied[-1]*1.1)+1)) if len(occupied) else 2048
    for ax in axes:
        if not np.array_equal(counts,all_counts):ax.stairs(all_counts,edges,color='#999999',label='All in-range triggers')
        ax.stairs(counts,edges,color='#238b8b',label='Selected (no flags/clipping)');ax.set(xlabel='Channel (2 ADC codes/channel)',ylabel='Counts');ax.grid(alpha=.2);ax.legend(fontsize=8)
    axes[0].set(xlim=(0,zoom),title='Linear scale')
    axes[1].set(xlim=(0,2048),title='Full range')
    if all_counts.any():axes[1].set_yscale('log');axes[1].set_ylim(bottom=.8)
    fig.suptitle(f"{d['label']} — uncalibrated;{d['wall_seconds']:.2f}s wall,{d['totals']['received']} received /{d['totals']['binned']} selected")
    dest=args.spectrum.with_suffix('.png');fig.savefig(dest,dpi=170);print(dest)

if __name__=='__main__':main()
