# Peak-hold tools and offline replay

[实验记录 / Bench record](../../measurements/2026-11-18-peakhold/README.md) · [English record](../../measurements/2026-11-18-peakhold/README.en.md)

Run commands from `nano/`. `verify_checkpoint.py` uses only the Python standard library and never opens a device:

```sh
python3 analysis/20261118/verify_checkpoint.py
```

It checks the public file/archive hashes, raw payload CRCs, frame metadata, native histogram accounting, RAW snapshot statistics and recorded EARLY/LATE stop timing. Failed records remain archived and are distinguished from completed experiments. This verifies saved evidence, not present hardware health.

For plots and fitting, install `requirements-analysis.txt` into a separate environment. Extract archives without changing the archived files:

```sh
python3 -m zipfile -e measurements/2026-11-18-peakhold/awg-bench.zip work/replay-20261118
python3 -m zipfile -e measurements/2026-11-18-peakhold/cs137-600s.zip work/replay-20261118
python3 analysis/20261118/analyze_fixed_pulse.py work/replay-20261118/awg-bench/pulse-300mv --nominal-mvpp 300 --output work/replayed-300mv
python3 analysis/20261118/analyze_raw_snapshots.py work/replay-20261118/awg-bench/raw-300mv-4m-01 --mode signal --output work/replayed-raw300
python3 analysis/20261118/fit_wait500_long.py work/replay-20261118/cs137-600s/source-10min --out work/replayed-cs600
```

Output directories must be new. The long-run wrapper applies the documented conservative analog-range exclusion to an analysis copy; it does not alter the native histogram or frames. The Gaussian/linear-continuum fit has model mismatch and ROI sensitivity and is not an energy calibration.

Offline tools:

- `analyze_fixed_pulse.py`: strict fast.7 frame/histogram replay and unbinned amplitude statistics.
- `analyze_raw_snapshots.py`: CRC/statistics/rate checks, local pulse baseline/area and output-off noise.
- `compare_amplitude_points.py`: nominal amplitude response from saved capture/analysis directories.
- `fit_long_run.py`, `fit_wait500_long.py`: portable copies of the archived fit with fast.7 decoding and the 500 µs analog guard.

Explicit hardware tools, only when invoked as scripts:

- `capture_raw_snapshots.py`: guarded DMA snapshots; restores the original RAW timer rate even on failure where communication permits.
- `run_stop_phase_comparison.py`: balanced existing-firmware EARLY/LATE batches; restores the saved profile.
- `../../firmware/at32-peakhold-fast7/capture_spectrum.py`: host histogram from batches.
- `../../scripts/owon_legacy_usb.py`: legacy AG1022 USB protocol, not standard SCPI. The archived final experiments used operator front-panel control instead.

Importing these modules does not open a device. Do not run hardware entry points merely to inspect the archive. No helper automatically flashes the board or starts generator output. The old desktop app does not implement this peak-hold protocol.
