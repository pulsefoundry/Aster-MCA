# Aster MCA v2.0 r8 quotation package

This directory is for fabrication and assembly **quotation only**.  It is made
from the current r8 editable source, including R9 = R10 = 22 ohm.  It is not an
electrical production release and must not be submitted as a final order until
the MAX 10 Quartus compile and the remaining physical checks are complete.

## Which files to upload

- PCB quotation: `Aster-MCA-v2.0-r8-Gerbers.zip`
- Minimum factory assembly quotation:
  - `Aster-MCA-v2.0-r8-BOM-core-SMT.csv`
  - `Aster-MCA-v2.0-r8-CPL-core-SMT.csv`
- Full SMT quotation for comparison:
  - `Aster-MCA-v2.0-r8-BOM-all-SMT.csv`
  - `Aster-MCA-v2.0-r8-CPL-all-SMT.csv`

The core option contains 38 placements: every 0402/0603 part, the four 0603x4
resistor arrays, FPGA, ADC, FDA, buck regulator and 40 MHz oscillator.  The
remaining 0805/1206 and through-hole parts are left for hand assembly.

The all-SMT option contains 86 placements and leaves only the RP2350 module,
connectors, switches, LEDs, headers, jumpers and test points for hand assembly.

## Exact critical part bindings used for quotation

| Ref. | Manufacturer part | LCSC part |
|---|---|---|
| U1 | 10M16SAE144C8G | C1521931 |
| U2 | ADS5560IRGZT | C571255 |
| U3 | THS4551IDGKT | C2860660 |
| U4 | AP63203WU-7 | C780769 |
| Y1 | ASE-40.000MHZ-L-C-T | C1670009 |
| RN1-RN4 | RTA03-4D330JTP | C102663 |
| C2 | GCM1885C1H222JA16D, 2.2 nF C0G | C343869 |
| C38 | CL05B104KO5NNNC, 100 nF 0402 X7R | C1525 |
| Other 100 nF 0603 | CC0603KPX7R8BB104, 25 V X7R | C1853266 |

Do not accept an automatic substitute for U1, U2, U3, U4 or Y1.  A package
match by itself is not sufficient.

## Stock and price warning, checked 2026-09-25

The public LCSC pages showed approximately USD 78.61 each for U1 and USD 73.26
each for U2.  The U2 page reported out of stock; U1 availability was inconsistent
between the product and image pages.  Therefore an online assembly quote may be
blocked even though the CSV files import correctly.

At the public reference prices, U1 and U2 alone are about USD 303.74 for two
assembled boards, approximately CNY 2,039 at 6.7133 CNY/USD.  Adding U3, U4 and
Y1 raises the five major-part subtotal to about CNY 2,155, before PCB, passive
parts, setup, assembly, tax and shipping.  These figures are reference estimates,
not a JLCPCB checkout quote.

If the assembly system reports U1 or U2 unavailable, stop at quotation.  The
practical alternatives are customer-supplied parts or purchasing the exact parts
elsewhere and arranging a service that accepts consigned components; do not let
the website choose a similar device automatically.
