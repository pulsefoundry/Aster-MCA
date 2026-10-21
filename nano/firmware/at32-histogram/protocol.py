"""Strict final-histogram protocol; data and metadata are checksummed."""
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
METHOD = 'mcu-area8-4M-v0.1'
PEAK_METHOD = 'mcu-peak-4M-v0.1'
PEAK_FIRMWARES = ('0.8.0', '0.8.1', '0.8.2')
FIRMWARES = ('0.6.0', '0.6.1', '0.6.2', '0.6.3') + PEAK_FIRMWARES
SNAPSHOT_FIRMWARES = ('0.6.2', '0.6.3') + PEAK_FIRMWARES


def validate_info(info):
    if info.get('fw') not in FIRMWARES:raise ValueError('不支持的板上采谱固件版本')
    expected=dict(type='info',board='Aster MCA Nano AT32 v0.3',mcu='AT32F423CCT7',
        method='onboard_histogram',core_hz=CORE,adc_hz=72000000,
        sample_rate_hz=RATE,timer_ticks=36,sample_cycles_x2=5,channels=2048,
        dma_samples=8192,ldo_mv=1300,adc_on=1,adc_fault=0,clock_fault=0,bist_fault=0,xtest=9)
    for key,value in expected.items():
        if info.get(key)!=value:raise ValueError(f'板上采谱配置错误：{key}={info.get(key)!r}')
    if info['fw'] in SNAPSHOT_FIRMWARES and info.get('snapshot_samples')!=4096:raise ValueError('缺少独立波形缓冲区')
    if info['fw'] in PEAK_FIRMWARES and (info.get('energy_estimator')!='sampled_peak' or info.get('bin_width_adc_codes')!=1):
        raise ValueError('取峰模式或 ADC 谱道单位错误')
    if type(info.get('session')) is not int or info['session']<0:raise ValueError('缺少采集序号')


def histogram_snapshot(counts,header):
    if header.get('fw') in PEAK_FIRMWARES:
        return dict(counts={'peak':list(counts)},under={'peak':header['underflow']},
            over={'peak':header['overflow']},events=header['accepted'],master_channels=2048,
            ranges={'peak':2048.0},mapping_version='mcu-peak-2048-v1')
    return dict(counts={'area8':list(counts)},under={'area8':header['underflow']},
        over={'area8':header['overflow']},events=header['accepted'],master_channels=2048,
        ranges={'area8':2048.0},mapping_version='mcu-area8-2048-v1')


