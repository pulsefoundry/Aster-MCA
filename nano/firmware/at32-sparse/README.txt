Aster MCA Nano AT32 — 4 MS/s waveform-window test firmware v0.4.3

Hardware: AT32F423CCT7, v0.3 board. PA0 ADC input, active-low RUN PB12,
PA9 VBUS input only. Original analog network is unchanged.
CPU 144 MHz, APB1 72 MHz / TMR3 144 MHz, ADC 72 MHz, 2.5-cycle sample time.
TMR3 ARR=35 PSC=0 gives 4 MS/s. ADC external-trigger spacing is 18 ADC cycles.
ADC XTEST=9 before calibration, USB HICK/ACC setup retained.

This is continuous ADC acquisition, NOT complete raw-waveform transport.
8192-sample circular DMA, 4096 samples per half (1.024 ms).
Every sample is scanned in 256-sample blocks (64 us). The MCU selects a
block when max(current plus preceding two blocks) - min(current) >= threshold.
This conservative gate preserves any block containing a host negative crossing
using the preceding 256-sample baseline and 16-sample guard. It intentionally
allows false positives. It does NOT measure energy or count physical events.
Each selected block retains two prior blocks and one following block.
Overlapping windows are sent once. A four-block baseline snapshot is retained
once per nominal second. Selected 12-bit samples are delta-compressed losslessly.

The PC keeps the absolute sample indices; gaps reset DSP history. It does not
stitch gaps together. Baseline 64 us, guard 4 us, event window 16 us including
1 us pretrigger; integrals over the first 4/8/16 us retain code*us units.
Host accepted-event count differs from MCU candidate-block count by design.
Startup DSP warmup is 68 us. Events incomplete at the end or a gap are excluded
and counted. A run ending with a selected final block may lack up to 64 us of
post-context; terminal metadata records this. Acquisition time is not MCA live time.

Protocol: ASTS04 CR LF, 80-byte header, 18 LE u32 fields. Frame sequence is
contiguous; sample indices may have explicit aligned gaps. Header, compressed
payload and decoded raw samples each have FNV checksums. The terminal frame
checks DMA/scanned-block/sample/frame/candidate-block counts. Any DMA overrun,
CPU deadline failure, queue full, USB stall, bad sequence or bad checksum makes
the record invalid. No silent dropping/resynchronization. All raw frames and
failure diagnostics are retained. Intentionally skipped baseline samples cannot
be reconstructed. High noise or high count rate can saturate the link/CPU.

Files: stream.asts = wire data; selected-samples.u16 = packed selected samples;
blocks.jsonl maps each stored offset to its absolute sample index. Never plot
selected-samples.u16 as a contiguous time series. events.csv, spectrum.csv,
capture.json and spectrum-summary.json store host results and validation.

Build: python3 firmware/at32-sparse/build.py
Tests: python3 -m unittest discover -s firmware/at32-sparse -p test_sparse.py
Flash after physical BOOT: python3 firmware/at32-sparse/flash.py
This updater expects exact v0.4.2, backs up flash/options, checks complete readback
and unchanged data outside the erased application pages. No option-byte writes.
Rollback from exact v0.4.3: same command with --restore-1m, after physical BOOT.

CPU history: v0.4.0 and v0.4.1 failed the 4M processing deadline even with
open input; those records are invalid. v0.4.3 uses a much lighter conservative
gate and combined scan/copy. Hardware acceptance must be recorded separately;
passing software tests or valid transport does not establish energy resolution.
The analog settling/noise of R20=100 ohm, C9=1 nF at the ADC input needs bench
verification. A 4 us detector pulse has about 16 samples at 4M; its peak may
still need interpolation or integral/template processing on the PC.

Verified hardware checkpoint: 2026-10-14, v0.4.3.
SIMD min/max/copy scans two 12-bit samples per iteration without dropping bits.
Twelve on-device SIMD/copy reference cases pass (selector_fault=0).
At threshold 64 ADC codes, 3 s + 30 s open-SMA tests completed with zero ADC,
DMA, deadline or queue errors. 30-second run scans 120000512 samples; worst
process time 69585/144 MHz = 0.48323 ms per 1.024 ms DMA half.
8 samples sampled during stop interrupt latency are explicitly excluded after
the last complete DMA half; this is an end trim, not a gap in the exposure.
At threshold 20 the open-input waveform fluctuations caused many candidate
blocks and processing deadline failure. 64 is a temporary diagnostic threshold,
not proof of preserved low-energy sensitivity. It is now the GUI 4M default;
1M remains 20. No 4M detector throughput or source spectrum yet verified.
