# Aster MCA v2.0 r8 output-damping correction

Date: 2026-09-25

## Applied change

- R9: `10R 1%` -> `22R 1%`
- R10: `10R 1%` -> `22R 1%`
- No nets, footprints, placement, routing, copper geometry, or other component values were changed.
- The source schematic, source PCB, `parts-manifest.json`, and current reference BOM were updated together.

R9 and R10 are the two symmetrical series resistors between the THS4551 outputs and the ADS5560 differential inputs. The change increases isolation between the FDA and the ADC input capacitor C2.

## Why it was changed

With the previous 10 ohm value, the TI THS4551 macro-model and the present 2.2 nF C2 load showed an underdamped output network in the 0.5x range:

| Configuration | AC peaking | Peak frequency | Post-pulse differential ringing | 1% settling |
|---|---:|---:|---:|---:|
| Previous 10 ohm | 9.742 dB | 35.48 MHz | 108.4 mVpp | Did not settle in the simulated window |
| Current 22 ohm | 0.000 dB | None observed | < 1 nVpp | 0.439 us |

The 22 ohm option is the lowest tested value that removed the simulated peaking and sustained ringing without the bandwidth and pulse-height loss seen with larger values.

## Post-fix range simulation

The default board simulation was rerun with R9 = R10 = 22 ohm:

| Range | Simulated gain | -3 dB bandwidth | AC peaking | 1% settling | Post-pulse ringing |
|---|---:|---:|---:|---:|---:|
| 0.5x | 0.50006 V/V | 1.648 MHz | 0.000 dB | 0.439 us | < 1 nVpp |
| 5x | 4.96867 V/V | 1.656 MHz | 0.000 dB | 0.441 us | < 1 nVpp |
| 25x | 25.39230 V/V | 1.564 MHz | 0.000 dB | 0.454 us | < 1 nVpp |

These results use TI's THS4551 PSpice macro-model. They do not model the ADS5560 switched-capacitor input exactly, so first-power-up oscilloscope verification remains required.

## CAD and connectivity verification

- Schematic ERC: 0 violations.
- PCB DRC: 0 violations, 0 unconnected items, 0 footprint errors.
- Static schematic/PCB/manifest connectivity audit: PASS.
- Critical maps for R9, R10, C2, ADC clock, and FPGA clock interfaces remain unchanged and correct.

## Release status

This correction is present in the editable source files. The older frozen production candidate packages were intentionally not regenerated and must not be ordered as r8. A fresh production export should only be made after the exact Quartus project compiles and the remaining physical switch and ADC-input bench checks are complete.
