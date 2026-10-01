#!/usr/bin/env python3
import unittest

import astermca
import astermca_gui


class FakeTransport:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeDevice:
    def __init__(self):
        self.threshold = 32
        self.polarity = 1
        self.mode = 0
        self.clears = 0

    def info(self):
        return {
            "version": "1.10",
            "adc_bits": 12,
            "features": 0x31,
            "sample_rate": 10_000_000,
            "channels": 4096,
            "baud": 1_000_000,
        }

    def stats(self):
        return {
            "sample": 2024,
            "baseline": 2024,
            "adc_min": 2018,
            "adc_max": 2110,
            "threshold": self.threshold,
            "polarity": self.polarity,
            "flags": 0,
            "triggers": 20,
            "accepted": 18,
            "rejected": 2,
            "saturated": 0,
            "dropped": 0,
            "live_samples": 20_000_000,
            "last_peak": 95,
            "uart_errors": 0,
            "energy_mode": self.mode,
            "last_energy": 95,
        }

    def histogram(self):
        result = [0] * 4096
        result[95] = 18
        return result

    def clear(self):
        self.clears += 1

    def set_threshold(self, value):
        self.threshold = max(4, value)
        return self.threshold

    def set_polarity(self, reverse):
        self.polarity = int(reverse)
        return self.polarity

    def set_energy_mode(self, mode):
        self.mode = mode
        self.clear()
        return mode


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.device = FakeDevice()
        self.controller = astermca_gui.DeviceController(
            lambda: (self.transport, self.device)
        )

    def tearDown(self):
        self.controller.close()

    def test_connect_and_snapshot(self):
        status = self.controller.connect()
        self.assertTrue(status["connected"])
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot["histogram_total"], 18)
        self.assertEqual(snapshot["live_seconds"], 2.0)
        self.assertEqual(snapshot["average_cps"], 9.0)

    def test_configuration_maps_strings_to_protocol(self):
        self.controller.connect()
        snapshot = self.controller.configure(
            {"threshold": 8, "polarity": "positive", "energy_mode": "area4"}
        )
        self.assertEqual(snapshot["stats"]["threshold"], 8)
        self.assertEqual(snapshot["stats"]["polarity"], 0)
        self.assertEqual(snapshot["stats"]["energy_mode"], astermca.ENERGY_MODES["area4"])
        self.assertEqual(self.device.clears, 1)

    def test_disconnect_closes_transport(self):
        self.controller.connect()
        self.controller.disconnect()
        self.assertTrue(self.transport.closed)
        self.assertFalse(self.controller.connected)

    def test_snapshot_requires_connection(self):
        with self.assertRaises(astermca.USBError):
            self.controller.snapshot()


if __name__ == "__main__":
    unittest.main()
