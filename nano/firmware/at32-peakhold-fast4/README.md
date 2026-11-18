# fast.4：使用 TRGIN 触发事件执行提前停止

基于已上板 fast.3，保留 CPU144MHz、ADC72/36/24/12MHz 四档、PEAK 采样时间切换及16字事件格式。

## 修改原因与实现

fast.3 的 EARLY 配置在6µs和32µs窗口各采128事件，c1_irq_n均为0，实际 DMA 停止均发生在 HOLD 中断入口之后。软件设置成功没有使提前停止路径执行。

fast.4 将早停入口从 TMR_C1_INT/捕获事件换成 TMR_TRIGGER_INT/TRGIN 触发事件。此事件对应当前从模式定时器的启动输入；HOLD 截止仍由原 C2 比较硬件完成。保留定时器未运行时忽略陈旧触发的保护。首次触发处理后禁止该中断并清除标志，C2完成及空闲路径均关闭 C1/TRIGGER/C2 中断。

PHCAP头部的c1_irq_n/c1_ignored_n改名为trigger_irq_n/trigger_ignored_n；有符号DMA停止时间戳保留。判断实际提前停止必须检查trigger_irq_n以及dma_stop_before_hold_irq_n，并查看dma_stop_minus_hold_irq_*_cycles。负值证明停止完成早于HOLD中断入口，不是外部示波器测得的HOLD边沿偏差。

默认仍为LATE。命令PHSTOP EARLY开启新路径；PHSTOP LATE用于同固件对照。PHADC/PHPK选择方式与fast.3一致。所有参数仅在空闲时切换，不保存到Flash。

## 验证状态

ARM编译、镜像向量、SRAM中断地址、栈余量检查通过；96个模拟主机传输用例及各速率环形索引模型通过。**尚未烧板，实际触发中断与提前停止效果未经实物验证。**

烧录工具仅接受SHA已核对的fast.3镜像：备份整片Flash和选项字节，写后完整读回，检查擦除范围外和选项字节未变。

下一步：实体BOOT烧录后先测空载，再用同一300mV波形检查TRGIN中断和实际停止时间；只有提前停止确已执行，才能进行有效的EARLY/LATE对照。

```
python3 firmware/at32-peakhold-fast4/build.py
python3 firmware/at32-peakhold-fast4/check_software.py
python3 firmware/at32-peakhold-fast4/flash.py
python3 firmware/at32-peakhold-fast4/read_timing.py --events 128 --expect-events --adc-mhz 72 --peak-sample-x2 49 --stop-phase early --output <新目录>
```

依据：本地官方参考手册RM_AT32F423_V2.04_EN.pdf中TRGIN触发模式与TRGIF/TIEN描述、官方SDK的TMR_TRIGGER_FLAG/TMR_TRIGGER_INT定义。原始实测见work/peakhold-fast3-20261116/stop-audit-sequence.json。

## 2026-11-16上板状态

fast.4已烧入，完整读回一致，选项字节及擦除范围外内容未变。控制自检15、fault0，4096点RAW4MSa/s的CRC/统计/内部块时长通过。初次空载EARLY观察到2个小幅触发，TRGIN中断2次，DMA均在HOLD中断入口前4.02–4.13µs停止，证明该入口确已执行。随后晚停也出现10个接收事件和1个基线拒绝；再之后连续448次尝试无事件。初始空载零触发判据未通过，记录已保留；原因未确定，不能宣称整段空载完全无误触发。当前EARLY、ADC72MHz/RAW4M/PEAK24.5cycles、HOLD/RESET1/1。等待用户接回已确认的300mV波形，再验证正常信号下的时序和重复性。

## 正常300mV脉冲对照

fast.4重烧后，用户确认发生器与信号已接好。八对共2048事件CRC全部通过，无超时/拒绝/标志。EARLY1024事件实际提前停止均验证，幅度相对标准差3.170%；LATE1024事件为3.141%。第四次读取分别在HOLD中断入口后9.02–11.15µs与11.31–13.38µs完成；批内忙碌均值72.01µs/74.15µs。另扫2–32µs窗口768事件，未显示明确改善。精度问题仍未解决；完整原始数据与解释见outputs/Aster-MCA-Nano-真实早停对照-20261116/。
