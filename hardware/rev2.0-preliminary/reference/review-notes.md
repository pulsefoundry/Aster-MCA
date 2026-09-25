# Aster MCA v2.0 preliminary review notes

Date: 2026-09-24
Status: **not released for fabrication**

## What is materially improved over v0.1

- 16-bit/40 MSPS converter instead of 12-bit/10 MSPS.
- MAX 10 provides substantially more logic, block RAM, multipliers, and PLLs
  without requiring external DDR.
- The 52 mm x 21 mm Pico 2-compatible RP2350 host is soldered directly through
  its castellated edges.  This lowers height and removes 40 socket contacts,
  but module replacement now requires hot air or careful desoldering.
- True dual analog gain changes both halves of the differential driver together.
- The corrected nominal ranges are 0.4945× and 2.004×; the calculation includes
  the shared 100-ohm series resistor before the gain switch.
- The 0.4945× low range is chosen specifically so a roughly -2.7 V amplified PMT pulse
  does not automatically overdrive a ±1.78 V differential ADC input.
- Through-hole BNC, JTAG, edge-facing switches, jumpers, test points, and 3 mm
  status LEDs; ordinary passives are 0805/1206.

## Items deliberately not hidden

- A nominal 16-bit ADC is not a 16-effective-bit spectrometer.  Clock noise,
  front-end noise, grounding, input filtering, and pulse processing dominate.
- MAX 10 Quartus tools are not native macOS applications.  The hardware keeps a
  standard JTAG header; FPGA compilation/programming will need a supported
  Windows/Linux environment or a tested remote workflow.
- The final layout has been manually audited after routing. Critical analog,
  clock, OVR/SAT, power and configuration nets are covered by the independent
  r4 audit; final hardware behavior still requires first-article measurement.
- JLC/LCSC stock was not used to weaken the architecture.  U1/U2/U3 may need
  customer-supplied parts or hand placement if the assembly service has no stock.

## Power estimate to verify

The ADS5560 alone is specified around 674 mW at 40 MSPS.  MAX 10 dynamic current
depends strongly on the final design; Pico 2 and the 3.3 V converter also consume
from USB.  Do not assume every laptop port or cable will tolerate the final load.
Measure VBUS current and 3.3 V ripple with the FPGA configured and ADC clocked.

## r4 audit status

- KiCad PCB DRC: 0 violations, 0 unconnected pads and 0 parity errors.
- KiCad schematic ERC: 0 errors and 0 warnings.
- Independent audit: 50 passed, 0 warnings, 0 failures; 420 pin assignments
  checked against the manifest.
- The RP2350 module footprint was rebuilt from a clean stock Pico envelope: the
  accidental off-board keepouts and paste apertures were removed. It remains a
  hand-soldered module and still requires a 1:1 check against the purchased
  clone.
- ADC OVR feeds the FPGA only. The SAT indicator is now driven from a separate
  FPGA output so the LED cannot load the ADC status pin.

## Mechanical r2 snapshot (historical, 2026-09-25)

- A1 now uses the standard Pico common SMD castellated footprint.  The supplied
  module photograph matches the standard 40-pin order and the stated envelope
  is 52 mm x 21 mm.
- SW1 is a right-angle DPDT at the left wall; SW2 is a right-angle tactile
  switch at the right wall.  The rendered actuator directions point outward.
- D2-D5 are 3 mm diffused through-hole indicators in a right-side column.
- The top-right carrier mounting hole moved inward because the direct-soldered
  RP2350 module occupies that corner.
- Routing was deliberately reset.  `DRC-mechanical-r2.rpt` is a mechanical
  placement snapshot, not an electrical sign-off.
- The KiCad schematic and PCB were imported into the native EasyEDA Pro project
  `Aster-MCA-v2.0` and saved as checkpoint `preliminary-20260924`.  This proves
  editability only; exact LCSC/JLC footprint binding, native DRC, SMT origin
  review, and 3D inspection remain mandatory.

## Current r7 gain experiment

The live files in `source/` now use a top-edge JS203011AQN DP3T switch and
0.5x / 5x / 25x resistor ranges. This supersedes the r2 DPDT placement only in
the engineering source; `production/candidate-r4/` remains the preserved,
earlier two-range candidate. See `GAIN-OPTIMIZATION-r7.md` for the exact gain
ratios and required bench validation.
