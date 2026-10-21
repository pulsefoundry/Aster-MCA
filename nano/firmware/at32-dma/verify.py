"""Verify live v0.2.0 rate settings, raw data integrity and DMA timing.

Uses the standard-library USB serial transport from the previous bring-up.
SMA should be disconnected for this validation to represent a baseline.
"""
from pathlib import Path
import datetime
import glob
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firmware/at32-bringup"))
from read_baseline import Serial, capture


def main():
    ports = glob.glob("/dev/cu.usbmodem13819F0C2876*")
    assert len(ports) == 1, ports
    out = ROOT / "work/at32-bringup-2026-10-14" / ("dma-validation-" + datetime.datetime.now().strftime("%H%M%S"))
    out.mkdir()
    r = {"started": datetime.datetime.now().astimezone().isoformat(), "completed": False,
         "input_condition": "SMA disconnected as requested for BOOT/reflash; user replug response is the bench checkpoint.",
         "captures": [], "rate_info": []}
    serial = Serial(ports[0])
    try:
        r["initial_info"] = serial.info()
        assert r["initial_info"]["fw"] == "0.2.0" and r["initial_info"]["adc_fault"] == 0
        assert serial.command("PING") == "PONG"
        for rate in [10000, 100000, 500000, 1000000]:
            info = serial.info("RATE " + str(rate)); r["rate_info"].append(info)
            assert info["sample_rate_hz"] == rate and info["method"] == "timer_dma"
            for i in range(3):
                stats = capture(serial, out / f"rate-{rate}-{i+1}")
                assert stats["sample_rate_hz"] == rate and stats["n"] == 8192
                r["captures"].append(stats)
                print(rate, "Hz, mean", round(stats["mean_code"], 3), "RMS", round(stats["rms_code"], 3),
                      "elapsed", stats["elapsed_cycles"], "timing ppm", round(stats["block_timing_error_ppm"], 1), "CRC OK", flush=True)
        r["invalid_rate_response"] = serial.command("RATE 2000000")
        assert r["invalid_rate_response"].startswith("ERR RATE_USE_")
        assert serial.info()["sample_rate_hz"] == 1000000
        r["off_info"] = serial.info("ADC OFF"); assert r["off_info"]["adc_on"] == 0
        r["off_capture_response"] = serial.command("STATS")
        assert r["off_capture_response"] == "ERR ADC_DISABLED_OR_FAULT"
        r["off_capture_info"] = json.loads(serial.line())
        r["on_info"] = serial.info("ADC ON")
        assert r["on_info"]["adc_fault"] == 0 and r["on_info"]["adc_on"] == 1
        r["captures"].append(capture(serial, out / "after-adc-restart"))
        r["final_info"] = serial.info("TURBO")
        assert r["final_info"]["led_edges"] > r["initial_info"]["led_edges"]
        r["completed"] = True
    except Exception as error:
        r["error"] = repr(error)
        raise
    finally:
        os.close(serial.fd)
        r["finished"] = datetime.datetime.now().astimezone().isoformat()
        (out / "result.json").write_text(json.dumps(r, indent=2) + "\n")
        (ROOT / "work/at32-bringup-2026-10-14/latest-dma-validation-path.txt").write_text(str(out) + "\n")
        print("OUTPUT", out, flush=True)


if __name__ == "__main__":
    main()
