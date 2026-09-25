# Aster MCA v2.0 r7 — simulation and electrical audit

Date: 2026-09-25
Design under test: `source/Aster-MCA-v2.0.kicad_sch` and
`source/Aster-MCA-v2.0.kicad_pcb`
Overall status: **HOLD FOR ONE ANALOGUE VALUE CHANGE AND DIGITAL COMPILE**

## Executive result

The core analogue topology runs in simulation. The 0.5x, 5x and 25x selected
gain networks produce 0.5015x, 4.9688x and 25.3930x respectively, which agrees
with the resistor calculations. The current r7 CAD also passes a fresh ERC and
DRC, and an independent board-to-manifest comparison found no connectivity,
value, DNP or footprint-reference mismatch.

One actionable problem was found: with the presently fitted **R9 = R10 =
10 ohm** and C2 = 2.2 nF, the TI THS4551 model predicts sustained/growing
high-frequency ringing in the 0.5x range. The AC sweep shows the same mode as a
9.74 dB peak near 35.5 MHz. A value sweep shows that changing **R9 and R10 to
22 ohm** removes the simulated ringing and peaking while retaining about 1.65 MHz closed-
loop bandwidth and approximately 0.44 us 1% settling for the tested pulse.
This is a BOM/value-only change; the nets and PCB placement do not need to move.

This report does **not** claim that the complete instrument can already boot.
There is not yet an exact MAX 10 Quartus project/bitstream for v2, so FPGA pin
legality, timing closure, ADC capture and RP2350 communication remain release
gates.

## What was actually simulated

- KiCad-bundled ngspice 45.2 shared library on macOS;
- TI THS4551 official PSpice macro-model from SBOMB92B;
- 5 V THS4551 supply and 1.5 V ADS5560 VCM drive;
- the actual r7 input and feedback resistor values;
- R9/R10 output isolation, C2 differential capacitor and a high-impedance ADC
  load;
- scaled negative small-signal pulses for all three ranges;
- a 2 us, -2.7 V source pulse for overload exploration;
- 10 Hz to 100 MHz AC sweeps;
- an R9/R10 damping sweep from 10 ohm to 100 ohm.

The TI model contains three PSpice `TABLE` controlled sources and PSpice switch
threshold syntax that the KiCad ngspice build cannot use directly. The included
preparation script translates each table to a behavioural PWL source with the
same data points and converts ON/OFF thresholds to the equivalent centre and
hysteresis values. No model electrical data points are altered.

The ADS5560 is represented by the board's external 2.2 nF differential
capacitor and a high-impedance differential load. Its internal sampled input,
aperture behaviour, code quantisation and kickback are not modeled. Therefore
the R9/R10 result is a strong design warning, not a substitute for the final
oscilloscope test on real hardware.

## Nominal small-signal results

Each range is driven with an input that should produce about 100 mV differential
output, avoiding intentional clipping.

| Range | Input step | Simulated gain | Baseline differential offset | -3 dB bandwidth | Peaking | Result |
|---|---:|---:|---:|---:|---:|---|
| 0.5x | -200 mV | 0.50154x | +0.567 mV | 3.71 MHz* | +9.74 dB at 35.5 MHz, sustained ringing | **Needs damping change** |
| 5x | -20 mV | 4.96881x | +6.087 mV | 3.85 MHz | 0 dB | Pass in model |
| 25x | -4 mV | 25.39299x | +18.588 mV | 3.08 MHz | 0 dB | Pass in model |

`*` The 0.5x response crosses -3 dB at about 3.71 MHz before rising into the
high-frequency ringing mode; that bandwidth number must not be read as a clean
single-pole response.

The simulated differential baseline offsets correspond to roughly 10, 111 and
338 ideal ADS5560 LSBs at a 3.6 Vpp full-scale span. They do not consume a
dangerous amount of ADC headroom, but each range needs its own baseline
subtraction and energy calibration.

The ADC polarity is intentionally inverted by the PCB connection: THS4551
`OUT+` goes to `ADC_INM`, while `OUT-` goes to `ADC_INP`. A negative PMT pulse
therefore moves the signed ADC differential code negative. Firmware must keep
that convention explicit instead of assuming positive-going peaks.

## R9/R10 damping sweep for the 0.5x range

All rows keep C2 = 2.2 nF and change both output-isolation resistors together.

| R9 = R10 | AC peaking | -3 dB bandwidth | Step overshoot | 1% settling | Assessment |
|---:|---:|---:|---:|---:|---|
| 10 ohm | 9.74 dB | 3.71 MHz before resonance | 9.67% plus ringing | Not settled before pulse end | Reject |
| 22 ohm | 0 dB | 1.65 MHz | 0.0005% | 0.44 us | **Recommended** |
| 33 ohm | 0 dB | 1.10 MHz | 0.027% | 0.66 us | Acceptable but slower |
| 47 ohm | 0 dB | 0.77 MHz | 0.31% | 0.89 us | Usable for slow pulses |
| 68 ohm | 0 dB | 0.53 MHz | 1.74% | Not within 1% before pulse end | Too slow here |
| 100 ohm | 0 dB | 0.36 MHz | 5.73% | Not within 1% before pulse end | Reject |

