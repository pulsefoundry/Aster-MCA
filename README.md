# Aster MCA

[简体中文](README.zh-CN.md)

Aster MCA is a compact, USB-powered 4096-channel pulse-height analyzer for
already-amplified detector signals. It combines a 12-bit 10 MSPS ADC, a Gowin
GW1N-4 FPGA, and a CH347T USB/JTAG/UART bridge on one 90 mm × 70 mm four-layer
board.

> **Prototype status:** revision 0.1 has acquired a repeatable Cs-137 spectrum
> from an amplified NaI(Tl)/PMT probe, but the published as-built hardware has
> three mandatory assembly notes. Do not order or assemble the v0.1 production
> package unchanged. See [Hardware errata](docs/hardware-errata-v0.1.md).

![Assembled Aster MCA v0.1 prototype board](docs/images/photos/aster-mca-board-front.jpg)

*Assembled and physically validated v0.1 prototype.*

## What works

- ADC12010 parallel capture at 10 MSPS.
- FPGA baseline tracking, threshold detection, peak-height extraction, pulse
  rejection, saturation recovery, and a 4096 × 32-bit histogram.
- USB communication on macOS through the on-board CH347T and libusb; no serial
  driver or external programmer is required.
- Volatile SRAM configuration over the same USB-C connector.
- Live diagnostics for ADC min/max/baseline, triggers, accepted/rejected and
  saturated events, histogram drops, live samples, and UART errors.
- Repeatable source-versus-background separation on the first repaired boards.

The current physically validated firmware is **v1.9**. It keeps the proven v1.3
MCA algorithm but moves all 12 ADC inputs into dedicated falling-edge IOLOGIC
registers, followed by a full-cycle fabric pipeline stage. Two independently
placed images now produce matching Cs-137 spectra. FPGA configuration is
volatile and must be reloaded after power loss.

## Aster MCA v2.0 concept

The repository also contains a routed, explicitly unreleased
[v2.0 high-performance concept](hardware/rev2.0-preliminary/README.md): a
16-bit 40 MSPS ADS5560, Intel MAX 10 FPGA, directly soldered RP2350 host module,
and three fixed analogue ranges of approximately 0.5x, 5x and 25x. The current
r8 CAD passes ERC, DRC and an independent 489-pin network audit, and its THS4551
front end has reproducible analogue simulations.

v2.0 has no FPGA firmware or physical prototype yet. Its manufacturing files
are published for review and quotation only and must not be treated as a
production release.

## Prototype photographs

| Powered bench prototype | Second PCB during assembly and inspection |
| --- | --- |
| ![Powered Aster MCA prototype](docs/images/photos/aster-mca-running.jpg) | ![Second Aster MCA PCB during assembly](docs/images/photos/aster-mca-board-assembly.jpg) |

![Initial Cs-137 bench setup](docs/images/photos/aster-mca-test-setup.jpg)

The full bench setup shows the amplified NaI(Tl)/PMT probe, oscilloscope,
Aster MCA prototype, and host computer during the initial Cs-137 validation.
The spectrum window in this photograph still carries the pre-release working
name used before the project was renamed Aster MCA.

## Measured prototype result

The initial validation used an amplified 1-inch NaI(Tl)/PMT probe and a Cs-137
check source. The analog stage was set to approximately ×3.33, the trigger
threshold was 32 ADC codes, and negative-going pulses were selected.

| Quantity | Result |
| --- | ---: |
| Source live time | 943.493 s |
| Source count rate | 252.19 counts/s |
| Background count rate | 77.72 counts/s |
| Net source rate | 174.47 counts/s |
| 662 keV peak position | about channel 95.8 |
| Preliminary FWHM | about 11.0 channels |
| Preliminary resolution | about 11.5% |
| Histogram drops | 0 |

These numbers describe one prototype setup, not a guaranteed instrument
specification. The energy estimate is based on a single known line, a short
background run, and a simple local-continuum subtraction. Raw CSV files are in
[`examples/cs137`](examples/cs137/).

![Measured Cs-137 spectrum and background](docs/images/cs137-spectrum.png)

## Analog gain options

R62/R63 are the matched 1.00 kohm `RG` pair and R64/R65 are the fitted matched
10.0 kohm `RF` pair. R66 and R67 are optional **parallel** feedback positions:
leave both open for nominal gain ×10, or fit the same value on both sides to
reduce the gain. The measured Cs-137 setup used 4.99 kohm, 0.1% at both R66 and
R67, giving `10k || 4.99k ≈ 3.33k` and nominal gain about ×3.33. Never populate
only one of the pair. See [Analog gain configuration](docs/gain-configuration.md)
for the formula, component roles, and calibration consequences.

## Signal path

```text
conditioned detector pulse
        │
        ▼
AC coupling and bias ──► AD8137 differential driver
        │
        ▼
ADC12010, 12 bit / 10 MSPS ──► GW1N-4 FPGA
        │                          │
        │                          ├─ baseline and peak extraction
        │                          └─ 4096-bin histogram
        ▼
CH347T USB UART/JTAG ──► macOS host utility
```

