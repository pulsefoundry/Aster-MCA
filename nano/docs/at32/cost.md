# AT32 单板成本 / Single-board cost

**已知价格合计 ¥17.86 / Priced subtotal CNY 17.86**，另加 USB-A、SMA 和两颗 LED 的实际成本。完整单板总价尚不能确定。

口径：2026-10-21 整理，按当前实测的 AT32 v0.3 改焊板计算：R21 = 40.2 kΩ、R22 = 10 kΩ，U1 为 AT32F423CCT7。39 个实装位号，另计 1 块 PCB。

| 项目 / Item | 单板金额 / CNY per board |
|---|---:|
| PCB，用户给定价格 / Owner-specified PCB price | 4.00 |
| AT32，用户给定价格 / Owner-specified MCU price | 5.00 |
| 其余有报价元件 / Other priced components | 8.855465 |
| **已知价格合计 / Priced subtotal** | **17.855465** |
| J1 USB-A、J2 SMA、LED1/LED2 | 未计价 / Unpriced |

BOM 单价取自 2026-10-10 的立创报价，沿用当时采购数量对应的单价，乘以单板实际用量；不把最低起订量、备件和库存余料分摊到一块板，也不以整单金额除以套数。PCB 和 MCU 按本次用户给定的 ¥4、¥5 覆盖。

USB-A、SMA 是外购件，LED 为已有库存，实际购入价格未提供；空缺不代表价格为零。原报价里的进口接头型号没有用于实装成本。未计运费、优惠券、焊接人工、设备、外壳、探头及其高压/前置放大器。手焊不产生贴片加工费。

The priced subtotal is **not a complete assembled-board price**. Add the actual externally sourced USB-A and SMA connectors and two stock LEDs. Missing prices remain unknown. Historical quoted unit prices are multiplied by fitted single-board quantities; minimum-order purchases, spares and leftover inventory are not charged entirely to one board. Shipping, coupons, assembly labour, tools, enclosure and the detector/preamplifier/HV supply are excluded. These are historical project costs, not current market quotations.

## 明细 / Itemized calculation

