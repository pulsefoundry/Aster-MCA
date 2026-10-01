# USB/UART protocol

The FPGA UART is 1,000,000 baud, 8 data bits, no parity, and one stop bit. The
10 MHz FPGA clock gives exactly ten FPGA clocks per UART bit. The on-board
CH347T exposes this UART through USB bulk endpoints; the reference host utility
uses libusb directly.

## Commands

Commands are a single ASCII byte unless an argument is listed.

| Command | Argument | Meaning |
| --- | --- | --- |
| `I` | none | Return firmware and acquisition capabilities. |
| `S` | none | Return current ADC state and statistics. |
| `H` | none | Pause acquisition and return all 4096 histogram bins. |
| `C` | none | Clear the histogram and statistics. |
| `T` | little-endian uint16 | Set threshold; values below 4 are clamped to 4. |
| `P` | uint8 | Set polarity: 0 = rising code, 1 = falling code. |
| `M` | uint8 | Select energy estimator: 0 = peak; 1/2/3/4 = fixed-window area divided by 1/2/4/8; 5/6/7 = 16/4/16 trapezoid divided by 4/8/16. |

## Response frame

Every response has this structure:

1. four-byte ASCII magic `MCA1`;
2. one-byte response type;
3. one-byte status (`0` means success);
4. little-endian uint16 payload length;
5. payload;
6. little-endian CRC-16/CCITT-FALSE over the header and payload.

CRC parameters are polynomial `0x1021`, initial value `0xffff`, no reflection,
and no final XOR.

Histogram values are little-endian uint32 values in channel order. The
histogram transfer pauses event processing so the host cannot read a bin while
the FPGA is updating it. Rate calculations should use the 64-bit live-sample
counter returned by `S`, divided by 10,000,000 samples/s.

The Python implementation in `astermca.py` is the executable protocol
reference. `tb_protocol.v` and `test_astermca.py` cover framing and CRC handling.

Successful `T`, `P`, and `M` commands return the four-byte payload
`command, 0x00, value_lo, value_hi`. An accepted `M` command also clears the
histogram and acquisition statistics, preventing peak-height and pulse-area
events from being mixed. Modes above 7 return status 1 and leave the current
mode unchanged.

## STATS payload compatibility

Firmware through v1.9 returns a 44-byte `S` payload. Firmware v1.10 and later append:

| Offset | Size | Meaning |
| ---: | ---: | --- |
| 43 | 1 | Selected energy mode. This byte was reserved and zero in v1.9. |
| 44 | 2 | Most recent histogram bin, little-endian uint16. |

The existing raw peak height remains at offsets 40-41. A compatible host must
accept both lengths; for a 44-byte response it should assume peak mode and use
the raw peak as the most recent histogram bin.

## INFO feature byte

The fourth byte of the 16-byte `I` payload is a feature bitmap:

| Bit | Meaning |
| ---: | --- |
| 0 | Peak-height histogram is implemented. |
| 1 | Triggering and peak extraction use a four-sample boxcar average. |
| 2 | A trigger requires two consecutive above-threshold samples. |
| 3 | Baseline IIR uses symmetric signed rounding. |
| 4 | ADC inputs use falling-edge IOLOGIC capture plus a fabric pipeline. |
| 5 | Selectable pulse-area energy estimation is implemented. |
| 6 | Pulse-area estimation uses a fixed acquisition window. |
| 7 | Digital trapezoidal shaping is implemented. |

Firmware v1.3 reports `0x01`; firmware v1.9 reports `0x11`; firmware v1.14
reports `0xf7`. Bits 1 through 3 retain their development-feature meanings in
v1.14. Unknown set bits must be ignored by compatible host software.
