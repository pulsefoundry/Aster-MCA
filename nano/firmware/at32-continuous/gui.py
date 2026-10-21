"""Aster Nano local GUI: standard-library server, no cloud or web dependencies."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import threading
import urllib.error
import urllib.request
import webbrowser
from gui_model import Model
from protocol import Codec

HERE = Path(__file__).resolve().parent


def create_server(port=8775, model=None, desktop=False):
    model = model or Model()
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def respond(self, status, data, mime='application/json; charset=utf-8'):
            if not isinstance(data, bytes): data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try: self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError): pass

        def allowed(self, api=False):
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in hosts: return False
            origin = self.headers.get('Origin')
            if origin and origin not in {'http://' + h for h in hosts}: return False
            if api and not secrets.compare_digest(self.headers.get('X-Aster-Token', ''), token): return False
            return True

        def do_GET(self):
            if not self.allowed(): return self.respond(403, {'error': '仅允许本机界面访问'})
            if self.path == '/health': return self.respond(200, {'app': 'Aster Nano GUI', 'version': '0.1'})
            if self.path in ('/', '/index.html'):
                page = (HERE / 'gui.html').read_text().replace('__ASTER_TOKEN__', token)
                if desktop:
                    page = page.replace('关闭页面不会中断定时采集；需要提前结束时请点“停止”。',
                                        '关闭窗口或退出应用会停止采集，完成校验和保存后退出。')
                return self.respond(200, page.encode(), 'text/html; charset=utf-8')
            if self.path in ('/gui.js', '/gui.css'):
                mime = 'text/javascript' if self.path.endswith('.js') else 'text/css'
                return self.respond(200, (HERE / self.path[1:]).read_bytes(), mime + '; charset=utf-8')
            if self.path.startswith('/api/') and not self.allowed(api=True):
                return self.respond(403, {'error': '请从本机主界面访问'})
            if self.path == '/api/state': return self.respond(200, model.state())
            if self.path == '/api/records': return self.respond(200, model.records())
            return self.respond(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.allowed(api=True): return self.respond(403, {'error': '请求来源无效，请刷新本机界面'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                limit = 8*1024*1024 if self.path == '/api/export-png' else 4096
                if not 0 < length <= limit: raise ValueError('请求长度无效')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict): raise ValueError('请求格式无效')
                if self.path == '/api/connect': model.connect(body['port'])
                elif self.path == '/api/start': model.start(body['seconds'], body['threshold'], body['condition'])
                elif self.path == '/api/stop': model.stop()
                elif self.path == '/api/load': model.load(body['id'])
                elif self.path == '/api/background': model.set_background(body.get('clear', False))
                elif self.path in ('/api/export-csv','/api/export-png'):
                    path = model.export(body['mode'],body['channels'],body['record_name'],
                                        body['image'] if self.path.endswith('-png') else None)
                    return self.respond(200, {'ok':True,'path':path})
                else: return self.respond(404, {'error': 'Not found'})
                return self.respond(200, {'ok': True})
            except (ValueError, KeyError, OSError, TimeoutError, EOFError) as exc:
                return self.respond(400, {'error': str(exc)})
            except Exception as exc:
                return self.respond(500, {'error': '操作失败：' + str(exc)})
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.model = model
    server.token = token
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8775)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--ready-file', type=Path)
    parser.add_argument('--parent-pid', type=int)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        import struct
        import tempfile
        from spectrum import Spectrum
        with tempfile.TemporaryDirectory() as folder:
            processor = Spectrum(folder)
            samples = [2048] * 4096
            samples[2047:2051] = [1948,1968,2008,2038]
            raw = struct.pack('<4096H', *samples)
            processor.feed(raw[:4096]); processor.feed(raw[4096:])
            result = processor.finish(True)
            if result['accepted'] != 1 or result['samples'] != 4096:
                raise RuntimeError('Bundled pulse processor self-test failed')
            from burst_adapter import get_capture as get_burst_capture
            get_burst_capture()
            from aster_burst.spectrum import Spectrum as BurstSpectrum
            burst_folder=Path(folder)/'burst';burst_folder.mkdir()
            processor=BurstSpectrum(burst_folder)
            samples=[2048]*8192
            samples[1000:1016]=[2048-v for v in [25,50,75,100,125,150,175,200,175,150,125,100,75,50,25,0]]
            processor.feed(struct.pack('<8192H',*samples),1)
            burst=processor.finish(True)
            if burst['accepted']!=1 or burst['samples']!=8192:
                raise RuntimeError('Bundled burst processor self-test failed')
            from histogram_adapter import get_capture as get_histogram_capture
            get_histogram_capture()
            from aster_histogram.protocol import histogram_snapshot
            counts=[0]*2048;counts[474]=7
            snapshot=histogram_snapshot(counts,{'accepted':7,'underflow':0,'overflow':0})
            if snapshot['master_channels']!=2048 or sum(snapshot['counts']['area8'])!=7:
                raise RuntimeError('Bundled histogram protocol self-test failed')
            print(json.dumps({'self_test':'passed','samples':4096,'accepted':1,'burst_samples':8192,'burst_accepted':1,'onboard_histogram_channels':2048}))
        return
    # Validate the packaged native library before showing the acquisition UI.
    Codec()
    url = f'http://127.0.0.1:{args.port}'
    # A second double-click reopens the already-running local instance.
    if args.port and not args.desktop:
        try:
            with urllib.request.urlopen(url + '/health', timeout=1) as r: existing = json.load(r)
            if existing.get('app') == 'Aster Nano GUI':
                print('界面已在运行：', url, flush=True)
                if args.open: webbrowser.open(url)
                return
        except (OSError, ValueError): pass
    import faulthandler
    faulthandler.dump_traceback_later(10,repeat=False)
    server = create_server(args.port, desktop=args.desktop)
    faulthandler.cancel_dump_traceback_later()
    url = f'http://127.0.0.1:{server.server_port}'
    shutting_down = threading.Event()
    def shutdown(*unused):
        if shutting_down.is_set(): return
        shutting_down.set()
        server.model.stop()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    if args.parent_pid:
        def watch_parent():
            while not shutting_down.wait(.5):
                if os.getppid() != args.parent_pid:
                    shutdown(); return
        threading.Thread(target=watch_parent, name='Desktop lifetime', daemon=True).start()
    if args.ready_file:
        temporary = args.ready_file.with_suffix('.tmp')
        temporary.write_text(json.dumps({'url':url, 'pid':os.getpid()}))
        os.replace(temporary,args.ready_file)
    print('Aster Nano GUI：' + url, flush=True)
    print('原始数据自动保存。结束采集请点击“停止”。', flush=True)
    if args.open: webbrowser.open(url)
    try: server.serve_forever(poll_interval=.2)
    finally:
        server.model.shutdown(); server.server_close()
        if args.ready_file: args.ready_file.unlink(missing_ok=True)


if __name__ == '__main__': main()
