# FPGA firmware v1.14 experimental

This directory contains the FPGA firmware for the Aster MCA v0.1 board. It is
designed for the Gowin `GW1N-LV4QN88C6/I5` and a 10 MHz external ADC clock.
The v1.9 peak-height path is the conservative physically validated fallback.
The v1.14 image has also been exercised on the physical detector in volatile
SRAM and adds selectable fixed-window pulse area and digital trapezoidal
shaping for better use of the 4096-bin histogram.

The normal load target writes volatile FPGA SRAM only. It does not modify the
device's non-volatile configuration memory.

This firmware, its HDL testbenches, and the Python host utility were developed
with assistance from OpenAI Codex/ChatGPT, then checked by simulation, complete
synthesis/place-and-route, timing analysis, and physical prototype operation.
See [`../../AI-DISCLOSURE.md`](../../AI-DISCLOSURE.md).

## Data path

- Capture all 12 ADC12010 offset-binary inputs on the falling edge using the
  Gowin IDDR cells physically located in IOLOGIC.
- Re-register the IDDR output after one complete 10 MHz clock period before it
  reaches the MCA engine, eliminating placement-dependent bus tearing.
- Track the quiet baseline, initialized at midscale (2048).
- Detect negative-going pulses by default with threshold and half-threshold
  release hysteresis.
- Freeze baseline tracking during large opposite-polarity excursions.
- Apply a four-sample boxcar and require two consecutive samples to trigger.
- Extract peak amplitude, integrate a fixed 64-sample pulse-area window, or
  apply a 16-sample rise, 4-sample gap, 16-sample trapezoidal FIR with a
  selectable power-of-two output scale.
- Reject saturated or overlong events and wait 1 ms after saturation before
  accepting another event.
- Accumulate accepted energy estimates in 4096 32-bit histogram bins, with
  saturation into bin 4095 rather than wraparound.
- Report trigger, accepted, rejected, saturated, dropped, live-sample, and
  UART-error diagnostics.
- Drive a heartbeat/status LED and emit a 1 us trigger pulse on J4 pin 3.

## Build dependencies

- Yosys with Gowin support
- nextpnr-himbaechel
- `gowin_pack`
- Icarus Verilog (`iverilog` and `vvp`)
- Python 3
- openFPGALoader for CH347 JTAG access

An OSS CAD Suite distribution supplies the synthesis, place-and-route,
packing, and simulation tools. Put its `bin` directory on `PATH`, or pass it
to make:

```sh
make TOOLBIN=/absolute/path/to/oss-cad-suite/bin
```

## Test and build

```sh
make sim
make host-test
make
```

The final image is `build/aster-mca-v1.fs`. The conservative v1.9 image is
checked in as `prebuilt/aster-mca-v1.9.fs`; the detector-tested v1.14 SRAM image
is `prebuilt/aster-mca-v1.14-experimental.fs`. The packer output requires the
included revision-ID/first-frame CRC correction, which the Makefile applies
with `tools/patch_gowin_id_crc.py`.

## Load through the on-board CH347T

Detect the FPGA:

```sh
make detect
```

Load the newly built image into SRAM:

```sh
make load-sram
```

Load the checked-in, physically validated v1.9 image directly:

```sh
openFPGALoader -c ch347_jtag --freq 1000000 -m \
  prebuilt/aster-mca-v1.9.fs
```

Load the v1.14 experimental image into SRAM:

```sh
openFPGALoader -c ch347_jtag --freq 1000000 -m \
  prebuilt/aster-mca-v1.14-experimental.fs
```

The original v1.3 image remains available as a fallback:

```sh
openFPGALoader -c ch347_jtag --freq 1000000 -m \
  prebuilt/aster-mca-v1.3.fs
```

The v1.9 image was tested with two independently placed-and-routed builds. Both
used 12 IOLOGIC input cells and produced matching 30-second Cs-137 spectra.
See [`../../docs/algorithm-development.en.md`](../../docs/algorithm-development.en.md).

After a power cycle, load the image again.

## Host utility

`astermca.py` uses libusb to access the CH347T UART bulk endpoints directly.
The tested host is macOS with Homebrew libusb:

```sh
brew install libusb
python3 astermca.py info
python3 astermca.py stats
python3 astermca.py threshold 32
python3 astermca.py polarity negative
python3 astermca.py mode peak
python3 astermca.py acquire 600 --mode trapezoid8 -o spectrum-trapezoid8.csv
```

The eight v1.14 energy modes are `peak`, `area`, `area2`, `area4`, `area8`,
`trapezoid4`, `trapezoid8`, and `trapezoid16`. The area modes use a fixed
64-sample window. The trapezoid modes use the same 16/4/16 filter and divide
its output by 4, 8, or 16. Changing the mode clears the histogram and
statistics automatically, so different energy definitions cannot be mixed.
For the tested NaI(Tl)/PMT and Am-241 arrangement, start with `trapezoid8`,
negative polarity, and threshold 256. Other detectors require fresh tuning.

These are real multi-sample estimators, not relabelled x axes. In the measured
Am-241 A/B run, trapezoid `/8` placed the net peak near channel 1148 and left
no net events above channel 2048. Source, background, and net accepted rates
were 63.35, 4.65, and 58.70 cps. The local FWHM was still roughly 31%, while
frequent ADC rail hits showed that analogue clipping—not histogram binning—was
the remaining resolution limit. Always compare equal-live-time spectra and
the saturation counters before adopting a mode.

The CSV output contains `channel,counts`. `acquire` clears the previous
histogram, waits, reads the FPGA live-time statistics, downloads all 4096
bins, and saves them. Histogram transfer pauses event processing briefly;
use the reported FPGA live time rather than wall-clock time for precise rates.

## Graphical spectrum viewer

The GUI is a self-contained local application. It uses the same CH347/libusb
transport as `astermca.py`, but needs no Python GUI, plotting, or numerical
packages. Python serves the interface only on `127.0.0.1`; spectrum data does
not leave the computer.

On macOS, double-click `launch-gui.command`, or run:

```sh
python3 astermca_gui.py
# Or inspect the interface without a board:
python3 astermca_gui.py --demo
```

The viewer provides a live 4096-channel spectrum, linear/log display, mouse
ROI selection, total and ROI count rates, peak/FWHM estimates, timed runs,
algorithm settings, ADC/event diagnostics, CSV export, and PNG export. A full
16 KiB histogram read temporarily pauses event handling, so the default live
refresh is deliberately 5 seconds. For quantitative work, use FPGA live time
and freeze or slow the live refresh during long runs.

## Non-volatile FPGA configuration

The fitted GW1N-4 includes embedded configuration flash and can auto-boot
without loading SRAM after every power cycle. Permanent programming has not
yet been physically verified on this custom CH347T board, so first validate an
image in SRAM and follow the guarded procedure in
[`../../docs/permanent-fpga-configuration.md`](../../docs/permanent-fpga-configuration.md).
Do not make the experimental v1.14 image the first permanent image; use the
physically validated v1.9 build until internal-flash boot and the analogue
headroom correction have both been verified.

## Protocol

See [`../../docs/protocol.md`](../../docs/protocol.md).

## Diagnostic images

The `aster-mca-adc-pulldown.cst` and `top_adc_pd_high.v` targets are bring-up
diagnostics, not the production image. They distinguish an actively driven
ADC bus from a tri-stated bus. Do not leave them loaded for detector use.
