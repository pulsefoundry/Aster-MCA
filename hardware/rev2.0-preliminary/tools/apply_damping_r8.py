#!/usr/bin/env python3
"""Apply the r8 output-damping value fix without changing placement or nets."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMATIC = ROOT / "source" / "Aster-MCA-v2.0.kicad_sch"
BOARD = ROOT / "source" / "Aster-MCA-v2.0.kicad_pcb"
MANIFEST = ROOT / "reference" / "parts-manifest.json"
BOM = ROOT / "reference" / "BOM-preliminary.csv"


def replace_exact(path: Path, old: str, new: str, expected_count: int) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected_count:
        raise RuntimeError(
            f"{path}: expected {expected_count} occurrences of {old!r}, found {count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def update_manifest() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for reference in ("R9", "R10"):
        if data[reference]["value"] != "10R 1%":
            raise RuntimeError(
                f"{reference}: expected old value 10R 1%, found {data[reference]['value']}"
            )
        data[reference]["value"] = "22R 1%"
        data[reference]["notes"] = (
            "ADC-driver output isolation; r8 value selected by THS4551 transient/AC damping sweep"
        )
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def update_bom() -> None:
    with BOM.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
        fieldnames = list(rows[0])
    matches = [row for row in rows if row["Designator"] == "R9, R10"]
    if len(matches) != 1 or matches[0]["Value"] != "10R 1%":
        raise RuntimeError("reference BOM does not contain the expected R9/R10 row")
    matches[0]["Value"] = "22R 1%"
    matches[0]["Notes"] = (
        "ADC-driver damping; use 22 ohm on both arms (r8 simulation fix)"
    )
    with BOM.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    replace_exact(SCHEMATIC, '"10R 1%"', '"22R 1%"', 4)
    replace_exact(BOARD, '"10R 1%"', '"22R 1%"', 2)
    update_manifest()
    update_bom()
    print("r8 damping fix applied: R9 = R10 = 22R 1%; nets and placement unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
