# FPGA algorithm and ADC-capture development

[简体中文](algorithm-development.md)

## Current conclusion

**v1.9 is the current physically validated firmware.** It keeps the baseline,
trigger, peak-height, and 4096-bin histogram algorithm from v1.3 and changes
only the ADC input path:

```text
parallel ADC bus
      |
      +-- 12 IOLOGIC IDDR cells, falling-edge capture
      |
      +-- one rising-edge fabric register, full-cycle timing margin
                |
                +-- v1.3 MCA engine
```

The extra register adds a fixed 100 ns latency at 10 MHz. It does not alter
pulse height or count rate.

**v1.14 is an experimental build that has completed physical SRAM A/B tests.**
It preserves the complete v1.9 capture path and peak-height mode, and adds a
four-sample input filter, two-sample trigger confirmation, a fixed 64-sample
area gate, and a 16-sample rise, 4-sample flat-top, 16-sample fall digital
trapezoid. Trapezoid output can be divided by 4, 8, or 16. Over-range events
are treated as saturated rather than wrapping into the low-energy region, and
changing mode clears the histogram automatically.

This is not cosmetic x-axis multiplication: the trapezoid is a finite impulse
response filter over multiple baseline-subtracted samples. It suppresses slow
tails and reduces single-sample phase sensitivity. It materially improves use
of the 4096-bin histogram, but the current x10 analogue gain still drives many
source pulses into the ADC rails. Digital processing cannot restore clipped
amplitudes, so v1.14 remains marked experimental.

## Why capture timing had to be fixed first

The original v1.3 design captured the 12-bit bus on the falling edge with
ordinary fabric registers. Their placement and input-routing delay were left to
place-and-route, without a robust input timing relationship.

An exact source rebuild was byte-for-byte identical to the checked-in v1.3
image. Re-running only place-and-route with seed 1, however, changed a 30-second
run from roughly 9,000 triggers and 1,500 rejected events to 53,364 triggers,
46,437 rejected events, and 1,737 saturated events. Baseline also moved from
about 2034 to 2106. Therefore several earlier apparent algorithm effects were
confounded by placement-dependent ADC bus tearing.

## Two-stage repair

1. **v1.8** placed one Gowin `IDDR` on every ADC pin. Baseline became correct,
   but IDDR Q1 still crossed into same-edge MCA logic; seed 1 produced 37,687
   triggers and 30,645 rejections.
2. **v1.9** added a fabric register after IDDR, providing a complete 100 ns
   IOLOGIC-to-fabric cycle. The placement-seed-dependent false triggers vanished.

## Physical v1.9 A/B result

The same NaI(Tl)/PMT detector, Cs-137 position, 32-code threshold, and 30 seconds
of FPGA live time were used:

| Item | Default placement | Seed 1 placement |
| --- | ---: | ---: |
| Triggers | 9,258 | 9,177 |
| Accepted | 7,782 | 7,742 |
| Rejected | 1,476 | 1,435 |
| Saturated | 207 | 183 |
| Mean accepted rate | 259.282 cps | 257.955 cps |
| Local Cs-137 peak | channel 99 | channel 99 |
| Centroid, channels 85-114 | 99.57 | 99.26 |

The mean channels over 32-159 were 62.97 and 63.03. These differences are
consistent with short-run counting statistics rather than the catastrophic
placement sensitivity of the old capture path.

## Build result

| Resource or timing item | Default placement | Seed 1 |
| --- | ---: | ---: |
| LUT4 | 2,120 / 4,608 | 2,117 / 4,608 |
| DFF | 982 / 3,456 | 982 / 3,456 |
| BSRAM | 8 / 10 | 8 / 10 |
| IOLOGICI | 12 / 198 | 12 / 198 |
| Estimated maximum clock | 61.13 MHz | 55.06 MHz |
| Required clock | 10 MHz | 10 MHz |

## Energy-estimator development from v1.10 through v1.14

- v1.10 first added scaled pulse area. Physical spectra later showed that
  ending the integral at threshold release quantised pulse width into a comb.
- v1.13 changed area measurement to a fixed 64-sample gate and required a
  baseline return at the end. The comb disappeared, but the Am-241 maximum
  remained near channel 392 with a long high-energy tail.
- v1.14 added the 16/4/16 trapezoidal FIR with `/4`, `/8`, and `/16` scales.
  HDL tests cover low-energy gain, over-range clamping, long-pulse rejection,
  clearing, and the default peak path. UART tests cover `M`, modes 0 through 7,
  and CRC. Host tests cover both 44- and 46-byte statistics payloads.
- Complete v1.14 place-and-route passes the 10 MHz requirement with an
  estimated maximum clock around 42.3 MHz.

With the same NaI(Tl)/PMT, Am-241 position, negative polarity, threshold 256,
and trapezoid `/8`, an 81.71 s source run measured 63.35 cps and a 105.36 s
background run measured 4.65 cps. Net rate was 58.70 cps, the subtracted peak
was near channel 1148, and there were no net counts above channel 2048. Local
FWHM was roughly 31%. A separate 32/8/32 long-shaper trial raised accepted rate
to about 155 cps but worsened FWHM to about 49%, so it did not replace 16/4/16.

The next step is to reduce analogue gain from x10 so the ADC no longer reaches
either rail, then retune trapezoid `/4` or `/8` and consider pole-zero
correction. Increasing digital channel gain alone cannot repair clipping.

## Treatment of earlier algorithm experiments

The v1.4 boxcar, v1.5 two-sample confirmation, v1.6 light confirmation, and
v1.7 baseline-rounding experiments were all physically exercised. Each build
also changed placement, so their spectrum differences can no longer be
attributed to the algorithm alone. They must not be published as recommended
images.

Future algorithm A/B tests must start from the v1.9 capture path, keep detector,
source, bias, gain, threshold, and FPGA live time fixed, and confirm the result
with at least two placement seeds. Trigger, accepted, rejected, saturated, and
dropped counters should be retained before comparing peak position and FWHM.

The next useful algorithm feature is a small triggered-waveform capture or
separate rejection-reason counters, followed by state-machine tuning based on
measured pulse shapes.
