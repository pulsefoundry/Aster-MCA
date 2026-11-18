# AT32 castellated core v0.4 — design input, NOT_FOR_FAB

Status: interface and schematic connectivity proposal checked against AT32F423 documentation. Placement is a starting floorplan, not a completed routing/DRC release. No board, firmware, analog timing or spectroscopy test has been performed for this revision.

## Deliverables

- `design.json`: generic CAD-tool input, including standard KiCad footprint names, part pin nets, initial placements, and a custom 22-pad castellated interface.
- `parts.json`: the same component array, following the project's existing PARTS schema.
- `module-spec.json`: mechanical/interface/default-state specification.
- `interface.csv`: numbered module interface in top-view clockwise order.
- `BOM.csv`: per-reference component list. No speculative unit prices included.

## Module and carrier boundary

The module is 26 × 20 mm, 2 layers, with all mounted components on TOP. Two 26 mm edges each have 11 plated half-holes at 2.0 mm pitch. Drills are 0.8 mm, pad size 1.4 × 2.0 mm, hole centers at x = 3,5,...,23 mm and y = 0 or 20 mm. The module drill/outline intersection is deliberate and must be ordered as metallized half-holes. Module pads have no paste opening. Their mask opening matches the 1.4 × 2.0 mm copper pad (0 mm expansion in the current output). Carrier lands are 1.5 × 2.8 mm; physical assembly fit remains to be checked. Do not populate components under the module.

TOP edge, left to right: 1 GND, 2 VBUS, 3 USB_DM, 4 USB_DP, 5 GND, 6 V3V3, 7 NRST, 8 SWDIO, 9 SWCLK, 10 BOOT0, 11 GND.
BOTTOM edge, right to left: 12 GND, 13 PEAK_ADC, 14 GND, 15 RAW_ADC, 16 BASE_ADC, 17 GND, 18 DAC_THRESH, 19 TRIG, 20 HOLD, 21 PEAK_RESET, 22 AUX.

The bottom analog inputs sit near the right side, facing the carrier analog circuit. U1 is rotated 180 degrees so PA0/PA1/PA2 face this side and USB faces the opposite side. Only buffered signals cross the module boundary; the storage capacitor and its high-impedance node stay on the carrier.

USB-A, USB ESD protection, SMA, input protection, gain/offset, comparator and peak hold live on the carrier. The module retains MCU, supply, BOOT, two 0603 blue LEDs with 1k resistors, and optional DNP reset button. SWD is exposed through module pins and should reach accessible carrier pads.

## Verified MCU connections

MCU is AT32F423CCT7, LQFP48, 256 KB Flash. VDD pins 1,24,36,48 all connect to V3V3, each with a close 100 nF ceramic. Pin 8 VSSA and pin 47 VSS share solid GND. Pin 9 VDDA/VREF+ connects to V3V3 through a populated 0-ohm link plus 100 nF and 1 uF at the pin. The datasheet requires VDDA and VDD to have the same DC potential. LQFP48 has no separate VREF+ pad.

| Signal | MCU pad | Peripheral |
|---|---:|---|
| Positive held peak | PA0 / 10 | ADC1_IN0 |
| Raw waveform | PA1 / 11 | ADC1_IN1 |
| Nominal0.623V BASE monitor | PA2 / 12 | ADC1_IN2 |
| Threshold command | PA4 / 14 | DAC1_OUT |
| Trigger, active high / rising edge | PA6 / 16 | TMR3_CH1 / EXINT6 |
| HOLD | PA7 / 17 | TMR3_CH2 / GPIO |
| PEAK_RESET | PB0 / 18 | TMR3_CH3 / GPIO |
| Auxiliary | PB1 / 19 | TMR3_CH4 / GPIO / ADC1_IN9 |
| Running LED | PB12 / 25 | Active-low GPIO |
| VBUS sense | PA9 / 30 | OTGFS1_VBUS, through 10k |
| USB D-/D+ | PA11 / 32, PA12 / 33 | OTGFS1 |
| SWD | PA13 / 34, PA14 / 37 | SWDIO / SWCLK |
| Reset / BOOT | 7 / 44 | NRST / BOOT0 |

All carrier logic and analog signals use 3.3 V rails. The analog inputs must stay within GND..VDDA; GPIO 5V tolerance does not authorize an overrange ADC signal.

## Analog interface

