"""Reproduce fast.3 fixed-pulse ADC and sample-time comparisons."""
from pathlib import Path
import json
import statistics as st
import struct
import zlib

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'work/peakhold-fast3-20261116'
OUT=ROOT/'outputs/Aster-MCA-Nano-ADC对照-20261116'
OUT.mkdir(parents=True,exist_ok=True)

def summarize(paths):
    ds=[json.loads(p.read_text()) for p in paths]
    rows=[]
    for p,d in zip(paths,ds):
        assert d['completed'] and d['header']['fault']==0 and d['raw_crc_verified']
        raw=(p.parent/'records.bin').read_bytes()
        assert zlib.crc32(raw)==d['header']['crc32']
        records=list(struct.iter_unpack('<16I',raw))
        assert len(records)==d['header']['n']==len(d['records'])
        for binary,r in zip(records,d['records']):
            assert list(binary)==[r[f] for f in d['record_fields']]
            assert r['amplitude_code']==st.mean(binary[6:10])-binary[1]
        rows+=d['records']
    amp=[r['amplitude_code'] for r in rows]
    n=len(rows)
    busy_n=sum(d['header']['within_batch_busy_n'] for d in ds)
    return dict(n=n,requested=sum(d['header']['requested'] for d in ds),
                rejected=sum(d['header']['baseline_rejects'] for d in ds),
                timeouts=sum(d['header']['timeouts'] for d in ds),
                flagged=sum(r['flags']!=0 for r in rows),
                mean_code=st.mean(amp),sigma_code=st.pstdev(amp),
                relative_rms_percent=100*st.pstdev(amp)/st.mean(amp),
                peak_sigma_code=st.pstdev(r['peak_mean_code'] for r in rows),
                baseline_sigma_code=st.pstdev(r['baseline'] for r in rows),
                within_batch_sigma_code=(sum(len(d['records'])*st.pvariance(r['amplitude_code'] for r in d['records']) for d in ds)/n)**.5,
                busy_mean_us=sum(d['header']['within_batch_busy_mean_cycles']*d['header']['within_batch_busy_n']/144 for d in ds)/busy_n,
                last_read_us_range=[min(r['last_read_us_after_hold_irq'] for r in rows),max(r['last_read_us_after_hold_irq'] for r in rows)],
                batches=[dict(mean_code=d['summary']['amplitude_mean_code'],rms_percent=100*d['summary']['amplitude_sigma_code']/d['summary']['amplitude_mean_code']) for d in ds],
                files=[str(p.relative_to(ROOT)) for p in paths])

samples={str(k/2):summarize(sorted(DATA.glob(f'pulse300-adc72-pk{k}-repeat*/result.json'))) for k in [49,95,185,495]}
clocks={str(k):summarize(sorted(DATA.glob(f'pulse300-clock-adc{k}-pk49-repeat*/result.json'))) for k in [72,36,24,12]}
audits=[]
for p in sorted(DATA.glob('pulse300-stop-audit-*/result.json')):
    d=json.loads(p.read_text());h=d['header']
    assert d['completed'] and d['raw_crc_verified'] and h['fault']==0
    assert zlib.crc32((p.parent/'records.bin').read_bytes())==h['crc32']
    audits.append(dict(mode=h['raw_stop_phase'],window_us=h['window_us'],n=h['n'],
                       c1_irq_n=h['c1_irq_n'],ignored_n=h['c1_ignored_n'],
                       stop_before_irq_n=h['dma_stop_before_hold_irq_n'],
                       stop_after_irq_us_range=[h['dma_stop_minus_hold_irq_min_cycles']/144,h['dma_stop_minus_hold_irq_max_cycles']/144],
                       file=str(p.relative_to(ROOT))))
result=dict(condition='User-confirmed AG1022,N61116A.bin,300mVpp,-150mV,~976.56Hz,High Z; source unchanged',
            cpu_hz=144000000,firmware='0.4.1-fast.3',sample_time_comparison=samples,adc_clock_comparison=clocks,
            dma_stop_audit=audits,
            limitations=['Electrical pulse repeatability, not detector energy resolution',
                         'ADC clock changes also change RAW rate, baseline time span, and trigger-to-rearm busy time',
                         'Sample-time comparison keeps ADC/RAW clock fixed; each clock-comparison batch recalibrates ADC',
                         'No clipping of distributions or removal of accepted outliers',
                         'C1 capture IRQ was never observed in EARLY; all measured DMA stops were after HOLD IRQ entry'])