The BNC input is **low-voltage and signal-only**. The board has no detector
high-voltage supply, no high-voltage blocking network, and no charge-sensitive
preamplifier. Never connect a PMT bias line, a bare photomultiplier, or a
high-voltage detector cable directly to the input.

## Complete schematic

[![Complete five-sheet Aster MCA v0.1 schematic](docs/images/schematic/aster-mca-v0.1-schematic-overview.png)](hardware/rev0.1-as-built/reference/Schematic.pdf)

The image above combines all five sheets of the as-built v0.1 schematic; click
it to open the original full-resolution PDF. It documents the manufactured
prototype and therefore includes the known U8, S1, and U6 assembly notes. Read
the [hardware errata](docs/hardware-errata-v0.1.md) before fabrication.

![Aster MCA v0.1 PCB preview](docs/images/pcb-preview.webp)

## Repository layout

- `hardware/rev0.1-as-built/` — EasyEDA Pro source, Gerbers, BOM, CPL,
  schematic, netlist, and pin/net reference for the manufactured prototype.
- `firmware/mca-v1/` — synthesizable Verilog, constraints, simulations, host
  utility, tests, and validated v1.3 and v1.9 SRAM images.
- `docs/` — bring-up procedure, protocol, hardware errata, and validation
  notes.
- `examples/cs137/` — raw spectrum and background CSV files.

## Fabrication archive

The complete v0.1 as-built package is available as
[`Aster-MCA-v0.1-as-built-production.zip`](release/Aster-MCA-v0.1-as-built-production.zip).
It contains the native EasyEDA Pro project, Gerbers, BOM, CPL, schematic,
netlist, pin/net reference, assembly overrides, and hardware licence. This is
the manufactured prototype archive, not a corrected production release: read
the included notice and [v0.1 errata](docs/hardware-errata-v0.1.md) first.

## Quick start with an existing repaired board

Requirements on macOS:

```sh
brew install libusb openfpgaloader iverilog
```

Load the tested prebuilt image into FPGA SRAM:

```sh
cd firmware/mca-v1
openFPGALoader -c ch347_jtag --freq 1000000 -m \
  prebuilt/aster-mca-v1.9.fs
```

The original v1.3 image remains available as a fallback. See
[Algorithm development](docs/algorithm-development.en.md) for the ADC capture
fault, physical placement-seed test, and the rules for future algorithm A/B
comparisons.

Read the board and acquire a spectrum:

```sh
python3 astermca.py info
python3 astermca.py stats
python3 astermca.py acquire 600 --threshold 32 -o spectrum.csv
```

For a first power-up, follow [`docs/bring-up.md`](docs/bring-up.md) rather than
connecting a detector immediately.

## Build and test

The FPGA build uses Yosys, nextpnr-himbaechel, `gowin_pack`, Icarus Verilog,
and openFPGALoader. The easiest route is an OSS CAD Suite release with its
`bin` directory on `PATH`.

```sh
cd firmware/mca-v1
make sim
make host-test
make
make detect
make load-sram
```

You can instead pass an OSS CAD Suite binary directory explicitly:

```sh
make TOOLBIN=/absolute/path/to/oss-cad-suite/bin
```

## Hardware revision warning

Revision 0.1 is published for transparency and reproducibility, not as a
drop-in production release:

1. **U8:** the released BOM specifies `LMV321IDBVR`, but the PCB net map expects
   the pin order of `MCP6001T-I/OT`. Fit the plain MCP6001T-I/OT variant or
   apply the documented bypass. Do not fit MCP6001R or MCP6001U.
2. **S1:** leave the reset switch unpopulated. The footprint contact pairing
   can hold `RECONFIG_N` low on the assembled board.
3. **U6:** the originally specified `SGM2037-1.2XN5G/TR` remains recommended
   for a new build. The substitute `AP2112K-1.2` was later verified to start
   successfully without added output capacitance. Extra parallel output
   capacitance is not normally required; consider it only if oscilloscope
   measurements confirm that an excessively fast +1V2 rise causes FPGA
   configuration or startup failure, then re-check regulator stability,
   overshoot, and repeatable FPGA configuration.

Read the full [v0.1 errata and recovery procedure](docs/hardware-errata-v0.1.md)
before using the fabrication files.

## Contributing

Bug reports, measurements from other detector/front-end combinations, host
support for additional operating systems, HDL review, and a corrected hardware
revision are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## AI-assisted development

The FPGA firmware, HDL tests, Python host utility, and parts of the technical
documentation were developed with assistance from OpenAI Codex/ChatGPT. The
release was subsequently checked by simulation, synthesis/place-and-route,
timing analysis, and operation on the physical prototype. See the full
[AI development disclosure](AI-DISCLOSURE.md).

## License

Hardware design files are licensed under CERN-OHL-P-2.0. Firmware, host
software, documentation, tests, images, and example data are licensed under
MIT. See [LICENSE.md](LICENSE.md) for the exact scope and full licence texts.
