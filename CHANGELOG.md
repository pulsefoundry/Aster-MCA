# Changelog

## Unreleased

- Prepared a public repository layout and documented the v0.1 hardware errata.
- Added measured Cs-137 and background example data.
- Added a prebuilt FPGA v1.3 SRAM image and reproducible tests.
- Renamed the public project to Aster MCA while preserving legacy CAD titles
  inside the manufactured v0.1 evidence files.
- Marked SGM2037-1.2 as the recommended U6, recorded successful AP2112K-1.2
  startup without added capacitance, and limited extra capacitance to a
  measurement-confirmed fast-ramp recovery case.
- Added a single-image overview of all five v0.1 schematic sheets to both
  repository home pages.
- Added an explicit AI-assisted development disclosure.
- Documented the R62-R67 gain network, including the physically validated
  matched 4.99 kohm R66/R67 population for nominal gain about ×3.33.

## Firmware v1.3 — 2026-09-21

- Prevented large opposite-polarity excursions from dragging the tracked
  baseline to an ADC rail.
- Added a 1 ms recovery interval after saturated events.
- Retained an 8-sample recovery interval after normal events.
- Added regression coverage for rail-sized opposite-polarity excursions.

## Firmware v1.2 — 2026-09-21

- Selected negative-going pulses by default.
- Set the default threshold to 32 ADC codes.
- Corrected histogram/statistics clear priority so live time resets reliably.
- Clarified pulse-polarity reporting in the host utility.

## Hardware v0.1 — 2026-09-16

- First manufactured four-layer FPGA MCA prototype.
- Native EasyEDA Pro project, Gerber, BOM, and placement data archived.
- Requires the U8 and S1 corrections documented in
  `docs/hardware-errata-v0.1.md`.
