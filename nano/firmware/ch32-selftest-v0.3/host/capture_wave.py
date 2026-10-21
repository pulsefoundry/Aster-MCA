#!/usr/bin/env python3
"""Capture checked Aster v0.3 waveform packets; return to NORMAL on exit.

The firmware acquires finite DMA blocks and pauses during upload. Neither
the trigger/frame count nor wall-clock rate is a detector count rate.
"""
import argparse
import csv
import glob
import json
import os
from pathlib import Path
import select
import statistics
import struct
import termios
import time
import tty

MAGIC = b'ASTW03\r\n'
HEADER = struct.Struct('<8s20I')
N = 4096


def fnv1a(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


class Decoder:
    def __init__(self):
        self.buffer = bytearray()
        self.bad_headers = 0
        self.bad_payloads = 0

    def feed(self, chunk):
        self.buffer.extend(chunk)
        frames = []
        while True:
            pos = self.buffer.find(MAGIC)
            if pos < 0:
                if len(self.buffer) > 7:
                    del self.buffer[:-7]
                break
            if pos:
                del self.buffer[:pos]
            if len(self.buffer) < HEADER.size:
                break
            fields = HEADER.unpack_from(self.buffer)
            h = fields[1:]
            if (h[0] != 3 or h[2] != 0 or h[3] != N or h[4] != 48000000 or
                    h[5] != 144 or fnv1a(self.buffer[:84]) != h[19]):
                self.bad_headers += 1
                del self.buffer[0]
                continue
            size = HEADER.size + h[3] * 2
            if len(self.buffer) < size:
                break
            payload = bytes(self.buffer[HEADER.size:size])
            if fnv1a(payload) != h[18]:
                self.bad_payloads += 1
                del self.buffer[0]
                continue
            samples = struct.unpack('<' + 'H' * h[3], payload)
            if (max(samples) > 4095 or min(samples) != h[10] or max(samples) != h[11]
                    or (sum(samples) * 10 + N // 2) // N != h[9]):
                self.bad_payloads += 1
                del self.buffer[0]
                continue
            frames.append((h, samples))
            del self.buffer[:size]
        return frames


def describe(h, samples, supply):
    ordered = sorted(samples)
    center = statistics.median(ordered)
    scale = supply * 1000 / 4095
    expected_ticks = h[3] * h[5]
    return {
        'sequence': h[1], 'channel': h[2], 'samples': h[3],
        'sample_period_us_nominal': h[5] / h[4] * 1e6,
        'capture_elapsed_us': h[6] / h[4] * 1e6,
        'elapsed_vs_nominal_ratio': h[6] / expected_ticks,
        'timing_sanity_ok': 0.98 <= h[6] / expected_ticks <= 1.10,
        'preceding_gap_us': h[7] / h[4] * 1e6,
        'flags': h[8], 'near_rail': bool(h[8] & 1),
        'mean_code': sum(samples) / len(samples), 'median_code': center,
        'min_code': min(samples), 'max_code': max(samples),
        'peak_to_peak_mV': (max(samples) - min(samples)) * scale,
        'positive_excursion_from_median_mV': (max(samples) - center) * scale,
        'negative_excursion_from_median_mV': (center - min(samples)) * scale,
        'p01_to_p99_mV': (ordered[int((N - 1) * .99)] - ordered[int((N - 1) * .01)]) * scale,
        'adc_errors': h[12], 'acquired_blocks': h[13], 'trigger_codes': h[14],
        'opa_ctl1': hex(h[15]), 'adc_ctl2_while_capturing': hex(h[16]),
        'adc_ctl3': hex(h[17]),
    }


def open_port(port):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        tty.setraw(fd)
        attrs = termios.tcgetattr(fd)
        attrs[2] |= termios.CLOCAL | termios.CREAD
        attrs[4] = attrs[5] = termios.B115200
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_for(fd, seconds):
    chunks = bytearray()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if select.select([fd], [], [], min(.1, max(0, deadline - time.monotonic())))[0]:
            try:
                chunks.extend(os.read(fd, 16384))
            except BlockingIOError:
                pass
    return bytes(chunks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['w', 't'], default='w')
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--supply', type=float, default=3.29)
    parser.add_argument('--port')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--label', default='generator')
    args = parser.parse_args()
    if not 0 < args.seconds <= 300 or not 2.5 <= args.supply <= 5.5:
        parser.error('Invalid capture duration or voltage scale')
    ports = [args.port] if args.port else glob.glob('/dev/cu.usbmodem*')
    if len(ports) != 1:
        parser.error('Expected exactly one CDC port: ' + repr(ports))
    out = args.out or Path(__file__).resolve().parents[1] / 'bench-logs' / (
        time.strftime('%Y%m%d-%H%M%S') + '-' + args.label)
    out.mkdir(parents=True, exist_ok=False)
    fd = open_port(ports[0])
    restore = b''
    raw = b''
    try:
        # Establish a known, readable mode before requesting binary packets.
        os.write(fd, b'n')
        before = read_for(fd, 2)
        (out / 'before.bin').write_bytes(before)
        if b'ASTER selftest v0.3' not in before or b'mode=NORMAL' not in before:
            raise RuntimeError('Expected v0.3 NORMAL acknowledgement missing')
        os.write(fd, args.mode.encode())
        raw = read_for(fd, args.seconds)
    finally:
        try:
            os.write(fd, b'n')
            restore = read_for(fd, 3)
        finally:
            os.close(fd)
            (out / 'stream.bin').write_bytes(raw + restore)
            (out / 'restore.bin').write_bytes(restore)
    decoder = Decoder()
    frames = decoder.feed(raw + restore)
    rows = [describe(h, samples, args.supply) for h, samples in frames]
    summary = {
        'mode': args.mode, 'requested_seconds': args.seconds, 'port': ports[0],
        'voltage_scale_supply_V': args.supply,
        'conditions': args.label,
        'limits': 'Block snapshots with upload dead time; no rate, energy-resolution or calibrated pulse-height claim. Median is a reference level, not guaranteed pre-pulse baseline. Nominal sample interval uses HSI clock and must be checked against DMA elapsed time.',
        'valid_frames': len(frames), 'bad_headers': decoder.bad_headers,
        'bad_payloads': decoder.bad_payloads,
        'normal_restored': b'ASTER selftest v0.3' in restore and b'mode=NORMAL' in restore,
        'frames': rows,
    }
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    if rows:
        with (out / 'amplitudes.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader(); writer.writerows(rows)
        # Export first, largest, and last blocks. The checked binary retains all.
        selected = sorted({0, len(frames) - 1,
                           max(range(len(rows)), key=lambda i: rows[i]['peak_to_peak_mV'])})
        for index in selected:
            h, samples = frames[index]
            with (out / f'wave-{h[1]:06d}.csv').open('w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['index', 'time_us_nominal', 'adc_code', 'volts_estimated'])
                for i, value in enumerate(samples):
                    writer.writerow([i, i * h[5] / h[4] * 1e6, value, value * args.supply / 4095])
    compact = {k: v for k, v in summary.items() if k != 'frames'}
    if rows:
        compact.update({
            'median_pp_mV': statistics.median(r['peak_to_peak_mV'] for r in rows),
            'min_pp_mV': min(r['peak_to_peak_mV'] for r in rows),
            'max_pp_mV': max(r['peak_to_peak_mV'] for r in rows),
            'all_timing_sanity_ok': all(r['timing_sanity_ok'] for r in rows),
            'max_adc_errors': max(r['adc_errors'] for r in rows),
            'rail_flag_frames': sum(r['near_rail'] for r in rows),
        })
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    print('Saved:', out)
    if not summary['normal_restored'] or not rows or decoder.bad_payloads or decoder.bad_headers:
        raise SystemExit(2)
    if any(not r['timing_sanity_ok'] or r['adc_errors'] for r in rows):
        raise SystemExit(3)


if __name__ == '__main__':
    main()
