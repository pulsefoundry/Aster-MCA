"""Saved v0.8.2 raw diagnostics and independent timed histograms only; no USB."""
from pathlib import Path
import csv
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'outputs/Aster-MCA-Nano-AT32-波形诊断-v0.8.2-20261018'
source = Path((HERE/'latest-source-v082-path.txt').read_text().strip())
background = Path((HERE/'latest-background-v082-path.txt').read_text().strip())
s = json.loads((source/'capture.json').read_text())
b = json.loads((background/'capture.json').read_text())
assert s['completed'] and b['completed']
ys = np.asarray(s['histogram']['counts']['peak'])
yb = np.asarray(b['histogram']['counts']['peak'])
scale = s['verified_sampled_seconds']/b['verified_sampled_seconds']
raw = np.fromfile(HERE/'cs-source-raw-500-v082/samples.u16', dtype='<u2').reshape(-1, 4096)
events = list(csv.DictReader((HERE/'cs-source-analysis-v082/events.csv').open()))
selected = [e for e in events if int(e['flags']) == 0 and 60 <= float(e['peak_code']) <= 100]
# Use the prior 60-second gross-spectrum centroid only to select an example.
# This does not identify a single event's radiation energy.
event = min(selected, key=lambda e:abs(float(e['peak_code'])-78.3333))
segment, trigger = int(event['segment']), int(event['trigger'])
lo, hi = trigger-20, min(4096, trigger+64)
time = (np.arange(lo, hi)-trigger)*.25
height = float(event['peak_code'])
voltage = (raw[segment, lo:hi].astype(float)-float(event['baseline_code']))*3300/4096

plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10,
    'axes.spines.top':False, 'axes.spines.right':False})
fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), layout='constrained')
axes[0].plot(time, voltage, 'o-', markersize=3, lw=1.4, color='#236e8e')
axes[0].axhline(0, color='#777', lw=.6)
axes[0].axhline(-height*3300/4096/2, color='#b46a48', lw=.9, ls='--', label='Half sampled height')
axes[0].set(xlabel='Time from threshold crossing (us)', ylabel='ADC voltage minus frozen baseline (mV)',
    title=f'Unsmoothed example: {height:.1f} ADC codes (~{height*3300/4096:.1f} mV)', xlim=(-4, 10))
axes[0].legend(frameon=False, fontsize=8, loc='lower right')
edges = np.arange(0, 142, 2)
axes[1].stairs(ys[:140].reshape(-1, 2).sum(axis=1), edges, color='#236e8e', label='Cs present, 10 s')
axes[1].stairs(yb[:140].reshape(-1, 2).sum(axis=1)*scale, edges, color='#9c7771', label='Background, scaled to 10 s')
axes[1].set(xlabel='Sampled peak above frozen baseline (ADC codes)', ylabel='Counts / 2-code display bin',
    title='Independent timed histograms; 2048 native channels', xlim=(10, 130))
axes[1].legend(frameon=False, fontsize=8)
for ax in axes: ax.grid(alpha=.15)
fig.suptitle('Aster Nano AT32 v0.8.2 | probe and Cs-source check', fontsize=14)
fig.supxlabel('4 MS/s; nominal 3.3 V reference; no energy calibration or resolution fit. Raw snapshot gaps excluded.', fontsize=8)
fig.savefig(OUT/'probe-cs-waveform-and-spectrum.png', dpi=180)
plt.close(fig)

result = dict(example=dict(segment=segment, trigger=trigger, peak_code=height,
    nominal_peak_mv=height*3300/4096, half_height_width_us=float(event['half_height_width_us']),
    selection='Nearest accepted sampled height to prior gross-spectrum centroid 78.3333; not an independently energy-tagged event'),
    background_record=str(background), source_record=str(source),
    histogram_background_scale=scale, spectrum_fit_performed=False,
    native_channels=2048, display_bin_width_adc_codes=2)
(OUT/'comparison-figure-metadata.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
