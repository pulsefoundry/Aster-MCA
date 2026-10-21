"""Finite 4M DMA frames; strict checks, no silent resynchronization."""
import json
import math
import os
import select
import struct
import time
import tty
import zlib

N = 8192
RATE = 4000000
CORE = 144000000


class Serial:
    def __init__(self, port, wire=None):
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            tty.setraw(self.fd)
        except BaseException:
            os.close(self.fd)
            raise
        self.buf = bytearray()
        self.wire = wire

    def close(self):
        os.close(self.fd)

    def fill(self, deadline):
        remain = deadline - time.monotonic()
        if remain <= 0 or not select.select([self.fd], [], [], remain)[0]:
            raise TimeoutError('AT32 分段采集响应超时')
        data = os.read(self.fd, 32768)
        if not data:
            raise EOFError('USB 已断开')
        if self.wire:
            self.wire.write(data)
        self.buf.extend(data)

    def line(self, timeout=3):
        deadline = time.monotonic() + timeout
        while b'\n' not in self.buf:
            if len(self.buf) > 4096:
                raise ValueError('Invalid response header')
            self.fill(deadline)
        n = self.buf.index(b'\n') + 1
        if n > 4096:
            raise ValueError('Invalid response header')
        line = bytes(self.buf[:n]); del self.buf[:n]
        return line.decode('ascii').strip()

    def exact(self, n, timeout=5):
        deadline = time.monotonic() + timeout
        while len(self.buf) < n:
            self.fill(deadline)
        data = bytes(self.buf[:n]); del self.buf[:n]
        return data

    def command(self, text):
        data = (text + '\n').encode('ascii')
        if os.write(self.fd, data) != len(data):
            raise IOError('Incomplete command write')
        return self.line()


def validate_info(info):
    expected = dict(board='Aster MCA Nano AT32 v0.3', mcu='AT32F423CCT7',
                    fw='0.5.0', method='burst_dma', core_hz=CORE, adc_hz=72000000,
                    sample_rate_hz=RATE, timer_ticks=36, sample_cycles_x2=5,
                    n=N, adc_on=1, adc_fault=0, clock_fault=0, xtest=9, ldo_mv=1300)
    for key, value in expected.items():
        if info.get(key) != value:
            raise ValueError(f'设备配置不符：{key}={info.get(key)!r}, expected {value!r}')
    if not isinstance(info.get('capture_id'), int):
        raise ValueError('Missing capture counter')


def validate_frame(stats, raw, expected_id):
    expected = dict(type='stats', method='burst_dma', fw='0.5.0', id=expected_id,
                    n=N, sample_rate_hz=RATE, timer_ticks=36, core_hz=CORE,
                    nominal_span_cycles=(N-1)*36, dma_remaining=0, dma_error=0,
                    adc_overrun=0)
    for key, value in expected.items():
        if stats.get(key) != value:
            raise ValueError(f'无效采集段：{key}={stats.get(key)!r}, expected {value!r}')
    if len(raw) != N*2:
        raise ValueError('Truncated raw waveform')
    values = struct.unpack('<8192H', raw)
    checks = dict(crc32=zlib.crc32(raw), min=min(values), max=max(values),
                  sum=sum(values), sum_sq=sum(v*v for v in values))
    for key, value in checks.items():
        if stats.get(key) != value:
            raise ValueError(f'波形校验失败：{key}')
    if checks['max'] > 4095:
        raise ValueError('ADC sample exceeds 12 bits')
    elapsed = stats.get('elapsed_cycles', -1)
    # Includes timer start, last conversion and completion-ISR entry overhead.
    # This is a duration plausibility check, not an independent calibrated clock.
    if not N*36 <= elapsed <= N*36+1440:
        raise ValueError(f'DMA timing outside expected range: {elapsed} cycles')
    mean = checks['sum']/N
    return dict(mean_code=mean, rms_code=math.sqrt(max(0, checks['sum_sq']/N-mean*mean)),
                checksum_statistics_verified=True,
                sampled_seconds=N/RATE, timing_overhead_cycles=elapsed-N*36)
