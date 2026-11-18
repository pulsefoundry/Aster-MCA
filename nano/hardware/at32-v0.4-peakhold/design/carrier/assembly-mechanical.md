# Carrier mechanics and interfaces — v0.4 draft

Input file: `mechanical.json`. This file contains only the mechanical/USB/module-interface subset, not the complete analog circuit or a fabrication release.

## Geometry

- Carrier outline: 60 × 32 mm, proposed finished thickness 1.6 mm.
- AT32 module M1: 26 × 20 mm; center (21,16), body bounds x8..34/y6..26. TOP facing up. Keep this area free of carrier-mounted components; copper and tented vias are permitted. No exposed pad or component may accidentally touch the module bottom.
- Carrier mating lands are 1.5 × 2.8 mm, 2.0 mm pitch, aligned to the module half-hole centers. Numbering is TOP VIEW; do not mirror the footprint. First top-left pad is1, top-right11, bottom-right12, bottom-left22.
- Module upper lands y6; lower lands y26. Half-hole drill centers are physically on the module outline; carrier pads are SMD only and have no drilling.
- Analog circuit reserved around x36..52/y3..28, subject to actual footprint courtyard/trace clearance.
- USB-A J1 uses the original CnC Tech1001-011-01101 footprint and placement(-3.8,16),180degrees. Keep its shell slots and two NPTH alignment holes. Signal pads are at x5.85,y19.5/17/15/12.5 for VBUS/D-/D+/GND; they clear the module body x8 start. The metal shell crosses the carrier x0 edge by design.
- J2 at(55,16) uses KiCad's SMA_Amphenol_132134_Vertical as a dimensional reference. Center signal drill1.5mm; four ground drills1.7mm at(+/-2.54,+/-2.54)mm. The four ground pins form a5.08mm square. The source footprint courtyard is8.34mm square. A low-cost replacement must match its own drawing; 'five pins' alone is not sufficient. This design does not require purchasing the expensive Amphenol part.
- J3 at(55,25) provides G-S-G wire pads on2.54mm pitch: pad1GND,pad2signal,pad3GND. Drill0.9mm,pad1.7mm. No connector is required. Use J2 or short wiring to J3 as an alternative input; do not attach two independently driven sources.

## USB and power connections

J1 connector-side nets are USB_DM_CONN and USB_DP_CONN. They enter D90 pins3 and1; D90 pins4 and6 leave as USB_DM and USB_DP to M1. USBLC6-2SC6 internally connects3/4 and1/6 respectively; split net names intentionally make the autorouter pass through the protection device instead of using a distant branch. D90 pin2GND,pin5VBUS. Its current top placement is(5.8,6),90degrees; the final routing should keep its return and VBUS decoupling short.

C90=1uF X7R10V at(6,24.3) provides local carrier VBUS storage. C91=100nF at(2.2,6) is local D90 VBUS decoupling. M1 receives5V at pin2 and provides V3V3 at pin6; no independent3.3V regulator or second source on the carrier. Add final analog power consumption to the module regulator thermal/current budget, and review total USB attach capacitance/inrush for the final complete assembly.

Official D90 reference: https://www.st.com/resource/en/datasheet/usblc6-2.pdf (pinout on page1; layout guidance pages6 and11). Main task is separately checking the SMA dimensional drawing: https://www.amphenolrf.com/en-us/assets/file/4065789557/ . The local KiCad footprint is a geometry source, not proof that an arbitrary substitute is compatible.

## Assembly order

1. Fit carrier low-profile analog/USB protection parts and inspect their polarity.
2. Inspect and electrically check the AT32 module separately. Clear any solder bead on its underside and clean the mating lands.
3. Align M1 with the correct top view; tack opposite corners, then solder all half-hole joints. Carrier lands extend beyond the module edge for iron access.
4. Fit USB-A and SMA, with enough heat for ground/shell pins. USB shell anchors and SMA mechanical pins carry insertion force; do not leave these relying on signal pads.
5. Check5V/3.3V to GND resistance, connection of every module land, and absence of solder bridges before power. Source/probe remains disconnected during first power check.
6. SWD/BOOT access should be exported to reachable carrier pads if the final layout adds them; module top buttons remain accessible.

## Mechanical-subset check

`mech-check/drc.json` after adjustment: zero shorts, ordinary clearance errors or courtyard overlaps. There are26 unrouted connections;2 expected library-configuration warnings for custom M1/J3 footprints;2 USB-footprint silkscreen lines clipped by the intentional board edge. The latter can be trimmed during final board preparation. This limited check does not include the analog parts, ground pours, routing, EDA-native DRC or real connector fit.
