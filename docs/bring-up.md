# First-board bring-up

This procedure is for the v0.1 prototype after applying the mandatory errata.
Do not connect a detector during the initial checks.

## Before power

1. Read `hardware-errata-v0.1.md`.
2. Leave S1 unpopulated.
3. Fit `MCP6001T-I/OT` at U8, or remove U8 and apply the documented temporary
   `ADC_VRM` to `VCM_BUF` bridge. Never leave the bridge in place with an
   active U8 output.
4. Inspect U1, U2, U3, U4, the USB-C connector, and all fine-pitch joints under
   magnification.
5. Confirm there is no low-resistance short from USB5V, +3V3, +1V2, or +5VA to
   ground.
6. Keep J2 open. The input is low-voltage only.

## Limited first power

Use a current-limited 5 V source through a USB power breakout while the
computer is disconnected. Verify:

- USB5V is near 5 V;
- +3V3 is near 3.3 V;
- +1V2 is near 1.2 V;
- +5VA follows the USB supply after the ferrite bead;
- the regulators and FPGA do not heat abnormally.

Fit the originally specified **SGM2037-1.2XN5G/TR** at U6 for a new build. A
prototype fitted with AP2112K-1.2 was later verified to start successfully
without added output capacitance, although that device is not the recommended
production population. Do not add capacitance by default. Only consider a
parallel output capacitor if oscilloscope measurements confirm that an
excessively fast +1V2 rise causes FPGA configuration or startup failure. If a
substitute or extra capacitance is used, characterize +1V2 rise time,
overshoot, regulator stability, and repeatable FPGA configuration.

## USB and FPGA

Connect the board to the host and check that the CH347T enumerates as USB
`1a86:55dd`. Then, from `firmware/mca-v1`:

```sh
make detect
openFPGALoader -c ch347_jtag --freq 1000000 -m \
  prebuilt/aster-mca-v1.9.fs
python3 astermca.py info
python3 astermca.py stats
```

A healthy open-input board should report an ADC baseline near midscale, about
2048. On the validated prototype it was approximately 2033 with a quiet range
near 2029–2039. A baseline stuck at 0 or 4095 is a fault; do not compensate for
it in software.

## Analog checks

With a repaired U8 path and the BNC open, verify approximately:

- C54 non-ground pad (`ADC_VRM`): 2.5 V;
- R63 VCM-side pad (`VCM_BUF`): 2.5 V;
- both C63 ADC input pads: near 2.5 V and within tens of millivolts;
- ADC baseline: near code 2048, not at either rail.

Apply only a small, controlled, low-voltage pulse first. Confirm polarity,
threshold behavior, and the absence of clipping before connecting a real
amplified detector module.

## Detector connection

J2 accepts an already-conditioned low-voltage signal. It does not accept PMT
high voltage or a detector bias line. Use a properly grounded BNC shell and
short coaxial return path. Start with the detector source removed and acquire a
background spectrum before placing a check source.
