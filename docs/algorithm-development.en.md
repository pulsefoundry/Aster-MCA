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
