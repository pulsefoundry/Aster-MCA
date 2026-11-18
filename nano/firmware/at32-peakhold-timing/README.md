# AT32 v0.4.1 峰值保持时序诊断

固件 `0.4.1-timing.1`。供固定信号发生器脉冲验板，不是最终连续 MCA。
旧版上电自检源码、镜像与首次烧录证据保留在 `at32-peakhold-bringup`。

## 控制与采样

- 内部 HICK 48 MHz、USB ACC、ADC 12 MHz；无超频。
- PA6/AF2/TMR3_CH1 接比较器正沿。TMR3 从模式采用 TRIGGER，禁止用每次边沿清零计数器的 RESET 模式。
- PA7/AF2/TMR3_CH2 控制 HOLD。武装时强制低，然后比较匹配置高并锁存；后续边沿不把 HOLD 拉低。高优先级比较中断停止触发、停止计数并记录 DWT 时间。窗口默认 6 µs。
- PB0 控制复位。所有停止、超时、异常路径先 HOLD=1 再 RESET=1。重新武装前保持复位至少 2 µs，释放后至少 1 µs。
- 上电等待参考稳定 600 ms；自测核心 PA7 引脚的高、低、比较后高以及中断完成四项，全部成功时 selftest=15。该回读不替代对底板开关控制端及模拟波形的示波器检查。
- PA4 DAC 开缓冲，默认阈值为 BASE ADC 均值加 40 码（实际阈值电压待测），每次更新等 2 ms。
- 每次武装前取 8 点 RAW 均值和范围，并检查是否偏离 BASE。这个基线来自武装前，**不是围绕随机事件的 DMA 预触发基线**。适用于本轮稳定周期信号，不作最终谱学算法的替代。
- 释放复位后、HOLD 仍高时读取注入残留；再武装等待触发。比较器超过阈值后定时器关闭捕获窗口。
- HOLD 比较中断后按指定延时切 PEAK，24.5 周期采样，弃首点再读 4 点；记录各有效点完成时刻相对中断的周期数。ADC 当前较慢，数据必须按实际读出延时解释，不能当作“峰后 10 µs 内完成”已通过。
- 阶段性屏蔽中断约数十微秒以稳定 ADC 读出；HOLD 的关闭由定时器硬件完成，不依赖 USB 调度。
- 每批最多 128 次尝试，采完先回到 HOLD/RESET=1/1，然后一次上传 64 字节/事件的记录及 CRC32。

## 命令及主机读取

`PHINFO`：版本、故障、自检、阈值、基准以及实际 HOLD 输入回读。

`PHCAP N WINDOW_US EXTRA_DELAY_US`：N=1..128、窗口=2..32 µs、比较中断后额外等待=0..200 µs。
返回一行 JSON，随后恰好 `bytes` 个二进制字节，再跟 CRLF。每条记录为 16 个小端 uint32，字段见 `read_timing.py` 的 FIELDS。
记录 flags bit0 表示捕获窗中发生输入再捕获，bit1 表示读出时 HOLD 不高。Busy 后的双脉冲不保证全部计入再捕获标记。

示例：

```
python3 firmware/at32-peakhold-timing/build.py
python3 firmware/at32-peakhold-timing/flash.py
python3 firmware/at32-peakhold-timing/read_timing.py --events 8 --expect-empty --output <新空载目录>
python3 firmware/at32-peakhold-timing/read_timing.py --events 64 --expect-events --output <新脉冲目录>
```

烧录工具只接受已核对的 `0.4.1-bringup.1` 镜像；备份整片 Flash 与选项字节，拒绝未知旧程序，写后读回比较，并验证擦除范围外和选项字节未变。
主机读取逐帧校验长度、CRC、ADC 范围、自检和最终空闲状态。各测试的真实输入条件应写入台架记录。

## 2026-11-16 首次上板

19472 字节程序读回逐字节一致。核心 HOLD 的四项自检均通过，fault=0。
SMA 断开、发生器输出关闭时，8 次武装均超时，0 次接受事件。BASE 约 772 码、PEAK 复位电平约 771 码、DAC 设置 812 码。
数字自检和空载验证已经完成；固定脉冲的模拟抓峰、下垂和复位效果须以随后的实测记录为准。

证据：`work/peakhold-timing-20261116/`，包括完整烧录备份、`verification.json`、`open-input-off-01/`。
外部波形：`outputs/Aster-MCA-Nano-峰值保持测试波形-20261116/`。

实现依据：官方 SDK 的 `tmr/one_cycle`、`tmr/pwm_input`、DAC 示例，以及 [AT32F423 参考手册](https://www.arterychip.com/download/RM/RM_AT32F423_EN_V2.03.pdf)和[数据手册](https://www.arterychip.com/download/DS/DS_AT32F423_V2.03_EN.pdf)。外部微秒时间和模拟波形仍需独立仪器核对。
