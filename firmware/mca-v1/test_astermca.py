#!/usr/bin/env python3
import struct
import unittest

import astermca


class FakeTransport:
    def __init__(self, data: bytes):
        self.data = bytearray(data)

    def read_exact(self, size: int, timeout_ms: int = 3000) -> bytes:
        if len(self.data) < size:
            raise astermca.USBError("fake timeout")
        result = bytes(self.data[:size])
        del self.data[:size]
        return result


class StubDevice(astermca.MCADevice):
    def __init__(self, payload: bytes):
        self.payload = payload

    def command(self, request, expected_type=None, timeout_ms=3000):
        return astermca.Frame(astermca.RESP_STATS, 0, self.payload)


def make_frame(response_type: int, status: int, payload: bytes) -> bytes:
    body = b"MCA1" + struct.pack("<BBH", response_type, status, len(payload)) + payload
    return body + struct.pack("<H", astermca.crc16_ccitt(body))


class ProtocolTests(unittest.TestCase):
    def test_crc_reference(self):
        self.assertEqual(astermca.crc16_ccitt(b"123456789"), 0x29B1)

    def test_frame_with_resynchronisation(self):
        payload = bytes(range(16))
        transport = FakeTransport(b"noise" + make_frame(ord("I"), 0, payload))
        frame = astermca.read_frame(transport)
        self.assertEqual(frame.response_type, ord("I"))
        self.assertEqual(frame.status, 0)
        self.assertEqual(frame.payload, payload)

    def test_bad_crc_is_rejected(self):
        raw = bytearray(make_frame(ord("S"), 0, b"abcd"))
        raw[-1] ^= 0x80
        with self.assertRaises(astermca.ProtocolError):
            astermca.read_frame(FakeTransport(raw))

    def test_v110_stats_report_energy_mode_and_bin(self):
        payload = struct.pack(
            "<HHHHHBBIIIIIQHBBH",
            2040, 2048, 1800, 2055, 32, 1, 0,
            10, 8, 2, 0, 0, 1_000_000, 100, 0, 3, 1234,
        )
        stats = StubDevice(payload).stats()
        self.assertEqual(stats["energy_mode"], 3)
        self.assertEqual(stats["last_peak"], 100)
        self.assertEqual(stats["last_energy"], 1234)

    def test_v19_stats_remain_compatible(self):
        payload = struct.pack(
            "<HHHHHBBIIIIIQHBB",
            2040, 2048, 1800, 2055, 32, 1, 0,
            10, 8, 2, 0, 0, 1_000_000, 100, 0, 0,
        )
        stats = StubDevice(payload).stats()
        self.assertEqual(stats["energy_mode"], 0)
        self.assertEqual(stats["last_energy"], 100)


if __name__ == "__main__":
    unittest.main()
