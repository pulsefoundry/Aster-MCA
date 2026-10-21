"""macOS USB CDC client for Aster AT32 bring-up 0.1.0 (Python stdlib only).

Usage: python3 read_baseline.py --port /dev/cu.usbmodemXXXX --output PATH
SMA must be disconnected for the results to represent a quiet baseline.
This script does not flash, reset the board, or change macOS permissions.
"""
import argparse
import datetime
import json
import math
import os
from pathlib import Path
import select
import struct
import termios
import time
import tty
import zlib


class Serial:
    def __init__(self, port):
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        tty.setraw(self.fd)
        settings = termios.tcgetattr(self.fd)
        settings[4] = settings[5] = termios.B115200
        settings[2] |= termios.CLOCAL | termios.CREAD
        termios.tcsetattr(self.fd, termios.TCSANOW, settings)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.buf = bytearray()

    def fill(self, deadline):
        remain = deadline - time.monotonic()
        if remain <= 0 or not select.select([self.fd], [], [], remain)[0]:
            raise TimeoutError("No complete response from AT32")
        chunk = os.read(self.fd, 16384)
        if not chunk:
            raise EOFError("USB CDC disconnected")
        self.buf.extend(chunk)

    def line(self, timeout=3):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buf:
            self.fill(deadline)
        n = self.buf.index(b"\n") + 1
        value = bytes(self.buf[:n])
        del self.buf[:n]
        return value.decode("ascii").strip()

    def exact(self, count, timeout=5):
        deadline = time.monotonic() + timeout
        while len(self.buf) < count:
            self.fill(deadline)
        value = bytes(self.buf[:count])
        del self.buf[:count]
        return value

    def command(self, command):
        payload = (command + "\n").encode("ascii")
        if os.write(self.fd, payload) != len(payload):
            raise IOError("Incomplete command write")
        return self.line()

    def info(self, command="INFO"):
        value = json.loads(self.command(command))
        if value.get("board") != "Aster MCA Nano AT32 v0.3" or value.get("fw") not in ("0.1.0", "0.2.0"):
            raise ValueError("Unexpected board or firmware")
        return value


def capture(serial, path):
    stats = json.loads(serial.command("RAW"))
    if stats.get("type") != "stats" or stats.get("n") not in (4096, 8192):
        raise ValueError("Unexpected capture header")
    raw = serial.exact(stats["n"] * 2)
    if serial.exact(2) != b"\r\n":
        raise ValueError("Missing binary frame terminator")
    values = struct.unpack("<" + "H" * stats["n"], raw)
    calculated = {"crc32": zlib.crc32(raw), "min": min(values), "max": max(values),
                  "sum": sum(values), "sum_sq": sum(v * v for v in values)}
    for key, value in calculated.items():
        if stats[key] != value:
            raise ValueError(f"Capture {key} mismatch: {stats[key]} != {value}")
    if calculated["max"] > 4095:
        raise ValueError("ADC data exceeds 12-bit range")
    mean = calculated["sum"] / len(values)
    rms = math.sqrt(max(0, calculated["sum_sq"] / len(values) - mean * mean))
    if stats.get("method") == "timer_dma":
        if any(stats[key] for key in ("dma_error", "dma_remaining", "adc_overrun")):
            raise ValueError("DMA acquisition error")
        nominal = stats["n"] * stats["timer_ticks"]
        timing_error = (stats["elapsed_cycles"] - nominal) / nominal
        stats.update(sample_rate_basis="timer_configuration",
                     effective_sps=stats["sample_rate_hz"],
                     measured_block_sps=stats["n"] * stats["core_hz"] / stats["elapsed_cycles"],
                     block_timing_error_ppm=timing_error * 1e6)
        if abs(timing_error) > 0.01:
            raise ValueError(f"DMA block duration differs by {timing_error:.3%}")
    else:
        stats.update(sample_rate_basis="measured_frame_span",
                     effective_sps=(len(values) - 1) * stats["core_hz"] / stats["span_cycles"])
    stats.update(mean_code=mean, rms_code=rms, mean_v_at_nominal_3v3=mean * 3.3 / 4096,
                 rms_mv_at_nominal_3v3=rms * 3300 / 4096,
                 crc_and_statistics_verified=True)
    path.with_suffix(".bin").write_bytes(raw)
    path.with_suffix(".json").write_text(json.dumps(stats, indent=2) + "\n")
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blocks", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.blocks <= 100:
        parser.error("--blocks must be 1..100")
    args.output.mkdir(parents=True, exist_ok=False)
    result = {"started": datetime.datetime.now().astimezone().isoformat(),
              "port": args.port, "completed": False, "captures": []}
    serial = None
    try:
        serial = Serial(args.port)
        result["initial_info"] = serial.info()
        if serial.command("PING") != "PONG":
            raise ValueError("PING failed")
        if result["initial_info"]["adc_fault"]:
            raise ValueError("ADC initialization fault")
        for mode in ("SLOW", "FAST"):
            result[mode.lower() + "_info"] = serial.info(mode)
            for index in range(args.blocks):
                stats = capture(serial, args.output / f"{mode.lower()}-{index + 1:02d}")
                result["captures"].append(stats)
                print(mode, "mean", round(stats["mean_code"], 3), "rms", round(stats["rms_code"], 3),
                      "range", stats["min"], stats["max"], "CRC OK", flush=True)
        result["adc_off_info"] = serial.info("ADC OFF")
        if result["adc_off_info"]["adc_on"] != 0:
            raise ValueError("ADC OFF did not disable ADC")
        result["disabled_capture_response"] = serial.command("STATS")
        result["disabled_capture_info"] = json.loads(serial.line())
        if result["disabled_capture_response"] != "ERR ADC_DISABLED_OR_FAULT":
            raise ValueError("Disabled ADC capture did not reject request")
        result["adc_on_info"] = serial.info("ADC ON")
        if result["adc_on_info"]["adc_on"] != 1 or result["adc_on_info"]["adc_fault"]:
            raise ValueError("ADC restart failed")
        result["captures"].append(capture(serial, args.output / "after-adc-restart"))
        result["final_info"] = serial.info("SLOW")
        result["heartbeat_counter_advanced"] = (
            result["final_info"]["led_edges"] > result["initial_info"]["led_edges"])
        result["completed"] = True
    except Exception as error:
        result["error"] = repr(error)
        raise
    finally:
        if serial:
            os.close(serial.fd)
        result["finished"] = datetime.datetime.now().astimezone().isoformat()
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
