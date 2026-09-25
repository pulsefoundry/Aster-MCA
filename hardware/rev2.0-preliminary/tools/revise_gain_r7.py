#!/usr/bin/env python3
"""Create the r7 three-range AFE revision from the checked r6 sources.

This script is intentionally project-specific.  It edits the generated flat
KiCad schematic and uses KiCad's pcbnew Python API for footprint, net and track
changes.  Run it with KiCad's bundled Python interpreter.
"""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import wx

# KiCad's footprint-library loader needs a wx application context even when
# this script is run headlessly from the command line.
WX_APP = wx.App(False)

import pcbnew


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source"
REFERENCE = ROOT / "reference"
SCHEMATIC = SOURCE / "Aster-MCA-v2.0.kicad_sch"
BOARD = SOURCE / "Aster-MCA-v2.0.kicad_pcb"
FOOTPRINT_DIR = SOURCE / "footprints" / "Aster_Production.pretty"
SWITCH_FP_NAME = "Button_Switch_THT__SW_CK_JS203011AQN_DP3T_Angled__AsterProd"
RESISTOR_FP_NAME = "Resistor_SMD__R_0805_2012Metric_Pad1.20x1.40mm_HandSolder__AsterProd"
PROJECT_PATH = "/6b4d6acb-c308-5b13-83b9-f67d5dd533ab"


def stable_uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "https://aster-mca.local/r7/" + name))


def matching_paren(text: str, start: int) -> int:
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError(f"unbalanced s-expression at byte {start}")


def replace_block(text: str, marker: str, replacement: str, *, start_at: int = 0) -> str:
    start = text.index(marker, start_at)
    end = matching_paren(text, start)
    return text[:start] + replacement + text[end:]


def remove_label_at(text: str, name: str, x: str, y: str) -> str:
    marker = f'(global_label "{name}"'
    cursor = 0
    while True:
        start = text.find(marker, cursor)
        if start < 0:
            raise ValueError(f"label not found: {name} at {x},{y}")
        end = matching_paren(text, start)
        block = text[start:end]
        if f"(at {x} {y} " in block:
            return text[:start] + text[end:]
        cursor = end


def label(name: str, x: float, y: float, key: str) -> str:
    return (
        f'(global_label "{name}" (shape input) (at {x:g} {y:g} 180) '
        f'(effects (font (size 0.9 0.9)) (justify right)) '
        f'(uuid "{stable_uuid("label-" + key)}"))'
    )


def resistor_lib(reference: str, value: str, pin1: str, pin2: str) -> str:
    return (
        f'(symbol "Aster:{reference}" (pin_names (offset 0.6)) (in_bom yes) (on_board yes) '
        f'(property "Reference" "R" (at 0 7.62 0) (effects (font (size 1.0 1.0)))) '
        f'(property "Value" "{value}" (at 0 -7.62 0) (effects (font (size 0.9 0.9)))) '
        f'(property "Footprint" "Aster_Production:{RESISTOR_FP_NAME}" (at 0 0 0) '
        f'(effects (font (size 1 1)) hide)) '
        f'(property "Datasheet" "" (at 0 0 0) (effects (font (size 1 1)) hide)) '
        f'(symbol "{reference}_0_1" (rectangle (start -12.7 5.08) (end 12.7 -5.08) '
        f'(stroke (width 0.254) (type default)) (fill (type background)))) '
        f'(symbol "{reference}_1_1" '
        f'(pin passive line (at -15.24 1.27 0) (length 2.54) '
        f'(name "{pin1}" (effects (font (size 0.8 0.8)))) '
        f'(number "1" (effects (font (size 0.8 0.8))))) '
        f'(pin passive line (at -15.24 -1.27 0) (length 2.54) '
        f'(name "{pin2}" (effects (font (size 0.8 0.8)))) '
        f'(number "2" (effects (font (size 0.8 0.8)))))))'
    )


