"""Verify the published checkpoint offline. Standard library; no device access."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import math
import struct
import sys
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'firmware/at32-peakhold-fast7'))
from capture_spectrum import decode_batch, add_events
from read_timing import FIELDS


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, default=ROOT/'measurements/2026-11-18-peakhold')
    args = p.parse_args()
    expected = json.loads((args.data/'SHA256.json').read_text())['files']
    for name, sha in expected.items():
        assert hashlib.sha256((args.data/name).read_bytes()).hexdigest() == sha, name
    totals = dict(public_files=len(expected), archive_files=0, unchanged_binary_files=0,
                  spectrum_runs=0, spectrum_batches=0, event_records=0,
                  timing_batches=0, preserved_failed_timing_runs=0, raw_snapshots=0)
    for filename in ['awg-bench.zip', 'cs137-600s.zip', 'wait-deadline-sweep.zip']:
        with zipfile.ZipFile(args.data/filename) as z:
            names = z.namelist()
            assert len(names) == len(set(names))
            assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names)
            manifests = [n for n in names if len(PurePosixPath(n).parts)==2 and n.endswith('/SHA256.json')]
            assert len(manifests) == 1
            prefix = manifests[0].split('/')[0]+'/'
            manifest = json.loads(z.read(manifests[0]))
            assert set(names) == {prefix+n for n in manifest['files']} | {manifests[0]}
            for name, sha in manifest['files'].items():
                assert hashlib.sha256(z.read(prefix+name)).hexdigest() == sha, name
                totals['archive_files'] += 1
            for name, sha in manifest['original_binary_sha256'].items():
                assert hashlib.sha256(z.read(prefix+name)).hexdigest() == sha
                totals['unchanged_binary_files'] += 1
            for name in names:
                if name.endswith('/spectrum.json'):
                    s = json.loads(z.read(name)); assert s['completed']
                    folder = name.rsplit('/', 1)[0]+'/'
                    counts, all_counts = [0]*2048, [0]*2048
                    sums = {k:0 for k in s['internal_timing_sums']}
                    selection = dict(received=0,binned=0,flagged=0,clipped=0,underflow=0,overflow=0)
                    batches = 0
                    for line in z.read(folder+'batches.jsonl').splitlines():
                        b = json.loads(line)
                        rows = decode_batch(b['header'],z.read(folder+b['file']),
                                            window_us=s['capture_window_us'],peak_sample_x2=s['peak_sample_cycles_x2'],
                                            wait_limit_us=s['wait_limit_us'])
                        check = add_events(counts, rows); assert check == b['selection']
                        for k in selection: selection[k] += check[k]
                        for k in sums: sums[k] += b['header'][k]
                        for row in rows:
                            if 0 <= row['amplitude_code'] < 4096:
                                all_counts[math.floor(row['amplitude_code']/2)] += 1
                        batches += 1; totals['event_records'] += len(rows)
                    assert counts == s['counts'] and all_counts == s['all_received_counts']
                    assert all(selection[k] == s['totals'][k] for k in selection)
                    assert sums == s['internal_timing_sums'] and batches == s['totals']['batches']
                    totals['spectrum_runs'] += 1; totals['spectrum_batches'] += batches
                elif name.endswith('/result.json'):
                    d = json.loads(z.read(name)); h = d.get('header',{})
                    if h.get('type') != 'phcapture': continue
                    raw = z.read(name.rsplit('/',1)[0]+'/records.bin')
                    assert zlib.crc32(raw) == h['crc32'] and len(raw) == 64*h['n']
                    assert h['fault']==0 and h['selftest']==15 and h['requested']==h['attempts_started']
                    assert h['n']+h['timeouts']+h['baseline_rejects']==h['requested']
                    binary = list(struct.iter_unpack('<16I',raw)); assert len(binary)==len(d['records'])
                    for words,r in zip(binary,d['records']):
                        assert list(words)==[r[k] for k in FIELDS] and r['hold_level']==1
                        assert r['amplitude_code']==sum(words[6:10])/4-words[1]
                    if h['dma_stop_n']:
                        if h['raw_stop_phase']=='trigger':
                            assert h['dma_stop_before_hold_irq_n']==h['dma_stop_n'] and h['dma_stop_minus_hold_irq_max_cycles']<0
                        else:
                            assert h['raw_stop_phase']=='hold' and h['dma_stop_before_hold_irq_n']==0
                            assert h['dma_stop_minus_hold_irq_min_cycles']>=0
                    totals['timing_batches'] += 1
                    totals['preserved_failed_timing_runs'] += not d['completed']
                elif name.endswith('.json') and PurePosixPath(name).name.startswith('snapshot-'):
                    h = json.loads(z.read(name))
                    assert h['type']=='phraw' and h['fault']==0
                    raw = z.read(str(PurePosixPath(name).with_suffix('.bin')))
                    vals = struct.unpack('<4096H',raw)
                    assert h['n']==len(vals) and h['crc32']==zlib.crc32(raw)
                    assert (min(vals),max(vals),sum(vals),sum(v*v for v in vals))==(h['min'],h['max'],h['sum'],h['sum_sq'])
                    assert max(vals)<=4095 and 0<h['guard_remaining']<=4096
                    assert h['sample_rate_hz']*h['timer_ticks']==h['core_hz']==144000000
                    assert abs(h['elapsed_cycles']/(h['n']*h['timer_ticks'])-1)<.01
                    totals['raw_snapshots'] += 1
    for n in [6,7]:
        folder = ROOT/f'firmware/at32-peakhold-fast{n}/prebuilt'
        m = json.loads((folder/'manifest.json').read_text())
        assert hashlib.sha256((folder/f'aster-at32-peakhold-fast-{n}.bin').read_bytes()).hexdigest()==m['sha256']
    wave = args.data/'waveform/N61118A.bin'
    assert hashlib.sha256(wave.read_bytes()).hexdigest()=='694b1d1c8fba6a53dd2dfc7ceef1cc5676572c86e490f4c379f8348ff12123d2'
    print(json.dumps(dict(passed=True,**totals),indent=2))


if __name__=='__main__': main()
