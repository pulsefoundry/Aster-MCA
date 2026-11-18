"""Reproduce fast.5 independent RAW-rate validation; preserve all accepted events."""
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
DATA=ROOT/'work/peakhold-fast5-20261116'
OUT=ROOT/'outputs/Aster-MCA-Nano-降采样率对照-20261117'
OUT.mkdir(parents=True,exist_ok=True)
rates=[4000,1000,500,250,125]

def read(paths):
    ds=[json.loads(p.read_text()) for p in paths];rows=[]
    for p,d in zip(paths,ds):
        h=d['header'];raw=(p.parent/'records.bin').read_bytes()
        assert d['completed'] and d['raw_crc_verified'] and zlib.crc32(raw)==h['crc32']
        assert h['fw']=='0.4.1-fast.5' and h['fault']==h['timeouts']==h['baseline_rejects']==0
        assert h['n']==h['requested']==128 and h['core_hz']==144000000 and h['adc_hz']==72000000
        assert h['window_us']==6 and h['peak_sample_cycles_x2']==49 and h['raw_stop_phase']=='trigger'
        assert h['trigger_irq_n']==h['dma_stop_n']==h['dma_stop_before_hold_irq_n']==128
        assert h['trigger_ignored_n']==0 and h['dma_stop_minus_hold_irq_max_cycles']<0
        binary=list(struct.iter_unpack('<16I',raw));assert len(binary)==len(d['records'])==128
        for words,r in zip(binary,d['records']):
            assert list(words)==[r[k] for k in d['record_fields']]
            assert r['amplitude_code']==st.mean(words[6:10])-words[1] and r['flags']==0
        rows+=d['records']
    return ds,rows

groups={};loaded={}
for rate in rates:
    paths=sorted(DATA.glob(f'pulse300-validation*-rate{rate}/result.json'));assert len(paths)==10
    ds,rows=read(paths);assert all(d['header']['raw_rate_hz']==rate*1000 for d in ds)
    amp=[r['amplitude_code'] for r in rows];mean=st.mean(amp);sigma=st.pstdev(amp)
    within=(sum(len(d['records'])*st.pvariance(r['amplitude_code'] for r in d['records']) for d in ds)/len(rows))**.5
    busy_n=sum(d['header']['within_batch_busy_n'] for d in ds)
    groups[str(rate)]=dict(n=len(rows),mean_code=mean,sigma_code=sigma,relative_rms_percent=100*sigma/mean,
        within_batch_sigma_code=within,within_batch_relative_rms_percent=100*within/mean,
        peak_sigma_code=st.pstdev(r['peak_mean_code'] for r in rows),baseline_sigma_code=st.pstdev(r['baseline'] for r in rows),
        busy_mean_us=sum(d['header']['within_batch_busy_n']*d['header']['within_batch_busy_mean_cycles']/144 for d in ds)/busy_n,
        prime_nominal_us=96000/rate,
        fourth_read_us_range=[min(r['last_read_us_after_hold_irq'] for r in rows),max(r['last_read_us_after_hold_irq'] for r in rows)],
        batches=[dict(started=d['started'],mean_code=d['summary']['amplitude_mean_code'],relative_rms_percent=100*d['summary']['amplitude_sigma_code']/d['summary']['amplitude_mean_code']) for d in ds],
        files=[str(p.relative_to(ROOT)) for p in paths])
    loaded[rate]=(ds,rows)

preliminary={}
for stage,pattern in [('initial','pulse300-balanced*-rate*/result.json'),('lower_rates','pulse300-lowrate-balanced*-rate*/result.json')]:
    paths=sorted(DATA.glob(pattern));ds,rows=read(paths)
    preliminary[stage]={'n':len(rows),'files':[str(p.relative_to(ROOT)) for p in paths]}
started=[d['started'] for ds,rows in loaded.values() for d in ds]
result=dict(firmware='0.4.1-fast.5',recorded_time_range=[min(started),max(started)],
            condition='Same user-confirmed AG1022 N61116A.bin,300mVpp,-150mV,~976.56Hz,High Z; source/connection unchanged after ordinary USB reconnect',
            fixed=dict(core_hz=144000000,adc_hz=72000000,peak_sample_cycles_x2=49,raw_sample_cycles_x2=5,stop_phase='EARLY',window_us=6,baseline_samples=32,guard_samples=8,prime_samples=96),
            groups=groups,preliminary=preliminary,validation_n=6400,total_pulse_n_including_check=11040,
            estimator='mean(PEAK1..4)-pretrigger RAW baseline; population sigma; no outlier cuts or offline corrections',
            limitations=['Electrical fixed-pulse repeatability,not detector energy resolution',
                         'RAW rate changes also stretch baseline time span and prearm prime duration',
                         'Peak-only sigma follows the rate trend;baseline sigma remains below0.6codes',
                         'Batch means drift;pooled sigma includes that drift;do not report best single batch as final result',
                         'Busy excludes batch upload/host waiting;periodic-source test is not full MCA live-time measurement'])
(OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n')

fig,axes=plt.subplots(1,3,figsize=(14.5,4.7),layout='constrained')
x=np.array(list(reversed(rates)));colors=['#8a65ad','#3878b5','#238b8b','#a7813d','#ba5e5e']
for i,rate in enumerate(x):
    g=groups[str(rate)]
    axes[0].scatter([rate]*10,[b['relative_rms_percent'] for b in g['batches']],color='#a6afb5',s=20,alpha=.7,label='Individual128-event batches' if i==0 else None)
axes[0].plot(x,[groups[str(r)]['relative_rms_percent'] for r in x],'o-',color='#238b8b',label='All1280 events per rate')
axes[0].set(xscale='log',xlabel='RAW sample rate (kSa/s)',ylabel='Amplitude relative standard deviation (%)',title='Lower RAW rate improves repeatability')
all_dev=[r['amplitude_code']-groups[str(rate)]['mean_code'] for rate,(ds,rows) in loaded.items() for r in rows]
bins=np.histogram_bin_edges(all_dev,bins=42)
for rate,color in zip(rates,colors):
    ds,rows=loaded[rate];mu=groups[str(rate)]['mean_code']
    axes[1].hist([r['amplitude_code']-mu for r in rows],bins=bins,density=True,histtype='step',linewidth=1.6,label=f'{rate}k',color=color)
axes[1].set(xlabel='Amplitude minus rate-group mean (ADC codes)',ylabel='Probability density (1/code)',title='All accepted events;no cuts')
axes[2].plot(x,[groups[str(r)]['busy_mean_us'] for r in x],'o-',color='#238b8b',label='Measured within-batch busy')
axes[2].plot(x,[groups[str(r)]['prime_nominal_us'] for r in x],'--',color='#9b9b9b',label='96-sample prime alone')
axes[2].set(xscale='log',xlabel='RAW sample rate (kSa/s)',ylabel='Time (us)',title='Current priming cost increases at low rates')
for ax in axes:
    ax.grid(alpha=.2);ax.legend(fontsize=8)
for ax in [axes[0],axes[2]]:ax.set_xticks(x,labels=[str(v) for v in x]);ax.minorticks_off()
fig.suptitle('Aster MCA Nano fast.5 — CPU144MHz / ADC72MHz / PEAK24.5cycles fixed')
fig.savefig(OUT/'independent-rate-comparison.png',dpi=170)

lines=['# Aster MCA Nano：独立降低RAW采样率对照','',
       '普通USB重插恢复通信后，使用fast.5，在同一发生器波形与接线下进行比较。',
       f"最终复核记录时间：{min(started)} 至 {max(started)}。数据目录沿用开始于11月16日的台架会话名。",'',
       '## 主要结果','',
       'CPU144MHz、ADC72MHz、PEAK24.5周期、RAW2.5周期、EARLY停止方式和6µs捕获窗固定。只用PHRATE改变RAW触发频率，不在批次间重校准ADC。',
       '五档在同一复核阶段轮换十轮，每档在各次序位置出现两次；每档1280事件，共6400事件。初步两阶段各2304事件，另有32事件初查，总计11040个有效事件。原始记录全部通过CRC，无超时、基线拒绝或事件标志。','',
       '| RAW速率 | 事件 | 幅度相对标准差 | PEAK自身标准差/码 | 基线标准差/码 | 批内忙碌/µs |',
       '|---|---:|---:|---:|---:|---:|']
for rate in rates:
    g=groups[str(rate)];lines.append(f"| {rate}kSa/s | {g['n']} | {g['relative_rms_percent']:.3f}% | {g['peak_sigma_code']:.3f} | {g['baseline_sigma_code']:.3f} | {g['busy_mean_us']:.2f} |")
lines+=['','相对标准差为总体标准差/均值，不是FWHM能量分辨率。没有剪尾、剔除离群点或应用离线修正。PEAK自身的离散随降速减少，基线标准差均低于0.6码，基线统计差异不足以解释整体改善。',
        '结果支持在本装置与当前固定脉冲条件下，降低RAW采样率可改善峰幅重复性。具体机理尚未定位：降低速率也同时拉长了96点预热以及32点基线/8点保护区的时间跨度。不能仅凭本结果认定是某个器件或某一种耦合机制。','',
        '## 批间变化和吞吐量','',
        '初步两个阶段的500k参考均值发生变化，因此没有把跨阶段最窄的单批数值当成最终成绩，而是补采了上表的五档同阶段复核。上表全样本标准差包含批间均值漂移；summary.json另存各批均值与合并批内标准差，便于继续检查增益/基线稳定性。',
        '当前程序每次重新采96点预热；4M时24µs，500k时192µs，125k时768µs。它解释了忙碌时间增加的大部分。该开销尚未优化；缩短预热后是否仍保持当前精度需要复测。',
        '批内忙碌不包含批次上传和等待电脑；本次是周期性约976.56Hz信号，不能据此声称任意输入计数率下的整机效率或总死时间。','',
        '## 留板配置与后续','',
        '建议先以500kSa/s作为继续实际能谱验证的折中点：相较4M，固定脉冲相对标准差显著降低，忙碌时间约241µs；125k是本轮较低噪声的参考档，但约817µs忙碌时间的代价更高。',
        '结束时运行时设置为500kSa/s、CPU144MHz、ADC72MHz、PEAK24.5周期、EARLY；HOLD/RESET1/1。重启固件默认仍是1MSa/s，上位机开始采集前应显式设置所选档位。',
        '发生器输出最后由用户确认开启，软件未关闭；本轮采集已结束。后续优先用所选档位验证真实探头能谱，再考虑预热开销优化和幅度零点/增益校准。','',
        '![独立降采样率对照](independent-rate-comparison.png)']
(OUT/'README.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:{a:v[a] for a in ['n','relative_rms_percent','peak_sigma_code','baseline_sigma_code','busy_mean_us','fourth_read_us_range']} for k,v in groups.items()},indent=2))
