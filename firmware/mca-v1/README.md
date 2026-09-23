# FPGA firmware v1.9

This directory contains the physically validated FPGA firmware for the Aster
MCA v0.1 board. It is designed for the Gowin `GW1N-LV4QN88C6/I5` and a 10 MHz
external ADC clock.

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
- Extract the peak amplitude after four quiet samples.
- Reject saturated or overlong events and wait 1 ms after saturation before
  accepting another event.
- Accumulate accepted peak heights in 4096 32-bit histogram bins.
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

The final image is `build/aster-mca-v1.fs`. A physically validated copy is
checked in as `prebuilt/aster-mca-v1.9.fs`. The packer output requires the
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
python3 astermca.py acquire 600 -o spectrum.csv
```

The CSV output contains `channel,counts`. `acquire` clears the previous
histogram, waits, reads the FPGA live-time statistics, downloads all 4096
bins, and saves them. Histogram transfer pauses event processing briefly;
use the reported FPGA live time rather than wall-clock time for precise rates.

## Protocol

See [`../../docs/protocol.md`](../../docs/protocol.md).

## Diagnostic images

The `aster-mca-adc-pulldown.cst` and `top_adc_pd_high.v` targets are bring-up
diagnostics, not the production image. They distinguish an actively driven
ADC bus from a tri-stated bus. Do not leave them loaded for detector use.
