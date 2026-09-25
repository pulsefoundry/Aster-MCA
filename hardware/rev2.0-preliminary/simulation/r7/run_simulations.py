#!/usr/bin/env python3
"""Run the Aster MCA v2 r7 analogue front-end audit.

The circuit under test is copied from the KiCad r7 design: THS4551 on 5 V,
2 kohm feedback arms, the selected two input resistors, 10 ohm output isolation
and 2.2 nF differential ADC charge-kickback capacitor.  ADS5560 is represented
as a high impedance differential load; its switched-capacitor aperture and
quantisation are outside the THS4551 vendor macro-model.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pathlib
import statistics
import subprocess
import sys
import urllib.request
import zipfile


HERE = pathlib.Path(__file__).resolve().parent
RESULTS = HERE / "results"
PLOTS = HERE / "plots"
WORK = HERE / "work"
TI_ZIP_URL = "https://www.ti.com/lit/zip/sbomb92"

RANGES = {
    "0p5x": {"rin_signal": 78.7 + 3920.0, "rin_reference": 4000.0, "vin": 0.2},
    "5x": {"rin_signal": 78.7 + 324.0, "rin_reference": 402.0, "vin": 0.02},
    "25x": {"rin_signal": 78.7, "rin_reference": 78.7, "vin": 0.004},
}


def fetch_model(destination: pathlib.Path) -> pathlib.Path:
    archive = destination / "SBOMB92B.ZIP"
    raw_model = destination / "ths4551.lib"
    destination.mkdir(parents=True, exist_ok=True)
    if not raw_model.exists():
        print(f"Fetching TI THS4551 model from {TI_ZIP_URL}")
        urllib.request.urlretrieve(TI_ZIP_URL, archive)
        with zipfile.ZipFile(archive) as source:
            raw_model.write_bytes(source.read("ths4551.lib"))
    return raw_model


def prepare_model(raw_model: pathlib.Path) -> pathlib.Path:
    converted = WORK / "ths4551-ngspice.lib"
    subprocess.run(
        [sys.executable, str(HERE / "prepare_ti_model.py"), str(raw_model), str(converted)],
        check=True,
    )
    return converted


def front_end_netlist(
    title: str,
    model: pathlib.Path,
    rin_signal: float,
    rin_reference: float,
    source_line: str,
    analysis: str,
    output_file: pathlib.Path,
    vectors: str,
    riso: float = 22.0,
    cfilt: float = 2.2e-9,
) -> str:
    return f"""{title}
