import unittest
from monitor.metrics import Metrics


def event(kind, at, **values):
    return {"type":"event_msg", "timestamp":at, "payload":{"type":kind, **values}}


class ElapsedTests(unittest.TestCase):
    def setUp(self):
        self.m=Metrics()
        self.base=1767225600000
        self.m.feed(event("task_started","2026-01-01T00:00:00Z",turn_id="a",started_at=1767225600))

    def test_elapsed_includes_tool_waits(self):
        self.m.feed(event("item_completed","2026-01-01T00:00:30Z",item={"type":"CommandExecution","id":"t"}))
        self.assertEqual(self.m.snapshot(now_ms=self.base+65000)["elapsed_ms"],65000)
        self.assertEqual(self.m.snapshot()["turn_status"],"active")

    def test_finish_freezes_authoritative_duration(self):
        self.m.feed(event("task_complete","2026-01-01T00:01:06Z",turn_id="a",duration_ms=65321))
        self.assertEqual(self.m.snapshot(now_ms=self.base+90000)["elapsed_ms"],65321)
        self.assertEqual(self.m.snapshot()["turn_status"],"completed")

    def test_new_turn_resets_and_old_completion_is_ignored(self):
        self.m.feed(event("task_started","2026-01-01T00:01:00Z",turn_id="b"))
        self.m.feed(event("task_complete","2026-01-01T00:01:01Z",turn_id="a",duration_ms=61000))
        self.assertEqual(self.m.snapshot(now_ms=self.base+62000)["elapsed_ms"],2000)
        self.assertEqual(self.m.snapshot()["turn_status"],"active")

    def test_interrupt_freezes_and_duplicate_start_does_not_restart(self):
        self.m.feed(event("turn_aborted","2026-01-01T00:00:12Z",turn_id="a"))
        self.m.feed(event("task_started","2026-01-01T00:00:20Z",turn_id="a"))
        self.assertEqual(self.m.snapshot(now_ms=self.base+40000)["elapsed_ms"],12000)
        self.assertEqual(self.m.snapshot()["turn_status"],"interrupted")

    def test_missing_start_never_uses_page_open_time(self):
        self.assertIsNone(Metrics().snapshot(now_ms=self.base)["elapsed_ms"])
        self.assertEqual(self.m.snapshot(now_ms=self.base-1)["elapsed_ms"],0)

    def test_completion_without_duration_uses_timestamp_difference(self):
        self.m.feed(event("task_complete","2026-01-01T00:00:07.321Z",turn_id="a"))
        self.assertEqual(self.m.snapshot(now_ms=self.base+10000)["elapsed_ms"],7321)


if __name__=="__main__":unittest.main()
