# AT32 v0.4.1 peak-hold board-pair errata

[中文](errata.md) · English · [BOM and placement aids](README.en.md) · [Full measurements](../../../measurements/2026-11-18-peakhold/README.en.md)

Status as of 2026-11-19, covering the v0.4.1 PTH core and peak-hold carrier. Confirmed assembly issues, bench rework and unresolved performance are listed separately. Frozen CAD/Gerbers retain their original release state.

## 1. Incomplete reference and pin-1 silkscreen

The manufactured boards lack complete reference labels and sufficiently clear IC pin-1 marks for hand assembly. Use the component-side top views for the [core](core-locator.png) and [carrier](carrier-locator.png); do not mirror them. Red `1` circles mark pin 1 and `K` marks cathodes. With BOOT/LED on the left in the core drawing, U1 pin 1 is at the lower right. With USB left and SMA right in the carrier drawing, U12 pin 1 is at the lower left.

These images supply missing assembly information. A manufacturing release with corrected silkscreen has not been published; the archived Gerbers still contain the original markings.

## 2. Insufficient D11 hand-soldering margin

D11 is BAS316,115, SOD-323, LCSC C109218. The operator reported that its pads were too small for comfortable hand soldering. A later revision should enlarge the solderable area and recheck clearance; no revised pad dimensions have been physically validated.

Check polarity against the native netlist: **D11 pin 1 = K / HOLD_CAP; pin 2 = A / PEAK_DIODE_A**. D12 is a different part: BAS70-04,215, SOT-23; pin 1 = A / PEAK_FB, pin 3 = K / PEAK_DRV, pin 2 NC. See the [carrier native netlist](../../../hardware/at32-v0.4.1-pth/carrier/native/Schematic-netlist.net).

## 3. Override the archived R105/C101 values for bench reproduction

| Reference | Frozen design / original assembly record | Confirmed bench configuration |
|---|---|---|
| R104 | 49.9 kΩ | Retain 49.9 kΩ |
| R105 | 49.9 kΩ | **Replace with one 10 kΩ resistor**, not a parallel addition |
| C101 | DNP, small compensation footprint | **Fit 100 pF** |
| C102 | 470 pF | Retain 470 pF |

With SMA disconnected and the ADC disabled, the operator still observed sustained RAW oscillation at approximately 4 MHz and 400 mVpp. After fitting C101, the operator reported that the sustained oscillation disappeared and RAW was approximately 0.6 V DC. This is a bench observation, not validation across temperature and load. C101 also changes the front-end frequency response and pulse shape.

The fitted R105 tolerance/manufacturer/part number and the fitted C101 manufacturer/dielectric were not recorded. Those BOM fields remain blank rather than borrowing another reference's part number. C0G/NP0 is preferred for reproducing C101.

## 4. Low-amplitude mapping bias remains unresolved

For nominal 300/400 mV negative pulses, RAW peak and area ratios are approximately **75.3%/74.7%**, close to the nominal 75% input ratio. Held-amplitude ratios are only about **60–61.5%**. The EARLY/LATE comparison changed the actual stop timing, but all 16 batches still had amplitude medians of 39.25 ADC codes. It did not recover the missing low-level response. The available evidence does not isolate the diode, op amp, switch, hold capacitor or firmware as the sole cause.

The ten-minute cesium fit gives **8.67% FWHM/centroid in channel coordinates**, with fit-window sensitivity and model mismatch. Multipoint energy calibration has not been performed. This is not a validated calibrated resolution at 662 keV. See the [amplitude, RAW and stop-phase comparisons](../../../measurements/2026-11-18-peakhold/README.en.md).

## 5. Assembly and firmware scope

- Board interfaces have **22 holes, 2.0 mm pitch and 0.8 mm drill diameter**. Standard 2.54 mm headers do not fit. The core BOOT/LED side faces carrier USB; a rotated photograph is not the orientation reference.
- C100 is **33 nF, 0805**. Core C12 (100 pF, 0402) and carrier C101 (100 pF, 0603) use different packages.
- SW2 is an optional reset switch with default BOM quantity zero; add one if desired. C103 is DNP and J3 provides alternative wire pads.
- The current peak-hold bench uses **fast.7**. The old v0.8.2 firmware/v0.3 desktop protocol does not control it. Power-on defaults are RAW 1 MSa/s, LATE and PHWAIT 10 ms; the saved bench profile uses RAW 500 kSa/s, EARLY and PHWAIT 0.5 ms, explicitly set by the host. See [firmware and tools](../../../firmware/at32-peakhold-fast7/README.md).
- The hold-capacitor node is sensitive to probe loading. Prefer the buffered PEAK_ADC/PEAK_OUT node when checking hold voltage; the measurement connection can affect the result.

This errata records the existing prototypes. It does not claim completed silkscreen, D11-pad or low-level-linearity design fixes.
