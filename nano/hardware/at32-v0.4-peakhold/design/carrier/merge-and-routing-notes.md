# Complete carrier merge and handoff

The full `design.json` combines the mechanical subset and the frozen positive-peak analog design. It supersedes the standalone mechanical subset for the actual board contents.

- Carrier remains60x32mm, module body x8..34/y6..26.
- Mechanical ESD D10 was renamed D90; mechanical C20/C21 became C90/C91. The frozen analog reference designators were retained unchanged.
- U12 is implemented with the installed KiCad `Package_SO:MSOP-10_3x3mm_P0.5mm` land pattern corresponding to the3x3mm,0.5mm-pitch TI DGS VSSOP10 package; package drawing/land geometry should remain part of final library audit.
- D12 final is BAS70-04,215 in SOT23, pins1=PEAK_FB,3=PEAK_DRV,pin2 intentionally unconnected. R101=43k, R102=10k, reference nominal0.62264V.
- The signal is converted from negative SMA pulse to positive RAW, then a positive peak is held. Energy estimator is PEAK_ADC minus the event-before RAW_ADC baseline. BASE_ADC monitors the reference and is not the event-before baseline.
- Explicit aliases in design.json: SMA_IN→PULSE_IN; RAW_OUT→RAW_ADC; PEAK_OUT→PEAK_ADC; BASE_BUF→BASE_ADC; RESET→PEAK_RESET; NC_RESET and NC_D12→unconnected. HOLD_CTL and RESET_CTL remain separate after their100ohm damping resistors.

## Critical routing

The held node joins D11 cathode, C102 pin1, U11B input pin5 and U12 pin6 with short top-layer branches and no via. C102 has no external test pad. U11B local feedback pins6/7 is connected. The buffered PEAK_ADC path to R107 uses two vias; these are not on the high-impedance storage node.

The capture input, peak driver, charging diode path, antisaturation feedback, and local U11 supply paths are partially hand routed. Preserve these routes during completion, including the three GND vias placed for connection to the bottom plane. The optional C103 feedback branch remains to be connected. Keep further digital/USB/LED routing away from HOLD_CAP; no unnecessary guard or ground copper should intrude into its local spacing. The board bottom should remain a continuous return plane.

Manual path lengths are in `critical-route-summary.json`. They describe drawn copper, not proven bandwidth, stability, hold error or energy resolution.

## Handoff check

The final pre-routing `cad/placement-drc.json` has zero shorts, ordinary clearance errors and courtyard overlaps after adding critical tracks.51segments/vias present,91remaining unconnected items. Three GND vias are reported dangling until the ground plane/remaining connections exist; two USB-footprint silk lines cross the intentional board edge and need trimming.

U12's standard0.5mm-pitch footprint has0.15mm adjacent copper-pad clearance. A conditional KiCad rule for pad pairs belonging to U12 is saved beside the board in `Aster-MCA-Nano-AT32-Peak-Carrier-v0.4-NOT_FOR_FAB.kicad_dru`; other pre-route geometry was checked with default0.2mm net clearance. The final native EDA rules and manufacturing minimum must explicitly accommodate0.15mm, rather than claiming the standard pad geometry meets0.2mm.

This checkpoint is not a finished board or a fabrication release. Routing ownership was transferred to the CAD tooling agent; do not rerun merge_layout.py, which is only the initial merge script and contains obsolete placement seed values. The current design.json is authoritative.
