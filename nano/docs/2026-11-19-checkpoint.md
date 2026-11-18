# Aster MCA Nano — saved checkpoint, 2026-11-19

[中文完整记录](../measurements/2026-11-18-peakhold/README.md) · [English](../measurements/2026-11-18-peakhold/README.en.md)

The November 18 bench session is preserved under `measurements/2026-11-18-peakhold/` with firmware, full raw archives, summaries, plots and offline verification. This publication did not access a board or generator.

Current hardware: AT32F423CCT7 v0.4.1 PTH core and peak-hold carrier. As-built analog rework is R104 49.9 kΩ, one R105 10 kΩ and C101 100 pF; C102 remains 470 pF. Archived CAD remains the original candidate, without silently incorporating the bench rework.

Installed firmware: `0.4.1-fast.7`; validated binary SHA-256 `e6a626ad15bb9c00f59dfa1767c5bcb3f14b45d59907700ba62f99f50eca4e2e`. Last saved profile: CPU 144 MHz, ADC 72 MHz, RAW 500 kSa/s, EARLY, PEAK 24.5 cycles, PHWAIT 500 µs, capture window 6 µs, additional read delay 1 µs. Last operator-confirmed generator state: **OFF**. Last recorded HOLD/RESET 1/1, fault 0, self-test 15; output-off check zero triggers. These are saved observations, not a fresh status query.

Key results:

1. Shorter waiting deadlines narrowed complete newly acquired Cs spectra at lower wall count rates. The 600-second record has an apparent channel-domain FWHM/centroid of 8.6658%, with fit-window/model limitations and no multipoint energy calibration.
2. Nominal electrical-pulse scans show a low-level response discrepancy. A repeated 500 mV point shifted by −2.1%, so smaller sweep deviations require repeatability checks.
3. RAW 300/400 mV peak and area ratios are 75.3%/74.7%, close to the nominal 75%. PEAK readout ratios are about 60–61.5%, including an immediate 300 mV recheck.
4. Sixteen balanced EARLY/LATE batches verified different actual stop timing, but both all-event amplitude medians were 39.25 codes. This switch did not solve the low-level deficit.
5. A no-signal attempt was stopped, preserved and followed by an explicit operator signal-path recheck before the valid comparison.

Open issue: the post-RAW hold/trigger/readout chain needs further characterization. Loop settling, diode/switch transients and reset/hold behavior are hypotheses, not established causes. The nominal component datasheet bandwidth and previous simplified simulation do not replace a same-event measurement.

Next planned work, **not yet run**: after the operator confirms reconnection and the generator setting, compare 2/4/6/10 µs capture windows at 300 mVpp/−150 mV with the same waveform, 976.5625 Hz and High Z. If a scope is available, observe RAW and buffered PEAK together to locate the onset of the amplitude loss. Retain raw data and actual timing/accounting, and restore the saved profile afterwards.

CH32 remains a separate diagnostic track with baseline drift and abnormal spikes unresolved. This checkpoint does not change its validation status.
