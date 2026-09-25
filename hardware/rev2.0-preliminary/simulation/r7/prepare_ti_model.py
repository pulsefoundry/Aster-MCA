#!/usr/bin/env python3
"""Prepare TI's THS4551 PSpice macro-model for KiCad's ngspice build.

TI's model contains three PSpice ``TABLE`` controlled sources.  The PSpice
compatibility translator in the KiCad ngspice build turns those sources into
XSPICE code models that are not present in that build.  This script performs a
small, auditable syntax translation to native behavioural PWL sources.  The
electrical table points are copied without alteration.

The vendor model itself is deliberately not stored in this repository.  Fetch
SBOMB92B.ZIP from TI, extract ``ths4551.lib``, then pass it to this script.
"""

from __future__ import annotations

import argparse
import pathlib
import re


HEADER = re.compile(
    r"^(?P<kind>[GE])(?P<name>\S*)\s+"
    r"(?P<nplus>\S+)\s+(?P<nminus>\S+)\s+"
    r"TABLE\s+\{\((?P<expr>.+)\)\}\s*=\s*$",
    re.IGNORECASE,
)
POINT = re.compile(
    r"^\+\s*\(\s*(?P<x>[^,]+)\s*,\s*(?P<y>[^)]+)\s*\)\s*$"
)


def _spice_number(value: str) -> float:
    """Parse the plain decimal/scientific thresholds used by this TI model."""
    return float(value)


def _replace_switch_thresholds(line: str) -> str:
    """Convert PSpice ON/OFF thresholds to ngspice centre/hysteresis form."""
    pairs = (("VON", "VOFF", "VT", "VH"), ("ION", "IOFF", "IT", "IH"))
    for on_name, off_name, centre_name, hysteresis_name in pairs:
        on_match = re.search(
            rf"\b{on_name}\s*=\s*([-+0-9.eE]+)", line, re.IGNORECASE
        )
        off_match = re.search(
            rf"\b{off_name}\s*=\s*([-+0-9.eE]+)", line, re.IGNORECASE
        )
        if on_match is None and off_match is None:
            continue
        if on_match is None or off_match is None:
            raise ValueError(f"incomplete switch thresholds: {line}")
        on_value = _spice_number(on_match.group(1))
        off_value = _spice_number(off_match.group(1))
        centre = (on_value + off_value) / 2.0
        hysteresis = (on_value - off_value) / 2.0
        line = re.sub(
            rf"\s*\b{on_name}\s*=\s*[-+0-9.eE]+", "", line,
            flags=re.IGNORECASE,
        )
        line = re.sub(
            rf"\s*\b{off_name}\s*=\s*[-+0-9.eE]+", "", line,
            flags=re.IGNORECASE,
        )
        insertion = f" {centre_name}={centre:.12g} {hysteresis_name}={hysteresis:.12g}"
        if line.rstrip().endswith(")"):
            stripped = line.rstrip()
            line = stripped[:-1] + insertion + ")"
        else:
            line += insertion
    return line


def translate(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    output: list[str] = []
    translated = 0
    index = 0
    while index < len(lines):
        match = HEADER.match(lines[index].strip())
        if match is None:
            line = re.sub(
                r"(\.MODEL\s+\S+\s+)VSWITCH\b", r"\1SW", lines[index],
                flags=re.IGNORECASE,
            )
            line = re.sub(
                r"(\.MODEL\s+\S+\s+)ISWITCH\b", r"\1CSW", line,
                flags=re.IGNORECASE,
            )
            line = _replace_switch_thresholds(line)
            # PSpice exposes TEMP in expressions; ngspice calls the current
            # circuit temperature ``temper``.
            line = re.sub(r"\bTEMP\b", "temper", line, flags=re.IGNORECASE)
            output.append(line)
            index += 1
            continue

        points: list[tuple[str, str]] = []
        cursor = index + 1
        while cursor < len(lines):
            point = POINT.match(lines[cursor].strip())
            if point is None:
                break
            points.append((point.group("x").strip(), point.group("y").strip()))
            cursor += 1
        if len(points) < 2:
            raise ValueError(f"TABLE source on line {index + 1} has too few points")

        quantity = "I" if match.group("kind").upper() == "G" else "V"
        pairs = ", ".join(f"{x}, {y}" for x, y in points)
        output.append(
            f"B{match.group('name')} {match.group('nplus')} {match.group('nminus')} "
            f"{quantity}=pwl(({match.group('expr')}), {pairs})"
        )
        output.append(
            "* ngspice compatibility: preceding PWL is a syntax-only translation "
            "of the TI PSpice TABLE source"
        )
        translated += 1
        index = cursor

    return "\n".join(output) + "\n", translated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    args = parser.parse_args()
    original = args.input.read_text(encoding="utf-8", errors="replace")
    converted, count = translate(original)
    if count != 3:
        raise SystemExit(f"expected 3 TABLE sources, translated {count}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(converted, encoding="utf-8")
    print(f"translated {count} PSpice TABLE sources: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
