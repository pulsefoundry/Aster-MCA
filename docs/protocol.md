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
