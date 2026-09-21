#!/usr/bin/env python3
"""Patch a Gowin .fs device ID and recompute the first-frame CRC16/ARC."""

from pathlib import Path
import sys


def crc16_arc(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def bits_to_bytes(line: str) -> bytearray:
    bits = line.strip()
    if len(bits) % 8:
        raise ValueError("bitstream line is not byte-aligned")
    return bytearray(int(bits[i : i + 8], 2) for i in range(0, len(bits), 8))


def bytes_to_bits(data: bytes) -> str:
    return "".join(f"{byte:08b}" for byte in data)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} INPUT.fs OUTPUT.fs")

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    lines = source.read_text().splitlines()
    data_indices = [i for i, line in enumerate(lines) if line and not line.startswith("//")]

    device_line = None
    frame_count_pos = None
    for pos, line_index in enumerate(data_indices):
        command = bits_to_bytes(lines[line_index])
        if command[0] == 0x06:
            device_line = line_index
        if command[0] == 0x3B:
            frame_count_pos = pos
            break

    if device_line is None or frame_count_pos is None:
        raise ValueError("device-ID or frame-count command not found")

    device_command = bits_to_bytes(lines[device_line])
    old_id = int.from_bytes(device_command[4:8], "big")
    if old_id != 0x0100381B:
        raise ValueError(f"unexpected source ID 0x{old_id:08X}")
    device_command[4:8] = (0x1100381B).to_bytes(4, "big")
    lines[device_line] = bytes_to_bits(device_command)

    first_frame_pos = frame_count_pos + 1
    first_frame_line = data_indices[first_frame_pos]
    first_frame = bits_to_bytes(lines[first_frame_line])
    if len(first_frame) < 8:
        raise ValueError("first frame is too short")

    crc_data = bytearray()
    # The first three non-comment lines are the Gowin preamble. The D2 SPI
    # address command is deliberately excluded, matching Apycula's writer.
    for pos in range(3, frame_count_pos + 1):
        command = bits_to_bytes(lines[data_indices[pos]])
        if command[0] != 0xD2:
            crc_data.extend(command)
    crc_data.extend(first_frame[:-8])

    crc = crc16_arc(bytes(crc_data))
    first_frame[-8] = crc & 0xFF
    first_frame[-7] = crc >> 8
    lines[first_frame_line] = bytes_to_bits(first_frame)

    destination.write_text("\n".join(lines) + "\n")
    print(f"patched ID: 0x{old_id:08X} -> 0x1100381B")
    print(f"first-frame CRC16/ARC: 0x{crc:04X}")
    print(destination)


if __name__ == "__main__":
    main()