def resistor_instance(reference: str, value: str, x: float, y: float) -> str:
    return (
        f'(symbol (lib_id "Aster:{reference}") (at {x:g} {y:g} 0) (unit 1) '
        f'(in_bom yes) (on_board yes) (dnp no) (uuid "{stable_uuid("symbol-" + reference)}") '
        f'(property "Reference" "{reference}" (at {x:g} {y - 9.08:g} 0) '
        f'(effects (font (size 0.9 0.9)))) '
        f'(property "Value" "{value}" (at {x:g} {y + 9.08:g} 0) '
        f'(effects (font (size 0.9 0.9)))) '
        f'(property "Footprint" "Aster_Production:{RESISTOR_FP_NAME}" (at {x:g} {y:g} 0) '
        f'(effects (font (size 0.9 0.9)) hide)) '
        f'(property "Datasheet" "" (at {x:g} {y:g} 0) '
        f'(effects (font (size 0.9 0.9)) hide)) '
        f'(pin "1" (uuid "{stable_uuid(reference + "-pin1")}")) '
        f'(pin "2" (uuid "{stable_uuid(reference + "-pin2")}")) '
        f'(instances (project "Aster-MCA-v2.0" '
        f'(path "{PROJECT_PATH}" (reference "{reference}") (unit 1)))))'
    )


def switch_lib() -> str:
    pin_names = [
        ("GAIN_H_SIG", "1", 8.89),
        ("GAIN_M_SIG", "2", 6.35),
        ("GAIN_SRC", "3", 3.81),
        ("GAIN_L_SIG", "4", 1.27),
        ("GAIN_H_GND", "5", -1.27),
        ("GAIN_M_GND", "6", -3.81),
        ("GND", "7", -6.35),
        ("GAIN_L_GND", "8", -8.89),
    ]
    pins = "".join(
        f'(pin passive line (at -15.24 {y:g} 0) (length 2.54) '
        f'(name "{name}" (effects (font (size 0.8 0.8)))) '
        f'(number "{number}" (effects (font (size 0.8 0.8)))))'
        for name, number, y in pin_names
    )
    return (
        f'(symbol "Aster:SW1" (pin_names (offset 0.6)) (in_bom yes) (on_board yes) '
        f'(property "Reference" "S" (at 0 15.24 0) (effects (font (size 1.0 1.0)))) '
        f'(property "Value" "GAIN 0.5x / 5x / 25x" (at 0 -15.24 0) '
        f'(effects (font (size 0.9 0.9)))) '
        f'(property "Footprint" "Aster_Production:{SWITCH_FP_NAME}" (at 0 0 0) '
        f'(effects (font (size 1 1)) hide)) '
        f'(property "Datasheet" '
        f'"https://www.littelfuse.com/assetdocs/littelfuse-ck-slide-js-series-datasheet?assetguid=aba42b08-0d2c-423b-813d-a2faa5a3bb14" '
        f'(at 0 0 0) (effects (font (size 1 1)) hide)) '
        f'(symbol "SW1_0_1" (rectangle (start -12.7 11.43) (end 12.7 -11.43) '
        f'(stroke (width 0.254) (type default)) (fill (type background)))) '
        f'(symbol "SW1_1_1" {pins}))'
    )


def switch_instance() -> str:
    x, y = 44.45, 80.01
    pins = "".join(
        f'(pin "{number}" (uuid "{stable_uuid("SW1-pin" + str(number))}")) '
        for number in range(1, 9)
    )
    return (
        f'(symbol (lib_id "Aster:SW1") (at {x:g} {y:g} 0) (unit 1) '
        f'(in_bom yes) (on_board yes) (dnp no) '
        f'(uuid "69dbb62c-cac4-5c32-a054-4469e0dd7183") '
        f'(property "Reference" "SW1" (at {x:g} 64.77 0) '
        f'(effects (font (size 0.9 0.9)))) '
        f'(property "Value" "GAIN 0.5x / 5x / 25x" (at {x:g} 95.25 0) '
        f'(effects (font (size 0.9 0.9)))) '
        f'(property "Footprint" "Aster_Production:{SWITCH_FP_NAME}" (at {x:g} {y:g} 0) '
        f'(effects (font (size 0.9 0.9)) hide)) '
        f'(property "Datasheet" '
        f'"https://www.littelfuse.com/assetdocs/littelfuse-ck-slide-js-series-datasheet?assetguid=aba42b08-0d2c-423b-813d-a2faa5a3bb14" '
        f'(at {x:g} {y:g} 0) (effects (font (size 0.9 0.9)) hide)) '
        f'{pins}(instances (project "Aster-MCA-v2.0" '
        f'(path "{PROJECT_PATH}" (reference "SW1") (unit 1)))))'
    )


