"""Recalculate the populated AT32 board cost from the published price inputs."""
import argparse
from decimal import Decimal
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'docs/at32/cost-inputs.json'
REPORT = ROOT / 'docs/at32/cost.md'


def render():
    data = json.loads(INPUT.read_text())
    known = data['priced_items']
    unknown = data['unpriced_items']
    all_refs = []
    total = Decimal(0)
    for item in known + unknown:
        assert item['quantity'] == len(item['references'])
        all_refs.extend(item['references'])
        price = item['unit_rmb']
        if price is not None:
            assert Decimal(price) >= 0
            total += Decimal(price) * item['quantity']
    assert len(all_refs) == len(set(all_refs)) == 40  # 39 fitted refs + PCB
    others = total - Decimal('9')
    lines = [
        '# AT32 单板成本 / Single-board cost', '',
        f'**已知价格合计 ¥{total:.2f} / Priced subtotal CNY {total:.2f}**，另加 USB-A、SMA 和两颗 LED 的实际成本。完整单板总价尚不能确定。', '',
        '口径：2026-10-21 整理，按当前实测的 AT32 v0.3 改焊板计算：R21 = 40.2 kΩ、R22 = 10 kΩ，U1 为 AT32F423CCT7。39 个实装位号，另计 1 块 PCB。', '',
        '| 项目 / Item | 单板金额 / CNY per board |',
        '|---|---:|',
        '| PCB，用户给定价格 / Owner-specified PCB price | 4.00 |',
        '| AT32，用户给定价格 / Owner-specified MCU price | 5.00 |',
        f'| 其余有报价元件 / Other priced components | {others:.6f} |',
        f'| **已知价格合计 / Priced subtotal** | **{total:.6f}** |',
        '| J1 USB-A、J2 SMA、LED1/LED2 | 未计价 / Unpriced |', '',
        'BOM 单价取自 2026-10-10 的立创报价，沿用当时采购数量对应的单价，乘以单板实际用量；不把最低起订量、备件和库存余料分摊到一块板，也不以整单金额除以套数。PCB 和 MCU 按本次用户给定的 ¥4、¥5 覆盖。', '',
        'USB-A、SMA 是外购件，LED 为已有库存，实际购入价格未提供；空缺不代表价格为零。原报价里的进口接头型号没有用于实装成本。未计运费、优惠券、焊接人工、设备、外壳、探头及其高压/前置放大器。手焊不产生贴片加工费。', '',
        'The priced subtotal is **not a complete assembled-board price**. Add the actual externally sourced USB-A and SMA connectors and two stock LEDs. Missing prices remain unknown. Historical quoted unit prices are multiplied by fitted single-board quantities; minimum-order purchases, spares and leftover inventory are not charged entirely to one board. Shipping, coupons, assembly labour, tools, enclosure and the detector/preamplifier/HV supply are excluded. These are historical project costs, not current market quotations.', '',
        '## 明细 / Itemized calculation', '',
        '| 位号 / Refs | 型号或规格 / Part | 立创 / LCSC | 数量 / Qty | 单价 / CNY | 金额 / CNY | 来源 / Source |',
        '|---|---|---|---:|---:|---:|---|',
    ]
    for item in known:
        refs = ', '.join(item['references'])
        price = Decimal(item['unit_rmb'])
        part = item.get('mpn', item['description'])
        code = item.get('lcsc', '—')
        if item.get('url'):
            code = f"[{code}]({item['url']})"
        source = f"报价第 {item['source_row']} 行 / quote row {item['source_row']}" if 'source_row' in item else '用户指定 / Owner'
        lines.append(f"| {refs} | {part} | {code} | {item['quantity']} | {price:f} | {price * item['quantity']:f} | {source} |")
    for item in unknown:
        lines.append(f"| {', '.join(item['references'])} | {item['description']} | — | {item['quantity']} | 未知 / Unknown | 未知 / Unknown | 外购或库存 / External or stock |")
    lines += ['',
        '## 复算和来源 / Reproduction and source', '',
        '[价格输入 JSON](cost-inputs.json) 保存逐项原单价、报价行号、立创料号和商品链接。原报价为 `'+data['quotation_file']+'`，工作表 `sheet`，AD 列（单价/RMB）；文件 SHA256 为 `'+data['quotation_sha256']+'`。公开的摘录只含所需物料数据，原 XLS 没有上传。', '',
        'The public JSON records the source worksheet row and original unit price for each component. R21 now uses the same part as R6, and R22 uses the same part as R7. The original v0.3 BOM remains unchanged as fabrication history; this calculation applies the documented gain rework.', '',
        '在仓库根目录运行 / Run from the repository root:', '',
        '```sh', 'python3 scripts/calculate_at32_cost.py --check', '```', '',
        '按完整精度先汇总，最后四舍五入到分；明细保留报价原精度。 / Sum at full precision, then round the subtotal to two decimal places.', '',
    ]
    return '\n'.join(lines), total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify the published report without writing')
    args = parser.parse_args()
    report, total = render()
    if args.check:
        if REPORT.read_text() != report:
            raise SystemExit('Cost report differs from price inputs; run without --check to regenerate')
    else:
        REPORT.write_text(report)
    print(f'AT32: CNY {total:.6f} priced subtotal ({total:.2f} rounded), plus unpriced connectors and LEDs')


if __name__ == '__main__':
    main()
