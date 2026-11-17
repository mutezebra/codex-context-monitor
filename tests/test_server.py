import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from monitor.server import Store, make_server

TID = "00000000-0000-0000-0000-000000000001"


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        (self.home / "sessions").mkdir()
        self.log = self.home / "sessions" / "test.jsonl"
        self.log.write_text('{"type":"turn_context","payload":{"model":"test-model"}}\n')
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("create table threads (id text, rollout_path text, title text)")
            db.execute("insert into threads values (?,?,?)", (TID, str(self.log), "测试"))
        self.store = Store(self.home)
        self.server = make_server(self.store, "test-secret", port=0)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()
        self.temp.cleanup()

    def test_incremental_append_and_partial_line(self):
        self.assertEqual(self.store.snapshot(TID)["model"], "test-model")
        with self.log.open("a") as f:
            f.write('{"type":"turn_context","payload":{"model":"new')
        self.assertEqual(self.store.snapshot(TID)["model"], "test-model")
        with self.log.open("a") as f:
            f.write('-model"}}\n')
        self.assertEqual(self.store.snapshot(TID)["model"], "new-model")

    def test_http_only_exposes_aggregate_for_valid_token(self):
        url = self.base + "/test-secret/api/session/" + TID
        with urlopen(url) as r:
            data = json.load(r)
            self.assertEqual(data["title"], "测试")
            self.assertNotIn("rollout_path", data)
        for path, headers in [("/api/session/"+TID, {}),
            ("/test-secret/../../auth.json", {}),
            ("/test-secret/api/session/"+TID, {"Origin":"https://evil.example"}),
            ("/test-secret/api/session/"+TID, {"Host":"evil.example"})]:
            with self.assertRaises(HTTPError) as raised:
                urlopen(Request(self.base+path, headers=headers))
            raised.exception.close()

    def test_invalid_session_and_outside_path_rejected(self):
        with self.assertRaises(ValueError):
            self.store.snapshot("../../auth.json")
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("update threads set rollout_path=?", (str(self.home / "auth.json"),))
        with self.assertRaises(ValueError):
            self.store.snapshot(TID)


if __name__ == "__main__":
    unittest.main()
