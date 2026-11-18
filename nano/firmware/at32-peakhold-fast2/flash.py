"""Guarded update from verified fast.1 to fast.2; keep full backup and readback."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from tool_paths import dfu_util


def main():
    manifest = json.loads((HERE / 'build/manifest.json').read_text())
    assert manifest['firmware'] == '0.4.1-fast.2'
    binary = HERE / 'build/aster-at32-peakhold-fast-2.bin'
    image = binary.read_bytes()
    assert hashlib.sha256(image).hexdigest() == manifest['sha256']
    dfu = dfu_util()
    listing = subprocess.run([dfu, '-l'], capture_output=True, text=True, check=True).stdout
    targets = [s for s in listing.splitlines() if '[2e3c:df11]' in s and 'alt=0,' in s]
    if len(targets) != 1 or '128*002Kg' not in targets[0]:
        raise SystemExit('Expected one AT32 256 KiB DFU target; no write performed')
    path = re.search(r'path="([^"]+)"', targets[0]).group(1)
    out = ROOT / 'work/peakhold-fast-20261116' / datetime.datetime.now().strftime('flash-%Y%m%d-%H%M%S-%f')
    out.mkdir(parents=True, exist_ok=False)
    (out / 'dfu-list.txt').write_text(listing)
    base = [dfu, '-d', '2e3c:df11', '-p', path]

    def run(name, args, leaving=False):
        r = subprocess.run(base + args, capture_output=True, text=True, timeout=30)
        (out / (name + '.log')).write_text(r.stdout + r.stderr)
        print(name, 'exit', r.returncode, flush=True)
        if not leaving:
            r.check_returncode()
        return r.returncode

    run('backup-flash', ['-a', '0', '-s', '0x08000000:262144', '-U', str(out / 'flash-before.bin')])
    run('backup-options', ['-a', '1', '-s', '0x1ffff800:512', '-U', str(out / 'options-before.bin')])
    before = (out / 'flash-before.bin').read_bytes()
    options = (out / 'options-before.bin').read_bytes()
    previous = (HERE.parent/'at32-peakhold-fast/build/aster-at32-peakhold-fast-1.bin').read_bytes()
    assert hashlib.sha256(previous).hexdigest() == '01be51447f42cb9305732fc50aac0cb389a46a50c1cc7c0650edf59cefa86cee'
    assert len(before) == 262144 and before[:len(previous)] == previous, 'Unexpected installed firmware; no write performed'
    assert before[len(previous):] == b'\xff'*(262144-len(previous)), 'Unexpected data beyond installed firmware; no write performed'
    assert len(options) == 512
    run('write', ['-a', '0', '-s', '0x08000000', '-D', str(binary)])
    run('readback-flash', ['-a', '0', '-s', '0x08000000:262144', '-U', str(out / 'flash-after.bin')])
    run('readback-options', ['-a', '1', '-s', '0x1ffff800:512', '-U', str(out / 'options-after.bin')])
    after = (out / 'flash-after.bin').read_bytes()
    erase_end = (len(image) + 2047) // 2048 * 2048
    checks = {
        'program_exact_match': after[:len(image)] == image,
        'erased_padding_ff': after[len(image):erase_end] == b'\xff' * (erase_end-len(image)),
        'outside_erase_unchanged': after[erase_end:] == before[erase_end:],
        'options_unchanged': (out / 'options-after.bin').read_bytes() == options,
        'full_readback_size': len(after) == 262144,
    }
    report = dict(checks, firmware=manifest['firmware'], sha256=manifest['sha256'], bytes=len(image))
    (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    assert all(checks.values()), 'Readback verification failed; not leaving DFU'
    report['leave_exit'] = run('leave', ['-a', '0', '-s', '0x08000000:leave'], leaving=True)
    (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    (out.parent / 'latest-flash-path.txt').write_text(str(out) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    print('OUTPUT', out, flush=True)


if __name__ == '__main__':
    main()
