# Open issues for r8

The current board is fully routed and the fresh PCB DRC, schematic ERC and
independent PCB/manifest audit are clean. The design remains on hold for:

1. exact-device MAX 10 Quartus pin-legality and timing compilation;
2. FPGA firmware and RP2350 host firmware;
3. a 1:1 physical overlay of the exact RP2350 clone;
4. continuity and position verification of the purchased DP3T switch;
5. real ADS5560 input-load, clock/data timing and power-integrity measurements;
6. safe overload/recovery validation, particularly in the 25x range;
7. exact purchasable-part binding and a final native EasyEDA/JLCPCB assembly
   review.

The files in `quote-r8-current-source/` are deliberately for quotation only.