- PEAK_ADC: 100 ohms followed by 1 nF C0G at PA0; buffered slowly varying positive held peak; wait for settling before readout.
- RAW_ADC: 33 ohms followed by 100 pF C0G at PA1; buffered positive pulse diagnostics/baseline path from inverted negative SMA input. The actual driver/ADC settling must be measured with the intended acquisition time.
- BASE_ADC: 100 ohms followed by 1 nF C0G at PA2; buffered nominal0.623V BASE/reference monitoring.
- BASE_ADC is NOT a held event-before baseline. For the final positive-peak design, pulse amplitude is PEAK_ADC minus the event-before RAW_ADC baseline. The nominal BASE voltage is0.623V and must not be substituted for a measured event baseline. A software baseline strategy still has to be implemented.
- ADC channel and sampling-time changes must clear stale conversions and observe settling. Sequential ADC reads are not simultaneous samples.
- DAC_THRESH: 33-ohm series link only on the module. The carrier supplies filtering/buffering. With the internal DAC buffer ON, the datasheet gives 0.2 V to VREF+−0.2 V output range, RLOAD ≥5k, CLOAD ≤50pF, maximum settling/wakeup 4 us under stated conditions. A carrier RC must isolate large capacitance; comparator thresholds need empirical calibration because DAC offset is not negligible at low pulse thresholds.

## Safe control defaults

The carrier places 100k pull-ups on HOLD and PEAK_RESET. At MCU reset/high impedance, HOLD is high (capture input switched to nominal0.623V BASE/frozen) and PEAK_RESET is high (storage reset to nominal0.623V BASE). Firmware should preload the two output latches HIGH before enabling their outputs, initialize ADC/DAC/trigger and thresholds, allow bias settling, then release reset and arm capture. No automatic re-arm before a completed read/reset cycle.

BOOT0 has a 10k module pull-down and button to V3V3. NRST has 10k pull-up and 100nF to ground; reset button is optional DNP. Preserve factory nBOOT1/boot memory. SWD voltage reference is V3V3; do not power through it while USB is connected.

PB12 LED is active low. Preload HIGH before GPIO output mode. Retain the existing user preference of blue 0603 LEDs and 1k current-limiting resistors.

## Supply and clock

Reuse the existing XC6206P332MR-G SOT-23 (1=GND,2=VOUT,3=VIN) from the proven board BOM, with local 1uF input and 4.7uF output ceramic capacitors. VBUS is the normal 5V supply input and V3V3 is an output feeding the carrier. The current and thermal budget must be reviewed after the final carrier BOM; the module pin is not an unrestricted external supply input.

No crystal is fitted. Official Artery documentation supports 48 MHz HICK plus ACC/SOF calibration for USB DEVICE operation. This does not establish a precision standalone timebase while USB is absent. Keep PF0/PF1 unconnected unless a deliberate later crystal revision is made. The family maximum is 150MHz under datasheet operating conditions; there is no need to commit this revision to overclocking. The existing 144MHz firmware setting is only a reuse candidate. Bootloader USB and application USB are separate checks.

## Firmware implications

This is a new hardware interface. Old v0.8.2 firmware does not operate HOLD/RESET, sample RAW on PA1 or use DAC threshold control, and must not be represented as compatible without changes. Expose the active-high comparator trigger to timer input and use its rising edge; use hardware timing where feasible, sequence held-value ADC read and reset, count busy/dead time, and retain raw-mode diagnostics. Exact timer MUX configuration and timing are firmware work, not yet tested. Preserve the existing ADC ES0010 XTEST workaround in the driver.

## Sources and checks

- Existing project `work/AT32F423-V2.03.pdf`, Artery DS Rev 2.03, 2025-01-17: p14 supplies/LDO; p16 clocks; p22 USB; p26 LQFP48 diagram; pp29–33 pin table; pp70–71 ADC decoupling; p73 DAC conditions.
- Official manufacturer page: https://www.arterychip.com/en/product/AT32F423.jsp
- Official datasheet cross-check: https://www.arterychip.com/download/DS/DS_AT32F423_V2.02_EN.pdf
- Official castellated-hole guidance: https://jlcpcb.com/help/article/what-is-castellated-holes
- Existing project generators `work/build_epro.py`, `work/release_build_epro.py`, `work/release_design.py`, `work/buffer_design.py` were reviewed for source format and previously used footprints. Their old board outlines, pin networks and titles must not be reused unchanged.

Checks still needed: component overlap/courtyard and access; carrier-module land registration; schematic-to-PCB pin-net equality; native DRC with explicit intentional half-hole edge cases; USB reference/return geometry; power/noise; ADC drive/settling; actual capture/hold/reset and pulse-pileup behavior; firmware and final spectrum A/B measurements.

## Placement checkpoint (2026-11-11)

The initial floorplan was iterated with the generated KiCad board. The final pre-routing report `cad/placement-drc.json` has no pad shorts, ordinary clearance violations, courtyard overlaps, or silkscreen conflicts. It contains 22 deliberate copper/board-edge findings for the 22 castellated pads and one missing configured `AsterCustom` library warning. There are still 78 unrouted connections at this checkpoint. This is a KiCad placement check, not an EasyEDA native release or a routed/fabrication-ready result.

To fit cleanly, the small R/C parts use 0402; C1/C2 remain 0603, and the user's two blue LEDs plus their 1k R1/R2 remain 0603. `BOM.csv`, `parts.json` and `design.json` were synchronized at handoff to routing. Subsequent routing ownership belongs to the CAD tooling agent.
