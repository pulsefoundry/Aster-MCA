"""Channel accounting, HTTP isolation and manual-stop capture regression tests."""
import csv
import json
import os
from pathlib import Path
import pty
import select
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from capture import run
from gui import create_server
from gui_model import ChannelHistogram, Model, read_record, compatible
from protocol import Codec, MAGIC, WORDS
from test_host import Checks


class ChannelTests(unittest.TestCase):
    def test_edges_and_count_conservation(self):
        h=ChannelHistogram()
        for peak,area in [(0,0),(1,1.999),(4095,2047.999),(4096,2048),(10,-.01)]: h.add(peak,area)
        self.assertEqual(h.under['area8'],1); self.assertEqual(h.over['area8'],1)
        self.assertEqual(h.over['peak'],1)
        for mode in ('peak','area8'):
            for n in (512,1024,2048,4096):
                bins=h.rebin(mode,n);self.assertEqual(len(bins),n)
                self.assertEqual(sum(bins)+h.under[mode]+h.over[mode],h.events)
        self.assertEqual(h.rebin('area8',1024)[0],2)
        self.assertEqual(h.rebin('area8',1024)[1023],1)

    def test_history_rebin_and_invalid_record(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            capture={'completed':True,'initial_info':{'fw':'0.3.1','sample_rate_hz':1000000},'input':'test','started':'now'}
            summary={'valid_continuous_run':True,'accepted':2,'candidates':3,'samples':2048,'sampled_seconds':.002048,'method':'host-pulse-v0.1','threshold_codes':20}
            (p/'capture.json').write_text(json.dumps(capture));(p/'spectrum-summary.json').write_text(json.dumps(summary))
            (p/'events.csv').write_text('flags,peak_code,area8_code_us\n0,50,465.7\n1,50,465.7\n0,30,-1\n')
            r=read_record(p)
            self.assertEqual(r['histogram']['counts']['area8'][931],1)
            self.assertEqual(r['histogram']['under']['area8'],1)
            self.assertTrue(compatible(r,r));other={**r,'threshold_codes':30};self.assertFalse(compatible(r,other))
            model=Model.__new__(Model);model.lock=threading.RLock();model.phase='idle';model.current=r;model.background=None
            exported=Path(model.export('area8',1024,r['name']))
            with exported.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),1024);self.assertEqual(sum(int(row['counts']) for row in rows),1)
            self.assertEqual(json.loads(exported.with_suffix('.json').read_text())['underflow'],1)
            capture['completed']=False;(p/'capture.json').write_text(json.dumps(capture))
            with self.assertRaises(ValueError):read_record(p)


class HTTPTests(unittest.TestCase):
    def test_token_origin_and_host_protection(self):
        class Stub:
            def state(self):return {'test':True}
            def records(self):return []
        server=create_server(0,Stub());thread=threading.Thread(target=server.serve_forever);thread.start()
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(url+'/api/state')
            caught.exception.close()
            req=urllib.request.Request(url+'/api/state',headers={'X-Aster-Token':server.token})
            with urllib.request.urlopen(req) as response:self.assertEqual(json.load(response),{'test':True})
            for headers in [{'Host':'evil.example'}, {'Origin':'https://evil.example'}]:
                headers['X-Aster-Token']=server.token
                with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(urllib.request.Request(url+'/api/state',headers=headers))
                caught.exception.close()
        finally:server.shutdown();server.server_close();thread.join()

    def test_acquisition_failure_cannot_be_exported(self):
        with tempfile.TemporaryDirectory() as folder, patch('gui_model.RECORD_ROOT',Path(folder)), patch('gui_model.run',side_effect=ValueError('Simulated checksum failure')):
            model=Model();model.connected={'port':'fake','info':{'fw':'0.3.1'}}
            model.start(1,20,'simulated failure');model.worker.join(2)
            self.assertEqual(model.phase,'error');self.assertFalse(model.current['valid'])
            with self.assertRaises(ValueError):model.export('area8',1024,model.current['name'])


class StopTests(unittest.TestCase):
    def test_manual_stop_is_valid_and_preserves_all_samples(self):
        helper=Checks();helper.setUp();codec=Codec();master,slave=pty.openpty();port=os.ttyname(slave)
        stopped=threading.Event();request=threading.Event();failures=[]
        def terminal(seq):
            payload=json.dumps({'errors':0,'adc_overrun':0,'completed_blocks':seq,'encoded_blocks':seq,'session':1}).encode()
            w=[1,2,1,seq,seq*2048,0,0,1000000,len(payload),0,0,codec.hash(payload),0,seq,seq*196608,0,seq*2,0]
            header=MAGIC+WORDS.pack(*w);w[-1]=codec.hash(header[:-4]);packet=MAGIC+WORDS.pack(*w)+payload
            return packet+b'\0'*(len(packet)%64==0)
        def device():
            buffer=b'';stream=False;seq=0
            try:
                while not stopped.is_set():
                    if select.select([master],[],[],.002)[0]:buffer+=os.read(master,4096)
                    while b'\n' in buffer:
                        command,buffer=buffer.split(b'\n',1)
                        if command==b'INFO':
                            os.write(master,json.dumps({'fw':'0.3.1','board':'Aster MCA Nano AT32 v0.3','adc_fault':0,'clock_fault':0}).encode()+b'\n')
                        elif command.startswith(b'STREAM '):os.write(master,b'OK STREAM\n');stream=True
                        elif command==b'STOP':
                            if stream:os.write(master,terminal(seq));stream=False
                    if stream:
                        os.write(master,helper.packet([2048]*2048,seq));seq+=1
            except BaseException as e:failures.append(e)
        thread=threading.Thread(target=device);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                out=Path(folder)/'capture'
                result=run(port,out,5,'fake device test',stop_event=request,on_progress=lambda _:request.set(),quiet=True)
                self.assertTrue(result['completed']);self.assertEqual(result['stop_reason'],'user_stop')
                self.assertLess(result['verified_sampled_seconds'],5)
                self.assertEqual(result['stored_raw_samples'],result['blocks']*2048)
                self.assertEqual(result['spectrum']['samples'],result['stored_raw_samples'])
        finally:
            stopped.set();thread.join(2);os.close(master);os.close(slave)
        self.assertFalse(failures)


if __name__=='__main__':unittest.main()
