"""Build OWON Ultrawave native files for the v0.4.1 peak-hold bench.

Format matched to the manufacturer's Ultrawave 2.1.14 FileSaveUtil.save:
four little-endian int32 header fields, a 32-byte basename, then uint16 samples.
The native geometry uses 0..20000; physical levels must be set after recall.
"""
from pathlib import Path
import hashlib
import json
import math
import struct

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/Aster-MCA-Nano-峰值保持测试波形-20261116'
N = 8192
DT_US = 0.125
PERIOD_US = N * DT_US
START_US = 128.0


def pulse(t, start, shape, rise=0.5):
    x = t - start
    if not 0 < x < 4:
        return 0.0
    if shape == 'sin2':
        return math.sin(math.pi * x / 4)**2
    return x / rise if x <= rise else (4-x) / (4-rise)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    specifications = []
    for amplitude in [0.1, 0.3, 0.5, 0.8]:
        specifications.append((f'PH{round(amplitude*1000):04d}.bin', 'sin2', amplitude, 2.0, None))
    for rise in [0.25, 0.5, 1.0, 2.0]:
        specifications.append((f'TR{round(rise*1000):04d}.bin', 'triangle', 0.3, rise, None))
    for delay in [4.0, 8.0, 16.0, 32.0]:
        specifications.append((f'DP{round(delay):02d}.bin', 'sin2', 0.5, 2.0, delay))
    for name, shape, amplitude, rise, delay in specifications:
        physical = []
        for i in range(N):
            t = i * DT_US
            if delay is None:
                v = -amplitude * pulse(t, START_US, shape, rise)
            else:
                v = -0.2 * pulse(t, START_US, shape) - 0.5 * pulse(t, START_US+delay, shape)
            physical.append(v)
        # Full-span geometry preserves shape resolution when output amplitude
        # is reduced. It is deliberately separate from the output settings.
        codes = [round(20000 * (1 + v/amplitude)) for v in physical]
        assert len(codes) == N and min(codes) == 0 and max(codes) == 20000
        assert codes[0] == codes[-1] == 20000
        assert len(name) <= 15
        native = (struct.pack('<4i', 1, 20000, 0, N) +
                  name.encode('ascii').ljust(32, b'\0') + struct.pack('<'+'H'*N, *codes))
        assert len(native) == 48 + 2*N
        (OUT/name).write_bytes(native)
        # Round-trip the complete file and check physical scale of every point.
        header = struct.unpack_from('<4i', native)
        decoded = struct.unpack_from('<'+'H'*N, native, 48)
        assert header == (1, 20000, 0, N) and list(decoded) == codes
        reconstructed = [amplitude * (q/20000-1) for q in decoded]
        error = max(abs(a-b) for a,b in zip(physical,reconstructed))
        assert error <= amplitude/40000 + 1e-12
        cases.append(dict(file=name, shape=shape, negative_peak_v=amplitude,
                          pulse_total_width_us=4.0, leading_edge_us=rise,
                          second_pulse_start_delay_us=delay,
                          pair_amplitudes_v=[0.2,0.5] if delay is not None else None,
                          period_us=PERIOD_US, frequency_hz=1e6/PERIOD_US,
                          effective_point_rate_sps=1e6/DT_US, points=N,
                          amplitude_vpp=amplitude, offset_v=-amplitude/2,
                          load='High Z', expected_high_v=0.0,
                          expected_low_v=-amplitude, output_enable=False,
                          digital_quantization_error_v=error,
                          sha256=hashlib.sha256(native).hexdigest()))
    name = 'N61116A.bin'
    initial = (OUT/cases[0]['file']).read_bytes()
    initial = initial[:16] + name.encode().ljust(32, b'\0') + initial[48:]
    (OUT/name).write_bytes(initial)
    cases[0]['initial_instrument_filename'] = name
    cases[0]['initial_instrument_sha256'] = hashlib.sha256(initial).hexdigest()
    (OUT/'test-cases.json').write_text(json.dumps(cases, indent=2)+'\n')
    print('Created',len(cases),'native files:',OUT)


if __name__ == '__main__':
    main()
