# AT32 peak-hold fast.7 — current bench firmware

[中文实验记录](../../measurements/2026-11-18-peakhold/README.md) · [English bench record](../../measurements/2026-11-18-peakhold/README.en.md) · [Protocol and original experiment plan](README.txt)

This is the experimentally used firmware for the **v0.4.1 PTH core plus peak-hold carrier**, not the old v0.3 desktop protocol. Low-amplitude readout bias remains unresolved. RAW/PEAK comparisons and the actual EARLY/LATE experiment are archived; the planned capture-window sweep has not been run.

The [prebuilt binary](prebuilt/aster-at32-peakhold-fast-7.bin) is 29,688 bytes, SHA-256 `e6a626ad15bb9c00f59dfa1767c5bcb3f14b45d59907700ba62f99f50eca4e2e`; see [manifest](prebuilt/manifest.json). A publication-time rebuild matched it exactly. fast.6 is preserved in the adjacent directory for rollback/reference.

From `nano/`, with the pinned SDK and compiler described in [development](../../docs/development.md):

```sh
AT32_SDK=/path/to/AT32F423_Firmware_Library python3 firmware/at32-peakhold-fast7/build.py
python3 firmware/at32-peakhold-fast7/check_software.py
python3 firmware/at32-peakhold-fast7/check_trigger_guards.py
python3 analysis/20261118/verify_checkpoint.py
```

These commands are offline. Hardware capture scripts open USB only when explicitly executed. `flash.py` expects build artifacts and checks the exact installed fast.6/fast.7 image before updating, with Flash/options backup and readback; it is not a generic blank-chip installer. The complete SDK and toolchain are external dependencies. Retain the project's [third-party notices](../../THIRD_PARTY_NOTICES.md) with redistributed binaries.

Boot defaults are RAW 1 MSa/s, LATE and PHWAIT 10 ms. The recorded bench profile is RAW 500 kSa/s, EARLY, PEAK 24.5 cycles and PHWAIT 0.5 ms, with a 6 µs window. Host tools configure that profile explicitly. Spectrum binning is performed on the host from event batches, with two ADC amplitude codes per channel; no true-live-time claim is made.
