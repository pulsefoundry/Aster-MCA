# Hardware v0.1 errata

This document applies to boards manufactured from
`hardware/rev0.1-as-built/production`. The archived files are the exact design
lineage used for the first boards and are intentionally not silently replaced
with a different revision.

## E1 — U8 pin-map mismatch (mandatory fix)

The PCB net map assumes U8 is a voltage follower with this SOT-23-5 pinout:

| Pad | Required function |
| ---: | --- |
| 1 | OUT / `VCM_BUF` |
| 2 | GND |
| 3 | IN+ / `ADC_VRM` |
| 4 | IN- / `VCM_BUF` |
| 5 | +5VA |

The v0.1 BOM instead specifies TI `LMV321IDBVR`, whose pins are 1 IN+, 2 GND,
3 IN-, 4 OUT, 5 V+. Fitting that part creates positive feedback and drives the
analog common-mode node to a rail. The observed failure signature was
`VCM_BUF` near 5.13 V and the ADC stuck at code 4095.

### Preferred repair

Fit **`MCP6001T-I/OT`** in U8. Its plain SOT-23-5 variant matches the PCB net
map: 1 OUT, 2 VSS, 3 IN+, 4 IN-, 5 VDD.

Do not use MCP6001R or MCP6001U suffix variants; their pin maps differ.

### Temporary bring-up bypass

With power removed:

1. remove U8 completely;
2. bridge C54 pin 1 / non-ground pad (`ADC_VRM`) to the VCM side of R63
   (`VCM_BUF`) with a short insulated wire;
3. check that neither endpoint is shorted to ground or +5VA before power-up.

The ADC12010 VRM output can supply the small DC common-mode load used here,
and this bypass was sufficient for prototype validation. It is not the
preferred low-noise final implementation.

**Never install this bridge while U8 remains active.** The op-amp output would
fight the ADC reference node.

## E2 — S1 switch contact pairing (mandatory fix)

Leave S1 unpopulated. The v0.1 PCB assigns opposite footprint numbers to
`RECONFIG_N` and GND, but the selected four-pin tactile switch internally pairs
contacts in a way that can hold `RECONFIG_N` low. The result is a board that
enumerates through CH347T but does not configure the FPGA reliably.

The first boards configured normally after S1 was removed. Use J3 or a future
corrected footprint if a manual reconfiguration input is required.

## E3 — Analog gain population

The archived BOM fits R64 and R65 as 10.0 kohm and leaves R66/R67 unpopulated,
giving a nominal differential gain magnitude of 10 with R62/R63 = 1.00 kohm.

R66 is directly in parallel with R64, and R67 is directly in parallel with
R65. They are not series positions or independent channel controls. Both must
be left open or populated with the same value:

```text
RF+ = R64 || R66
RF- = R65 || R67
Gain ≈ RF / RG, with R62 = R63 = RG = 1.00 kohm
```

The reported Cs-137 validation populated **4.99 kohm, 0.1%** at both R66 and
R67 in parallel with the fitted 10.0 kohm pair. The effective feedback
resistance was about 3.33 kohm, for a gain near ×3.33. Both sides must remain
matched. Gain changes alter input range, clipping behavior, and calibration.
The detailed population table and the roles of R60/R61/R69/R70 are documented
in [`gain-configuration.md`](gain-configuration.md).

## E4 — Restore the original U6 regulator for new builds

Fit the originally specified **`SGM2037-1.2XN5G/TR`** at U6 for a new build. A
board assembled with a factory-substituted `AP2112K-1.2` was later verified to
start successfully without added output capacitance, so extra capacitance is
not an inherent requirement of that substitute. The AP2112K remains a tested
prototype substitution rather than the recommended production population.

Only consider parallel output capacitance if oscilloscope measurements confirm
that an excessively fast +1V2 rise is causing FPGA configuration or startup
failure. If it is added, verify the regulator's allowed output-capacitance and
ESR range, rise time, overshoot, loop stability, current limit, and repeatable
FPGA configuration. For any substitute, first verify pinout and enable logic.

## Post-repair acceptance checks

With the BNC open and v1.3 firmware loaded:

1. `ADC_VRM` is approximately 2.5 V.
2. `VCM_BUF` is approximately 2.5 V.
3. Both ADC inputs are near 2.5 V.
4. ADC baseline is near midscale and not at 0 or 4095.
5. The heartbeat LED runs after SRAM configuration.
6. A small safe test pulse produces the expected polarity without clipping.

Only after these checks should an amplified detector module be connected.
