"""Guarded stable-v0.6.3 <-> peak-v0.8.0 DFU, with full backup and readback."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DFU = '/Users/liu/Documents/Codex/2026-09-10/new-chat/tools/oss-cad-suite/bin/dfu-util'
STABLE = ROOT/'outputs/Aster-MCA-Nano-AT32-板上2048道-v0.6.3/aster-at32-histogram-v0.6.3.bin'
STABLE_SHA = 'f5aab7343fc84d456aaad627ad77f435f8f500e0eb7633f9b9c88d7496935cc8'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-histogram', action='store_true')
    args = parser.parse_args()
    peak = HERE/'build/aster-at32-peak-v0.8.0.bin'
    manifest = json.loads((HERE/'build/manifest.json').read_text())
    assert manifest['firmware'] == '0.8.0'
    assert hashlib.sha256(peak.read_bytes()).hexdigest() == manifest['sha256']
    assert hashlib.sha256(STABLE.read_bytes()).hexdigest() == STABLE_SHA
    binary, previous_path = (STABLE, peak) if args.restore_histogram else (peak, STABLE)
    image, previous = binary.read_bytes(), previous_path.read_bytes()
    listing = subprocess.run([DFU, '-l'], capture_output=True, text=True, check=True).stdout
    targets = [s for s in listing.splitlines() if '[2e3c:df11]' in s and 'alt=0,' in s]
    if len(targets) != 1 or '128*002Kg' not in targets[0]:
        raise SystemExit('Expected exactly one AT32 256 KiB DFU device: '+repr(targets))
    path = re.search(r'path="([^"]+)"', targets[0]).group(1)
    out = ROOT/'work/at32-peak-2026-10-18'/datetime.datetime.now().strftime(
        ('restore-stable-' if args.restore_histogram else 'flash-')+'%Y%m%d-%H%M%S-%f')
    out.mkdir(parents=True, exist_ok=False)
    (out/'dfu-list.txt').write_text(listing)
    base = [DFU, '-d', '2e3c:df11', '-p', path]

    def run(name, arguments, allow_disconnect=False):
        result = subprocess.run(base+arguments, capture_output=True, text=True, timeout=30)
        (out/(name+'.log')).write_text(result.stdout+result.stderr)
        print(name, 'exit', result.returncode, flush=True)
        if not allow_disconnect:
            result.check_returncode()
        return result.returncode

    run('backup-flash', ['-a', '0', '-s', '0x08000000:262144', '-U', str(out/'flash-before.bin')])
    run('backup-options', ['-a', '1', '-s', '0x1ffff800:512', '-U', str(out/'options-before.bin')])
    before = (out/'flash-before.bin').read_bytes()
    assert len(before) == 262144 and before[:len(previous)] == previous, 'Unexpected installed firmware; no write performed'
    assert len((out/'options-before.bin').read_bytes()) == 512
    run('write', ['-a', '0', '-s', '0x08000000', '-D', str(binary)])
    run('readback-flash', ['-a', '0', '-s', '0x08000000:262144', '-U', str(out/'flash-after.bin')])
    run('readback-options', ['-a', '1', '-s', '0x1ffff800:512', '-U', str(out/'options-after.bin')])
    after = (out/'flash-after.bin').read_bytes()
    erase_end = (len(image)+2047)//2048*2048
    checks = dict(program_exact_match=after[:len(image)] == image,
        erased_padding_ff=after[len(image):erase_end] == b'\xff'*(erase_end-len(image)),
        flash_outside_erase_unchanged=before[erase_end:] == after[erase_end:],
        options_unchanged=(out/'options-before.bin').read_bytes() == (out/'options-after.bin').read_bytes(),
        full_readback_size=len(after) == 262144,
        firmware_sha256=hashlib.sha256(image).hexdigest(), written_bytes=len(image), erase_end_offset=erase_end)
    (out/'verification.json').write_text(json.dumps(checks, indent=2)+'\n')
    assert all(checks[key] for key in ('program_exact_match', 'erased_padding_ff',
        'flash_outside_erase_unchanged', 'options_unchanged', 'full_readback_size'))
    checks['leave_exit'] = run('leave', ['-a', '0', '-s', '0x08000000:leave'], allow_disconnect=True)
    (out/'verification.json').write_text(json.dumps(checks, indent=2)+'\n')
    (ROOT/'work/at32-peak-2026-10-18/latest-flash-path.txt').write_text(str(out)+'\n')
    print(json.dumps(checks, indent=2)); print('OUTPUT', out)


if __name__ == '__main__':
    main()
