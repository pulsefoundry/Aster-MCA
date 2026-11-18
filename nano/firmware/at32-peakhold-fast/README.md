# AT32 v0.4.1 高速峰值保持诊断

固件 `0.4.1-fast.1`，从已验证的 `timing.1` 单独派生；旧版源码、镜像及记录保留。

## 时钟与采样

- 按用户选择沿用早期实测配置：CPU 144 MHz，APB1 72 MHz，TMR2/TMR3 144 MHz，ADC 72 MHz；USB 仍取 HICK 48 MHz 并使用 ACC。
- 切换 PLL 前设置 Flash 等待周期和内部 LDO 1.3 V。此设置位于芯片额定 150 MHz 范围内。
- 用户最初提到 140 MHz；严格 140 MHz 时 ADC 分频到 70 MHz，手册 18 ADC 周期的外触发间隔只能支持约 3.889 MSa/s。用户已确认改用 144 MHz / 72 MHz，以每 36 个定时器周期触发一次得到 4 MSa/s。
- **4 MSa/s 用于 RAW 输入及预触发 DMA。** 保持峰的独立读数用 24.5 周期采样，兼顾其 100 Ω / 1 nF 输入网络。单 ADC 在冻结后切换通道，不能把两个阶段都称作 4 MSa/s。

## 优化路径

- TMR3 保留比较器正沿启动与硬件 HOLD 截止；TMR2 专供 ADC 4 MHz 触发，避免复用冲突。
- 武装前启动 256 点循环 DMA 并预热至少 96 点；HOLD 中断停 RAW 触发、停止转换并冻结缓冲。
- 由内部时钟与 DMA 位置定位事件前基线，取比较器触发前约 10..2 µs 的 32 点，避开前沿。索引软件模型覆盖相位、停止延迟及转换延迟共 960 个条件；实物的延时与波形仍需验证。
- ADC 仅在切通道时配置采样时间，随后直接启动转换、检查标志并取数，弃首点后读 4 点。计时记录继续保留，不按代码估计值冒充实测读出时间。
- 关键中断复制到 SRAM；构建检查实际符号位置和至少 4 KiB 栈余量。
- 增加批内从事件触发到下一次武装的忙碌周期统计。最后一个事件到批次上传、等待下一命令的停采时间不包含在该值中。
- 保留故障、超时、基线污染拒绝、数据 CRC，以及停止时 HOLD/RESET=1/1。

## 工具

```
python3 firmware/at32-peakhold-fast/build.py
python3 firmware/at32-peakhold-fast/flash.py
python3 firmware/at32-peakhold-fast/read_raw.py --output <新目录>
python3 firmware/at32-peakhold-fast/read_timing.py --events 8 --expect-empty --output <新目录>
python3 firmware/at32-peakhold-fast/read_timing.py --events 128 --expect-events --output <新目录>
```

`PHRAW`：4096 点 RAW 定时 DMA 快照，后置 4096 点保护区吸收停止前的尾部转换。主机逐点重算统计和 CRC，并以 DWT 检查块时长是否符合 4 MSa/s 的内部时钟配置。该块时长检查不是外部频率计校准。

`PHCAP N WINDOW_US EXTRA_DELAY_US`：每事件 64 字节，字段保持旧版一致；基线已改为预触发 DMA。头部增加 `within_batch_busy_*`、`raw_rate_hz`，版本和基线方法必须一起存档。

烧录脚本只接受已验证的 timing.1 镜像。写前备份整片 Flash 与选项字节，写后读回比对，检查擦除范围外及选项字节未变。

## 验证状态

编译、镜像向量、SRAM 中断位置、内存余量、时钟整数分频与合成索引检查已完成。
硬件验证记录放在 `work/peakhold-fast-20261116/`。需要在烧录后分别确认：时钟及 HOLD 自检、空载快照、无输入误触发、固定脉冲下的时间与重复性。
这仍是分批台架诊断固件，尚不是完整连续 MCA；不能用其批内忙碌时间代表整机总死时间或计数效率。

参考：[AT32F423 数据手册](https://www.arterychip.com/download/DS/DS_AT32F423_V2.03_EN.pdf)、[参考手册](https://www.arterychip.com/download/RM/RM_AT32F423_EN_V2.03.pdf)、仓库内官方 SDK 与先前 144 MHz / 4 MSa/s 固件。
