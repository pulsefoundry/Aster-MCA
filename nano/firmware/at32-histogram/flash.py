"""Flash the identified AT32 prototype via its factory DFU, then verify reads.

Requires the user to put the board into BOOT/DFU first. Never writes option
bytes, never mass-erases, and refuses an unexpected previous application.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DFU = "/Users/liu/Documents/Codex/2026-09-10/new-chat/tools/oss-cad-suite/bin/dfu-util"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-burst',action='store_true',help='Restore verified v0.5.0 after exact v0.6.3 match')
    args=parser.parse_args()
    listing = subprocess.run([DFU, "-l"], capture_output=True, text=True, check=True).stdout
    targets = [line for line in listing.splitlines() if "[2e3c:df11]" in line and "alt=0," in line]
    if len(targets) != 1 or "128*002Kg" not in targets[0]:
        raise SystemExit("Expected one AT32 DFU device with 256 KiB / 2 KiB pages. " + repr(targets))
    path = re.search(r'path="([^"]+)"', targets[0]).group(1)
    out = ROOT / "work/at32-histogram-2026-10-15" / ( ("restore-burst-" if args.restore_burst else "histogram-flash-") + datetime.datetime.now().strftime("%H%M%S"))
    out.mkdir(parents=True)
    (out / "dfu-list.txt").write_text(listing)
    base = [DFU, "-d", "2e3c:df11", "-p", path]

    def run(name, args, allow_disconnect=False):
        result = subprocess.run(base + args, capture_output=True, text=True, timeout=30)
        (out / (name + ".log")).write_text(result.stdout + result.stderr)
        print(name, "exit", result.returncode, flush=True)
        if not allow_disconnect:
            result.check_returncode()
        return result.returncode

    binary = (ROOT / "firmware/at32-burst/build/aster-at32-burst-v0.5.0.bin" if args.restore_burst
              else HERE / "build/aster-at32-histogram-v0.6.3.bin")
    image = binary.read_bytes()
    manifest = json.loads((binary.parent / "manifest.json").read_text())
    assert hashlib.sha256(image).hexdigest() == manifest["sha256"]
    run("backup-flash", ["-a", "0", "-s", "0x08000000:262144", "-U", str(out / "flash-before.bin")])
    run("backup-options", ["-a", "1", "-s", "0x1ffff800:512", "-U", str(out / "options-before.bin")])
    previous_path = (HERE / "build/aster-at32-histogram-v0.6.3.bin" if args.restore_burst else
                ROOT / "outputs/Aster-MCA-Nano-AT32-板上2048道-v0.6.2/aster-at32-histogram-v0.6.2.bin")
    previous=previous_path.read_bytes()
    previous_manifest=json.loads((previous_path.parent/'manifest.json').read_text())
    assert hashlib.sha256(previous).hexdigest()==previous_manifest['sha256'], 'Previous image reference checksum mismatch'
    before = (out / "flash-before.bin").read_bytes()
    assert len(before) == 262144 and before[:len(previous)] == previous, "Unexpected previous firmware; no write performed"
    run("write", ["-a", "0", "-s", "0x08000000", "-D", str(binary)])
    run("readback-flash", ["-a", "0", "-s", "0x08000000:262144", "-U", str(out / "flash-after.bin")])
    run("readback-options", ["-a", "1", "-s", "0x1ffff800:512", "-U", str(out / "options-after.bin")])
    after = (out / "flash-after.bin").read_bytes()
    erase_end = ((len(image) + 2047) // 2048) * 2048
    checks = {"program_exact_match": after[:len(image)] == image,
              "erased_padding_ff": all(b == 255 for b in after[len(image):erase_end]),
              "flash_outside_erase_unchanged": before[erase_end:] == after[erase_end:],
              "options_unchanged": (out / "options-before.bin").read_bytes() == (out / "options-after.bin").read_bytes(),
              "firmware_sha256": manifest["sha256"], "written_bytes": len(image), "erase_end_offset": erase_end}
    (out / "verification.json").write_text(json.dumps(checks, indent=2) + "\n")
    assert all(checks[k] for k in ["program_exact_match", "erased_padding_ff", "flash_outside_erase_unchanged", "options_unchanged"])
    checks["leave_exit"] = run("leave", ["-a", "0", "-s", "0x08000000:leave"], allow_disconnect=True)
    (out / "verification.json").write_text(json.dumps(checks, indent=2) + "\n")
    (ROOT / "work/at32-histogram-2026-10-15/latest-histogram-flash-path.txt").write_text(str(out) + "\n")
    print(json.dumps(checks, indent=2)); print("OUTPUT", out)


if __name__ == "__main__":
    main()
