"""Local GUI model. Acquisition uses the same verified capture/DSP path."""
import csv
import base64
import datetime
import glob
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import tty
from capture import line, run
from sparse_adapter import get_capture
from burst_adapter import get_capture as get_burst_capture
from histogram_adapter import get_capture as get_histogram_capture

ROOT = Path(os.environ.get('ASTER_DATA_ROOT', Path(__file__).resolve().parents[2])).expanduser().resolve()
RECORD_ROOT = ROOT / 'work/at32-gui-recordings'
HISTORY_ROOT = ROOT / 'work/at32-continuous-2026-10-14'
SPARSE_ROOT = ROOT / 'work/at32-sparse-2026-10-14'
BURST_ROOT = ROOT / 'work/at32-burst-2026-10-14'
MASTER_CHANNELS = 4096
RANGES = {'peak': 4096.0, 'area8': 2048.0}


class ChannelHistogram:
    """Fixed physical ranges; display rebinning never moves a peak's meaning.

    4096 master bins: peak width=1 ADC code, area width=.5 ADC code*us.
    1024 display bins: peak width=4 codes, area width=2 code*us.
    Under/overflow is counted explicitly, never folded into endpoint bins.
    """
    def __init__(self):
        self.counts = {k: [0] * MASTER_CHANNELS for k in RANGES}
        self.under = dict.fromkeys(RANGES, 0)
        self.over = dict.fromkeys(RANGES, 0)
        self.events = 0

    def add(self, peak, area8):
        for key, value in [('peak', peak), ('area8', area8)]:
            if not math.isfinite(value): raise ValueError('Non-finite event value')
            index = math.floor(value * MASTER_CHANNELS / RANGES[key])
            if index < 0: self.under[key] += 1
            elif index >= MASTER_CHANNELS: self.over[key] += 1
            else: self.counts[key][index] += 1
        self.events += 1

    def snapshot(self):
        return {'counts': {k: v.copy() for k, v in self.counts.items()},
                'under': self.under.copy(), 'over': self.over.copy(),
                'events': self.events, 'master_channels': MASTER_CHANNELS,
                'ranges': RANGES.copy(), 'mapping_version': 'gui-channels-v1'}

    def rebin(self, key, channels):
        if channels not in (512, 1024, 2048, 4096): raise ValueError('Unsupported channel count')
        width = MASTER_CHANNELS // channels
        return [sum(self.counts[key][i:i+width]) for i in range(0, MASTER_CHANNELS, width)]


def read_record(folder):
    folder = Path(folder)
    capture = json.loads((folder / 'capture.json').read_text())
    summary = json.loads((folder / 'spectrum-summary.json').read_text())
    fw=capture['initial_info'].get('fw')
    valid_key={'0.3.1':'valid_continuous_run','0.4.4':'valid_sparse_run','0.5.0':'valid_burst_run','0.6.0':'valid_histogram_run','0.6.1':'valid_histogram_run','0.6.2':'valid_histogram_run','0.6.3':'valid_histogram_run'}.get(fw)
    if not valid_key:raise ValueError('此记录的固件版本不兼容')
    if not capture['completed'] or not summary.get(valid_key):
        raise ValueError('此记录未通过采集完整性校验，不能作为有效能谱打开')
    if fw in ('0.6.0','0.6.1','0.6.2','0.6.3'):
        get_histogram_capture()
        from aster_histogram.protocol import validate_result, histogram_snapshot, validate_info
        validate_info(capture['initial_info'])
        header=capture['device_result'];raw=(folder/'histogram.u32').read_bytes()
        import struct
        verified=validate_result(header,raw,capture['initial_info']['session']+1,
            round(capture['requested_seconds']*1000),summary['threshold_codes'],capture['stop_reason']=='user_stop')
        if verified!=summary:raise ValueError('能谱摘要与原始结果不一致')
        snapshot=histogram_snapshot(struct.unpack('<2048I',raw),header)
    else:
        h = ChannelHistogram()
        with (folder / 'events.csv').open() as f:
            for event in csv.DictReader(f):
                if int(event['flags']) == 0:
                    h.add(float(event['peak_code']), float(event['area8_code_us']))
        if h.events != summary['accepted']: raise ValueError('事件表与采集记录计数不一致')
        snapshot=h.snapshot()
    return {'name': folder.name, 'path': str(folder.resolve()), 'valid': True,
            'seconds': summary['sampled_seconds'], 'samples': summary['samples'],
            'candidates': summary['candidates'], 'accepted': summary['accepted'],
            'sample_rate_hz':capture['initial_info']['sample_rate_hz'],
            'acquisition_mode':capture.get('acquisition_mode','continuous'),
            'wall_seconds':capture.get('wall_seconds'), 'duty_cycle':capture.get('duty_cycle'),
            'analysis_window_seconds':summary.get('analysis_window_seconds'),
            'method': summary['method'], 'threshold_codes': summary['threshold_codes'],
            'condition': capture['input'], 'started': capture['started'],
            'histogram': snapshot, 'stop_reason': capture.get('stop_reason', 'duration')}