def revise_schematic() -> None:
    text = SCHEMATIC.read_text(encoding="utf-8")
    if "GAIN 0.5x / 5x / 25x" in text or 'Aster:R46' in text:
        raise RuntimeError("schematic already appears to be r7")

    text = text.replace('"100R 0.1%"', '"78R7 0.1%"')
    text = text.replace('"3k90 0.1%"', '"3k92 0.1%"')

    lib_start = text.index("(lib_symbols")
    text = replace_block(text, '(symbol "Aster:SW1"', switch_lib(), start_at=lib_start)
    lib_start = text.index("(lib_symbols")
    lib_end = matching_paren(text, lib_start)
    additions = resistor_lib("R46", "324R 0.1%", "GAIN_M_SIG", "FDA_INN")
    additions += resistor_lib("R47", "402R 0.1%", "GAIN_M_GND", "FDA_INP")
    text = text[: lib_end - 1] + additions + text[lib_end - 1 :]

    old_switch = text.index('(symbol (lib_id "Aster:SW1")')
    text = replace_block(text, '(symbol (lib_id "Aster:SW1")', switch_instance(), start_at=old_switch)

    old_labels = [
        ("GAIN_H_SIG", "29.21", "73.66"),
        ("GAIN_SRC", "29.21", "76.2"),
        ("GAIN_L_SIG", "29.21", "78.74"),
        ("GAIN_H_GND", "29.21", "81.28"),
        ("GND", "29.21", "83.82"),
        ("GAIN_L_GND", "29.21", "86.36"),
    ]
    for name, x, y in old_labels:
        text = remove_label_at(text, name, x, y)

    # This generated flat schematic has no sheet_instances table.  Insert new
    # top-level labels and symbol instances immediately before embedded_fonts.
    sheet_marker = text.index("(embedded_fonts no)")
    switch_labels = "".join(
        [
            label("GAIN_H_SIG", 29.21, 71.12, "sw1-1"),
            label("GAIN_M_SIG", 29.21, 73.66, "sw1-2"),
            label("GAIN_SRC", 29.21, 76.2, "sw1-3"),
            label("GAIN_L_SIG", 29.21, 78.74, "sw1-4"),
            label("GAIN_H_GND", 29.21, 81.28, "sw1-5"),
            label("GAIN_M_GND", 29.21, 83.82, "sw1-6"),
            label("GND", 29.21, 86.36, "sw1-7"),
            label("GAIN_L_GND", 29.21, 88.9, "sw1-8"),
            label("GAIN_M_SIG", 191.77, 285.75, "r46-1"),
            label("FDA_INN", 191.77, 288.29, "r46-2"),
            label("GAIN_M_GND", 220.98, 285.75, "r47-1"),
            label("FDA_INP", 220.98, 288.29, "r47-2"),
        ]
    )
    new_symbols = resistor_instance("R46", "324R 0.1%", 207.01, 287.02)
    new_symbols += resistor_instance("R47", "402R 0.1%", 236.22, 287.02)
    text = text[:sheet_marker] + switch_labels + new_symbols + text[sheet_marker:]

    SCHEMATIC.write_text(text, encoding="utf-8")


