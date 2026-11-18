"""Guarded fast.7 RAW snapshots with restoration of the original timer rate."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse
import glob
import json
import os
import struct
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'firmware/at32-peakhold-fast7'))
from capture_spectrum import transport, validate_info


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--condition', required=True)
    p.add_argument('--nominal-mvpp', type=float, required=True)
    p.add_argument('--snapshots', type=int, default=20)
    p.add_argument('--raw-ksa', type=int, choices=[500, 1000, 2000, 4000], default=4000)
    args = p.parse_args()
    assert 1 <= args.snapshots <= 100
    ports = glob.glob('/dev/cu.usbmodem*')
    assert len(ports) == 1, 'Expected one Nano serial port'
    args.output.mkdir(parents=True, exist_ok=False)
    result = dict(completed=False, started=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                  condition=args.condition, nominal_generator_mvpp=args.nominal_mvpp,
                  nominal_generator_offset_mv=-args.nominal_mvpp/2, port=ports[0], snapshots=[],
                  note='Discontinuous RAW DMA snapshots; no true live time or trigger efficiency measurement.')
    ser, initial = None, None
    begin = time.monotonic()
    try:
        ser = transport.Serial(ports[0])
        assert ser.command('PING') == 'PONG'
        initial = json.loads(ser.command('PHINFO'))
        result['initial'] = initial
        validate_info(initial)
        configured = json.loads(ser.command(f'PHRATE {args.raw_ksa}'))
        result['configured'] = configured
        validate_info(configured)
        rate = args.raw_ksa*1000
        assert configured['raw_rate_hz'] == rate
        assert configured['raw_timer_ticks']*rate == configured['timer_hz']
        assert configured['adc_hz'] == initial['adc_hz'] == 72000000
        for i in range(args.snapshots):
            stem = f'snapshot-{i+1:03d}'
            head = json.loads(ser.command('PHRAW'))
            (args.output/f'{stem}.json').write_text(json.dumps(head, indent=2)+'\n')
            assert head['type'] == 'phraw' and head['n'] == 4096 and head['channel'] == 'RAW'
            raw = ser.exact(head['n']*2)
            (args.output/f'{stem}.bin').write_bytes(raw)
            assert ser.exact(2) == b'\r\n'
            assert head['fw'] == initial['fw'] and head['fault'] == 0
            assert head['sample_rate_hz'] == rate and head['core_hz'] == 144000000
            assert head['adc_hz'] == 72000000 and head['sample_cycles_x2'] == 5
            assert head['timer_ticks']*rate == head['core_hz']
            assert 0 < head['guard_remaining'] <= 4096
            values = struct.unpack('<4096H', raw)
            calculated = dict(min=min(values), max=max(values), sum=sum(values),
                              sum_sq=sum(v*v for v in values), crc32=zlib.crc32(raw))
            assert all(head[k] == v for k, v in calculated.items())
            assert max(values) <= 4095
            duration_error = head['elapsed_cycles']/(head['n']*head['timer_ticks'])-1
            assert abs(duration_error) < .01
            result['snapshots'].append(dict(file=f'{stem}.bin', header_file=f'{stem}.json',
                                          crc_statistics_guard_verified=True,
                                          duration_error_fraction=duration_error,
                                          minimum_code=min(values), maximum_code=max(values)))
        result['capture_completed'] = True
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        if ser is not None:
            try:
                if initial is not None:
                    final = json.loads(ser.command(f"PHRATE {initial['raw_rate_hz']//1000}"))
                    result['final'] = final
                    validate_info(final)
                    for k in ['raw_rate_hz', 'raw_timer_ticks', 'timer_hz', 'adc_hz',
                              'raw_stop_phase', 'peak_sample_cycles_x2', 'wait_limit_us', 'threshold_offset']:
                        assert final[k] == initial[k], f'Failed to restore {k}'
                    result['original_profile_restored'] = True
            except BaseException as error:
                result['restore_error'] = repr(error)
            os.close(ser.fd)
        result['wall_seconds'] = time.monotonic()-begin
        result['completed'] = bool(result.get('capture_completed') and result.get('original_profile_restored'))
        (args.output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    assert result['completed'], 'Capture or profile restoration failed; see saved result'
    print(json.dumps(dict(completed=True, snapshots=len(result['snapshots']),
                         wall_seconds=result['wall_seconds'], restored_raw_hz=result['final']['raw_rate_hz'],
                         minimum_code=min(s['minimum_code'] for s in result['snapshots']),
                         maximum_code=max(s['maximum_code'] for s in result['snapshots']),
                         final=result['final']), indent=2))


if __name__ == '__main__':
    main()
