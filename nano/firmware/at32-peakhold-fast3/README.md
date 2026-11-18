# AT32 峰值保持 ADC 对照固件 fast.3

CPU 固定 144 MHz；沿用已上板的 fast.2，增加 ADC 分频/采样时间切换与实际 DMA 停止记录。默认 ADC 72 MHz、RAW 4 MSa/s、PEAK 24.5 周期、PHSTOP LATE。

## 运行时选择

仅在批次之间切换参数，先让 HOLD/RESET 回到 1/1。PHADC 重新初始化并校准 ADC；每个事件不做校准。配置不写 Flash，重启恢复默认值。

| 命令 | ADC 时钟 | RAW 速率 | 定时器周期 / CPU 周期 |
|---|---:|---:|---:|
| PHADC 72 | 72 MHz | 4 MSa/s | 36 |
| PHADC 36 | 36 MHz | 2 MSa/s | 72 |
| PHADC 24 | 24 MHz | 1 MSa/s | 144 |
| PHADC 12 | 12 MHz | 0.5 MSa/s | 288 |

PHPK 49 / 95 / 185 / 495：选择 24.5 / 47.5 / 92.5 / 247.5 个 ADC 周期的峰值采样时间。以两倍周期数表示，避免小数解析。RAW 始终为 2.5 周期。
PHSTOP EARLY / LATE：保留 fast.2 的停止方式对照；PHINFO 回读全部配置。

降低 ADC 时钟必须同步降低 RAW 速率，以满足外触发转换间隔。32 点 DMA 基线和 8 点保护区保留，因此基线的时间跨度也随 RAW 速率变化。比较时应分别检查 PEAK 本身和基线的离散，不能把结果单独归因于 PEAK 转换时钟。
同一 ADC 时钟下的 PHPK 对照保持 RAW 速率、DMA 基线算法和 CPU 时钟不变，是优先进行的采样时间对照。

## 时序证据

PHCAP 保留每事件 16 个 uint32 字段和 CRC。头部新增：

- c1_irq_n、c1_ignored_n：首次捕获中断及因定时器未运行而忽略的次数。
- dma_stop_n、dma_stop_before_hold_irq_n：完成事件的停止记录数、在 HOLD 中断入口前已完成 DMA 停止的事件数。
- dma_stop_minus_hold_irq_min/max/mean_cycles：实际停止完成时间减 HOLD 中断入口时间，有符号 CPU 周期。负值可证明在该中断入口前已经停下，不能当作外部测量的硬件 HOLD 边沿偏差。
- adc_hz、raw_rate_hz、peak_sample_cycles_x2：每批配置，禁止把低速测试标为 4 MSa/s。

停止完成时间点在停止定时器、取消触发、ADC 中止等待、DMA 冻结及读出 DMA 位置之后。统计覆盖成功触发的事件，也包含之后因基线污染而拒绝的事件。
批内忙碌统计仍不包含整批上传和等待电脑；本固件仍为分批诊断工具。

## 使用与验证

```
python3 firmware/at32-peakhold-fast3/build.py
python3 firmware/at32-peakhold-fast3/check_software.py
python3 firmware/at32-peakhold-fast3/flash.py
python3 firmware/at32-peakhold-fast3/read_raw.py --output <新目录>
python3 firmware/at32-peakhold-fast3/read_timing.py --events 128 --expect-events --adc-mhz 72 --peak-sample-x2 95 --stop-phase late --output <新目录>
```

主机检查通过全部 32 种时钟/采样时间/停止配置组合的模拟传输，以及 64 种 CRC/速率错误拒绝场景；各档位的环形基线索引模型也已检查。这些检查不代表实物 ADC 精度验证。
构建检查镜像向量、实际 SRAM 中断地址和至少 4 KiB 栈余量。烧录工具仅接受已验证 fast.2 镜像，先备份整片 Flash 和选项字节，写后读回核对并检查擦除范围外和选项字节不变。

状态：2026-11-16 已烧入实物并完整读回核对；选项字节及擦除范围外内容未变。四种 ADC 时钟/RAW 速率档各通过 4096 点 DMA CRC、统计及内部时长检查；所有峰值采样时间档已做空载准备/超时/恢复检查，合计 28 次尝试，无误触发。fault=0、selftest=15、HOLD/RESET=1/1。尚未采集 fast.3 的输入脉冲重复性数据。
下一步：等待用户接回并开启原 300 mV 波形，先做短批检查，再按原设置交替对照，不需要为每个档位再次烧录。当前配置已恢复 ADC72MHz / RAW4MSa/s / PEAK24.5cycles / LATE。完整记录：work/peakhold-fast3-20261116/。

## 已有模拟峰值保持证据

旧 timing.1 下，测试文件脉冲全宽约 4 µs。100 mV 档，额外延后 200 µs 再读仍有约 106.86 码的峰幅，128 个事件 HOLD 电平均为高；复位后 PEAK 相对基线均值为 −1.81 码。常规读取约 109 码，300 mV 档约 377.6 码，复位后约 −1 码。
这支持捕获、保持及复位功能已工作。幅度由发生器设定，未由示波器校准；各延迟组不是同一批事件，不能将组均值之差直接当作准确的保持下垂率。线性、温漂、完整输入范围和高速读取重复性仍待验证。

参考：[官方数据手册](https://www.arterychip.com/download/DS/DS_AT32F423_V2.03_EN.pdf)、[官方参考手册](https://www.arterychip.com/download/RM/RM_AT32F423_EN_V2.03.pdf)、本地官方 SDK。

## 输入脉冲对照已完成

2026-11-16共4640事件均CRC通过、无超时/拒绝/事件标志；改变采样时间及ADC时钟均未恢复旧版重复性。EARLY模式6µs/32µs窗口各128事件的C1中断次数均为0，DMA实际仍在HOLD中断后停止。原始数据和结果见outputs/Aster-MCA-Nano-ADC对照-20261116/。已准备使用专用TRGIN中断的fast.4，尚未烧入。