def mm(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def ensure_net(board: pcbnew.BOARD, name: str) -> pcbnew.NETINFO_ITEM:
    found = board.FindNet(name)
    if found:
        return found
    item = pcbnew.NETINFO_ITEM(board, name)
    board.Add(item)
    return item


def add_track(board: pcbnew.BOARD, net: pcbnew.NETINFO_ITEM, layer: int, points: list[tuple[float, float]]) -> None:
    for start, end in zip(points, points[1:]):
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(mm(*start))
        track.SetEnd(mm(*end))
        track.SetWidth(pcbnew.FromMM(0.18))
        track.SetLayer(layer)
        track.SetNet(net)
        board.Add(track)


def add_via(board: pcbnew.BOARD, net: pcbnew.NETINFO_ITEM, x: float, y: float) -> None:
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(mm(x, y))
    via.SetWidth(pcbnew.FromMM(0.6))
    via.SetDrill(pcbnew.FromMM(0.3))
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetNet(net)
    board.Add(via)


def set_fpid(footprint: pcbnew.FOOTPRINT, library: str, name: str) -> None:
    footprint.SetFPID(pcbnew.LIB_ID(library, name))


def revise_board() -> None:
    board = pcbnew.LoadBoard(str(BOARD))
    if board.FindFootprintByReference("R46") or board.FindFootprintByReference("R47"):
        raise RuntimeError("board already appears to be r7")

    # Load library objects before deleting tracks.  KiCad 10's Python wrapper
    # can invalidate its footprint I/O plug-in after removed TRACK proxies are
    # released, so doing this first avoids that upstream SWIG quirk.
    switch = pcbnew.FootprintLoad(str(FOOTPRINT_DIR), SWITCH_FP_NAME)
    resistor_templates = [
        pcbnew.FootprintLoad(str(FOOTPRINT_DIR), RESISTOR_FP_NAME),
        pcbnew.FootprintLoad(str(FOOTPRINT_DIR), RESISTOR_FP_NAME),
    ]
    if switch is None or any(item is None for item in resistor_templates):
        raise RuntimeError("could not load one or more r7 footprints")
    switch_pads = list(switch.Pads())

    names = [
        "GAIN_H_SIG",
        "GAIN_M_SIG",
        "GAIN_SRC",
        "GAIN_L_SIG",
        "GAIN_H_GND",
        "GAIN_M_GND",
        "GAIN_L_GND",
        "FDA_INN",
        "FDA_INP",
        "FDA_PD",
        "5VA",
        "GND",
    ]
    nets = {name: ensure_net(board, name) for name in names}

    set_fpid(switch, "Aster_Production", SWITCH_FP_NAME)
    switch.SetReference("SW1")
    switch.SetValue("GAIN 0.5x / 5x / 25x")
    # Put the right-angle switch on the top edge with the actuator facing out.
    # Keeping it directly above the AFE makes every range arm shorter and
    # avoids the BNC keepout entirely.
    switch.SetPosition(mm(28.0, 6.3))
    switch.SetOrientationDegrees(180)
    switch_pad_nets = {
        "1": "GAIN_H_SIG",
        "2": "GAIN_M_SIG",
        "3": "GAIN_SRC",
        "4": "GAIN_L_SIG",
        "5": "GAIN_H_GND",
        "6": "GAIN_M_GND",
        "7": "GND",
        "8": "GAIN_L_GND",
    }
    for pad in switch_pads:
        pad.SetNet(nets[switch_pad_nets[pad.GetNumber()]])

    resistor_specs = [
        ("R46", "324R 0.1%", 25.8, 45.3, 90.0, "GAIN_M_SIG", "FDA_INN"),
        ("R47", "402R 0.1%", 25.5, 32.8, 0.0, "GAIN_M_GND", "FDA_INP"),
    ]
    configured_resistors = []
    for (reference, value, x, y, rotation, net1, net2), resistor in zip(
        resistor_specs, resistor_templates
    ):
        pads = {pad.GetNumber(): pad for pad in resistor.Pads()}
        set_fpid(resistor, "Aster_Production", RESISTOR_FP_NAME)
        resistor.SetReference(reference)
        resistor.SetValue(value)
        resistor.SetDNP(False)
        resistor.SetPosition(mm(x, y))
        resistor.SetOrientationDegrees(rotation)
        pads["1"].SetNet(nets[net1])
        pads["2"].SetNet(nets[net2])
        configured_resistors.append(resistor)

    for reference, value in [
        ("R2", "78R7 0.1%"),
        ("R4", "78R7 0.1%"),
        ("R5", "3k92 0.1%"),
    ]:
        board.FindFootprintByReference(reference).SetValue(value)

    # Create a little more assembly and copper clearance for the new vertical
    # middle-range resistor without disturbing R11's original connections.
    board.FindFootprintByReference("R11").SetPosition(mm(22.9, 46.5))

    old_switch = board.FindFootprintByReference("SW1")
    for item in board.GetDrawings():
        if not isinstance(item, pcbnew.PCB_TEXT):
            continue
        if item.GetText() == "LOW 0.5x":
            item.SetText("RANGE")
            item.SetPosition(mm(18.0, 15.0))
        elif item.GetText() == "HIGH 20x":
            item.SetText("0.5x / 5x / 25x")
            item.SetPosition(mm(31.0, 15.0))

    for item in list(board.Tracks()):
        net_name = item.GetNetname()
        remove_item = net_name in {
            "GAIN_H_SIG",
            "GAIN_SRC",
            "GAIN_L_SIG",
            "GAIN_H_GND",
            "GAIN_L_GND",
        }
        if isinstance(item, pcbnew.PCB_TRACK):
            start = item.GetStart()
            end = item.GetEnd()
            endpoints = {
                (round(pcbnew.ToMM(start.x), 4), round(pcbnew.ToMM(start.y), 4)),
                (round(pcbnew.ToMM(end.x), 4), round(pcbnew.ToMM(end.y), 4)),
            }
            if net_name == "5VA" and endpoints == {(24.5, 48.5), (22.5, 46.5)}:
                remove_item = True
            if (
                net_name == "FDA_PD"
                and not isinstance(item, pcbnew.PCB_VIA)
                and item.GetLayer() == pcbnew.F_Cu
                and min(pcbnew.ToMM(start.y), pcbnew.ToMM(end.y)) > 44.0
                and min(pcbnew.ToMM(start.x), pcbnew.ToMM(end.x)) >= 24.5
            ):
                remove_item = True
        if remove_item:
            board.Remove(item)

    board.Remove(old_switch)
    board.Add(switch)
    for resistor in configured_resistors:
        board.Add(resistor)

    # Short local fan-in from the middle-range arms to the existing FDA stars.
    add_track(board, nets["FDA_INN"], pcbnew.F_Cu, [(25.8, 44.3), (28.0, 44.3), (29.0, 44.7)])
    add_track(board, nets["FDA_INP"], pcbnew.F_Cu, [(26.5, 32.8), (29.0, 32.8)])
    add_track(board, nets["5VA"], pcbnew.F_Cu, [(24.5, 48.5), (24.5, 50.5), (22.2, 50.5), (22.2, 46.5), (21.9, 46.5)])
    add_track(board, nets["FDA_PD"], pcbnew.B_Cu, [(27.3733, 45.3737), (28.0, 46.0), (28.0, 49.5), (23.9, 49.5), (23.9, 48.2)])
    add_via(board, nets["FDA_PD"], 23.9, 48.2)
    add_track(board, nets["FDA_PD"], pcbnew.F_Cu, [(23.9, 48.2), (23.9, 46.5)])

    # Fan the signal row into a narrow B.Cu range bus.  The short top fan-out
    # is on In2.Cu so it cannot cross the reference-row fan-out on B.Cu.
    signal_fanouts = [
        ("GAIN_L_SIG", [(20.0, 6.3), (20.0, 8.0), (16.7, 8.0)]),
        ("GAIN_SRC", [(22.0, 6.3), (22.0, 9.0), (18.1, 9.0)]),
        ("GAIN_M_SIG", [(26.0, 6.3), (26.0, 10.0), (16.0, 10.0)]),
        ("GAIN_H_SIG", [(28.0, 6.3), (28.0, 11.0), (17.4, 11.0)]),
    ]
    for net_name, points in signal_fanouts:
        add_track(board, nets[net_name], pcbnew.In2_Cu, points)
        add_via(board, nets[net_name], points[-1][0], points[-1][1])

    # Reference-row fan-out is wholly on B.Cu.
    add_track(board, nets["GAIN_H_GND"], pcbnew.B_Cu, [(20.0, 3.0), (19.0, 3.0), (19.0, 8.0), (19.5, 8.0)])
    add_track(board, nets["GAIN_M_GND"], pcbnew.B_Cu, [(22.0, 3.0), (23.0, 3.0), (23.0, 9.0), (20.2, 9.0)])
    add_track(board, nets["GAIN_L_GND"], pcbnew.In2_Cu, [(28.0, 3.0), (29.0, 3.0), (29.0, 12.0), (18.8, 12.0)])
    add_via(board, nets["GAIN_L_GND"], 18.8, 12.0)

    # Seven parallel B.Cu corridors are ordered by their termination depth.
    # This lets each horizontal branch leave to the right after all deeper
    # corridors have already ended, so the range nets cannot cross each other.
    add_track(board, nets["GAIN_M_GND"], pcbnew.B_Cu, [(20.2, 9.0), (20.2, 30.0), (23.7, 30.0)])
    add_via(board, nets["GAIN_M_GND"], 23.7, 30.0)
    add_track(board, nets["GAIN_M_GND"], pcbnew.F_Cu, [(23.7, 30.0), (24.5, 30.8), (24.5, 32.8)])

    add_track(board, nets["GAIN_H_GND"], pcbnew.B_Cu, [(19.5, 8.0), (19.5, 33.8), (23.7, 33.8)])
    add_via(board, nets["GAIN_H_GND"], 23.7, 33.8)
    add_track(board, nets["GAIN_H_GND"], pcbnew.F_Cu, [(23.7, 33.8), (24.5, 35.2)])

    add_track(board, nets["GAIN_SRC"], pcbnew.B_Cu, [(18.1, 9.0), (18.1, 37.54), (21.5, 37.54)])

    add_track(board, nets["GAIN_L_GND"], pcbnew.B_Cu, [(18.8, 12.0), (18.8, 36.2), (23.7, 36.2)])
    add_via(board, nets["GAIN_L_GND"], 23.7, 36.2)
    add_track(board, nets["GAIN_L_GND"], pcbnew.F_Cu, [(23.7, 36.2), (24.5, 37.6)])

    add_track(board, nets["GAIN_H_SIG"], pcbnew.B_Cu, [(17.4, 11.0), (17.4, 38.8), (23.7, 38.8)])
    add_via(board, nets["GAIN_H_SIG"], 23.7, 38.8)
    add_track(board, nets["GAIN_H_SIG"], pcbnew.F_Cu, [(23.7, 38.8), (24.5, 40.0)])

    add_track(board, nets["GAIN_L_SIG"], pcbnew.B_Cu, [(16.7, 8.0), (16.7, 41.8), (23.7, 41.8)])
    add_via(board, nets["GAIN_L_SIG"], 23.7, 41.8)
    add_track(board, nets["GAIN_L_SIG"], pcbnew.F_Cu, [(23.7, 41.8), (24.5, 42.4)])

    add_track(board, nets["GAIN_M_SIG"], pcbnew.B_Cu, [(16.0, 10.0), (16.0, 47.5), (25.0, 47.5)])
    add_via(board, nets["GAIN_M_SIG"], 25.0, 47.5)
    add_track(board, nets["GAIN_M_SIG"], pcbnew.F_Cu, [(25.0, 47.5), (25.8, 46.3)])

    pcbnew.SaveBoard(str(BOARD), board)


def snapshot_r6() -> None:
    target = REFERENCE / "r6-source-snapshot"
    target.mkdir(parents=True, exist_ok=True)
    for path in [SCHEMATIC, BOARD, REFERENCE / "GAIN-OPTIMIZATION-r6.md"]:
        destination = target / path.name
        if not destination.exists():
            shutil.copy2(path, destination)
    old_footprint = FOOTPRINT_DIR / "Button_Switch_THT__SW_CK_JS202011AQN_DPDT_Angled__AsterProd.kicad_mod"
    destination = target / old_footprint.name
    if not destination.exists():
        shutil.copy2(old_footprint, destination)


def main() -> None:
    snapshot_r6()
    revise_schematic()
    revise_board()
    print("Created Aster MCA r7 three-range engineering sources")


if __name__ == "__main__":
    sys.exit(main())
