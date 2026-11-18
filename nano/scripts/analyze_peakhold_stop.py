"""Compare measured EARLY/LATE stop phases in fast.4, without event cuts."""
from pathlib import Path
import json
import statistics as st
import struct
import zlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'work/peakhold-fast4-20261116'
OUT=ROOT/'outputs/Aster-MCA-Nano-真实早停对照-20261116'
OUT.mkdir(parents=True,exist_ok=True)
groups={};loaded={}
for mode in ['early','late']:
    paths=sorted(DATA.glob(f'pulse300-pair*-{mode}/result.json'))
    assert len(paths)==8
    ds=[json.loads(p.read_text()) for p in paths]
    rows=[]
    for p,d in zip(paths,ds):
        h=d['header'];raw=(p.parent/'records.bin').read_bytes()
        assert d['completed'] and d['raw_crc_verified'] and zlib.crc32(raw)==h['crc32']
        assert h['fw']=='0.4.1-fast.4' and h['fault']==0
        assert h['n']==h['requested']==128 and h['timeouts']==h['baseline_rejects']==0
        assert h['core_hz']==144000000 and h['adc_hz']==72000000 and h['raw_rate_hz']==4000000
        assert h['peak_sample_cycles_x2']==49 and h['window_us']==6
        binary=list(struct.iter_unpack('<16I',raw))
        assert len(binary)==len(d['records'])==128
        for words,r in zip(binary,d['records']):
            assert list(words)==[r[k] for k in d['record_fields']]
            assert r['amplitude_code']==st.mean(words[6:10])-words[1] and r['flags']==0
        if mode=='early':
            assert h['trigger_irq_n']==h['dma_stop_n']==h['dma_stop_before_hold_irq_n']==128
            assert h['trigger_ignored_n']==0 and h['dma_stop_minus_hold_irq_max_cycles']<0
        else:
            assert h['trigger_irq_n']==h['dma_stop_before_hold_irq_n']==0
            assert h['dma_stop_minus_hold_irq_min_cycles']>=0
        rows+=d['records']
    amp=[r['amplitude_code'] for r in rows]
    nbusy=sum(d['header']['within_batch_busy_n'] for d in ds)
    groups[mode]=dict(n=len(rows),mean_code=st.mean(amp),sigma_code=st.pstdev(amp),
        relative_rms_percent=100*st.pstdev(amp)/st.mean(amp),
        baseline_sigma_code=st.pstdev(r['baseline'] for r in rows),
        peak_sigma_code=st.pstdev(r['peak_mean_code'] for r in rows),
        mean_four_read_range_code=st.mean(max(r[f'peak{i}'] for i in range(1,5))-min(r[f'peak{i}'] for i in range(1,5)) for r in rows),
        fourth_read_us_range=[min(r['last_read_us_after_hold_irq'] for r in rows),max(r['last_read_us_after_hold_irq'] for r in rows)],
        within_batch_busy_mean_us=sum(d['header']['within_batch_busy_mean_cycles']*d['header']['within_batch_busy_n']/144 for d in ds)/nbusy,
        actual_stop_minus_hold_irq_us_range=[min(d['header']['dma_stop_minus_hold_irq_min_cycles'] for d in ds)/144,max(d['header']['dma_stop_minus_hold_irq_max_cycles'] for d in ds)/144],
        actual_stop_before_irq_n=sum(d['header']['dma_stop_before_hold_irq_n'] for d in ds),
        batches=[dict(n=d['header']['n'],mean=d['summary']['amplitude_mean_code'],relative_rms_percent=100*d['summary']['amplitude_sigma_code']/d['summary']['amplitude_mean_code']) for d in ds],
        files=[str(p.relative_to(ROOT)) for p in paths])
    loaded[mode]=(ds,rows)
windows=json.loads((DATA/'window-scan-sequence.json').read_text())
for w in windows:
    p=ROOT/w['file'];d=json.loads(p.read_text())
    assert d['completed'] and zlib.crc32((p.parent/'records.bin').read_bytes())==d['header']['crc32']
    w['relative_rms_percent']=100*w['sigma']/w['mean']
result=dict(condition='User confirmed N61116A.bin300mVpp/-150mV/~976.56Hz/High Z unchanged, input connected/outputON',
            firmware='0.4.1-fast.4',core_hz=144000000,adc_hz=72000000,raw_rate_hz=4000000,
            estimator='mean(PEAK1..4)-RAW pretrigger baseline; all accepted events included, no outlier cuts',
            groups=groups,window_scan=windows,
            limitations=['Fixed electrical pulse repeatability, not detector energy resolution',
                         'Stop and read timestamps relative to HOLD IRQ entry, not externally measured HOLD edge',
                         'EARLY stops about2us after trigger; ADC was still active during the start of pulse capture',
                         'Busy excludes batch upload and host waiting; window scan is one128event batch per setting'])
(OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
fig,axes=plt.subplots(1,3,figsize=(14,4.6),layout='constrained')
all_amp=[r['amplitude_code'] for ds,rows in loaded.values() for r in rows]
bins=np.histogram_bin_edges(all_amp,bins=34)
for mode,color in [('early','#238b8b'),('late','#9363ad')]:
    ds,rows=loaded[mode];g=groups[mode]
    axes[0].hist([r['amplitude_code'] for r in rows],bins=bins,density=True,histtype='step',linewidth=1.7,label=mode.upper(),color=color)
    axes[1].plot(range(1,9),[b['relative_rms_percent'] for b in g['batches']],'o-',label=mode.upper(),color=color)
    lo,hi=g['actual_stop_minus_hold_irq_us_range'];axes[2].plot([lo,hi],[mode,mode],'o-',linewidth=3,color=color)
axes[0].set(xlabel='Amplitude (ADC codes)',ylabel='Probability density (1/code)',title='All1024 events per mode; no cuts')
axes[1].set(xlabel='Balanced pair',ylabel='Amplitude relative standard deviation (%)',title='No clear repeatability improvement',ylim=(0,4))
axes[2].axvline(0,color='black',linestyle='--',linewidth=1)
axes[2].set(xlabel='Stop completion minus HOLD IRQ entry (us)',title='Different stop phases verified',xlim=(-5,2))
for ax in axes:ax.grid(alpha=.2)
for ax in axes[:2]:ax.legend()
fig.suptitle('Aster MCA Nano fast.4 — actual DMA stop comparison,2026-11-16')
fig.savefig(OUT/'actual-stop-comparison.png',dpi=170)

e,l=groups['early'],groups['late']
lines=['# Aster MCA Nano：实际早停/晚停对照','',
       '日期：2026-11-16。CPU144MHz、ADC72MHz、RAW4MSa/s、PEAK24.5周期、捕获窗6µs。',
       '发生器N61116A.bin，300mVpp、−150mV、约976.56Hz、High Z。用户确认设置不变并已接好、开启输出。','',
       '## 结果','',
       '| 模式 | 事件 | 相对标准差 | 标准差/码 | 第四次读完/µs | 批内忙碌/µs |',
       '|---|---:|---:|---:|---:|---:|']
for name,g in [('EARLY',e),('LATE',l)]:
    lo,hi=g['fourth_read_us_range'];lines.append(f"| {name} | {g['n']} | {g['relative_rms_percent']:.3f}% | {g['sigma_code']:.3f} | {lo:.2f}–{hi:.2f} | {g['within_batch_busy_mean_us']:.2f} |")
lines+=['','八对各128事件，交替并反转顺序，全部2048事件CRC通过，无超时、基线拒绝或事件标志。初查另32事件。统计没有丢弃尾部，也未应用离线校正。',
        'EARLY的1024事件均观测到专用触发中断，全部在HOLD中断入口前3.85–4.23µs停止DMA；LATE均在该入口后1.17–1.49µs停止。与fast.2/fast.3仅切配置不同，本次实际停止相位已得到记录验证。',
        '早停使读出略快，但未显示幅度重复性改善。不能据此排除所有ADC耦合：早停仍在触发后约2µs才停止转换，捕获前半段ADC依然工作。','',
        '## 同事件读取与窗口扫描','',
        f"同一事件四次PEAK读数的最大差平均为EARLY {e['mean_four_read_range_code']:.2f}码、LATE {l['mean_four_read_range_code']:.2f}码，而事件间PEAK标准差约11.4–11.5码。预触发基线标准差约0.55码。主要离散出现在事件之间，简单增加四次读数的平均次数没有明确依据。",'',
        '| EARLY窗口/µs | 事件 | 均值/码 | 标准差/码 | 相对标准差 |','|---|---:|---:|---:|---:|']
for w in sorted(windows,key=lambda w:w['window_us']):lines.append(f"| {w['window_us']} | {w['n']} | {w['mean']:.3f} | {w['sigma']:.3f} | {w['relative_rms_percent']:.3f}% |")
lines+=['','窗口扫描每档只有128事件，同阶段6µs对照也比前一阶段更窄；不能把某一档单批最小值当成改善结论。2–32µs未显示明确、单调的改善。',
        '探索性检查wait_cycles的36/72/144CPU周期相位关联，用前四对训练、后四对检验，未降低留出数据标准差。该拟合未用于表中数据。','',
        '## 解释与下一步','',
        '峰值捕获、保持、复位的基本功能仍成立；精度问题尚未解决。本轮不能断言是探头、ADC本体或某一模拟器件的问题。',
        '下一项有区分力的诊断是：先采基线，再在整个峰值捕获期间完全停止ADC，冻结后才读PEAK。这可以更直接检查采样动作对保持过程的影响。当前fast.4尚无该模式；本轮没有准备或烧入新的固件。',
        '结束时留板fast.4、EARLY、ADC72MHz/RAW4M/PEAK24.5周期，HOLD/RESET1/1。发生器输出最后由用户确认开启，软件未关闭；没有采集任务继续运行。',
        '上述为固定电信号的相对标准差，不是探测器能量分辨率。读出时间参照HOLD中断入口；批内忙碌不含上传及电脑等待。','',
        '![实际停止时间和幅度对照](actual-stop-comparison.png)']
(OUT/'README.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(groups,indent=2))
