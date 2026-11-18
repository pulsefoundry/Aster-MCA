# Aster MCA Nano AT32 v0.4.1 — ordinary PTH interconnect

This is a minimal mechanical revision of the v0.4 two-board prototype. The core is now **26 × 23 mm**, obtained by extending each long edge by 1.5 mm without moving the 22 interface holes or any components. The carrier remains **60 × 32 mm**. Both boards use standard 0.8 mm plated through holes at 2.0 mm pitch, with no castellations.

The carrier's mating pads now have copper and solder-mask openings on both sides. Its USB_DP bottom-layer route was locally redirected to clear the new PTH pads. The analog circuit and all pin assignments are unchanged from v0.4.

- [Core EasyEDA Pro project](https://pro.lceda.cn/editor#id=c6272f473a3b4635be2af605c1985002)
- [Peak carrier EasyEDA Pro project](https://pro.lceda.cn/editor#id=92f59a72e90643bdbdeead96785b24e1)

Each board's `native/` directory contains its native project, schematic PDF, Gerber ZIP and netlists. Order the boards separately using their individual Gerber ZIPs; the outer delivery archive is not a combined manufacturing panel.

Assemble component-side up. Align pin 1 on both boards, with the core's BOOT/LED side toward USB. Join corresponding holes with short 2.0 mm-pitch pins or approximately 0.4–0.5 mm tinned wire. Keep approximately 1 mm insulating separation. Solder at the core's top and the carrier's underside, then trim and check all connections. Standard 2.54 mm headers do not match this interface.

The original coordinate origin is retained: the core outline is x=0..26, y=-1.5..21.5 mm, while the two hole rows remain at y=0 and y=20 mm. The hole center is 1.5 mm from the board edge; copper edge clearance at the interface pads is 0.5 mm.

Both local KiCad and native EasyEDA PCB DRC passed with no findings. Native schematic-to-PCB comparison tables were empty; exported schematic/PCB netlists match and preserve every v0.4 electrical connection. The carrier retains five known reserved single-pin-net schematic warnings and an informational USB mechanical-pad mapping message. The exported Gerber outlines and all 22 interface holes were independently read back.

Ordinary PTH does not require the specialized castellation process. Final pricing depends on the fabricator's quote and selected order options. The native Gerber ZIP retains EasyEDA's supplemental via drill file; it is a subset of the main PTH file and is not counted twice in the audit.

`NOT_FOR_FAB` denotes an engineering prototype: this revision verifies mechanical changes and layout, not measured peak-hold performance or firmware support. The older v0.8.2 firmware is not a peak-hold control implementation for this pin assignment.