| 位号 / Refs | 型号或规格 / Part | 立创 / LCSC | 数量 / Qty | 单价 / CNY | 金额 / CNY | 来源 / Source |
|---|---|---|---:|---:|---:|---|
| PCB | AT32 PCB, 32 x 18 mm, 1.6 mm | — | 1 | 4 | 4 | 用户指定 / Owner |
| U1 | AT32F423CCT7 | — | 1 | 5 | 5 | 用户指定 / Owner |
| U3 | TLV9061IDBVR | [C398358](https://item.szlcsc.com/380588.html) | 1 | 0.5708 | 0.5708 | 报价第 9 行 / quote row 9 |
| U2 | XC6206P332MR-G | [C5446](https://item.szlcsc.com/5896.html) | 1 | 0.8768 | 0.8768 | 报价第 10 行 / quote row 10 |
| D1 | USBLC6-2SC6 | [C7519](https://item.szlcsc.com/7996.html) | 1 | 1.0864 | 1.0864 | 报价第 11 行 / quote row 11 |
| D2 | BAT54S,235 | [C503463](https://item.szlcsc.com/516159.html) | 1 | 0.1707 | 0.1707 | 报价第 12 行 / quote row 12 |
| SW1 | B3U-1000P | [C231329](https://item.szlcsc.com/231216.html) | 1 | 1.1469 | 1.1469 | 报价第 13 行 / quote row 13 |
| R19 | FRC0402F0000TS | [C2906858](https://item.szlcsc.com/3180371.html) | 1 | 0.008265 | 0.008265 | 报价第 16 行 / quote row 16 |
| R20 | ERJ2RKF1000X | [C413063](https://item.szlcsc.com/405058.html) | 1 | 0.0342 | 0.0342 | 报价第 17 行 / quote row 17 |
| R7, R22 | TNPW040210K0BEED | [C844452](https://item.szlcsc.com/904026.html) | 2 | 0.4545 | 0.9090 | 报价第 18 行 / quote row 18 |
| R16, R17, R18 | ERJ2RKF1002X | [C191123](https://item.szlcsc.com/213966.html) | 3 | 0.0284 | 0.0852 | 报价第 19 行 / quote row 19 |
| R5 | CRCW04021M00FKED | [C482082](https://item.szlcsc.com/490008.html) | 1 | 0.0254 | 0.0254 | 报价第 20 行 / quote row 20 |
| R13, R14 | TNPW04021K00BEED | [C843869](https://item.szlcsc.com/903443.html) | 2 | 0.4135 | 0.8270 | 报价第 21 行 / quote row 21 |
| R6, R21 | TNPW040240K2BEED | [C2088750](https://item.szlcsc.com/2180341.html) | 2 | 0.6237 | 1.2474 | 报价第 22 行 / quote row 22 |
| R1, R2 | 0603WAF1001T5E | [C21190](https://item.szlcsc.com/21904.html) | 2 | 0.0154 | 0.0308 | 报价第 29 行 / quote row 29 |
| C3, C8, C10, C11, C12, C13, C15, C17 | CGA0402X7R104K100GT | [C22435935](https://item.szlcsc.com/24066916.html) | 8 | 0.014 | 0.112 | 报价第 31 行 / quote row 31 |
| C16 | 0402CG101J500NT | [C1546](https://item.szlcsc.com/1898.html) | 1 | 0.0255 | 0.0255 | 报价第 32 行 / quote row 32 |
| C9 | CL05C102JB5NNNC | [C307441](https://item.szlcsc.com/291115.html) | 1 | 0.0557 | 0.0557 | 报价第 33 行 / quote row 33 |
| C14 | FCC0402B105K100AT | [C54938484](https://item.szlcsc.com/58499306.html) | 1 | 0.0618 | 0.0618 | 报价第 34 行 / quote row 34 |
| C1 | 0603B105K100NT | [C167338](https://item.szlcsc.com/178721.html) | 1 | 0.1521 | 0.1521 | 报价第 37 行 / quote row 37 |
| C2 | TCC0603X7R475K100CT | [C18185770](https://item.szlcsc.com/19332544.html) | 1 | 0.1333 | 0.1333 | 报价第 38 行 / quote row 38 |
| C7 | CC0805KKX7R6BB106 | [C1952580](https://item.szlcsc.com/2044114.html) | 1 | 0.5728 | 0.5728 | 报价第 40 行 / quote row 40 |
| C4 | C2012C0G1H333JT000N | [C76628](https://item.szlcsc.com/77755.html) | 1 | 0.7234 | 0.7234 | 报价第 41 行 / quote row 41 |
| J1 | Externally sourced USB-A male | — | 1 | 未知 / Unknown | 未知 / Unknown | 外购或库存 / External or stock |
| J2 | Externally sourced SMA female | — | 1 | 未知 / Unknown | 未知 / Unknown | 外购或库存 / External or stock |
| LED1, LED2 | Existing blue 0603 LED stock, Vf 2.5-3 V | — | 2 | 未知 / Unknown | 未知 / Unknown | 外购或库存 / External or stock |

## 复算和来源 / Reproduction and source

[价格输入 JSON](cost-inputs.json) 保存逐项原单价、报价行号、立创料号和商品链接。原报价为 `Aster-MCA-Nano-5套-合并采购清单-立创_20261010.xls`，工作表 `sheet`，AD 列（单价/RMB）；文件 SHA256 为 `9383b34d6d809e52df711a8ac7147cf0142432ffb269a085d248d30e5a42a9be`。公开的摘录只含所需物料数据，原 XLS 没有上传。

The public JSON records the source worksheet row and original unit price for each component. R21 now uses the same part as R6, and R22 uses the same part as R7. The original v0.3 BOM remains unchanged as fabrication history; this calculation applies the documented gain rework.

在仓库根目录运行 / Run from the repository root:

```sh
python3 scripts/calculate_at32_cost.py --check
```

按完整精度先汇总，最后四舍五入到分；明细保留报价原精度。 / Sum at full precision, then round the subtotal to two decimal places.
