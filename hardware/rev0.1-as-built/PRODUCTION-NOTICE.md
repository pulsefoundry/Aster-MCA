# Read this before fabrication

This archive preserves the exact Aster MCA v0.1 design lineage used to
manufacture the first prototype boards. It is provided for reproducibility
and review, **not as an error-free drop-in production release**.

Before assembling a board:

1. fit `MCP6001T-I/OT` at U8 instead of the BOM-listed `LMV321IDBVR`;
2. leave S1 unpopulated;
3. fit the originally specified `SGM2037-1.2XN5G/TR` at U6 for a new build;
   `AP2112K-1.2` was tested to start without extra capacitance. Consider adding
   a parallel output capacitor only after measurements prove an overly fast
   +1V2 rise is causing FPGA startup failure;
4. read `hardware-errata-v0.1.md` and `assembly-overrides.csv` in full.

R66 and R67 are matched parallel feedback options. Leave both DNP for nominal
gain ×10, or fit the same value at both positions. The validated detector setup
used 4.99 kohm, 0.1% at both positions for nominal gain about ×3.33. Read the
included analog gain configuration guide; never populate only one side.

The BNC input is for an already-amplified, conditioned, low-voltage detector
signal. It is not a PMT high-voltage input and contains no detector bias supply
or charge-sensitive preamplifier.

## Package contents

- native EasyEDA Pro project;
- Gerber fabrication archive;
- native and human-readable BOM/CPL files;
- assembly overrides;
- schematic, netlist, and pin/net reference;
- hardware errata and CERN-OHL-P-2.0 licence text.
