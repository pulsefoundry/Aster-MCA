# Build, run and reproduce / 开发与离线复核

[中文总览](../README.md) | [English overview](../README.en.md)

Run the commands below from the repository root. Software tests and offline replay do not require a connected board. Current host/native-app validation is on macOS with Python 3 and a working C compiler (`cc`).

## Current firmware build

The validated build used ARM GNU Toolchain **14.2.Rel1** with newlib, and the [official AT32F423 Firmware Library](https://github.com/ArteryTek/AT32F423_Firmware_Library) at commit `a60472b248c39034f111ac17e7b1286549594435`.

```sh
git clone https://github.com/ArteryTek/AT32F423_Firmware_Library.git work/at32-bringup-2026-10-14/sdk
git -C work/at32-bringup-2026-10-14/sdk checkout a60472b248c39034f111ac17e7b1286549594435
export ARM_GCC_BIN=/path/to/arm-gnu-toolchain/bin
python3 firmware/at32-peak-scope/build.py
```

`AT32_SDK` can select a different SDK directory; `ARM_GCC_BIN` selects the compiler directory. Tool lookup also supports PATH. A successful build does not replace board-level validation. See the [AT32 guide](at32/README.en.md) before using the guarded historical flash updater.

## Software checks

```sh
python3 -m unittest discover -s firmware/at32-peak-scope -p 'test_*.py' -v
python3 -m unittest discover -s firmware/at32-continuous -p 'test_*gui.py' -v
python3 scripts/verify_artifacts.py
python3 scripts/calculate_at32_cost.py --check
```

Some long historical replay tests depend on uncommitted `work/` fixtures and explicitly skip when absent. The gain-comparison spectra and current 500-segment raw captures are committed. [Earlier repository validation](repository-validation-2026-10-18.md) records the checks performed on the archived checkpoint.

## Desktop software

Browser development entry:

```sh
python3 firmware/at32-continuous/gui.py --open
```

Native macOS packaging requires Xcode Command Line Tools, Python and PyInstaller:

```sh
python3 -m venv work/desktop-build-venv
work/desktop-build-venv/bin/python -m pip install -r requirements-desktop.txt
work/desktop-build-venv/bin/python firmware/at32-continuous/desktop/build_desktop.py
```

The output is `outputs/Aster Nano.app`, with a native window. The packaged runtime is not committed. The current v0.6.1 UI restores a threshold of 20 on reconnect; **set 100 for the gain-reworked board**. Do not let two programs access the same serial port simultaneously.

## Offline spectrum fits

```sh
python3 -m venv work/analysis-venv
work/analysis-venv/bin/python -m pip install -r requirements-analysis.txt
work/analysis-venv/bin/python analysis/20261018/fit_gain_comparison.py
```

Derived results go to ignored `work/replayed-gain-comparison`; archived evidence is not overwritten. Native 2048-channel counts and display rebinning are separate. Fits use unsmoothed gross-source counts.

The overview's full-spectrum figure can also be regenerated from the archived native CSV:

```sh
work/analysis-venv/bin/python analysis/20261018/plot_public_spectrum.py
```

This rewrites only the derived figure `docs/at32/cs137-60s-spectrum.png`, not the source CSV or archived fits.

Finite-waveform replay:

```sh
work/analysis-venv/bin/python firmware/at32-peak-scope/analyze_scope.py \
  outputs/Aster-MCA-Nano-AT32-增益5倍实测-20261018/raw-Cs-present \
  --out work/replayed-Cs-waveforms --threshold 100 --nominal-relative-gain 5.02
```

The analyzer rechecks segment IDs, lengths, ADC range, CRC, statistics and stop timing, then compares the reference processor with the integer MCU engine. Upload gaps are not passed off as continuous samples. A final histogram alone does not retain the per-event data required for later digital shaping.

## Repository layout and history

- `firmware/at32-peak-scope`: current v0.8.2 peak histogram and idle-only RAW diagnostics.
- `firmware/at32-peak`: v0.8.0 sampled-peak baseline.
- `firmware/at32-histogram`: v0.6.3 integral histogram and shared protocol validation.
- `firmware/at32-continuous`: shared host model, GUI/native app, and earlier continuous-sampling experiments.
- `firmware/ch32-selftest-v0.3`: CH32 analog-chain diagnostic source, with baseline drift still under investigation.
- Other `firmware/at32-*` directories: historical experiments. v0.7.x did not pass sustained processing with real pulses; v0.8.1 RAW failed ADC-overflow validation.
- `outputs`: named hardware packages, hand-assembly references, firmware images and measurement evidence.
- `analysis/20261018`: portable gain-comparison analysis using committed data.
- `docs`: bilingual project/track documentation, price inputs and photographs.
- `work`: ignored SDKs, toolchains, virtual environments and temporary captures.

Manufacturing and experimental artifacts keep their original bytes. Do not normalize archived line endings or overwrite measurements when reproducing analyses. Project licensing has not been selected; retain all third-party notices and restrictions.
