# Hardware revision 0.1 — as built

SPDX-License-Identifier: CERN-OHL-P-2.0

This directory is Covered Source under CERN-OHL-P-2.0. See the repository
root `LICENSE.md` and `LICENSES/CERN-OHL-P-2.0.txt`.

This directory archives the exact design lineage used for the first
manufactured Aster MCA boards. The native CAD archive still contains the
pre-publication `OpenMCA FPGA` working title; it is preserved unchanged inside
the evidence files so the manufactured revision remains traceable.

**Do not order this revision unchanged.** Apply the mandatory U8 replacement
leave S1 unpopulated, and fit the original SGM2037-1.2 at U6 as described in
[`../../docs/hardware-errata-v0.1.md`](../../docs/hardware-errata-v0.1.md).

## Contents

- `source/Aster-MCA-v0.1.epro2` — native EasyEDA Pro project archive (legacy
  project title retained internally).
- `production/Gerber.zip` — four-layer fabrication data.
- `production/BOM-native.tsv.utf16` — exact native UTF-16 BOM archive.
- `production/CPL-native.tsv.utf16` — exact native UTF-16 placement archive.
- `production/BOM-readable.tsv` and `CPL-readable.tsv` — UTF-8 copies for
  browser review and version-control inspection.
- `production/assembly-overrides.csv` — required deviations and DNP notes.
- `reference/Schematic.pdf` — five-page schematic export.
- `reference/Netlist.net` — exported netlist.
- `reference/Pin-net-reference.csv` — pin-to-net audit table.

The board is approximately 90 mm × 70 mm, four-layer FR-4, 1.6 mm thick. The
validated order used ENIG, 1 oz outer copper, 0.5 oz inner copper, and a stackup
with a thin outer-layer-to-reference-plane dielectric. USB differential
impedance was not verified by field solving, TDR, or an eye diagram; successful
enumeration on the tested boards is not a substitute for those measurements.

J2 is a hand-fitted BNC and is not part of the SMT placement file. J3/J4 are
optional headers. R60, R66, and R67 are configuration positions rather than
unconditionally fitted parts.
