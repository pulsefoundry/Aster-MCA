# Prototype validation record

## Setup

- Hardware: repaired Aster MCA v0.1 prototype.
- Firmware: v1.3 loaded into FPGA SRAM.
- Detector: amplified 1-inch NaI(Tl)/PMT module.
- Source: Cs-137 check source in a repeatable nearby position.
- Pulse polarity: negative-going ADC codes.
- Trigger threshold: 32 ADC codes.
- Analog gain: approximately ×3.33, using matched 4.99 kohm R66/R67 in
  parallel with the fitted 10.0 kohm feedback pair.
- Source live time: 943.493 s.
- Background live time: 30.017 s.

## Raw statistics

| Quantity | Source | Background |
| --- | ---: | ---: |
| Saved events | 237943 | 2333 |
| Count rate | 252.19 counts/s | 77.72 counts/s |
| Net source rate | 174.47 counts/s | — |
| Histogram drops | 0 | 0 |

The source acquisition reported 294804 triggers, 237942 accepted events,
56862 rejected events, and 6562 saturated events. The one-count difference
between the statistics snapshot and saved histogram is consistent with an
event arriving between the two host reads.

## Spectrum result

The source and background spectra were normalized by FPGA live time. After
background subtraction, the full-energy feature was centered near channel
95.8. A five-bin smoothing pass and a linear local-continuum estimate gave a
preliminary FWHM of about 11.0 channels, or approximately 11.5% at the assumed
662 keV Cs-137 line.

This is an engineering validation, not a calibrated spectroscopy claim:

- only one known gamma line was available;
- the background run was much shorter than the source run;
- source geometry was not metrologically fixed;
- BNC grounding and the U8 repair were still prototype arrangements;
- the calculation did not perform a full detector-response fit.

The important result is that the independent source and background runs show
a stable, source-dependent peak with zero histogram drops and a baseline that
remained near midscale.

![Source, background, and net spectrum](images/cs137-spectrum.png)

Raw files:

- `examples/cs137/source-943s.csv`
- `examples/cs137/background-30s.csv`
