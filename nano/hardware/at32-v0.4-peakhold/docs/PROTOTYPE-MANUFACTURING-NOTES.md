# AT32 v0.4 核心模块 + 峰值保持底板：工程样机制造说明

**状态：NOT_FOR_FAB。** 这是当前工程样机的制造数据导出，尚不是量产或实测性能确认。载板原生 EDA 检查、最新版丝印的原生复核以及完整电气评审仍由主审查记录决定。不得仅凭此目录中的 Gerber 文件下单。2026-11-12 导出；确切源文件指纹在各目录 `source-hashes.json`。

## 两块板分开制造

| 项目 | 核心模块 | 峰值保持底板 |
|---|---|---|
| 尺寸 | 26 × 20 mm | 60 × 32 mm |
| 板厚 / 铜层 | 1.6 mm / 2 层 | 1.6 mm / 2 层 |
| 基材 | FR-4 | FR-4 |
| 铜厚订单建议 | 外层 1 oz；以下设计不依赖阻抗控制 | 外层 1 oz；以下设计不依赖阻抗控制 |
| 特殊工艺 | **22 个板边金属化半孔，必须选择半孔工艺并明确告知工厂** | 2 个 USB 外壳金属化长孔，另有 2 个非金属化定位孔 |
| 孔数 | 49 PTH = 22 半孔 + 27 过孔；0 NPTH | 56 PTH（其中 2 长孔）+ 2 NPTH |
| 装配 | 元件全部在顶面，底面贴到底板 | 元件全部在顶面，核心模块顶面朝上 |

两者是独立电路板、独立文件包，不应当将两个 ZIP 误作同一块板的层。未提供钢网层，按手工装配使用。

## 半孔与板框的关系

核心半孔孔中心确实位于板框线上：上长边 y = 0 mm，下长边 y = 20 mm；每边 x = 3、5、7、…、23 mm，间距 2 mm。22 个孔均为 PTH，钻孔数据直径 0.8 mm，焊盘为 1.4 × 2.0 mm，正反面均有铜和阻焊开窗。

工厂需保留板内半圆孔壁金属化；不能把孔向板内平移、按普通 NPTH 处理，或把穿出板框的焊盘自动裁成不连续铜。板框是矩形切割中心线；CAM 预览在板框外仍显示半个完整焊盘，是铣边前数据的预期表现。

原生核心 PCB 检查曾报告 22 条板框到通孔焊盘、22 条板框到钻孔；这是这 22 个特定半孔的几何例外。KiCad 对应 22 条铜到板边例外。该例外**不能扩展到其它焊盘、走线或板边**，也不应全板取消板边间距规则。

## 模块朝向与手焊

从顶面看、底板 USB 在左、SMA 在右时，核心模块同样顶面朝上，LED 和 BOOT 按键位于左侧。核心半孔 1 对准底板 M1 的 1；两者均有三角形和“1”标记。顶部从左至右为 1–11，底部从左至右为 22–12。**不得镜像或旋转 180° 安装。**

M1 的 22 个底板焊盘为 1.5 × 2.8 mm，2 mm 间距，模块每条长边外露约 1.4 mm 焊盘供烙铁接触。核心底面没有器件，底板模块覆盖区域没有元件。先完成并检查核心与底板各自焊接，再少量上锡固定两个对角位置，检查对齐后焊完 22 个半孔。模块与底板之间不放排针或绝缘垫；不要用过量锡把模块垫高。

核心仍有 0402 阻容和 0.5 mm 间距 LQFP；底板 U12 为 0.5 mm 间距 MSOP-10。这不是全部 0603 的宽松手焊板，应配合放大观察、细焊锡和适合的助焊剂。`pcb-top.svg/png` 是带位号的装配参考图；`CAM-top.svg/png` 才是实际制造丝印和铜层预览。小阻容没有逐个印制位号。

HOLD_CAP 高阻节点附近焊后清洁并干燥，避免助焊剂残留。其 8.615 mm 分支铜线位于顶层，无过孔；顶层局部地铜有避让，底层保持连续地铜。不要在该区域随意增加飞线、测试点或贴覆盖导电物。

## 外购接口必须核对机械尺寸

- USB J1：当前为 USB-A 公头、CNCTech 1001-011-01101 图形参考。4 个信号焊盘、2 个金属化固定长孔、2 个 1.1 mm 非金属化定位孔。外购替代品须核对全部脚距、定位柱、外壳焊脚和板边位置；型号图形参考不代表必须购买该品牌。
- SMA J2：直立母座，中心信号 + 4 个地脚，四地脚构成 5.08 × 5.08 mm 方形。中心钻孔 1.5 mm、地脚 1.7 mm。它不是原先的夹板边缘 SMA 封装，不能仅按“SMA 母座”下单。
- J3：G–S–G 线焊接备用孔，间距 2.54 mm、孔径 0.9 mm。可作为外购 SMA 不匹配时的短线连接位置；默认 DNP，不需要购买排针。不能让 J2 和 J3 同时连接两个驱动源。
- 核心 SW2 及底板 J3、C101、C103 默认 DNP。核心 J1 是板边半孔结构，不是采购连接器；M1 是已制成的核心模块。

## 文件与检查范围

每份 Gerber ZIP 包含 2 个铜层、2 个阻焊层、2 个丝印层、1 个矩形外框及独立 PTH/NPTH Excellon 文件。外框扩展名为 `.gm1`；空 NPTH 文件在核心板上正常。USB 长孔保留在 PTH 的铣槽指令中，不能仅按圆孔解释。

`cam-readback-audit.json` 已独立回读并比对板框、所有圆孔/长孔、元件铜焊盘中心、核心半孔位置和冻结源哈希。该检查不等于完整 CAM 铜连通性提取，不证明 USB 信号完整性、模拟峰值保持误差、脉冲堆积性能或已测能量分辨率。新版接线合同需要配套固件，旧版 v0.8.x 固件不能视作直接验证。

## English manufacturing summary

**NOT_FOR_FAB — engineering prototype export, pending release gates and bench validation.** Manufacture the 26 × 20 mm core and the 60 × 32 mm carrier separately, both as 1.6 mm two-layer FR-4 boards. Specify plated castellations for the core: 22 nominal 0.8 mm plated holes centered exactly on its two long board edges, 11 per edge at 2 mm pitch. Do not shift these holes inward or remove their wall plating. The intentional edge intersections apply only to these 22 pads; all other edge rules remain active.

The carrier has two plated USB shell slots and two nonplated USB locating holes. Use both Excellon files and preserve routed slots. Match the actual purchased USB-A male and vertical five-pin SMA connectors against the footprint dimensions before ordering. The SMA ground pins form a 5.08 mm square; optional G–S–G wire pads are provided.

Mount the assembled core top-side up, LEDs/BOOT towards the USB side, pin 1 to pin 1. The two long rows are not mirror images. This package is for hand assembly; no stencil layers are included. Fine-pitch LQFP/MSOP and 0402 passives require careful magnified assembly. Native DRC, prototype electrical checks, firmware compatibility and measured analog performance are separate acceptance steps.
