Aster MCA Nano AT32 — 采谱算法预研 v0.1
日期：2026-10-14

当前内容
replay.py 是电脑端离线分析程序，不会访问或烧录板子。
只接受现有 v0.2.0 定时器 DMA 1 MS/s 数据，独立复核每段 CRC、样本统计、
采样时钟与 DMA 状态，再生成候选事件表、峰高分布和固定时间窗积分分布。
check_replay.py 检验已知脉冲、直流偏移、反向尾波的有符号积分、相邻事件、
削顶、帧边界、阶跃及损坏的数据，不把通过软件测试等同于能谱性能验证。

算法
1. 触发参考：前 64 点平均值，距当前点留 4 点间隔。
2. 负向触发阈值：20 ADC 码，名义 3.3 V 参考下约 16.1 mV。
3. 最终基线：每个候选事件之前那 64 点的中位数；积分期间保持固定。
4. 保存采样峰高，以及从触发点前一个样本开始的 4、8、16 us 有符号面积。
   不把负数截成零，不把回摆面积误加到主脉冲上。
5. 标记基线不稳、局部幅度不足、长脉冲、峰值过晚、相邻候选、削顶、未恢复。
   不同标记可以重叠；全部原始候选均写入事件 CSV。
6. 帧间不拼接，不以插值补点；一帧开头 68 点及末尾 16 点不允许新触发。

运行环境
Python + NumPy + Matplotlib；本机已验证的解释器：
/Users/liu/Documents/Codex/2026-09-10/new-chat/work/mac-adc-venv/bin/python

运行形式
python replay.py --dataset source=/path/to/source-capture \
  --dataset removed=/path/to/removed-capture --out /path/to/output
python check_replay.py

输入目录包含 result.json 和逐帧 .bin；可重复添加 --dataset，标签须为唯一字母数字名。
原始工作目录和文件 SHA256 写入 replay-summary.json。
输出包括 spectra.csv、每组的 events.csv/summary.json、汇总 JSON 和 PNG。
各分布按 N/fs 的已采样时长归一化；这不是经过效率/死时间校正的真实 CPS。
CSV 的峰高单位是 ADC 节点 mV；面积单位是 mV·us，没有 keV 标定。

限制
1 MS/s 下多数脉冲仅有 1–2 个半高宽样本，峰高和面积都可能受采样相位影响。
门限和事件筛选有选择偏差，不能用接受数量代替真实核事件计数。
相隔很近、合并成一个候选的堆积仍不能可靠识别。
当前实现保留离线稳健中位数和诊断标记；不是 MCU 连续采谱固件。
数字成形参数、能量标定和能量分辨率均未定案。

本轮结果
/Users/liu/Documents/Codex/2026-10-09/ch32x033f8p6/outputs/Aster-MCA-Nano-AT32-采谱算法预研-20261014/
