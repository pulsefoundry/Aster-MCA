"""Desktop packaging/lifetime checks; no physical hardware is accessed."""
import json
import os
from pathlib import Path
import pty
import re
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

SOURCE = Path(__file__).resolve().parents[1]
ROOT = SOURCE.parents[1]
BACKEND = ROOT / 'outputs/Aster Nano.app/Contents/Resources/backend/aster-backend'
sys.path.insert(0, str(SOURCE))
from test_host import Checks
from protocol import MAGIC, WORDS


def wait_ready(process, path):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None: raise RuntimeError('Backend exited before ready')
        if path.exists(): return json.loads(path.read_text())
        time.sleep(.05)
    raise TimeoutError('Backend did not start')


class DesktopTests(unittest.TestCase):
    def environment(self, folder):
        return {'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'ASTER_DATA_ROOT':str(folder)}

    def test_bundled_processor_without_system_python_or_compiler(self):
        with tempfile.TemporaryDirectory() as folder:
            p = subprocess.run([str(BACKEND),'--self-test'], env=self.environment(folder),
                               capture_output=True, text=True, timeout=8, check=True)
            self.assertEqual(json.loads(p.stdout)['accepted'],1)

    def test_bundled_lifecycle_and_port_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            ready = Path(folder)/'ready.json'; env = self.environment(folder)
            p = subprocess.Popen([str(BACKEND),'--desktop','--port','0','--ready-file',str(ready),
                                  '--parent-pid',str(os.getpid())],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                info = wait_ready(p,ready); self.assertEqual(info['pid'],p.pid)
                with urllib.request.urlopen(info['url']) as response: page=response.read().decode()
                self.assertIn('关闭窗口或退出应用会停止采集',page)
                # Another instance must fail instead of taking ownership or stopping this one.
                other=subprocess.run([str(BACKEND),'--desktop','--port',info['url'].rsplit(':',1)[1]],
                                     env=env,capture_output=True,timeout=8)
                self.assertNotEqual(other.returncode,0);self.assertIsNone(p.poll())
                p.terminate();self.assertEqual(p.wait(timeout=12),0)
                self.assertFalse(ready.exists())
                with self.assertRaises(OSError):urllib.request.urlopen(info['url']+'/health',timeout=1)
            finally:
                if p.poll() is None:p.terminate();p.wait(timeout=12)

    def test_backend_stops_when_desktop_parent_disappears(self):
        with tempfile.TemporaryDirectory() as folder:
            # A deliberately different parent simulates an abruptly closed desktop process.
            p=subprocess.Popen([str(BACKEND),'--desktop','--port','0','--parent-pid','1'],
                               env=self.environment(folder),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:self.assertEqual(p.wait(timeout=8),0)
            finally:
                if p.poll() is None:p.terminate();p.wait(timeout=12)

    def test_sigterm_during_simulated_acquisition_preserves_valid_record(self):
        helper=Checks();helper.setUp();codec=helper.codec
        master,slave=pty.openpty();port=os.ttyname(slave)
        done=threading.Event();stop_seen=threading.Event();failures=[]
        def terminal(seq):
            payload=json.dumps({'errors':0,'adc_overrun':0,'completed_blocks':seq,
                                'encoded_blocks':seq,'session':1}).encode()
            w=[1,2,1,seq,seq*2048,0,0,1000000,len(payload),0,0,codec.hash(payload),0,seq,seq*196608,0,seq*2,0]
            header=MAGIC+WORDS.pack(*w);w[-1]=codec.hash(header[:-4])
            packet=MAGIC+WORDS.pack(*w)+payload
            return packet+b'\0'*(len(packet)%64==0)
        def fake_device():
            buffer=b'';stream=False;seq=0
            try:
                while not done.is_set():
                    if select.select([master],[],[],.003)[0]:buffer+=os.read(master,4096)
                    while b'\n' in buffer:
                        command,buffer=buffer.split(b'\n',1)
                        if command==b'INFO':
                            info={'fw':'0.3.1','board':'Aster MCA Nano AT32 v0.3','adc_fault':0,
                                  'clock_fault':0,'sample_rate_hz':1000000,'adc_on':True}
                            os.write(master,json.dumps(info).encode()+b'\n')
                        elif command.startswith(b'STREAM '):os.write(master,b'OK STREAM\n');stream=True
                        elif command==b'STOP' and stream:
                            stop_seen.set();os.write(master,terminal(seq));stream=False
                    if stream:os.write(master,helper.packet([2048]*2048,seq));seq+=1
            except BaseException as exc:failures.append(exc)
        device=threading.Thread(target=fake_device);device.start()
        p=None
        try:
            with tempfile.TemporaryDirectory() as folder:
                ready=Path(folder)/'ready.json'
                code="import sys;sys.path.insert(0,sys.argv.pop(1));import gui_model;port=sys.argv.pop(1);gui_model.glob.glob=lambda pattern:[port];import gui;gui.main()"
                p=subprocess.Popen([sys.executable,'-c',code,str(SOURCE),port,'--desktop','--port','0',
                                    '--ready-file',str(ready)],env=self.environment(folder),
                                   stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                url=wait_ready(p,ready)['url']
                with urllib.request.urlopen(url) as response:page=response.read().decode()
                token=re.search(r'name="aster-token" content="([^"]+)"',page)[1]
                def api(path,body=None):
                    request=urllib.request.Request(url+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,
                                                   headers={'X-Aster-Token':token,'Content-Type':'application/json'})
                    with urllib.request.urlopen(request) as response:return json.load(response)
                api('connect',{'port':port});api('start',{'seconds':60,'threshold':20,'condition':'SIMULATED EXIT TEST'})
                deadline=time.monotonic()+4
                while api('state')['phase']!='acquiring':
                    self.assertLess(time.monotonic(),deadline);time.sleep(.05)
                p.terminate();self.assertEqual(p.wait(timeout=12),0)
                self.assertTrue(stop_seen.is_set());self.assertFalse(ready.exists())
                record_path=next((Path(folder)/'work/at32-gui-recordings').glob('*/capture.json'))
                record=json.loads(record_path.read_text())
                self.assertTrue(record['completed']);self.assertEqual(record['stop_reason'],'user_stop')
                self.assertGreater(record['stored_raw_samples'],0)
                self.assertEqual(record['stored_raw_samples'],record['blocks']*2048)
                self.assertEqual(record['spectrum']['samples'],record['stored_raw_samples'])
        finally:
            if p:
                if p.poll() is None:p.terminate();p.wait(timeout=12)
                p.stderr.close()
            done.set();device.join(timeout=3);os.close(master);os.close(slave)
        self.assertFalse(failures)


if __name__=='__main__':unittest.main()
