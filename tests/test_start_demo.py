"""Startup transport regressions; stdlib-only, including a real resetting TCP peer."""
from contextlib import contextmanager,redirect_stderr,redirect_stdout
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import socket
import struct
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from scripts import start_demo


def response(payload):return io.BytesIO(json.dumps(payload).encode())


@contextmanager
def booting_server():
    counts={'radio':0,'husky':0};posts=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,body):
            self.send_response(status);self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path=='/radio/health':
                counts['radio']+=1;n=counts['radio']
                if n==1:
                    self.connection.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('ii',1,0))
                    self.close_connection=True;self.connection.close();return
                if n==2:return self.reply(503,b'starting')
                if n==3:
                    self.send_response(200);self.send_header('Content-Length','100')
                    self.end_headers();self.wfile.write(b'{"status":');self.close_connection=True;return
                if n==4:return self.reply(200,b'<html>starting</html>')
                if n==5:return self.reply(200,b'[]')
                return self.reply(200,b'{"status":"ok","builder":true}')
            if self.path=='/husky/health':
                counts['husky']+=1
                if counts['husky']==1:self.close_connection=True;return
                # Nav2 is intentionally not ready before starting the world.
                return self.reply(200,b'{"status":"ok","navigation":{"ready":false}}')
            self.reply(404,b'unknown endpoint')
        def do_POST(self):
            posts.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.reply(200,b'{"status":"starting"}')
    with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
        try:yield 'http://127.0.0.1:'+str(server.server_port),counts,posts
        finally:server.shutdown();worker.join(timeout=3)


class StartupTests(unittest.TestCase):
    def test_actual_reset_partial_http_and_delayed_husky_are_retried_before_one_start(self):
        with booting_server() as (base,counts,posts),patch('scripts.start_demo.time.sleep'),redirect_stdout(io.StringIO()):
            start_demo.start(base+'/radio','office',husky_base=base+'/husky')
        self.assertEqual(counts,{'radio':6,'husky':2})
        self.assertEqual(posts,[('/radio/api/mission/start',{'mission':'office','response_profile':'responsive',
            'config':{'method':'GPR-pathloss','beta':1}})])

    def test_exact_connection_reset_error_at_health_read_is_retried(self):
        calls=[]
        class Opener:
            def open(self,url,**kwargs):
                calls.append(url)
                if len(calls)==1:raise ConnectionResetError(104,'Connection reset by peer')
                if isinstance(url,urllib.request.Request):return response({'status':'starting'})
                return response({'status':'ok','builder':True,'navigation':{}})
        with patch('scripts.start_demo.urllib.request.build_opener',return_value=Opener()),patch('scripts.start_demo.time.sleep'),redirect_stdout(io.StringIO()):
            start_demo.start('http://localhost:8010','shadow')
        self.assertEqual(calls[:3],['http://localhost:8010/health','http://localhost:8010/health','http://localhost:8766/health'])
        self.assertEqual(sum(isinstance(c,urllib.request.Request) for c in calls),1)

    def test_combined_deadline_expires_on_husky_without_posting_a_mission(self):
        clock=[0.];calls=[]
        class Opener:
            def open(self,url,**kwargs):
                calls.append(url)
                if url.endswith(':8010/health') and len(calls)>1:return response({'status':'ok','builder':True})
                raise ConnectionResetError(104,'not ready')
        with patch('scripts.start_demo.urllib.request.build_opener',return_value=Opener()),\
             patch('scripts.start_demo.time.monotonic',side_effect=lambda:clock[0]),\
             patch('scripts.start_demo.time.sleep',side_effect=lambda t:clock.__setitem__(0,clock[0]+t)),redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(TimeoutError,'Husky API.*docker compose logs'):
                start_demo.start('http://localhost:8010','shadow',wait_s=1)
        self.assertEqual(clock[0],1)
        self.assertEqual(len(calls),3)
        self.assertTrue(all(isinstance(c,str) for c in calls))

    def test_ambiguous_start_connection_reset_never_repeats_the_post(self):
        calls=[]
        class Opener:
            def open(self,url,**kwargs):
                calls.append(url)
                if isinstance(url,urllib.request.Request):raise ConnectionResetError(104,'Connection reset by peer')
                return response({'status':'ok','builder':True,'navigation':{}})
        with patch('scripts.start_demo.urllib.request.build_opener',return_value=Opener()),redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'may already be running.*not repeated'):
                start_demo.start('http://localhost:8010','shadow')
        self.assertEqual(sum(isinstance(c,urllib.request.Request) for c in calls),1)

    def test_active_mission_http_error_is_reported_without_retry(self):
        posts=[]
        class Opener:
            def open(self,url,**kwargs):
                if isinstance(url,urllib.request.Request):
                    posts.append(url);raise urllib.error.HTTPError(url.full_url,400,'Bad Request',{},response({'error':'Stop the current mission first'}))
                return response({'status':'ok','builder':True,'navigation':{}})
        with patch('scripts.start_demo.urllib.request.build_opener',return_value=Opener()),redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'Stop the current mission first'):
                start_demo.start('http://localhost:8010','shadow')
        self.assertEqual(len(posts),1)

    def test_cli_transport_failure_has_a_short_message_and_nonzero_exit(self):
        errors=io.StringIO()
        with patch('scripts.start_demo.start',side_effect=ConnectionResetError(104,'Connection reset by peer')),redirect_stderr(errors):
            code=start_demo.main([])
        self.assertEqual(code,1)
        self.assertIn('Cannot start mission:',errors.getvalue())
        self.assertNotIn('Traceback',errors.getvalue())


if __name__=='__main__':unittest.main()