Recommendation: change the schematic/BOM values of R9 and R10 from 10 ohm to
22 ohm, then rerun ERC/DRC and regenerate manufacturing outputs. On the first
assembled board, verify 0.5x and 25x with a calibrated fast pulse while probing
both ADC inputs. If the real ADS5560 load differs significantly from the model,
33 ohm remains a conservative bench alternative.

## Large-pulse behaviour

For a -2.7 V detector pulse, the linear closed-loop demand is approximately
-1.35 V, -13.4 V and -68.6 V differential in the three ranges. Only 0.5x can
remain inside the ADS5560 nominal 3.6 Vpp input span.

| Range | Estimated source current through selected signal resistor | Overload run | Interpretation |
|---|---:|---|---|
| 0.5x | 0.675 mA | Completed; minimum ADC differential -1.356 V; residual 0.186 mV by 8–10 us | Expected to accept this pulse |
| 5x | 6.70 mA | TI macro-model stopped near the onset of deep saturation | Must saturate; recovery needs bench measurement |
| 25x | 34.3 mA | TI macro-model stopped near the onset of deep saturation | Must saturate; input-current protection risk |

The incomplete 5x/25x overload runs are a macro-model convergence failure in
the model's ideal internal switch, not evidence that the physical board cannot
power up. They also cannot be treated as recovery validation. The 25x estimated
current exceeds the THS4551 continuous-input absolute-maximum value of 10 mA.
Because the observed PMT occasionally produces multi-volt pulses, 25x must be
treated as a weak-signal range: begin on 0.5x, do not switch ranges during
acquisition, and reject/safely clamp large events before calling the input
universally protected. D1 remains DNP because its present single-diode footprint
is not a validated symmetric low-capacitance clamp.

## Static electrical and CAD audit

Fresh runs against the current source files:

- ERC: 0 errors, 0 warnings;
- DRC: 0 violations, 0 unconnected pads, 0 footprint errors;
- 111 of 111 manifest references found on the PCB;
- all 111 PCB footprints accounted for;
- all values and DNP states match the manifest;
- all 489 numbered pad/net assignments match the manifest;
- four copper layers confirmed;
- AP63203 FB, EN, VIN, GND, SW and BST nets rechecked;
- THS4551 eight-pin net map rechecked;
- DP3T pins 1–8 and all six selected gain-resistor branches rechecked;
- R9/R10/C2 analogue output-filter nets rechecked;
- C9/C10/R15/R16 clock interface nets rechecked;
- worst nominal two-arm resistor-ratio mismatch is 0.174% in the 5x range.

No accidental short, missing selected branch, reversed THS4551 pin, stale DPDT
pad or unmatched PCB/schematic net was found.

## What is not yet proven

1. **FPGA compile and timing:** compile the exact 10M16SAE144C8G project in
   Quartus with all package assignments and clock constraints. There is no v2
   bitstream yet.
2. **ADC capture:** verify 40 MHz data timing, source-synchronous CLKOUT capture,
   signed code polarity and overflow handling in hardware.
3. **Real ADC load stability:** repeat the R9/R10 damping test on an assembled
   board. The simulation does not include ADS5560 internal sampling kickback.
4. **Power integrity:** the AP63203 static pin map is correct, but no vendor
   switcher transient model was included. Measure 3V3_RAW, 3V3_D, 3V3_A,
   3V3_FPGA_A, 5VA and supply current during FPGA configuration and ADC running.
5. **Physical switch order:** the C&K DP3T contact topology is accounted for,
   but verify the purchased part's slider positions with a continuity meter
   before printing enclosure labels.
6. **RP2350 clone fit:** retain the existing physical overlay/mechanical gate
   for the exact 52 mm x 21 mm clone.

## Release decision

The design is electrically coherent and the analogue core is viable, but r7
should not be promoted to a production package unchanged. The minimum next step
is:

1. change R9 and R10 to 22 ohm;
2. rerun this simulation plus ERC/DRC;
3. build and compile the exact MAX 10 firmware project;
4. bench-check all three ranges, especially 0.5x damping and 25x overload
   recovery/protection.

After those gates, the board has a credible path to a working instrument.

## Reproduction

Run the analogue tests (the model is fetched directly from TI if needed):

```sh
cd simulation/r7
python3 run_simulations.py --fetch-model
```

Run the board/manifest audit with KiCad's bundled Python:

```sh
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9 audit_static.py
```

Generated summaries and figures:

- `results/summary.json`
- `results/summary.csv`
- `results/static-audit.json`
- `results/ERC-current-r7.rpt`
- `results/DRC-current-r7.rpt`
- `plots/small-signal-transient.svg`
- `plots/minus-2p7v-overload.svg`
- `plots/low-range-output-damping-sweep.svg`

## Primary references

- TI, THS4551 datasheet: <https://www.ti.com/lit/ds/symlink/ths4551.pdf>
- TI, THS4551 product/model page: <https://www.ti.com/product/THS4551>
- TI, ADS5560 datasheet: <https://www.ti.com/lit/ds/symlink/ads5560.pdf>
- Diodes Incorporated, AP63203 datasheet:
  <https://www.diodes.com/assets/Datasheets/AP63200-AP63201-AP63203-AP63205.pdf>
