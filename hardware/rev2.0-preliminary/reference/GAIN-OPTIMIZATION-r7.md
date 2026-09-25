# Aster MCA v2.0 three-range front end r7

Status: engineering revision for bench validation. This is not yet a released
production package, and `production/candidate-r4/` remains unchanged.

## Why three fixed ranges

The detector produces mostly tens-to-hundreds of millivolts pulses, with rare
background pulses reaching several volts. A continuous potentiometer would be
convenient, but two accurately related resistance arms are required around the
fully differential amplifier. An ordinary dual potentiometer adds tracking
error, wiper noise, temperature drift and an easily disturbed calibration.

r7 therefore uses one DP3T switch and three pairs of fixed 0.1% resistors. It
provides a wide safety range, a general-purpose range and a high-sensitivity
range while remaining reproducible and calibratable.

## Fitted values and nominal gains

R7 and R8 are 2.00 kohm feedback resistors. R2, 78.7 ohm, is shared by all
signal-side ranges. With negligible detector source impedance:

| Range | Signal-side path | Signal gain | Reference-side path | Reference gain | Arm mismatch |
|---|---:|---:|---:|---:|---:|
| 0.5x | R2 + R5 = 78.7 + 3920 ohm | 0.50016x | R6 = 4000 ohm | 0.50000x | 0.0325% |
| 5x | R2 + R46 = 78.7 + 324 ohm | 4.96648x | R47 = 402 ohm | 4.97512x | 0.174% |
| 25x | R2 + R3 = 78.7 + 0 ohm | 25.41296x | R4 = 78.7 ohm | 25.41296x | nominally 0% |

These are circuit ratios, not energy calibration constants. Detector output
impedance, resistor tolerance, amplifier error, ADC reference and digital pulse
processing all affect the measured channel position. Each range needs its own
energy calibration.

## Switch and net map

SW1 is C&K/Littelfuse JS203011AQN, a right-angle, non-shorting DP3T slide
switch. Its two poles select both differential input arms together:

| SW1 pin | Net | Function |
|---:|---|---|
| 1 | GAIN_H_SIG | 25x signal path |
| 2 | GAIN_M_SIG | 5x signal path |
| 3 | GAIN_SRC | signal pole common |
| 4 | GAIN_L_SIG | 0.5x signal path |
| 5 | GAIN_H_GND | 25x reference path |
| 6 | GAIN_M_GND | 5x reference path |
| 7 | GND | reference pole common |
| 8 | GAIN_L_GND | 0.5x reference path |

The PCB labels the available ranges, but the left/middle/right slider-to-range
order must be confirmed with a continuity meter on the purchased switch before
enclosure labeling. Because the switch is non-shorting, stop acquisition before
changing range, then clear/restart the histogram after switching.

## Expected use

- Use 0.5x for the largest amplified PMT pulses and initial bring-up.
- Use 5x as the normal wide-dynamic-range spectroscopy setting.
- Use 25x for weak/low-energy pulses. Rare several-volt events will saturate in
  this range and should be reported as overflow or rejected, not interpreted as
  valid pulse heights.

The optional D1 input protector remains DNP. Its present one-diode footprint is
not a validated symmetric low-capacitance clamp for this bipolar pulse input.
The THS4551 datasheet specifies an absolute maximum differential input voltage
of +/-1 V and continuous input current of +/-10 mA. A multi-volt detector pulse
while the amplifier is saturated is therefore not a released operating
condition for the 25x range, even if the pulse is brief. Keep first bring-up on
0.5x, validate overload recovery with a current-limited pulse source, and add a
proper symmetric low-capacitance clamp/current limiter before advertising the
input as universally overvoltage tolerant.

## Release gates

1. Verify the purchased switch pin map and all three positions with power off.
2. Measure baseline, quiescent output and supply current in every range.
3. Inject calibrated negative pulses and measure gain, linearity, overshoot,
   settling and saturation recovery in every range.
4. Repeat with the intended PMT and with JP1 open. Fit the 50-ohm termination
   only if the detector output is specified to drive it.
5. Compare background and Cs-137 spectra between ranges, including overflow and
   pile-up statistics.
6. Only after those tests, copy r7 into a new production release directory and
   generate fresh Gerber, drill, BOM and placement files.

## Automated checks

- `ERC-r7-gain.report`: 0 violations.
- `DRC-r7-gain.report`: 0 violations, 0 unconnected pads and 0 schematic parity
  errors.

These checks prove CAD consistency, not analog performance or purchasability.
