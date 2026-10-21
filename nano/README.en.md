# Aster MCA Nano

[中文](README.md) | English

A low-cost, **32 × 18 mm USB multichannel pulse-height analyzer prototype**, with separate AT32 and CH32 development tracks. It accepts the low-voltage output of a detector's existing amplifier/shaper. The board samples pulses and accumulates a pulse-height histogram; the computer displays and saves the result.

This project is separate from the FPGA-based [Aster MCA](https://github.com/pulsefoundry/Aster-MCA).

## Development tracks

| Track | Status | Documentation | Branch |
|---|---|---|---|
| **AT32F423 + TLV9061** | Active spectroscopy track; 4 MS/s, 2048 channels, archived cesium-source measurements | [AT32 guide](docs/at32/README.en.md) | [codex/at32](https://github.com/pulsefoundry/Aster-MCA-Nano/tree/codex/at32) |
| **CH32X033F8P6** | **Baseline drift and abnormal spikes are still under investigation.** Analog-chain diagnostics are available; reliable spectroscopy has not been validated. | [CH32 status and hardware](docs/ch32/README.md) | [codex/ch32](https://github.com/pulsefoundry/Aster-MCA-Nano/tree/codex/ch32) |

`main` contains the overview, shared desktop software and experiment archives. The device branches provide separate entry points; each firmware implementation has its own directory. Documentation updated on 2026-10-21; latest physical-board measurements were recorded on 2026-10-18.

## AT32 prototype

<p>
  <img src="docs/at32/photos/IMG_1201.JPG" width="300" alt="Hand-soldered AT32 MCA Nano beside a fingertip for scale">
  <img src="docs/at32/photos/IMG_1202.JPG" width="300" alt="Powered AT32 MCA Nano connected to USB with two blue LEDs">
</p>

The photographed prototype uses an **AT32F423CCT7**, a **TLV9061** external op amp, a USB-A male connector and an SMA female connector. The PCB is 1.6 mm thick. Two blue LEDs indicate power and operation. Published photographs retain the original image pixels and display orientation, with location and other personal metadata removed.

## Current AT32 configuration

| Item | Configuration |
|---|---|
| PCB | v0.3, 32 × 18 mm; original design lists CBT7, tested hardware uses CCT7 |
| Analog rework | R21 = 40.2 kΩ, R22 = 10 kΩ; nominal U3 gain 5.02 |
| Firmware | **v0.8.2**: [source](firmware/at32-peak-scope), [validated binary](outputs/Aster-MCA-Nano-AT32-波形诊断-v0.8.2-20261018/aster-at32-peak-v0.8.2.bin) |
| Spectrum acquisition | 4 MS/s, 12-bit ADC; negative-pulse sampled-peak extraction; 2048 on-board bins; stop at the requested duration, then transfer the final histogram |
| Trigger threshold | **100 ADC codes for the reworked board**; historical unity-op-amp-gain configuration used 20 |
| Diagnostic waveforms | Idle-only captures of 4096 samples / 1.024 ms, uploaded after sampling stops; gaps exist between segments |
| Desktop software | macOS native app v0.6.1, [source and packager](firmware/at32-continuous/desktop); browser development UI also available |

The desktop UI currently restores a threshold of 20 on reconnect. **Set it to 100 for the reworked board.** The normal spectrum contains only the final histogram; it cannot be used to repeat event-level digital shaping after acquisition.

## Archived cesium-source spectra

![Latest 60-second AT32 cesium-source spectrum, all 2048 channels and a detail view](docs/at32/cs137-60s-spectrum.png)

Blue shows unsmoothed gross-source counts; gray shows background scaled to the source sampled duration, without subtraction. The left panel covers all 2048 channels, and the right panel shows channels 0–650. The original gain-comparison peak fits follow below.

![AT32 cesium-source peak fits before and after the gain rework, 60 seconds each](outputs/Aster-MCA-Nano-AT32-增益5倍实测-20261018/gain-peak-fit-comparison.png)

| Gross-source spectrum, 60 s | Before rework | After rework |
|---|---:|---:|
| Firmware | v0.8.0 | v0.8.2, same integer peak engine |
| Nominal op-amp gain / threshold | 1 / 20 codes | 5.02 / 100 codes |
| Accepted events | 15,896 | 17,611 |
| Peak centroid, ADC codes | 78.33 | 408.79 |
| FWHM / centroid | 17.20% | **16.07%** |

The plots use channel / ADC-code coordinates, without multipoint energy calibration. Fits use a bin-integrated Gaussian plus a nonnegative linear continuum on unsmoothed gross-source counts, rather than background-subtracted data. The post-rework fit varies from about 15.36% to 16.96% with the fit window. The model-conditional 95% interval for the after-minus-before change is −2.50 to +0.33 percentage points. A resolution improvement has **not** been established, and these results do not establish the detector's intrinsic resolution.

The latest 60.000256 s acquisition accepted 17,611 events and processed all 58,594 DMA blocks, with no reported device error or ADC overflow. This validates that recorded run; it does not establish performance over every input rate.

- [Latest native 2048-channel spectrum CSV](outputs/Aster-MCA-Nano-AT32-增益5倍实测-20261018/Cs-source-60s-2048ch.csv) and [metadata](outputs/Aster-MCA-Nano-AT32-增益5倍实测-20261018/Cs-source-60s-2048ch-metadata.json).
- [Source/background histograms, finite raw waveforms and fits](outputs/Aster-MCA-Nano-AT32-增益5倍实测-20261018); [detailed checkpoint](docs/2026-10-18-checkpoint.md).
- [Earlier 10-minute v0.6.3 cesium spectrum](outputs/Aster-MCA-Nano-AT32-v0.6.3-铯源10分钟分辨率-20261016/铯源谱与分辨率拟合.png), retained as history. Its integral estimator and configuration differ from the current peak mode.

## AT32 single-board cost

**Priced subtotal: approximately CNY 17.86 per board, plus the actual USB-A connector, SMA connector and two stock LEDs.**

| Item | CNY per board |
|---|---:|
| PCB, project-specified cost | 4.00 |
| AT32 MCU, project-specified cost | 5.00 |
| Other quoted parts, current reworked population | 8.855465 |
| **Priced subtotal** | **17.855465 ≈ 17.86** |
| USB-A, SMA, LED1/LED2 | Actual prices unavailable; excluded |

Other component prices come from the project's **2026-10-10 LCSC quotation**, multiplied by fitted single-board quantities. They are historical costs, not current retail quotes. The calculation does not allocate all minimum-order stock or spares to a single board. Shipping, assembly labour, enclosure and detector electronics are excluded. See the bilingual [itemized cost and part numbers](docs/at32/cost.md) and [price inputs](docs/at32/cost-inputs.json).

## Schematics, Gerbers and assembly

| Download | AT32 v0.3 | CH32 v0.3 |
|---|---|---|
| Schematic PDF | [AT32 schematic](outputs/Aster-MCA-Nano-AT32-v0.3-USB-A-LED/Aster-MCA-Nano-AT32-v0.3-USB-A-LED-Schematic.pdf) | [CH32 schematic](outputs/Aster-MCA-Nano-CH32-v0.3-USB-A-LED/Aster-MCA-Nano-CH32-v0.3-USB-A-LED-Schematic.pdf) |
| Gerber ZIP | [AT32 Gerbers](outputs/Aster-MCA-Nano-AT32-v0.3-USB-A-LED/Aster-MCA-Nano-AT32-v0.3-USB-A-LED-Gerber.zip) | [CH32 Gerbers](outputs/Aster-MCA-Nano-CH32-v0.3-USB-A-LED/Aster-MCA-Nano-CH32-v0.3-USB-A-LED-Gerber.zip) |
| EasyEDA project, BOM and board views | [AT32 hardware package](outputs/Aster-MCA-Nano-AT32-v0.3-USB-A-LED) | [CH32 hardware package](outputs/Aster-MCA-Nano-CH32-v0.3-USB-A-LED) |
| Hand-assembly reference | [AT32 assembly](outputs/Aster-MCA-Nano-AT32-v0.3-焊接对照) | [CH32 assembly](outputs/Aster-MCA-Nano-CH32-v0.3-焊接对照) |

The original v0.3 schematic/BOM is archived unchanged: R21 = 0 Ω and R22 = DNP. Apply the documented [R21/R22 gain rework](outputs/Aster-MCA-Nano-AT32-增益改焊-20261018) to reproduce current AT32 measurements. The historical CH32 removal of C9 was a diagnostic change and must not be copied to AT32. Match connector substitutes to the footprint and actual PCB thickness; the externally sourced connectors in the photographs are not confirmed to be the original BOM part numbers.

The [historical paired-board panel](outputs/Aster-MCA-Nano-v0.3.1-SlotCut-Bridge2p5-32x38) was rejected by the fabricator for containing two designs in one file. Use the two independent single-board Gerber packages above.

## Build, run and reproduce

See the [development guide](docs/development.md) for firmware builds, native desktop packaging, offline analysis and archive verification. The original ARM toolchain and AT32 SDK are pinned there. `work/`, third-party toolchains, virtual environments and temporary captures are not committed.

Historical v0.7.x waveform-streaming experiments failed sustained processing with real pulses. v0.8.1 RAW capture was rejected after ADC overflow. Neither is the current acquisition release. The v0.8.2 flasher is a guarded historical updater, not an arbitrary blank-chip installer; see the [AT32 guide](docs/at32/README.en.md).

## Licensing

A project-wide open-source license has not yet been selected. Public visibility does not change third-party license terms. WCH code retains its original notices and WCH-microcontroller-only restrictions; see [SOURCE-NOTES](firmware/ch32-selftest-v0.3/SOURCE-NOTES.txt). Obtain the AT32 SDK and complete toolchains from their original sources.
