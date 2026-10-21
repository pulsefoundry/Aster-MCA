"""Summarize saved probe captures without asserting a detector event count.

All amplitudes are ADC-node values using nominal VDDA=3.3 V. The clock is
internal and per-sample timestamps are unavailable. No waveform smoothing.
"""
import argparse
import json
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture_dir", type=Path)
    ap.add_argument("output_dir", type=Path)
    ap.add_argument("--expected-polarity", choices=["negative", "positive", "unknown"], default="unknown")
    args = ap.parse_args()
    record = json.loads((args.capture_dir / "result.json").read_text())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scale = 3300 / 4096
    threshold = 20
    events, traces, stats_map = [], {}, {}
    for stats in record["captures"]:
        name = stats["file"]
        y = np.fromfile(args.capture_dir / (name + ".bin"), dtype="<u2").astype(float)
        baseline = float(np.median(y))
        traces[name], stats_map[name] = y, stats
        indices = np.flatnonzero(np.abs(y - baseline) >= threshold)
        groups = np.split(indices, np.flatnonzero(np.diff(indices) > 3) + 1) if len(indices) else []
        for group in groups:
            peak = int(group[np.argmax(np.abs(y[group] - baseline))])
            delta = float(y[peak] - baseline)
            signed = (y - baseline) * np.sign(delta)
            left = right = peak
            while left > 0 and signed[left - 1] >= abs(delta) / 2:
                left -= 1
            while right < len(y) - 1 and signed[right + 1] >= abs(delta) / 2:
                right += 1
            events.append({"file": name, "index": peak, "baseline_code": baseline,
                           "peak_code": float(y[peak]), "delta_mv": delta * scale,
                           "polarity": "negative" if delta < 0 else "positive",
                           "threshold_samples": len(group), "half_height_samples": right - left + 1,
                           "touches_frame_edge": bool(group[0] == 0 or group[-1] == len(y) - 1)})
    events.sort(key=lambda event: -abs(event["delta_mv"]))
    all_values = np.concatenate(list(traces.values()))
    summary = {
        "input_condition": record["input"], "expected_polarity_user_reported": args.expected_polarity,
        "frame_count": len(record["captures"]),
        "sample_count": len(all_values), "host_duration_seconds": record["host_duration_seconds"],
        "captured_frame_spans_seconds": sum((s["nominal_span_cycles"] if s.get("method") == "timer_dma"
                                              else s["span_cycles"]) / s["core_hz"] for s in record["captures"]),
        "sample_rate_hz": sorted(set(round(s["effective_sps"]) for s in record["captures"])),
        "frame_span_basis": "timer configuration for DMA; internal frame counter for polling",
        "nominal_vdda_v": 3.3,
        "all_frames_crc_and_statistics_verified": all(s["crc_and_statistics_verified"] for s in record["captures"]),
        "median_baseline_v": float(np.median(all_values)) * scale / 1000,
        "sampled_min_v": float(all_values.min()) * scale / 1000,
        "sampled_max_v": float(all_values.max()) * scale / 1000,
        "sampled_rail_hits": int(np.count_nonzero((all_values == 0) | (all_values == 4095))),
        "analysis_threshold_codes": threshold, "analysis_threshold_mv": threshold * scale,
        "merge_maximum_index_gap": 3,
        "transient_groups": len(events),
        "negative_groups": sum(e["polarity"] == "negative" for e in events),
        "positive_groups": sum(e["polarity"] == "positive" for e in events),
        "single_threshold_sample_groups": sum(e["threshold_samples"] == 1 for e in events),
        "events": events,
        "limitations": ["Groups are threshold excursions, not validated radiation events or count rate.",
                        "There are gaps between frames; this is not continuous acquisition.",
                        "Single-sample transients do not resolve pulse peak or width.",
                        "No sampled rail hit does not rule out an excursion between samples.",
                        "Expected polarity is user-reported; individual excursions are not validated detector events."]}
    (args.output_dir / "probe-analysis.json").write_text(json.dumps(summary, indent=2) + "\n")
    shutil.copytree(args.capture_dir, args.output_dir / "raw", dirs_exist_ok=True)
    negative = next((e for e in events if e["polarity"] == "negative"), None)
    positive = next((e for e in events if e["polarity"] == "positive"), None)
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.5), layout="constrained")
    for row, event in enumerate([negative, positive]):
        if event is None:
            for ax in axes[row]:
                ax.text(0.5, 0.5, "No excursion of this polarity", ha="center", transform=ax.transAxes)
            continue
        y = traces[event["file"]]
        fs = stats_map[event["file"]]["effective_sps"]
        t = np.arange(len(y)) / fs
        mv = (y - event["baseline_code"]) * scale
        ax = axes[row, 0]
        ax.plot(t * 1000, mv, lw=0.8, color="#137cb5")
        ax.axhline(0, color="#8996a4", ls="--", lw=0.8)
        ax.set(xlabel="Time within frame (ms)", ylabel="Change from baseline (mV)",
               title=f"{event['file']}: complete {len(y)/fs*1000:.3f} ms frame")
        ax = axes[row, 1]
        dt = (t - t[event["index"]]) * 1e6
        limits = (-8e6/fs, 12e6/fs) if row == 0 else (-100, 700)
        select = (dt >= limits[0]) & (dt <= limits[1])
        ax.plot(dt[select], mv[select], ".-", ms=5, lw=0.8, color="#137cb5")
        ax.axhline(0, color="#8996a4", ls="--", lw=0.8)
        ax.set(xlabel="Time relative to sampled peak (us)", ylabel="Change from baseline (mV)",
               title=f"{event['polarity'].capitalize()} excursion: {event['delta_mv']:+.1f} mV", xlim=limits)
        for ax in axes[row]:
            ax.grid(alpha=0.22)
    rates = ", ".join(f"{rate/1000:g}" for rate in summary["sample_rate_hz"])
    fig.suptitle(f"Aster AT32 - probe-connected captures at {rates} kS/s", fontsize=16)
    fig.supxlabel("Points are actual samples; connecting lines do not resolve between-sample shape. ADC-node volts, nominal 3.3 V reference.", fontsize=9)
    fig.savefig(args.output_dir / "AT32-probe-waveforms.png", dpi=160)
    plt.close(fig)
    print(json.dumps({k: v for k, v in summary.items() if k not in ["events", "limitations"]}, indent=2))
    print("Strongest negative:", negative)
    print("Strongest positive:", positive)


if __name__ == "__main__":
    main()
