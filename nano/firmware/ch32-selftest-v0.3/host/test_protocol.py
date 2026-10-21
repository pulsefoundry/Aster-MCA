"""Exercise USB fragmentation, corruption recovery and amplitude reporting."""
import struct
import unittest
from capture_wave import Decoder, HEADER, MAGIC, N, describe, fnv1a


def make_packet(sequence=1):
    samples = [2048] * N
    samples[1010:1015] = [2050, 2080, 2168, 2080, 2050]
    payload = struct.pack('<4096H', *samples)
    h = [3, sequence, 0, N, 48000000, 144, 589824, 0, 4,
         (sum(samples) * 10 + N // 2) // N, 2048, 2168, 0,
         sequence, 32, 0x10001, 0x1e0103, 6, fnv1a(payload), 0]
    prefix = HEADER.pack(MAGIC, *h)
    h[-1] = fnv1a(prefix[:84])
    return HEADER.pack(MAGIC, *h) + payload


class ProtocolTest(unittest.TestCase):
    def test_known_hash(self):
        self.assertEqual(fnv1a(b'hello'), 0x4f9f2cab)

    def test_fragmented_usb_and_pulse_amplitude(self):
        decoder = Decoder()
        stream = b'ASTER selftest v0.3 mode=WAVE\r\n' + make_packet()
        frames = []
        for i in range(0, len(stream), 63):
            frames += decoder.feed(stream[i:i + 63])
        self.assertEqual(len(frames), 1)
        self.assertEqual((decoder.bad_headers, decoder.bad_payloads), (0, 0))
        row = describe(*frames[0], 3.29)
        self.assertEqual(row['median_code'], 2048)
        self.assertAlmostEqual(row['positive_excursion_from_median_mV'], 120 * 3290 / 4095)
        self.assertEqual(row['negative_excursion_from_median_mV'], 0)
        self.assertTrue(row['timing_sanity_ok'])

    def test_corruption_and_recovery(self):
        bad_header = bytearray(make_packet(1)); bad_header[20] ^= 1
        bad_payload = bytearray(make_packet(2)); bad_payload[1000] ^= 1
        decoder = Decoder()
        frames = decoder.feed(bad_header + bad_payload + make_packet(3))
        self.assertEqual([h[1] for h, samples in frames], [3])
        self.assertEqual((decoder.bad_headers, decoder.bad_payloads), (1, 1))

    def test_no_partial_frame_and_bad_timing_flagged(self):
        packet = make_packet()
        decoder = Decoder()
        self.assertEqual(decoder.feed(packet[:-1]), [])
        frames = decoder.feed(packet[-1:])
        self.assertEqual(len(frames), 1)
        h, samples = frames[0]
        h = list(h); h[6] *= 2
        self.assertFalse(describe(h, samples, 3.29)['timing_sanity_ok'])


if __name__ == '__main__':
    unittest.main()
