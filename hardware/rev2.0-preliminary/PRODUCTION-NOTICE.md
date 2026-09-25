# Production status: hold

The editable source is the **r8 engineering revision** with nominal 0.5x, 5x
and 25x analogue ranges and 22 ohm THS4551-to-ADC isolation resistors. It
passes schematic ERC, PCB DRC and the independent PCB/manifest network audit.
It has not been built and has no matching MAX 10 firmware.

Files under `production/quote-r8-current-source/` are for quotation only. Do
not authorize an FPGA/ADC assembly order until all of the following are true:

1. the exact `10M16SAE144C8G` project passes Quartus pin-legality, timing and
   configuration checks;
2. the actual 52 mm x 21 mm RP2350 clone passes a 1:1 footprint and USB-overhang
   check;
3. the purchased DP3T switch's contact map and slider order are confirmed;
4. every fitted BOM line is bound to the exact manufacturer part and verified
   stock source;
5. customer-supplied or externally purchased FPGA/ADC parts have an assembly
   and inspection route appropriate for their fine-pitch exposed-pad packages;
6. the final native EasyEDA/JLCPCB job passes DRC, paste, rotation and 3D review.

The current CAD audit covers 111 footprints and 489 numbered pin/net
assignments. It does not prove ADC capture timing, USB power margin, real ADC
input stability, overload recovery or detector performance. Those require the
first physical prototype.

The older `candidate-r3` and `candidate-r4` archives are historical layout
milestones with superseded gain values. They are not r8 production packages.
