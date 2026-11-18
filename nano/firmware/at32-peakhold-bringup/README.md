# AT32 v0.4.1 PTH 首次上电自检

固件 `0.4.1-bringup.1`，适用于 AT32F423CCT7 核心板及峰值保持底板。
基于本仓库早期上电诊断的 USB 和 ADC 实现，单独构建，不修改旧版固件。

- 内部 HICK 48 MHz + USB ACC，无外部晶振，无超频。
- PB12 低有效 RUN，每 500 ms 翻转，每秒一个明暗周期。
- 输出前预置 PA7/HOLD=1、PB0/PEAK_RESET=1，全程保持复位到 BASE。
- PA0/PA1/PA2 分别为 PEAK/RAW/BASE ADC 输入；PA4 保持模拟高阻，DAC 未启用。
- PA6 仅作比较器状态输入，PA9 为 VBUS 检测输入；保留 SWD。
- ADC 12 MHz，12 位，应用 ES0010 XTEST=9 修正。默认长采样周期、软件定时诊断取样，收到命令才采集。
- 尚无事件触发、保持窗口、释放复位时序或能谱累加功能。

## 构建和首次烧录

在仓库根目录执行 `python3 firmware/at32-peakhold-bringup/build.py`。
依赖既有 `work/at32-bringup-2026-10-14/sdk` 与 ARM GNU 工具链，工具链可由 `ARM_GCC_BIN` 指定。
运行 `flash.py` 前需按住 BOOT 重插 USB。脚本只接受一个报告 256 KiB 的 AT32 DFU 设备，先备份整片 Flash 与选项字节，拒绝写入非空白芯片。
写入后读回整片比对程序、页尾、擦除范围外和选项字节，再退出 DFU。
脚本不写选项字节；不适合作为后续固件升级工具。

## 静态检查

`python3 firmware/at32-peakhold-bringup/read_static.py --output <新的结果目录>`

输入保持断开，程序逐个选择三个 ADC 通道，每路读取三组各 4096 点。
主机独立核对 CRC32、最小值、最大值、总和及平方和，并检查 ADC 停用/重启和心跳计数。
命令包括 `INFO`、`PING`、`CHANNEL PEAK` / `RAW` / `BASE`、`STATS`、`RAW`、`ADC OFF`、`ADC ON`。
电压换算中的 3.3 V 为名义值，实际电压应由万用表确认；此诊断采样不是等间隔 DMA 采样或脉冲性能证明。

## 2026-11-16 实板记录

首次写入前 Flash 全为 FF。程序 14972 字节，读回逐字节相符，其他 Flash 及选项字节未变。
Mac 出现 USB CDC 接口；USB 命令、ADC 初始化、三通道共 36864 点的原始数据校验通过。
用户确认 RUN 灯每秒闪烁一轮，报告核心板电源约 3.4 V。
保持/复位输出寄存器为 1/1；实体控制线电压及动态峰值保持仍需后续测量。

证据在 `work/peakhold-bringup-20261116/`：`bringup-summary.json`、`static-01/`、首次烧录备份与校验记录。