raw_reference=json.loads((DATA/'raw-reference-summary.json').read_text())
result['raw_reference']=raw_reference
(OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n')

fig,axes=plt.subplots(1,3,figsize=(14,4.6),layout='constrained')
for ax,groups,title,xlabel in [(axes[0],samples,'Longer peak acquisition; ADC72MHz / RAW4M','PEAK sample time (ADC cycles)'),
                              (axes[1],clocks,'Lower ADC clock; CPU144MHz fixed','ADC clock (MHz)')]:
    keys=list(groups)
    for i,key in enumerate(keys):
        ax.scatter([i]*4,[b['rms_percent'] for b in groups[key]['batches']],c='#96a1aa',s=25,alpha=.8,label='Individual128-event batches' if i==0 else None)
    ax.plot(range(len(keys)),[groups[k]['relative_rms_percent'] for k in keys],'o-',color='#178c89',label='All512 events / setting')
    ax.set(xticks=range(len(keys)),xticklabels=keys,title=title,xlabel=xlabel,ylabel='Amplitude relative standard deviation (%)',ylim=(0,4))
    ax.legend(fontsize=8)
for mode,color in [('hold','#268c8b'),('trigger','#9364b1')]:
    docs=[json.loads((ROOT/a['file']).read_text()) for a in audits if a['mode']==mode and a['window_us']==6]
    for d in docs:
        x=d['header']['dma_stop_minus_hold_irq_min_cycles']/144
        y=d['header']['dma_stop_minus_hold_irq_max_cycles']/144
        axes[2].plot([x,y],[mode,mode],'o-',color=color,linewidth=3)
axes[2].axvline(0,color='black',linestyle='--',linewidth=1)
axes[2].set(xlabel='DMA stop completion minus HOLD IRQ entry (us)',title='Both modes stopped after HOLD IRQ',xlim=(-.5,2),yticks=['hold','trigger'],yticklabels=['LATE setting','EARLY setting'])
axes[2].text(.04,.93,'EARLY: C1 IRQ count=0 /128 events\nStop before HOLD IRQ=0 /128',transform=axes[2].transAxes,va='top',fontsize=9)
for ax in axes:ax.grid(alpha=.2)
fig.suptitle('Aster MCA Nano fast.3 — fixed300mV negative pulse,2026-11-16')
fig.savefig(OUT/'adc-comparison.png',dpi=170)

lines=['# Aster MCA Nano：ADC 与峰值采样时间对照','',
       '2026-11-16，fast.3，CPU144MHz；发生器原300mV负脉冲设置与接线保持不变。',
       '本轮采样时间对照2048事件，ADC时钟对照2048事件，停止路径审计512事件，初查32事件；共4640事件。',
       '全部原始CRC通过，没有超时、基线拒绝或事件标志。','',
       '## 固定ADC72MHz和RAW4MSa/s，改变PEAK采样时间','',
       '| 采样周期 | 事件 | 标准差/码 | 相对标准差 | 批内忙碌/µs |','|---|---:|---:|---:|---:|']
for k,v in samples.items():lines.append(f"| {k} | {v['n']} | {v['sigma_code']:.3f} | {v['relative_rms_percent']:.3f}% | {v['busy_mean_us']:.2f} |")
lines+=['','## 固定CPU144MHz与PEAK24.5周期，改变ADC时钟','',
        '| ADC/MHz | RAW/MSa/s | 标准差/码 | 相对标准差 | 批内忙碌/µs |','|---|---:|---:|---:|---:|']
for k,v in clocks.items():lines.append(f"| {k} | {dict(zip(['72','36','24','12'],[4,2,1,.5]))[k]} | {v['sigma_code']:.3f} | {v['relative_rms_percent']:.3f}% | {v['busy_mean_us']:.2f} |")
lines+=['','## 解释与下一步','',
        '延长采样和降低ADC时钟均未恢复旧版约1.31%的固定电信号重复性。当前数据不支持选择低ADC时钟作为改善方案。',
        'PEAK本身的标准差约9–12码，预触发基线标准差不足1码；主要离散出现在峰值读数。尚不能确定来自模拟保持、采样耦合、触发或其他因素。',
        'EARLY设置下，6µs与32µs窗口各128事件，C1中断执行次数均为0；DMA停止完成时间均在HOLD中断入口后约1.2–1.5µs。因此早停路径没有按预期执行，不能用fast.2/fast.3的配置对照排除DMA停止时刻的影响。',
        '已准备fast.4：将早停入口改为启动定时器所用TRGIN事件的专用触发中断，保留执行次数和停止时间戳。仅软件检查通过，尚未烧板，效果须实测。',
        '当前板保留fast.3，结束时恢复ADC72MHz/RAW4MSa/s/PEAK24.5周期/LATE，HOLD/RESET1/1。发生器仍由前面板开启，软件未关闭输出。','',
        '本表为电信号重复性，不是探测器能量分辨率。忙碌时间不包含上传和主机等待。ADC时钟对照同时改变RAW速率及32点基线的时间跨度，且每批重新校准ADC；保持这些差异后再解读结果。',
        '各设置按轮换顺序采四批128事件，保留所有接收事件；summary.json同时保存各批均值、批内标准差、PEAK与基线各自的标准差。','',
        '另采32帧RAW4MSa/s参考，每帧4096点，CRC与逐点统计均通过。以帧内最大值减中位数估计幅度：平均373.31码，标准差2.38码，范围369–378码。采RAW时保持电路处于复位状态，且不是与PEAK同事件配对；可作为线索，尚不能据此排除负载或模拟保持过程的影响。','',
        '![对照图](adc-comparison.png)']
(OUT/'README.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'samples':samples,'clocks':clocks,'stop_audits':audits},indent=2))