.include {model}
.options method=gear reltol=1e-4 abstol=1e-12 vntol=1e-7
VCC vcc 0 5
VVCM vcm 0 1.5
VPD pd 0 5
{source_line}
RSRC src gain_src 0.1
RINS gain_src inn {rin_signal:.12g}
RINR 0 inp {rin_reference:.12g}
RFP outp inn 2k
RFN outn inp 2k
XU3 inp inn outp outn vcm vcc 0 THS4551
RISO_P outp adcm {riso:.12g}
RISO_N outn adcp {riso:.12g}
CFILT adcp adcm {cfilt:.12g}
RLOAD adcp adcm 1Meg
.control
set wr_vecnames
set wr_singlescale
{analysis}
wrdata {output_file} {vectors}
.endc
.end
"""


def run_netlist(path: pathlib.Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(HERE / "run_shared_ngspice.py"),
            "--pspice-compatibility",
            "--quiet",
            str(path),
        ],
        check=True,
    )


def read_wrdata(path: pathlib.Path) -> tuple[list[str], list[list[float]]]:
    lines = [line.split() for line in path.read_text().splitlines() if line.strip()]
    return lines[0], [[float(item) for item in row] for row in lines[1:]]


def median_window(times: list[float], values: list[float], lo: float, hi: float) -> float:
    selected = [value for time, value in zip(times, values) if lo <= time <= hi]
    if not selected:
        raise ValueError(f"empty window {lo:g} to {hi:g}")
    return statistics.median(selected)


def transient_metrics(path: pathlib.Path, input_amplitude: float) -> dict[str, float]:
    _header, rows = read_wrdata(path)
    # scale, v(src), v(outp), v(outn), v(adcp), v(adcm), v(adcp,adcm)
    t = [row[0] for row in rows]
    vin = [row[1] for row in rows]
    outp = [row[2] for row in rows]
    outn = [row[3] for row in rows]
    adcp = [row[4] for row in rows]
    adcm = [row[5] for row in rows]
    diff = [row[6] for row in rows]
    common = [(p + m) / 2.0 for p, m in zip(adcp, adcm)]

    baseline = median_window(t, diff, 0.2e-6, 0.8e-6)
    plateau = median_window(t, diff, 1.6e-6, 2.8e-6)
    vin_base = median_window(t, vin, 0.2e-6, 0.8e-6)
    vin_plateau = median_window(t, vin, 1.6e-6, 2.8e-6)
    delta_in = vin_plateau - vin_base
    delta_out = plateau - baseline
    gain = delta_out / delta_in

    edge_values = [value for time, value in zip(t, diff) if 1.0e-6 <= time <= 2.9e-6]
    extreme = min(edge_values) if delta_out < 0 else max(edge_values)
    overshoot = max(0.0, abs(extreme - baseline) / abs(delta_out) - 1.0) * 100.0

    target_band = max(abs(delta_out) * 0.01, 50e-6)
    settle_us = math.nan
    candidates = [index for index, time in enumerate(t) if time >= 1.02e-6]
    end_index = max(index for index, time in enumerate(t) if time <= 2.9e-6)
    for index in candidates:
        if index > end_index:
            break
        if all(abs(value - plateau) <= target_band for value in diff[index : end_index + 1]):
            settle_us = (t[index] - 1.02e-6) * 1e6
            break

    plateau_common = [value for time, value in zip(t, common) if 1.5e-6 <= time <= 2.9e-6]
    post_pulse = [value for time, value in zip(t, diff) if 5.0e-6 <= time <= 7.9e-6]
    return {
        "input_step_v": delta_in,
        "baseline_diff_v": baseline,
        "plateau_diff_v": plateau,
        "output_step_v": delta_out,
        "simulated_gain_v_per_v": gain,
        "overshoot_percent": overshoot,
        "settling_1pct_us": settle_us,
        "adc_common_mode_min_v": min(plateau_common),
        "adc_common_mode_max_v": max(plateau_common),
        "outp_min_v": min(outp),
        "outp_max_v": max(outp),
        "outn_min_v": min(outn),
        "outn_max_v": max(outn),
        "adc_diff_min_v": min(diff),
        "adc_diff_max_v": max(diff),
        "post_pulse_peak_to_peak_v": max(post_pulse) - min(post_pulse),
        "requested_amplitude_v": input_amplitude,
    }


def overload_metrics(path: pathlib.Path) -> dict[str, float]:
    _header, rows = read_wrdata(path)
    t = [row[0] for row in rows]
    outp = [row[2] for row in rows]
    outn = [row[3] for row in rows]
    adcp = [row[4] for row in rows]
    adcm = [row[5] for row in rows]
    diff = [row[6] for row in rows]
    baseline = median_window(t, diff, 0.2e-6, 0.8e-6)
    completed = t[-1] >= 11.9e-6
    late = median_window(t, diff, 8e-6, 10e-6) if completed else math.nan
    return {
        "simulation_end_time_us": t[-1] * 1e6,
        "simulation_completed": completed,
        "baseline_diff_v": baseline,
        "adc_diff_min_v": min(diff),
        "adc_diff_max_v": max(diff),
        "outp_min_v": min(outp),
        "outp_max_v": max(outp),
        "outn_min_v": min(outn),
        "outn_max_v": max(outn),
        "late_residual_from_baseline_mv": (late - baseline) * 1e3,
        "adc_exceeds_nominal_3p6vpp": max(abs(min(diff)), abs(max(diff))) > 1.8,
    }


def ac_metrics(path: pathlib.Path) -> dict[str, float]:
    _header, rows = read_wrdata(path)
    frequency = [row[0] for row in rows]
    gain_db = [row[1] for row in rows]
    phase_deg = [row[2] for row in rows]
    reference_db = statistics.median(gain_db[:5])
    target = reference_db - 3.0
    bandwidth = math.nan
    for f0, f1, g0, g1 in zip(frequency, frequency[1:], gain_db, gain_db[1:]):
        if (g0 - target) * (g1 - target) <= 0 and g1 != g0:
            fraction = (target - g0) / (g1 - g0)
            bandwidth = math.exp(math.log(f0) + fraction * (math.log(f1) - math.log(f0)))
            break
    peak_index = max(range(len(gain_db)), key=lambda index: gain_db[index])
    return {
        "low_frequency_gain_db": reference_db,
        "bandwidth_3db_hz": bandwidth,
        "peaking_db": gain_db[peak_index] - reference_db,
        "peaking_frequency_hz": frequency[peak_index],
        "phase_at_last_point_deg": phase_deg[-1],
    }


def svg_plot(
    traces: list[tuple[str, list[float], list[float], str]],
    destination: pathlib.Path,
    title: str,
    x_label: str,
    y_label: str,
) -> None:
    width, height = 1000, 580
    left, right, top, bottom = 88, 28, 58, 72
    all_x = [x for _name, xs, _ys, _colour in traces for x in xs]
    all_y = [y for _name, _xs, ys, _colour in traces for y in ys]
    xmin, xmax = min(all_x), max(all_x)
    ymin, ymax = min(all_y), max(all_y)
    if ymax == ymin:
        ymax += 1.0
    ypad = 0.08 * (ymax - ymin)
    ymin -= ypad
    ymax += ypad

    def px(x: float) -> float:
        return left + (x - xmin) / (xmax - xmin) * (width - left - right)

    def py(y: float) -> float:
        return top + (ymax - y) / (ymax - ymin) * (height - top - bottom)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="30" text-anchor="middle" font-family="sans-serif" font-size="21">{title}</text>',
    ]
    for tick in range(6):
        x = xmin + tick * (xmax - xmin) / 5
        xp = px(x)
        parts.append(f'<line x1="{xp:.2f}" y1="{top}" x2="{xp:.2f}" y2="{height-bottom}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{xp:.2f}" y="{height-bottom+24}" text-anchor="middle" font-family="sans-serif" font-size="12">{x:.3g}</text>')
        y = ymin + tick * (ymax - ymin) / 5
        yp = py(y)
        parts.append(f'<line x1="{left}" y1="{yp:.2f}" x2="{width-right}" y2="{yp:.2f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left-10}" y="{yp+4:.2f}" text-anchor="end" font-family="sans-serif" font-size="12">{y:.3g}</text>')
    parts.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#111827"/>',
            f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#111827"/>',
            f'<text x="{width/2}" y="{height-20}" text-anchor="middle" font-family="sans-serif" font-size="14">{x_label}</text>',
            f'<text x="22" y="{height/2}" text-anchor="middle" transform="rotate(-90 22 {height/2})" font-family="sans-serif" font-size="14">{y_label}</text>',
        ]
    )
    for trace_index, (name, xs, ys, colour) in enumerate(traces):
        stride = max(1, len(xs) // 2400)
        points = " ".join(
            f"{px(x):.2f},{py(y):.2f}" for x, y in zip(xs[::stride], ys[::stride])
        )
        parts.append(f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="2"/>')
        legend_x = left + trace_index * 180
        parts.append(f'<line x1="{legend_x}" y1="48" x2="{legend_x+24}" y2="48" stroke="{colour}" stroke-width="3"/>')
        parts.append(f'<text x="{legend_x+30}" y="52" font-family="sans-serif" font-size="13">{name}</text>')
    parts.append("</svg>")
    destination.write_text("\n".join(parts) + "\n", encoding="utf-8")


def json_safe(value: object) -> object:
    """Replace non-finite floats with JSON null for standards-compliant output."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=pathlib.Path)
    parser.add_argument("--fetch-model", action="store_true")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    PLOTS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    raw_model = args.model
    if raw_model is None:
        candidates = [pathlib.Path("/tmp/ths4551.lib"), WORK / "ths4551.lib"]
        raw_model = next((path for path in candidates if path.exists()), None)
    if raw_model is None and args.fetch_model:
        raw_model = fetch_model(WORK)
    if raw_model is None:
        raise SystemExit(
            "THS4551 model not found. Pass --model /path/to/ths4551.lib or "
            "use --fetch-model to retrieve TI SBOMB92B.ZIP."
        )
    model = prepare_model(raw_model.resolve())

    summary: dict[str, object] = {
        "engine": "KiCad bundled ngspice 45.2 shared library",
        "amplifier_model": "TI THS4551 PSpice model SBOMB92B Rev B package",
        "model_translation": "3 TABLE sources to identical-point behavioural PWL; switch threshold syntax normalized",
        "ranges": {},
        "low_range_output_isolation_sweep": {},
    }
    colours = {"0p5x": "#2563eb", "5x": "#16a34a", "25x": "#dc2626"}
    small_traces = []
    overload_traces = []
    damping_traces = []

    for name, configuration in RANGES.items():
        output_small = RESULTS / f"{name}-small-signal.tsv"
        netlist_small = WORK / f"{name}-small-signal.cir"
        netlist_small.write_text(
            front_end_netlist(
                f"Aster MCA v2 r7 {name} small-signal",
                model,
                configuration["rin_signal"],
                configuration["rin_reference"],
                f"VIN src 0 PULSE(0 -{configuration['vin']:.12g} 1u 20n 20n 2u 20u)",
                "tran 2n 8u",
                output_small,
                "v(src) v(outp) v(outn) v(adcp) v(adcm) v(adcp,adcm)",
            ),
            encoding="utf-8",
        )
        run_netlist(netlist_small)

        output_overload = RESULTS / f"{name}-overload-2p7v.tsv"
        netlist_overload = WORK / f"{name}-overload-2p7v.cir"
        netlist_overload.write_text(
            front_end_netlist(
                f"Aster MCA v2 r7 {name} -2.7 V overload",
                model,
                configuration["rin_signal"],
                configuration["rin_reference"],
                # The vendor model's ideal internal switches do not converge
                # for a 20 ns, 2.7 V edge.  A 200 ns edge remains much faster
                # than the measured detector pulse envelope and permits the
                # advertised overload-recovery model to run deterministically.
                "VIN src 0 PULSE(0 -2.7 1u 200n 200n 2u 20u)",
                "tran 2n 12u",
                output_overload,
                "v(src) v(outp) v(outn) v(adcp) v(adcm) v(adcp,adcm)",
            ),
            encoding="utf-8",
        )
        run_netlist(netlist_overload)

        output_ac = RESULTS / f"{name}-ac.tsv"
        netlist_ac = WORK / f"{name}-ac.cir"
        netlist_ac.write_text(
            front_end_netlist(
                f"Aster MCA v2 r7 {name} AC response",
                model,
                configuration["rin_signal"],
                configuration["rin_reference"],
                "VIN src 0 DC 0 AC 1",
                "ac dec 60 10 100Meg",
                output_ac,
                "vdb(adcp,adcm) vp(adcp,adcm)",
            ),
            encoding="utf-8",
        )
        run_netlist(netlist_ac)

        range_summary = {
            "resistors": {
                "signal_input_ohm": configuration["rin_signal"],
                "reference_input_ohm": configuration["rin_reference"],
                "feedback_ohm": 2000.0,
            },
            "small_signal": transient_metrics(output_small, configuration["vin"]),
            "overload_minus_2p7v": overload_metrics(output_overload),
            "ac": ac_metrics(output_ac),
            "estimated_peak_source_current_at_minus_2p7v_a": 2.7
            / configuration["rin_signal"],
        }
        summary["ranges"][name] = range_summary

        _header, small_rows = read_wrdata(output_small)
        small_traces.append(
            (
                name,
                [row[0] * 1e6 for row in small_rows],
                [row[6] for row in small_rows],
                colours[name],
            )
        )
        _header, overload_rows = read_wrdata(output_overload)
        overload_traces.append(
            (
                name,
                [row[0] * 1e6 for row in overload_rows],
                [row[6] for row in overload_rows],
                colours[name],
            )
        )

    # The nominal 0.5x network showed a high-frequency resonance in the first
    # pass.  Sweep only the two output-isolation resistors while retaining the
    # board's 2.2 nF differential capacitor to distinguish a topology problem
    # from an easily tunable ADC-interface damping problem.
    for riso in (10.0, 22.0, 33.0, 47.0, 68.0, 100.0):
        label = f"riso-{riso:g}ohm"
        output_ac = RESULTS / f"0p5x-{label}-ac.tsv"
        netlist_ac = WORK / f"0p5x-{label}-ac.cir"
        configuration = RANGES["0p5x"]
        netlist_ac.write_text(
            front_end_netlist(
                f"Aster MCA v2 r7 0p5x {label} AC response",
                model,
                configuration["rin_signal"],
                configuration["rin_reference"],
                "VIN src 0 DC 0 AC 1",
                "ac dec 60 10 100Meg",
                output_ac,
                "vdb(adcp,adcm) vp(adcp,adcm)",
                riso=riso,
            ),
            encoding="utf-8",
        )
        run_netlist(netlist_ac)

        output_transient = RESULTS / f"0p5x-{label}-transient.tsv"
        netlist_transient = WORK / f"0p5x-{label}-transient.cir"
        netlist_transient.write_text(
            front_end_netlist(
                f"Aster MCA v2 r7 0p5x {label} transient",
                model,
                configuration["rin_signal"],
                configuration["rin_reference"],
                "VIN src 0 PULSE(0 -0.2 1u 20n 20n 2u 20u)",
                "tran 2n 8u",
                output_transient,
                "v(src) v(outp) v(outn) v(adcp) v(adcm) v(adcp,adcm)",
                riso=riso,
            ),
            encoding="utf-8",
        )
        run_netlist(netlist_transient)
        summary["low_range_output_isolation_sweep"][label] = {
            "ac": ac_metrics(output_ac),
            "transient": transient_metrics(output_transient, 0.2),
        }
        if riso in (10.0, 22.0, 33.0, 47.0):
            _header, damping_rows = read_wrdata(output_transient)
            damping_traces.append(
                (
                    f"{riso:g} ohm",
                    [row[0] * 1e6 for row in damping_rows],
                    [row[6] for row in damping_rows],
                    {10.0: "#dc2626", 22.0: "#16a34a", 33.0: "#2563eb", 47.0: "#7c3aed"}[riso],
                )
            )

    safe_summary = json_safe(summary)
    (RESULTS / "summary.json").write_text(
        json.dumps(safe_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (RESULTS / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "range",
                "gain_v_per_v",
                "baseline_diff_v",
                "overshoot_percent",
                "settling_1pct_us",
                "bandwidth_3db_hz",
                "overload_diff_min_v",
                "overload_diff_max_v",
                "overload_late_residual_mv",
                "estimated_input_current_at_2p7v_ma",
            ]
        )
        for name, data in summary["ranges"].items():
            writer.writerow(
                [
                    name,
                    data["small_signal"]["simulated_gain_v_per_v"],
                    data["small_signal"]["baseline_diff_v"],
                    data["small_signal"]["overshoot_percent"],
                    data["small_signal"]["settling_1pct_us"],
                    data["ac"]["bandwidth_3db_hz"],
                    data["overload_minus_2p7v"]["adc_diff_min_v"],
                    data["overload_minus_2p7v"]["adc_diff_max_v"],
                    data["overload_minus_2p7v"]["late_residual_from_baseline_mv"],
                    data["estimated_peak_source_current_at_minus_2p7v_a"] * 1e3,
                ]
            )
    svg_plot(
        small_traces,
        PLOTS / "small-signal-transient.svg",
        "Aster MCA v2 r7 — scaled small-signal pulse response",
        "Time (us)",
        "ADC differential input (V)",
    )
    svg_plot(
        overload_traces,
        PLOTS / "minus-2p7v-overload.svg",
        "Aster MCA v2 r7 — response to a 2 us, -2.7 V source pulse",
        "Time (us)",
        "ADC differential input (V)",
    )
    svg_plot(
        damping_traces,
        PLOTS / "low-range-output-damping-sweep.svg",
        "0.5x range — output-isolation resistor sweep (Cdiff = 2.2 nF)",
        "Time (us)",
        "ADC differential input (V)",
    )
    print(json.dumps(safe_summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
