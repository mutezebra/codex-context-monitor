import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest


class Handler(BaseHTTPRequestHandler):
    hits=0
    app_hits=0
    def log_message(self,*_):pass
    def do_GET(self):
        type(self).hits+=1
        if self.path=='/json/list':type(self).app_hits+=1
        body=b'[]' if self.path=='/json/list' else b'{"service":"codex-context-monitor"}'
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)


@unittest.skipUnless(shutil.which('node'),'需要 Node.js')
class AttachRecoveryTests(unittest.TestCase):
    def test_persistent_worker_survives_missing_app_and_reconnects(self):
        service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        service_thread=threading.Thread(target=service.serve_forever,daemon=True);service_thread.start()
        app=ThreadingHTTPServer(('127.0.0.1',0),Handler);port=app.server_port;app.server_close()
        process=None;app_thread=None
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'server.json').write_text(json.dumps({'url':f'http://127.0.0.1:{service.server_port}/'}))
            try:
                process=subprocess.Popen(['node',str(Path(__file__).resolve().parents[1]/'scripts/attach.mjs'),
                    '--runtime',folder,'--port',str(port),'--persist'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                # 超过旧版“五次失败后退出”的窗口。
                time.sleep(12)
                self.assertIsNone(process.poll(),'应用未启动时，常驻采集器应等待而不是退出')
                before=Handler.app_hits
                app=ThreadingHTTPServer(('127.0.0.1',port),Handler)
                app_thread=threading.Thread(target=app.serve_forever,daemon=True);app_thread.start()
                deadline=time.monotonic()+6
                while Handler.app_hits<=before and time.monotonic()<deadline:time.sleep(.1)
                self.assertIsNone(process.poll())
                self.assertGreater(Handler.app_hits,before,'端口恢复后应重新轮询')
                app.shutdown();app.server_close();app_thread.join()
                time.sleep(3)
                self.assertIsNone(process.poll(),'已经连上后再次断开也应继续等待')
                before=Handler.app_hits
                app=ThreadingHTTPServer(('127.0.0.1',port),Handler)
                app_thread=threading.Thread(target=app.serve_forever,daemon=True);app_thread.start()
                deadline=time.monotonic()+6
                while Handler.app_hits<=before and time.monotonic()<deadline:time.sleep(.1)
                self.assertGreater(Handler.app_hits,before,'再次打开应用后应重新连接')
                app.shutdown();app.server_close();app_thread.join()
                process.terminate();out,err=process.communicate(timeout=10)
                self.assertIn('connected',out)
            finally:
                if app_thread and app_thread.is_alive():app.shutdown();app.server_close();app_thread.join()
                if process:
                    if process.poll() is None:process.kill()
                    process.communicate()
                service.shutdown();service.server_close();service_thread.join()


if __name__=='__main__':unittest.main()
