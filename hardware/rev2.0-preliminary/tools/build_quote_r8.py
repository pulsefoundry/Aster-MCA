#!/usr/bin/env python3
"""Build quote-only JLC-style BOM/CPL files from the current r8 manifest."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "reference" / "parts-manifest.json"
OUT = ROOT / "production" / "quote-r8-current-source"

# Exact purchasable bindings used only for quotation.  They do not authorize
# substitutes and do not change the electrical design.
PART_BINDINGS = {
    "C2": ("GCM1885C1H222JA16D", "C343869"),
    "C38": ("CL05B104KO5NNNC", "C1525"),
    "RN1": ("RTA03-4D330JTP", "C102663"),
    "RN2": ("RTA03-4D330JTP", "C102663"),
    "RN3": ("RTA03-4D330JTP", "C102663"),
    "RN4": ("RTA03-4D330JTP", "C102663"),
    "U1": ("10M16SAE144C8G", "C1521931"),
    "U2": ("ADS5560IRGZT", "C571255"),
    "U3": ("THS4551IDGKT", "C2860660"),
    "U4": ("AP63203WU-7", "C780769"),
    "Y1": ("ASE-40.000MHZ-L-C-T", "C1670009"),
}


def is_100n_0603(part: dict) -> bool:
    return part["value"] == "100n" and "0603" in part["footprint"]


def is_core(ref: str, part: dict) -> bool:
    fp = part.get("footprint", "")
    return (
        "0402" in fp
        or "0603" in fp
        or ref.startswith("RN")
        or ref in {"U1", "U2", "U3", "U4", "Y1"}
    )


def binding(ref: str, part: dict) -> tuple[str, str]:
    if ref in PART_BINDINGS:
        return PART_BINDINGS[ref]
    if is_100n_0603(part):
        return "CC0603KPX7R8BB104", "C1853266"
    return part.get("mpn", ""), part.get("lcsc", "")


def write_bom(path: Path, refs: list[str], manifest: dict[str, dict]) -> None:
    groups: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for ref in refs:
        part = manifest[ref]
        mpn, lcsc = binding(ref, part)
        key = (part["value"], part["footprint"], lcsc, mpn)
        groups[key].append(ref)

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Comment",
                "Designator",
                "Footprint",
                "LCSC Part #",
                "Manufacturer Part Number",
                "Qty",
            ]
        )
        for (value, footprint, lcsc, mpn), designators in sorted(
            groups.items(), key=lambda item: item[1][0]
        ):
            writer.writerow(
                [value, ",".join(designators), footprint, lcsc, mpn, len(designators)]
            )


def write_cpl(path: Path, refs: list[str], manifest: dict[str, dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref in refs:
            part = manifest[ref]
            writer.writerow(
                [
                    ref,
                    f"{part['x']:.3f}mm",
                    f"{part['y']:.3f}mm",
                    "Top",
                    f"{part['rotation'] % 360:.1f}",
                ]
            )


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)

    all_smt = sorted(
        ref
        for ref, part in manifest.items()
        if part.get("assembly") == "SMT"
        and not part.get("dnp")
        and not ref.startswith("H")
    )
    core_smt = [ref for ref in all_smt if is_core(ref, manifest[ref])]

    write_bom(OUT / "Aster-MCA-v2.0-r8-BOM-core-SMT.csv", core_smt, manifest)
    write_cpl(OUT / "Aster-MCA-v2.0-r8-CPL-core-SMT.csv", core_smt, manifest)
    write_bom(OUT / "Aster-MCA-v2.0-r8-BOM-all-SMT.csv", all_smt, manifest)
    write_cpl(OUT / "Aster-MCA-v2.0-r8-CPL-all-SMT.csv", all_smt, manifest)

    print(f"core SMT placements: {len(core_smt)}")
    print(f"all SMT placements: {len(all_smt)}")


if __name__ == "__main__":
    main()
