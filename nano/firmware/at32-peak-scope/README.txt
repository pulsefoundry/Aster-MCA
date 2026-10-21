Aster MCA Nano AT32 v0.8.2 — idle-only finite waveform diagnostics

The v0.8.0 sampled-peak engine is unchanged. CPU 144 MHz, ADC 72 MHz,
4 MS/s, threshold 20 by default, 2048 one-ADC-code bins, LDO 1.3 V.
The normal ACQUIRE/RESULT workflow still accumulates on the board and sends
one final spectrum. RAW is available only when acquisition is idle.

RAW captures the FIRST 4096 samples of an 8192-sample normal-mode DMA buffer.
The half-transfer interrupt stops timer triggers. DMA remains enabled while
the ADC drains/stops, so late conversions land in the unused second half.
The first half is frozen before USB transmission starts. Checks require:
  - exact 4096-sample payload, metadata CRC, payload CRC and statistics;
  - zero ADC overflow and zero firmware error;
  - DMA remaining count 4032..4096 after stopping;
  - stop interrupt timing 147456..148896 core cycles from timer start;
  - monotonically increasing raw capture ID; histogram session unchanged.

Each segment spans 1.024 ms of sampled time, followed by an upload gap.
Never concatenate segments as continuous data. This mode diagnoses amplitude,
noise and pulse shape; it does not measure absolute detector count rate,
corrected live time or calibrated energy. The MCU ADC cannot exclude analog
oscillation beyond its measurement bandwidth.

v0.8.1 was rejected at first physical RAW test: full-buffer DMA stopped too
late relative to subsequent ADC conversions, producing adc_overrun=1/errors=2.
Its data is invalid. Firmware/image/flash backup/wire record remain in
work/at32-scope-2026-10-18. Do not use v0.8.1 RAW as evidence or a release.
The subsequent v0.8.1 normal 3-second histogram passed; this does not validate
the replacement RAW path. v0.8.2 subsequently passed full flash readback,
unloaded RAW/histogram mode transitions, powered-probe background and Cs-source
RAW/histogram tests, including a 60-second histogram after the R21/R22 rework.
Current checkpoint: docs/2026-10-18-checkpoint.md. The reworked board uses
threshold100; default-gain historical runs used threshold20.

Build: python3 firmware/at32-peak-scope/build.py
Software tests: python3 -m unittest discover -s firmware/at32-peak-scope -p 'test_*.py'
Flash: python3 firmware/at32-peak-scope/flash.py
  Requires factory DFU 2e3c:df11, SMA disconnected. Default updater accepts
  only the exact saved v0.8.1 image identified in reference/; this is a guarded
  historical migration tool, not an arbitrary blank-device installer.
  Full flash/options backup precedes writes. Full readback/options equality
  and unchanged flash outside target erase pages are mandatory.
Rollback: same flash.py --restore-peak (v0.8.2 -> frozen v0.8.0).

Host capture:
  python3 firmware/at32-peak-scope/scope_capture.py --port <AT32 CDC port> \
    --out <new-folder> --segments 500 --input '<actual topology/source state>'
Offline plot (Python with NumPy/Matplotlib):
  python firmware/at32-peak-scope/analyze_scope.py <capture-folder> --out <new-folder>
The offline plot revalidates every segment and compares the reference event
processor histogram against the unchanged integer MCU engine per segment.
Every segment resets both processors; upload gaps are not passed to them.
Plots show raw samples without smoothing. Voltage conversion assumes a
nominal 3.3 V reference. No resolution fit is made from these snapshots.

Desktop app v0.6.1 accepts v0.8.2 peak spectra. Diagnostic capture is currently
a bench tool and does not add a RAW button to the ordinary spectrum UI.