def compatible(a, b):
    return bool(a and b and a.get('method') == b.get('method') and
                a.get('threshold_codes') == b.get('threshold_codes') and
                a['histogram']['mapping_version'] == b['histogram']['mapping_version'] and
                a['histogram']['ranges'] == b['histogram']['ranges'])


def acquisition_error(exc):
    text=str(exc)
    if 'Run ended with acquisition/transport loss:' in text:
        try:
            info=json.loads(text[text.index('{'):]);errors=info.get('errors',0)
            meanings=[(1,'DMA 错误'),(2,'ADC 数据溢出'),(4,'采样中断异常'),
                      (8,'主控处理超时'),(16,'发送缓冲区已满'),(32,'USB 传输中断'),
                      (64,'命令异常'),(128,'采样超时')]
            reason='、'.join(label for bit,label in meanings if errors&bit) or '数据完整性校验失败'
            return f'本轮采集无效：{reason}。记录与诊断信息已保存；请降低数据负载后重试。'
        except (ValueError,KeyError):pass
    return text


class Model:
    def __init__(self):
        self.lock = threading.RLock()
        self.worker = None
        self.stop_event = threading.Event()
        self.connected = None
        self.phase = 'idle'
        self.error = ''
        self.current = None
        self.background = None
        self.paths = {}
        self.origin = 'empty'
        self.requested_seconds = 60
        RECORD_ROOT.mkdir(parents=True, exist_ok=True)
        # Open the saved experiment without accessing the connected hardware.
        for attribute, marker in [('current', 'latest-cs-source-path.txt'),
                                  ('background', 'latest-detector-background-path.txt')]:
            try:
                choices=[]
                for root in [HISTORY_ROOT,BURST_ROOT]:
                    try:
                        folder=Path((root/marker).read_text().strip())
                        if folder.resolve().parent not in (HISTORY_ROOT.resolve(),BURST_ROOT.resolve(),RECORD_ROOT.resolve()):continue
                        choices.append(read_record(folder))
                    except (OSError,ValueError,KeyError):pass
                if choices:setattr(self,attribute,max(choices,key=lambda r:r['started']))
            except (OSError, ValueError, KeyError):
                pass
        try:
            folder=Path((RECORD_ROOT/'latest-current-path.txt').read_text().strip())
            if folder.resolve().parent==RECORD_ROOT.resolve():self.current=read_record(folder)
        except (OSError,ValueError,KeyError):pass
        if self.current: self.origin = 'history'

    def busy(self):
        return self.phase in ('connecting', 'loading', 'starting', 'acquiring', 'stopping')

    def records(self):
        result = []
        for root in [HISTORY_ROOT, SPARSE_ROOT, BURST_ROOT, RECORD_ROOT]:
            for file in root.glob('*/capture.json'):
                try:
                    record = json.loads(file.read_text())
                    if not record['completed'] or record['initial_info']['fw'] not in ('0.3.1','0.4.4','0.5.0','0.6.0','0.6.1','0.6.2','0.6.3'): continue
                    path = file.parent.resolve()
                    # Do not follow a user-created symlink outside the record roots.
                    if path.parent != root.resolve(): continue
                    identity = hashlib.sha256(str(path).encode()).hexdigest()[:20]
                    result.append({'id': identity, 'name': path.name,
                                   'started': record['started'],
                                   'seconds': record['verified_sampled_seconds']})
                    with self.lock: self.paths[identity] = path
                except (ValueError, OSError, KeyError): continue
        return sorted(result, key=lambda r: r['started'], reverse=True)

    def state(self):
        with self.lock:
            ports = sorted(glob.glob('/dev/cu.usbmodem*'))
            if self.connected and self.connected['port'] not in ports: self.connected = None
            return {'phase': self.phase, 'error': self.error, 'connected': self.connected,
                    'ports': ports, 'current': self.current, 'background': self.background,
                    'background_compatible': compatible(self.current, self.background),
                    'origin': self.origin, 'requested_seconds': self.requested_seconds,
                    'save_root': str(RECORD_ROOT), 'busy': self.busy()}

    def connect(self, port):
        with self.lock:
            if self.busy(): raise ValueError('请先结束当前操作')
            if port not in glob.glob('/dev/cu.usbmodem*'): raise ValueError('设备端口不存在，请刷新')
            self.phase = 'connecting'; self.error = ''
        fd = None
        try:
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK); tty.setraw(fd)
            os.write(fd, b'INFO\n'); info = json.loads(line(fd))
            if (info.get('board') != 'Aster MCA Nano AT32 v0.3' or
                    (info.get('fw'),info.get('sample_rate_hz')) not in (('0.3.1',1000000),('0.4.4',4000000),('0.5.0',4000000),('0.6.0',4000000),('0.6.1',4000000),('0.6.2',4000000),('0.6.3',4000000))):
                raise ValueError('需要 Aster AT32 的 v0.3.1、v0.4.4、v0.5.0 或板上采谱 v0.6.0–v0.6.3 固件')
            if info.get('fw')=='0.5.0':
                get_burst_capture()
                from aster_burst.protocol import validate_info
                validate_info(info)
            if info.get('fw') in ('0.6.0','0.6.1','0.6.2','0.6.3'):
                get_histogram_capture()
                from aster_histogram.protocol import validate_info
                validate_info(info)
            if info['adc_fault'] or info.get('clock_fault') or info.get('selector_fault',0) or not info['adc_on']:
                raise ValueError('设备 ADC 或时钟状态异常')
            with self.lock: self.connected = {'port': port, 'info': info}
        except Exception:
            with self.lock: self.connected = None
            raise
        finally:
            if fd is not None: os.close(fd)
            with self.lock: self.phase = 'idle'

    def load(self, identity):
        with self.lock:
            if self.busy(): raise ValueError('采集结束后再打开历史记录')
            if identity not in self.paths: raise ValueError('记录不存在，请刷新列表')
            path = self.paths[identity]; self.phase = 'loading'
        try:
            loaded = read_record(path)
            with self.lock:
                self.current = loaded; self.origin = 'history'; self.error = ''
        finally:
            with self.lock: self.phase = 'idle'

    def set_background(self, clear=False):
        with self.lock:
            if self.busy(): raise ValueError('请先结束采集')
            if clear: self.background = None; return
            if not self.current or not self.current['valid']: raise ValueError('请先打开有效记录')
            # Current snapshots are replaced rather than modified in place.
            self.background = self.current

    def start(self, seconds, threshold, condition):
        seconds = float(seconds); threshold = float(threshold)
        if not math.isfinite(seconds) or not 1 <= seconds <= 3600: raise ValueError('采集时长应为 1–3600 秒')
        if not math.isfinite(threshold) or not 1 <= threshold <= 2048: raise ValueError('门限应为 1–2048 码')
        condition = str(condition).strip()
        if not condition or len(condition) > 500: raise ValueError('请填写本次输入或源的状态（不超过 500 字）')
        with self.lock:
            if self.busy(): raise ValueError('已有采集任务运行')
            if not self.connected: raise ValueError('请先连接并确认设备')
            port = self.connected['port']
            sparse=self.connected['info']['fw']=='0.4.4'
            burst=self.connected['info']['fw']=='0.5.0'
            onboard=self.connected['info']['fw'] in ('0.6.0','0.6.1','0.6.2','0.6.3')
            if (sparse or onboard) and threshold!=int(threshold):raise ValueError('4M 模式的门限须为整数 ADC 码')
            capture_run=get_histogram_capture() if onboard else get_burst_capture() if burst else get_capture() if sparse else run
            self.stop_event = threading.Event(); self.phase = 'starting'; self.error = ''
            self.origin = 'live'; self.requested_seconds = seconds
            out = RECORD_ROOT / datetime.datetime.now().strftime('capture-%Y%m%d-%H%M%S-%f')
            h = ChannelHistogram()
            if onboard:
                from aster_histogram.protocol import histogram_snapshot
                empty=histogram_snapshot([0]*2048,{'underflow':0,'overflow':0,'accepted':0})
            else:empty=h.snapshot()
            initial = {'name': out.name, 'path': str(out), 'valid': False,
                       'seconds': 0, 'samples': 0, 'candidates': 0, 'accepted': 0,
                       'method': 'mcu-area8-4M-v0.1' if onboard else 'host-pulse-4M-burst-v0.1' if burst else 'host-pulse-4M-v0.2' if sparse else 'host-pulse-v0.1',
                       'acquisition_mode':'histogram' if onboard else 'burst' if burst else 'continuous',
                       'sample_rate_hz':4000000 if sparse or burst or onboard else 1000000,'threshold_codes': threshold,
                       'condition': condition, 'histogram': empty, 'awaiting_result':onboard}
            self.current = initial
            def progress(update):
                with self.lock:
                    self.current = {**initial, **update, 'histogram': empty if onboard else h.snapshot()}
                    if self.phase != 'stopping': self.phase = 'acquiring'
            def acquire():
                try:
                    result = capture_run(port, out, seconds, condition, threshold,
                                 stop_event=self.stop_event, on_progress=progress,
                                 on_event=h.add, quiet=True)
                    snap = result['histogram'] if onboard else h.snapshot()
                    (out / 'gui-histogram.json').write_text(json.dumps(snap) + '\n')
                    (RECORD_ROOT/'latest-current-path.txt').write_text(str(out)+'\n')
                    with self.lock:
                        self.current = {**initial, **result['spectrum'], 'histogram': snap,
                                        'seconds': result['verified_sampled_seconds'],
                                        'wall_seconds':result['wall_seconds'],
                                        'duty_cycle':result.get('duty_cycle'),
                                        'valid': result['completed'], 'stop_reason': result['stop_reason'], 'awaiting_result':False}
                        self.phase = 'complete'
                except Exception as exc:
                    with self.lock:
                        self.error = acquisition_error(exc); self.phase = 'error'
                        self.current = {**self.current, 'valid': False}
            self.worker = threading.Thread(target=acquire, name='ADC reader', daemon=False)
            self.worker.start()

    def stop(self):
        with self.lock:
            if self.phase not in ('starting', 'acquiring', 'stopping'): return
            self.phase = 'stopping'; self.stop_event.set()

    def export(self, mode, channels, record_name, image=None):
        channels = int(channels)
        if mode not in RANGES or channels not in (512, 1024, 2048, 4096):
            raise ValueError('无效的谱类型或道数')
        with self.lock:
            if self.busy() or not self.current or not self.current['valid']:
                raise ValueError('请等待本轮采集结束并通过校验')
            current, background = self.current, self.background
            native=current['histogram']['master_channels']
            if mode not in current['histogram']['counts'] or channels>native or native%channels:
                raise ValueError('该记录不支持此谱类型或道数；板上谱最多为 2048 道')
            if current['name'] != record_name: raise ValueError('记录已改变，请重新导出')
            if not compatible(current, background): background = None
        folder = Path(current['path']) / 'exports'; folder.mkdir(exist_ok=True)
        stem = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + f'-{mode}-{channels}ch'
        path = folder / (stem + ('.png' if image is not None else '.csv'))
        if image is not None:
            if not isinstance(image,str) or not image.startswith('data:image/png;base64,'):
                raise ValueError('需要 PNG 图像')
            data = base64.b64decode(image.split(',',1)[1],validate=True)
            if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) > 5*1024*1024:
                raise ValueError('图像格式或大小无效')
            path.write_bytes(data)
        else:
            def rebin(record):
                values = record['histogram']['counts'][mode]
                width=len(values)//channels
                return [sum(values[i:i+width]) for i in range(0,len(values),width)]
            values = rebin(current); base = rebin(background) if background else None
            ratio = current['seconds']/background['seconds'] if background else 0
            step = RANGES[mode]/channels
            with path.open('w',newline='',encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['channel','lower_value','upper_value','counts','rate_per_sampled_s',
                            'background_scaled_counts','net_counts','net_sigma_counts'])
                for i,count in enumerate(values):
                    bg = base[i]*ratio if base is not None else None
                    w.writerow([i,i*step,(i+1)*step,count,count/current['seconds'],
                                bg,'' if bg is None else count-bg,
                                '' if bg is None else math.sqrt(count+base[i]*ratio*ratio)])
        metadata = {'record':current['path'],'background':background['path'] if background else None,
                    'mode':mode,'channels':channels,'full_scale':RANGES[mode],
                    'unit':'ADC code*us' if mode=='area8' else 'ADC code',
                    'sampled_seconds':current['seconds'],'threshold_codes':current['threshold_codes'],
                    'acquisition_mode':current.get('acquisition_mode','continuous'),
                    'wall_seconds':current.get('wall_seconds'),'duty_cycle':current.get('duty_cycle'),
                    'analysis_window_seconds':current.get('analysis_window_seconds'),
                    'condition':current['condition'],'calibration':None,
                    'mapping_version':current['histogram']['mapping_version'],'underflow':current['histogram']['under'][mode],
                    'overflow':current['histogram']['over'][mode]}
        path.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
        return str(path)

    def shutdown(self):
        self.stop()
        worker = self.worker
        if worker and worker.is_alive(): worker.join(timeout=12)
