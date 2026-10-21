"""Analyze saved RAW captures; requires NumPy and Matplotlib, no board access.

Sample times are approximated from the frame span, not per-sample timestamps.
ADC voltages assume nominal VDDA=3.3 V. All results are at the ADC node.
"""
import argparse
import json
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def fit_sine(y, t, frequency):
    phase = 2 * np.pi * frequency * t
    basis = np.column_stack((np.ones(len(t)), np.sin(phase), np.cos(phase)))
    coef = np.linalg.lstsq(basis, y, rcond=None)[0]
    fitted = basis @ coef
    return np.mean((y - fitted) ** 2), coef, fitted


def analyze(raw, stats):
    y = np.fromfile(raw, dtype="<u2").astype(float)
    fs = stats["effective_sps"]
    t = np.arange(len(y)) / fs
    spectrum = np.abs(np.fft.rfft((y - y.mean()) * np.hanning(len(y))))
    k = np.argmax(spectrum[1:]) + 1
    spacing = fs / len(y)
    grid = np.linspace(max(spacing * 0.1, (k - 1) * spacing), (k + 1) * spacing, 81)
    errors = [fit_sine(y, t, f)[0] for f in grid]
    best = int(np.argmin(errors))
    lo, hi = grid[max(0, best - 1)], grid[min(len(grid) - 1, best + 1)]
    # Bounded one-dimensional least-squares frequency refinement.
    ratio = (np.sqrt(5) - 1) / 2
    for _ in range(45):
        a, b = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
        if fit_sine(y, t, a)[0] < fit_sine(y, t, b)[0]:
            hi = b
        else:
            lo = a
    frequency = (lo + hi) / 2
    mse, coef, fitted = fit_sine(y, t, frequency)
    scale = 3.3 / 4096
    result = {
        "file": raw.name, "n": len(y), "estimated_sample_rate_hz": fs,
        "sine_frequency_hz": frequency,
        "fitted_midpoint_v": coef[0] * scale,
        "fitted_fundamental_vpp": 2 * np.hypot(coef[1], coef[2]) * scale,
        "raw_vpp": np.ptp(y) * scale,
        "raw_min_v": np.min(y) * scale, "raw_max_v": np.max(y) * scale,
        "fit_residual_rms_mv": np.sqrt(mse) * scale * 1000,
        "adc_rail_hits": int(np.count_nonzero((y == 0) | (y == 4095))),
        "fit_r_squared": 1 - mse / np.var(y),
        "nominal_vdda_v": 3.3,
    }
    return result, (t, y * scale, fitted * scale)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    capture = json.loads((args.capture_dir / "result.json").read_text())
    assert capture["completed"]
    results, waveforms = [], {}
    for stats in capture["captures"]:
        result, waveform = analyze(args.capture_dir / (stats["file"] + ".bin"), stats)
        results.append(result)
        waveforms[stats["file"]] = waveform
    report = {"input_condition": capture["input"], "captures": results,
              "limitations": ["Nominal 3.3 V reference; ADC-node voltage, not SMA voltage.",
                              "Approximate uniform time axis based on internal cycle counter.",
                              "Low-frequency sine test does not validate narrow-pulse acquisition.",
                              "Fit residual includes noise, waveform distortion and timing error."]}
    (args.output_dir / "sine-analysis.json").write_text(json.dumps(report, indent=2) + "\n")
    shutil.copytree(args.capture_dir, args.output_dir / "raw", dirs_exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), layout="constrained")
    for ax, key, label in zip(axes, ["slow-1", "fast-1"], ["10 kS/s", "100 kS/s"]):
        t, y, fitted = waveforms[key]
        fit = next(v for v in results if v["file"] == key + ".bin")
        chosen = t <= 0.04
        ax.plot(t[chosen] * 1000, y[chosen], color="#147ab6", lw=1,
                label="ADC samples", rasterized=True)
        ax.plot(t[chosen] * 1000, fitted[chosen], color="#e97928", lw=1.5,
                label="Fundamental sine fit")
        ax.set_title(f"{label}: {fit['sine_frequency_hz']:.2f} Hz | "
                     f"{fit['fitted_fundamental_vpp'] * 1000:.1f} mVpp (fit)", loc="left")
        ax.set(xlabel="Time (ms)", ylabel="ADC input (V)", xlim=(0, 40))
        ax.grid(alpha=0.22)
        ax.legend(loc="upper right", fontsize=9)
    fig.suptitle("Aster MCA Nano AT32 - measured sine wave", fontsize=16)
    fig.supxlabel("Nominal VDDA = 3.3 V; internal timebase; separate captures", fontsize=10)
    fig.savefig(args.output_dir / "AT32-100Hz-sine.png", dpi=170)
    plt.close(fig)
    for r in results:
        print(r["file"], f"{r['sine_frequency_hz']:.4f} Hz",
              f"fit {r['fitted_fundamental_vpp'] * 1000:.3f} mVpp",
              f"raw {r['raw_vpp'] * 1000:.3f} mVpp",
              f"residual {r['fit_residual_rms_mv']:.3f} mV",
              f"R2 {r['fit_r_squared']:.5f}")


if __name__ == "__main__":
    main()
