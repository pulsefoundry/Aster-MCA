# fast.5：独立降低 RAW 采样率

目的：按用户要求回查提高采样率后出现的重复性问题。旧 PHADC 命令同时改变 ADC 时钟与 RAW 速率，无法单独判断 RAW 转换频率的影响。本版增加独立 PHRATE，只改变 TMR2 触发周期。

默认 CPU144MHz、ADC72MHz、RAW1MSa/s、PEAK24.5个ADC周期、LATE。保留 fast.4 已实测的TRGIN早停路径、硬件HOLD截止、RESET顺序及停止时间戳。

## 调速与记录

| 命令（kSa/s） | RAW速率 | TMR2周期/CPU周期 | 96点预热时间 |
|---|---:|---:|---:|
| PHRATE 4000 | 4MSa/s | 36 | 24µs |
| PHRATE 2000 | 2MSa/s | 72 | 48µs |
| PHRATE 1000 | 1MSa/s | 144 | 96µs |
| PHRATE 500 | 500kSa/s | 288 | 192µs |
| PHRATE 250 | 250kSa/s | 576 | 384µs |
| PHRATE 125 | 125kSa/s | 1152 | 768µs |

PHRATE在空闲状态切换，不复位或重新校准ADC，不改变ADC时钟、RAW2.5周期采样设置、PEAK采样时间、捕获窗、触发阈值或CPU时钟。PHINFO、PHRAW、PHCAP均记录实际配置速率；主机核对定时周期、CRC与统计。

PHADC仍可选择72/36/24/12MHz并重新校准，但现在会尽量保留已选RAW速率；ADC降频无法支持原速率时，降至相应安全上限。高于当前ADC时钟允许触发频率的PHRATE命令会拒绝，不开始采集。

## 解释结果时的限制

- RAW转换率与ADC时钟已解耦，比较时固定CPU144MHz、ADC72MHz、PEAK24.5周期和同一停止模式。不要在每个速率批次重复PHADC校准。
- 32点基线、8点保护区与96点预热保留；速率下降会拉长其时间跨度，并增加批内忙碌时间。因此需要分别比较PEAK自身与基线的标准差，不能把幅度变化全部归因于保持电路。
- 最低档预热768µs，小于现有1ms预热期限；4096点RAW快照为32.768ms，小于100ms快照期限。较低采样率的RAW快照可能漏掉4µs脉冲的峰顶，不能直接把低速RAW最大值用于评价模拟保持的精度。
- 本版尚未加入“整个捕获期间ADC静默”模式。

## 软件检查与上板计划

编译、向量、SRAM中断位置及栈余量检查通过。576个模拟主机协议用例覆盖合法ADC时钟/RAW速率组合、四种PEAK采样时间、两种停止模式，以及CRC和速率元数据错误拒绝；各速率定时相位的环形索引模型通过。软件检查不代表降速后的实测精度。

状态：已准备，尚未烧入。当前板上的fast.4及其原始数据保留。
烧录工具仅接受已核对的fast.4或完全一致的fast.5，先备份整片Flash及选项字节，写后完整读回并核对擦除范围外内容和选项字节。

下一步：用户关闭发生器输出、断开SMA并实体BOOT重插；烧录后先检验各RAW速率的DMA完整性与空载控制，再确认接回原300mV波形。先交替测4M、1M、500k，必要时再测250k和125k。

```
python3 firmware/at32-peakhold-fast5/build.py
python3 firmware/at32-peakhold-fast5/check_software.py
python3 firmware/at32-peakhold-fast5/flash.py
python3 firmware/at32-peakhold-fast5/read_timing.py --events 128 --expect-events --raw-ksa 1000 --stop-phase early --output <新目录>
```

## 2026-11-16上板检查

fast.5已烧入并完整读回一致，选项字节与擦除范围外内容未变。六档RAW速率均在CPU144MHz、ADC72MHz不变的条件下完成4096点DMA快照，合计24576点CRC/统计/内部块时长检查通过；每档8次空载等待，48次均无事件。控制自检15、fault0。当前1MSa/s、EARLY、PEAK24.5周期、HOLD/RESET1/1。尚未采集新固件的300mV输入脉冲重复性数据。

## 独立降速输入对照完成

USB普通重插恢复通信后，共采11040个有效事件，CRC全通过，无超时/基线拒绝/事件标志。最终五档同阶段轮换，每档1280事件：4M相对标准差2.744%，1M2.226%，500k1.489%，250k1.269%，125k1.079%。CPU144MHz、ADC72MHz、PEAK24.5周期不变，PEAK自身的离散同样随降速减少；具体机制仍未定位，基线与预热的时间跨度也随速率变化。批内忙碌约72.74/144.73/240.74/432.73/816.74µs，不含上传与主机等待。当前运行时留在500k、EARLY、HOLD/RESET1/1；重启默认仍为1M。详细原始数据和对照图见outputs/Aster-MCA-Nano-降采样率对照-20261117/。
