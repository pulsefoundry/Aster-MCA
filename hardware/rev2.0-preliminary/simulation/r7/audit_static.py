#!/usr/bin/env python3
"""Independent board/manifest/net audit for Aster MCA v2 r8.

Run with KiCad's bundled Python so pcbnew is available.  The script does not
modify the design; it compares the routed board against the generated manifest
and checks the current gain/switch and critical power/clock invariants explicitly.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pcbnew


HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOARD_PATH = ROOT / "source" / "Aster-MCA-v2.0.kicad_pcb"
MANIFEST_PATH = ROOT / "reference" / "parts-manifest.json"
OUTPUT_PATH = HERE / "results" / "static-audit.json"


def pad_map(footprint: object) -> dict[str, str]:
    result: dict[str, str] = {}
    for pad in footprint.Pads():
        number = str(pad.GetNumber())
        if not number:
            continue
        net = str(pad.GetNetname())
        if number in result and result[number] != net:
            raise ValueError(
                f"{footprint.GetReference()} has duplicate pad {number} on "
                f"different nets: {result[number]} and {net}"
            )
        result[number] = net
    return result


def main() -> int:
    board = pcbnew.LoadBoard(str(BOARD_PATH))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    footprints = {str(fp.GetReference()): fp for fp in board.GetFootprints()}
    board_refs = set(footprints)
    manifest_refs = set(manifest)
    failures: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []

    missing = sorted(manifest_refs - board_refs)
    extra = sorted(board_refs - manifest_refs)
    if missing:
        failures.append(f"manifest references missing from PCB: {missing}")
    else:
        passed.append("all manifest references are present on the PCB")
    if extra:
        failures.append(f"unexpected non-mechanical PCB references: {extra}")
    else:
        passed.append("PCB has no unexpected references")

    checked_pins = 0
    for ref in sorted(manifest_refs & board_refs):
        expected = manifest[ref]
        footprint = footprints[ref]
        actual_value = str(footprint.GetValue())
        if actual_value != expected["value"]:
            failures.append(
                f"{ref} value mismatch: PCB={actual_value!r}, manifest={expected['value']!r}"
            )
        actual_dnp = bool(footprint.IsDNP())
        if actual_dnp != bool(expected.get("dnp", False)):
            failures.append(
                f"{ref} DNP mismatch: PCB={actual_dnp}, manifest={expected.get('dnp')}"
            )
        actual_pins = pad_map(footprint)
        expected_pins = {
            str(number): net
            for number, net in expected["pins"].items()
            if str(number)
        }
        for number, net in expected_pins.items():
            checked_pins += 1
            if actual_pins.get(number, "") != net:
                failures.append(
                    f"{ref}.{number} net mismatch: PCB={actual_pins.get(number)!r}, manifest={net!r}"
                )
        unexpected_numbers = sorted(set(actual_pins) - set(expected_pins))
        if unexpected_numbers:
            failures.append(f"{ref} has unexpected numbered pads: {unexpected_numbers}")

    if not any("value mismatch" in item for item in failures):
        passed.append("all PCB values match the current design manifest")
    if not any("DNP mismatch" in item for item in failures):
        passed.append("all PCB DNP attributes match the current design manifest")
    if not any("net mismatch" in item or "unexpected numbered pads" in item for item in failures):
        passed.append(f"all {checked_pins} numbered pad/net assignments match the current design manifest")

    def require_pin(ref: str, number: str, net: str, description: str) -> None:
        actual = pad_map(footprints[ref]).get(number, "")
        if actual == net:
            passed.append(description)
        else:
            failures.append(
                f"{description}: expected {ref}.{number}={net}, found {actual}"
            )

    # Critical manufacturer-pin invariants already checked against the
    # datasheets in candidate-r4; assert their current routed nets again.
    for number, net, description in (
        ("1", "3V3_RAW", "AP63203 FB senses the fixed 3.3 V output"),
        ("2", "5V_FUSED", "AP63203 EN is tied to the fused 5 V input"),
        ("3", "5V_FUSED", "AP63203 VIN uses the fused 5 V input"),
        ("4", "GND", "AP63203 ground pin is grounded"),
        ("5", "BUCK_SW", "AP63203 SW drives only the buck switch node"),
        ("6", "BUCK_BST", "AP63203 BST uses the bootstrap node"),
    ):
        require_pin("U4", number, net, description)

    for number, net, description in (
        ("1", "FDA_INN", "THS4551 inverting input uses FDA_INN"),
        ("2", "ADC_VCM", "THS4551 VOCM is driven by ADS5560 VCM"),
        ("3", "5VA", "THS4551 positive supply uses filtered 5VA"),
        ("4", "FDA_OUTP", "THS4551 OUT+ uses FDA_OUTP"),
        ("5", "FDA_OUTN", "THS4551 OUT- uses FDA_OUTN"),
        ("6", "GND", "THS4551 negative supply is grounded"),
        ("7", "FDA_PD", "THS4551 PD has its dedicated pull-up net"),
        ("8", "FDA_INP", "THS4551 noninverting input uses FDA_INP"),
    ):
        require_pin("U3", number, net, description)

    switch_expected = {
        "1": "GAIN_H_SIG",
        "2": "GAIN_M_SIG",
        "3": "GAIN_SRC",
        "4": "GAIN_L_SIG",
        "5": "GAIN_H_GND",
        "6": "GAIN_M_GND",
        "7": "GND",
        "8": "GAIN_L_GND",
    }
    if pad_map(footprints["SW1"]) == switch_expected:
        passed.append("DP3T gain switch pad/net map matches the current design table")
    else:
        failures.append("DP3T gain switch pad/net map does not match the current design table")

    resistor_pins = {ref: pad_map(footprints[ref]) for ref in ("R2", "R3", "R4", "R5", "R6", "R7", "R8", "R46", "R47")}
    required_resistors = {
        "R2": {"1": "PMT_IN", "2": "AFE_IN"},
        "R3": {"1": "GAIN_H_SIG", "2": "FDA_INN"},
        "R4": {"1": "GAIN_H_GND", "2": "FDA_INP"},
        "R5": {"1": "GAIN_L_SIG", "2": "FDA_INN"},
        "R6": {"1": "GAIN_L_GND", "2": "FDA_INP"},
        "R7": {"1": "FDA_OUTP", "2": "FDA_INN"},
        "R8": {"1": "FDA_OUTN", "2": "FDA_INP"},
        "R46": {"1": "GAIN_M_SIG", "2": "FDA_INN"},
        "R47": {"1": "GAIN_M_GND", "2": "FDA_INP"},
    }
    if resistor_pins == required_resistors:
        passed.append("all three gain ranges connect to the intended THS4551 feedback arms")
    else:
        failures.append("gain-range resistor network connectivity mismatch")

    gains = {
        "0p5x_signal": 2000.0 / (78.7 + 3920.0),
        "0p5x_reference": 2000.0 / 4000.0,
        "5x_signal": 2000.0 / (78.7 + 324.0),
        "5x_reference": 2000.0 / 402.0,
        "25x_signal": 2000.0 / 78.7,
        "25x_reference": 2000.0 / 78.7,
    }
    gains["0p5x_arm_mismatch_percent"] = (
        abs(gains["0p5x_signal"] - gains["0p5x_reference"])
        / gains["0p5x_reference"]
        * 100.0
    )
    gains["5x_arm_mismatch_percent"] = (
        abs(gains["5x_signal"] - gains["5x_reference"])
        / gains["5x_reference"]
        * 100.0
    )
    gains["25x_arm_mismatch_percent"] = 0.0
    if gains["5x_arm_mismatch_percent"] < 0.2:
        passed.append("worst nominal gain-arm mismatch is below 0.2%")
    else:
        failures.append("gain-arm mismatch is 0.2% or greater")

    # Clock and ADC output routing invariants.
    critical_nets = {
        "C9": {"1": "ADC_CLKM", "2": "GND"},
        "C10": {"1": "CLK40_RAW", "2": "ADC_CLKP"},
        "R15": {"1": "CLK40_RAW", "2": "FPGA_REFCLK"},
        "R16": {"1": "ADC_CLKOUT", "2": "FPGA_ADCCLK"},
        "R9": {"1": "FDA_OUTP", "2": "ADC_INM"},
        "R10": {"1": "FDA_OUTN", "2": "ADC_INP"},
        "C2": {"1": "ADC_INP", "2": "ADC_INM"},
    }
    for ref, expected in critical_nets.items():
        if pad_map(footprints[ref]) == expected:
            passed.append(f"critical interface component {ref} has the intended net map")
        else:
            failures.append(f"critical interface component {ref} net map mismatch")

    copper_layers = int(board.GetCopperLayerCount())
    if copper_layers == 4:
        passed.append("board has four copper layers")
    else:
        failures.append(f"expected four copper layers, found {copper_layers}")

    if not failures:
        status = "PASS"
    else:
        status = "FAIL"
    warnings.extend(
        [
            "Quartus pin legality and timing are not proven until the exact MAX 10 project compiles.",
            "ADS5560 switched-capacitor input and quantisation are not represented by the analogue macro-model.",
            "Purchased JS203011AQN switch continuity and physical slider order still require bench confirmation.",
        ]
    )
    report = {
        "status": status,
        "board": BOARD_PATH.relative_to(ROOT).as_posix(),
        "manifest": MANIFEST_PATH.relative_to(ROOT).as_posix(),
        "passed": passed,
        "warnings": warnings,
        "failures": failures,
        "metrics": {
            "manifest_parts": len(manifest_refs),
            "pcb_footprints": len(board_refs),
            "numbered_pins_checked": checked_pins,
            "copper_layers": copper_layers,
            "nominal_gains": gains,
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
