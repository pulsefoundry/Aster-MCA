# Analog gain configuration

The AD8137 stage converts the AC-coupled single-ended detector pulse into the
differential signal used by the ADC. Its external matched resistor networks set
the nominal differential closed-loop gain. Analog Devices defines the matched
network gain as approximately `RF / RG`.

## Relevant positions

| Positions | Fitted value in the archived BOM | Function |
| --- | ---: | --- |
| R60 | DNP | Optional BNC input termination; changes source loading, not the AD8137 feedback ratio. |
| R61 | 100 kohm | DC bias return from the AC-coupled input to `VCM_BUF`; not a gain adjustment. |
| R62, R63 | 1.00 kohm, matched | The two `RG` arms. |
| R64, R65 | 10.0 kohm, matched | The permanently fitted `RF` pair. |
| R66, R67 | DNP by default | Optional resistors in parallel with R64 and R65 respectively. |
| R69, R70 | 33 ohm | ADC input isolation/settling resistors; not closed-loop gain adjustments. |

R66 and R67 are **parallel gain-option pads**, not series resistors and not two
independent controls. Fit both with the same value and tolerance, or leave both
unpopulated. Fitting only one side unbalances the differential driver.

With `R62 = R63 = RG = 1.00 kohm`, the nominal gain magnitude is:

```text
RF+ = R64 || R66
RF- = R65 || R67
Gain ≈ RF / RG, provided RF+ and RF- are matched
```

An unpopulated option pad is treated as infinite resistance.

| R66 and R67 population | Effective RF on each side | Nominal gain | Status |
| ---: | ---: | ---: | --- |
| DNP | 10.0 kohm | about ×10 | Archived BOM default; likely to clip the amplified PMT pulses used in validation. |
| 10.0 kohm each | 5.00 kohm | about ×5 | Calculated example; not physically characterized. |
| 4.99 kohm, 0.1% each | 3.33 kohm | about ×3.33 | Physically validated with the amplified 1-inch NaI(Tl)/PMT probe and Cs-137 source. |

Reducing the gain increases the detector-input amplitude that can be accepted
before ADC clipping, but it also reduces ADC codes per volt and therefore makes
small pulses use fewer channels. Every population change requires a new energy
calibration and a check of baseline, pulse polarity, clipping, and noise.

The values above describe the AD8137 feedback ratio, not a guaranteed end-to-end
calibration. Source impedance, optional R60 termination, coupling components,
ADC range, and detector electronics also affect the measured system response.

Reference: [Analog Devices AD8137 data sheet](https://www.analog.com/media/en/technical-documentation/data-sheets/ad8137.pdf).
