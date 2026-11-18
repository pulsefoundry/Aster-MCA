"""Balanced existing-firmware EARLY/LATE batches; restore the saved profile."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse
import glob
import json
import os
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT/'firmware/at32-peakhold-fast7'
sys.path.insert(0, str(FW))
from capture_spectrum import transport, validate_info


def info():
    ports = glob.glob('/dev/cu.usbmodem*')
    assert len(ports) == 1
    ser = transport.Serial(ports[0])
    try:
        assert ser.command('PING') == 'PONG'
        value = json.loads(ser.command('PHINFO'))
        validate_info(value)
        return value
    finally:
        os.close(ser.fd)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--condition', required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = dict(completed=False, started=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                  condition=args.condition, order=['early', 'late', 'late', 'early']*4,
                  blocks=4, batches=[])
    initial = None
    try:
        initial = info()
        validate_info(initial, True, 49, 500)
        result['initial'] = initial
        for i, phase in enumerate(result['order']):
            name = f'batch-{i+1:02d}-{phase}'
            command = [sys.executable, str(FW/'read_timing.py'), '--output', str(args.output/name),
                       '--events', '128', '--window-us', '6', '--delay-us', '1',
                       '--raw-ksa', '500', '--peak-sample-x2', '49', '--wait-us', '500',
                       '--stop-phase', phase, '--expect-events']
            with (args.output/f'{name}.log').open('x') as log:
                proc = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            assert proc.returncode == 0, f'{name} failed; preserve logs'
            d = json.loads((args.output/name/'result.json').read_text())
            h = d['header']
            assert d['completed'] and d['raw_crc_verified'] and h['requested'] == 128
            assert h['n']+h['timeouts']+h['baseline_rejects'] == 128
            assert h['fault'] == 0 and h['selftest'] == 15
            assert h['raw_stop_phase'] == {'early':'trigger', 'late':'hold'}[phase]
            assert h['window_us'] == 6 and h['extra_delay_us'] == 1 and h['wait_limit_us'] == 500
            if phase == 'early':
                assert h['dma_stop_before_hold_irq_n'] == h['dma_stop_n']
                assert h['dma_stop_minus_hold_irq_max_cycles'] < 0
            else:
                assert h['dma_stop_before_hold_irq_n'] == h['trigger_irq_n'] == 0
                assert h['dma_stop_minus_hold_irq_min_cycles'] >= 0
            entry = dict(index=i+1, block=i//4+1, phase=phase, path=name,
                         received=h['n'], flagged=sum(bool(r['flags']) for r in d['records']),
                         amplitude_all_median_code=statistics.median(r['amplitude_code'] for r in d['records']))
            result['batches'].append(entry)
            (args.output/'sequence.json').write_text(json.dumps(result, indent=2)+'\n')
            if (i+1)%4 == 0:
                print(json.dumps(dict(block=i//4+1, batches=result['batches'][-4:])), flush=True)
        result['capture_completed'] = True
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        if initial is not None:
            ser = None
            try:
                ports = glob.glob('/dev/cu.usbmodem*'); assert len(ports) == 1
                ser = transport.Serial(ports[0])
                for command in [f"PHRATE {initial['raw_rate_hz']//1000}",
                                f"PHPK {initial['peak_sample_cycles_x2']}",
                                f"PHWAIT {initial['wait_limit_us']}",
                                'PHSTOP '+('EARLY' if initial['raw_stop_phase']=='trigger' else 'LATE')]:
                    value = json.loads(ser.command(command)); validate_info(value)
                final = json.loads(ser.command('PHINFO')); result['final'] = final
                validate_info(final)
                for k in ['raw_rate_hz', 'raw_timer_ticks', 'raw_stop_phase', 'peak_sample_cycles_x2',
                          'wait_limit_us', 'adc_hz', 'timer_hz', 'threshold_offset']:
                    assert final[k] == initial[k], f'Not restored: {k}'
                result['original_profile_restored'] = True
            except BaseException as error:
                result['restore_error'] = repr(error)
            finally:
                if ser is not None: os.close(ser.fd)
        result['completed'] = bool(result.get('capture_completed') and result.get('original_profile_restored'))
        (args.output/'sequence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    assert result['completed']
    print(json.dumps(dict(completed=True, batches=len(result['batches']), final=result['final'])), flush=True)


if __name__ == '__main__':
    main()
