"""Capture complete 8192-point 4M bursts, then process spectra on the PC."""
import argparse
import datetime
import json
import math
from pathlib import Path
import time
try:
    from .protocol import Serial, N, RATE, validate_info, validate_frame
    from .spectrum import Spectrum
except ImportError:
    from protocol import Serial, N, RATE, validate_info, validate_frame
    from spectrum import Spectrum


def run(port, out, seconds, input_condition, threshold=20, stop_event=None,
        on_progress=None, on_event=None, quiet=False):
    if not math.isfinite(seconds) or not .01 <= seconds <= 3600:
        raise ValueError('seconds must be .01..3600')
    if not math.isfinite(threshold) or not 1 <= threshold <= 2048:
        raise ValueError('threshold must be 1..2048')
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    record = dict(started=datetime.datetime.now().astimezone().isoformat(), port=port,
                  input=input_condition, requested_seconds=seconds, duration_basis='wall_time',
                  acquisition_mode='burst', completed=False,
                  host_processing='Finite 8192-sample 4 MS/s DMA bursts, followed by raw USB transfer. All samples within each burst saved; gaps are not sampled.')
    serial = None; spectrum = None; blocks = 0; t0 = None; last_progress = 0
    try:
        spectrum = Spectrum(out, threshold, on_event)
        with (out/'wire.bin').open('wb') as wire, (out/'samples.u16').open('wb') as rawfile, \
             (out/'blocks.jsonl').open('w') as headers:
            serial = Serial(port, wire)
            info = json.loads(serial.command('INFO')); record['initial_info'] = info
            validate_info(info)
            expected_id = info['capture_id'] + 1
            t0 = time.monotonic(); last_progress = t0
            while time.monotonic()-t0 < seconds:
                if stop_event is not None and stop_event.is_set():
                    break
                requested_at = time.monotonic()-t0
                header = serial.command('RAW')
                if header.startswith('ERR'):
                    raise ValueError('设备拒绝采集：'+header)
                stats = json.loads(header)
                # Do not trust a malformed length to determine allocation/read size.
                if stats.get('n') != N or stats.get('type') != 'stats':
                    raise ValueError('Unexpected burst header')
                raw = serial.exact(N*2)
                if serial.exact(2) != b'\r\n':
                    raise ValueError('Missing waveform terminator')
                verified = validate_frame(stats, raw, expected_id)
                meta = dict(stats, **verified, segment_index=blocks,
                            stored_sample_offset=blocks*N, request_wall_offset_s=requested_at,
                            received_wall_offset_s=time.monotonic()-t0)
                rawfile.write(raw); headers.write(json.dumps(meta)+'\n')
                spectrum.feed(raw, stats['id']); blocks += 1; expected_id += 1
                wall = time.monotonic()-t0
                if on_progress and time.monotonic()-last_progress >= .25:
                    on_progress(dict(samples=blocks*N, seconds=blocks*N/RATE,
                                     wall_seconds=wall, duty_cycle=(blocks*N/RATE)/wall,
                                     candidates=spectrum.total, accepted=spectrum.accepted,
                                     threshold_codes=threshold, blocks=blocks,
                                     analysis_window_seconds=spectrum.analysis_samples/RATE))
                    last_progress = time.monotonic()
            if not blocks:
                raise ValueError('本轮没有完整采集段')
            final_info = json.loads(serial.command('INFO')); record['final_info'] = final_info
            validate_info(final_info)
            if final_info['capture_id'] != expected_id-1:
                raise ValueError('Capture counter changed unexpectedly')
            record['completed'] = True
            record['stop_reason'] = 'user_stop' if stop_event is not None and stop_event.is_set() else 'duration'
    except BaseException as exc:
        record['error'] = repr(exc)
        raise
    finally:
        if serial is not None:
            serial.close()
        wall = time.monotonic()-t0 if t0 is not None else 0
        sampled = blocks*N/RATE
        record.update(finished=datetime.datetime.now().astimezone().isoformat(), blocks=blocks,
                      wall_seconds=wall, observed_sampled_seconds=sampled,
                      verified_sampled_seconds=sampled if record['completed'] else 0,
                      unsampled_wall_seconds=max(0, wall-sampled),
                      duty_cycle=sampled/wall if wall else 0, stored_raw_samples=blocks*N,
                      spectrum=spectrum.finish(record['completed']) if spectrum else None)
        (out/'capture.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
        if not quiet:
            print(json.dumps({k:record[k] for k in ['completed','blocks','wall_seconds',
                      'verified_sampled_seconds','duty_cycle']}, ensure_ascii=False), flush=True)
    return record


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=10); p.add_argument('--input', required=True)
    p.add_argument('--threshold', type=float, default=20)
    a = p.parse_args()
    run(a.port, a.out, a.seconds, a.input, a.threshold)
