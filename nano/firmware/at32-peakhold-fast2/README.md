# AT32 v0.4.1 高速峰值保持诊断

固件 `0.4.1-fast.2`，从 fast.1 单独派生；timing.1 与 fast.1 的源码、镜像及记录保留。

## 时钟与采样

- 按用户选择沿用早期实测配置：CPU 144 MHz，APB1 72 MHz，TMR2/TMR3 144 MHz，ADC 72 MHz；USB 仍取 HICK 48 MHz 并使用 ACC。
- 切换 PLL 前设置 Flash 等待周期和内部 LDO 1.3 V。此设置位于芯片额定 150 MHz 范围内。
- 用户最初提到 140 MHz；严格 140 MHz 时 ADC 分频到 70 MHz，手册 18 ADC 周期的外触发间隔只能支持约 3.889 MSa/s。用户已确认改用 144 MHz / 72 MHz，以每 36 个定时器周期触发一次得到 4 MSa/s。
- **4 MSa/s 用于 RAW 输入及预触发 DMA。** 保持峰的独立读数用 24.5 周期采样，兼顾其 100 Ω / 1 nF 输入网络。单 ADC 在冻结后切换通道，不能把两个阶段都称作 4 MSa/s。

## 优化路径

- TMR3 保留比较器正沿启动与硬件 HOLD 截止；TMR2 专供 ADC 4 MHz 触发，避免复用冲突。
- 武装前启动 256 点循环 DMA 并预热至少 96 点；默认在首次 TRIG 输入捕获中断中停止 RAW DMA 并预选 PEAK 通道；TMR3 继续计时，仍由比较硬件截止 HOLD。
- 由内部时钟与 DMA 位置定位事件前基线，取比较器触发前约 10..2 µs 的 32 点，避开前沿。索引软件模型覆盖相位、停止延迟及转换延迟共 960 个条件；实物的延时与波形仍需验证。
- ADC 仅在切通道时配置采样时间，随后直接启动转换、检查标志并取数，弃首点后读 4 点。计时记录继续保留，不按代码估计值冒充实测读出时间。
- 关键中断复制到 SRAM；构建检查实际符号位置和至少 4 KiB 栈余量。
- 增加批内从事件触发到下一次武装的忙碌周期统计。最后一个事件到批次上传、等待下一命令的停采时间不包含在该值中。
- 保留故障、超时、基线污染拒绝、数据 CRC，以及停止时 HOLD/RESET=1/1。

## 工具

```
python3 firmware/at32-peakhold-fast2/build.py
python3 firmware/at32-peakhold-fast2/flash.py
python3 firmware/at32-peakhold-fast2/read_raw.py --output <新目录>
python3 firmware/at32-peakhold-fast2/read_timing.py --events 8 --expect-empty --output <新目录>
python3 firmware/at32-peakhold-fast2/read_timing.py --events 128 --expect-events --output <新目录>
```

`PHRAW`：4096 点 RAW 定时 DMA 快照，后置 4096 点保护区吸收停止前的尾部转换。主机逐点重算统计和 CRC，并以 DWT 检查块时长是否符合 4 MSa/s 的内部时钟配置。该块时长检查不是外部频率计校准。

`PHCAP N WINDOW_US EXTRA_DELAY_US`：每事件 64 字节，字段保持旧版一致；基线已改为预触发 DMA。头部增加 `within_batch_busy_*`、`raw_rate_hz`，版本和基线方法必须一起存档。

烧录脚本只接受已验证的 fast.1 镜像。写前备份整片 Flash 与选项字节，写后读回比对，检查擦除范围外及选项字节未变。

## 验证状态

编译、镜像向量、SRAM 中断位置、内存余量、时钟整数分频与合成索引检查已完成。
硬件验证记录放在 `work/peakhold-fast-20261116/`。需要在烧录后分别确认：时钟及 HOLD 自检、空载快照、无输入误触发、固定脉冲下的时间与重复性。
这仍是分批台架诊断固件，尚不是完整连续 MCA；不能用其批内忙碌时间代表整机总死时间或计数效率。

参考：[AT32F423 数据手册](https://www.arterychip.com/download/DS/DS_AT32F423_V2.03_EN.pdf)、[参考手册](https://www.arterychip.com/download/RM/RM_AT32F423_EN_V2.03.pdf)、仓库内官方 SDK 与先前 144 MHz / 4 MSa/s 固件。

## fast.2 运行时对照

`PHSTOP EARLY`：默认；首次输入捕获时停 RAW DMA，提前切 PEAK，随后等硬件 HOLD 截止。

`PHSTOP LATE`：复现 fast.1；等 HOLD 截止后再停 DMA 并切 PEAK。

两个命令都先回到 HOLD/RESET=1/1，再更新设置。PHINFO 和 PHCAP 均记录 `raw_stop_phase`，分别为 `trigger` 或 `hold`。捕获窗口中额外的输入边沿不会重新打开 RAW DMA 或重启本次窗口。

fast.1 已实测主频/ADC 配置、DMA 数据完整性与更短读出，但固定脉冲重复性退化；延后读取没有解决。fast.2 用于在同一时钟下对照 DMA 停止和通道切换时刻，结果必须保留两种模式及其原始分布。

## 2026-11-16 实测结果

三对交替测试各 128 个事件，两种配置均 384/384 通过，CRC 正确、无超时或事件标志。
LATE：幅度相对标准差 2.628%，第四次读完 10.76–11.72 µs，批内忙碌均值 73.54 µs。
EARLY：2.718%，10.74–11.82 µs，73.94 µs。旧 timing.1 为 1.308%、41.42–44.13 µs。
固定脉冲的幅度重复性退化，尚未解决。上述时间相对于 HOLD 中断入口。

**EARLY 的实际 DMA 停止相位尚未直接验证。** 当前记录只包含配置值，没有首次捕获中断计数和 DMA 停止时间戳，不能据此断言两个实际停止相位等效。拉长到 32 µs 窗口也未显示明确改善。

结束时运行时设为 LATE，fault=0、selftest=15、HOLD/RESET=1/1；重启仍默认 EARLY。
完整记录：`outputs/Aster-MCA-Nano-144M-4MSa-读出对照-20261116/`。