def validate_result(h,raw,session,requested_ms,threshold,allow_stop=False):
    if h.get('fw') not in FIRMWARES:raise ValueError('不支持的板上采谱结果版本')
    peak=h['fw'] in PEAK_FIRMWARES
    expected=dict(type='spectrum',method=PEAK_METHOD if peak else METHOD,session=session,requested_ms=requested_ms,
        threshold_codes=threshold,channels=2048,sample_rate_hz=RATE,core_hz=CORE,
        errors=0,adc_overrun=0)
    expected.update(dict(bin_width_adc_codes=1,energy_estimator='sampled_peak') if peak else dict(bin_width_code_us=1))
    if peak and 'bin_width_code_us' in h:raise ValueError('取峰谱不能标成积分单位')
    for key,value in expected.items():
        if h.get(key)!=value:raise ValueError(f'板上采谱无效：{key}={h.get(key)!r}，期望 {value!r}')
    keys=['blocks','processed_blocks','engine_blocks','fine_blocks','tail_samples_excluded','stop_user',
        'acquisition_ms','span_cycles_mod32','irq_delta_min','irq_delta_max','process_max_cycles',
        'latency_max_cycles','candidates','accepted','rejected','underflow','overflow','pending_excluded',
        'minimum','maximum','histogram_crc32']
    if any(type(h.get(k)) is not int or not 0<=h[k]<=0xffffffff for k in keys):raise ValueError('无效的能谱计数或时序字段')
    if h['stop_user'] not in (0,1) or h['pending_excluded'] not in (0,1):raise ValueError('无效的停止状态')
    limit=(requested_ms*4000+4095)//4096;b=h['blocks'];samples=b*4096
    if not 0<b<=limit or (not h['stop_user'] and b!=limit) or (h['stop_user'] and not allow_stop):
        raise ValueError('采集样本数与设定时长不符')
    if h['processed_blocks']!=b or h['engine_blocks']!=b*64 or h['fine_blocks']>b*64:
        raise ValueError('DMA 与能谱处理计数不一致')
    if not 0<=h['minimum']<=h['maximum']<=4095 or h['tail_samples_excluded']>=4096:
        raise ValueError('ADC 范围或末尾样本计数异常')
    elapsed=samples/RATE
    if abs(h['acquisition_ms']-elapsed*1000)>3:raise ValueError('板上采样时长检查失败')
    span_error=(h['span_cycles_mod32']-samples*36)&0xffffffff
    if span_error>1440:raise ValueError('板上周期计数检查失败')
    if b>1 and not 4096*36-1440<=h['irq_delta_min']<=h['irq_delta_max']<=4096*36+1440:
        raise ValueError('DMA 间隔异常')
    if h['latency_max_cycles']>=4096*36:
        raise ValueError('主控处理超过 DMA 缓冲期限')
    if h['fw'] in SNAPSHOT_FIRMWARES:
        if h.get('snapshot_samples')!=4096:raise ValueError('波形快照大小错误')
        if any(type(h.get(k)) is not int or not 0<h[k]<4096*36 for k in ['copy_max_cycles','copy_end_max_cycles']):
            raise ValueError('波形快照复制超过 DMA 覆盖期限')
        if h['copy_max_cycles']>h['copy_end_max_cycles'] or h['copy_max_cycles']>h['process_max_cycles']:
            raise ValueError('波形快照时序不一致')
    elif h['process_max_cycles']>=4096*36:
        raise ValueError('主控处理超过 DMA 缓冲期限')
    if len(raw)!=8192 or zlib.crc32(raw)!=h['histogram_crc32']:raise ValueError('能谱数据校验失败')
    counts=struct.unpack('<2048I',raw)
    if sum(counts)+h['underflow']+h['overflow']!=h['accepted'] or h['accepted']+h['rejected']!=h['candidates']:
        raise ValueError('谱计数不守恒')
    flags=h.get('rejection_flags')
    if not isinstance(flags,list) or len(flags)!=5 or any(type(x) is not int or not 0<=x<=h['rejected'] for x in flags) or sum(flags)<h['rejected']:
        raise ValueError('事件筛选计数不一致')
    return dict(method=PEAK_METHOD if peak else METHOD,acquisition_mode='histogram',valid_histogram_run=True,
        sample_rate_hz=RATE,samples=samples,sampled_seconds=elapsed,channels=2048,
        threshold_codes=threshold,candidates=h['candidates'],accepted=h['accepted'],
        rejected=h['rejected'],rejection_flags=flags,underflow=h['underflow'],overflow=h['overflow'],
        boundary_partial_events_excluded=h['pending_excluded'],tail_samples_excluded=h['tail_samples_excluded'],
        analysis_window_seconds=max(0,samples-272-59)/RATE,calibration=None,
        limitations=['Only the final histogram is retained; no raw waveform or event list.',
            'Sample-clock duration rounds up to a 4096-sample DMA boundary (at most 1.024 ms).',
            'No calibrated energy or dead-time/quality-cut corrected live time.'])


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
            raise TimeoutError('AT32 能谱响应超时')
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

    def write(self, text):
        data = (text + '\n').encode('ascii')
        if os.write(self.fd, data) != len(data):
            raise IOError('Incomplete command write')

    def command(self, text):
        self.write(text)
        return self.line()
