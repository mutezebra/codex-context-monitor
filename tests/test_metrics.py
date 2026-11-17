import unittest
from monitor.metrics import Metrics


def event(kind, **payload):
    return {"type": "event_msg", "timestamp": "2026-01-01T00:00:00Z", "payload": {"type": kind, **payload}}


def usage(rid, tokens, timestamp, total=None):
    u = dict(input_tokens=1000, cached_input_tokens=800, output_tokens=tokens,
             reasoning_output_tokens=20, total_tokens=1000 + tokens)
    return {"type": "token_usage_record", "timestamp": timestamp,
            "payload": {"response_id": rid, "usage": u, "thread_token_usage": total or u}}


def item(start, end, kind="Reasoning", ident="i"):
    return event("item_completed", started_at_ms=start, completed_at_ms=end,
                 item={"type": kind, "id": ident})


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.m = Metrics()
        self.m.feed(event("task_started", turn_id="turn1", model_context_window=10000))
        self.base = 1767225600000

    def test_weighted_average_excludes_tool_execution(self):
        self.m.feed(item(self.base, self.base + 900))
        self.m.feed(usage("r1", 100, "2026-01-01T00:00:01Z"))
        self.m.feed(item(self.base + 1000, self.base + 50000, "CommandExecution", "tool"))
        self.m.feed(item(self.base + 50000, self.base + 53000, ident="i2"))
        self.m.feed(usage("r2", 600, "2026-01-01T00:00:53Z"))
        s = self.m.snapshot()
        self.assertEqual(s["latest_tps"], 200)
        self.assertEqual(s["average_tps"], 175)
        self.assertEqual(s["measured_seconds"], 4)

    def test_missing_time_does_not_fabricate_speed(self):
        self.m.feed(usage("r", 100, "2026-01-01T00:00:01Z"))
        self.assertIsNone(self.m.snapshot()["latest_tps"])
        self.assertIsNone(self.m.snapshot()["average_tps"])
        self.assertEqual(self.m.snapshot()["unmeasured_responses"], 1)

    def test_duplicate_usage_does_not_double_count(self):
        self.m.feed(item(self.base, self.base+900))
        e = usage("r", 100, "2026-01-01T00:00:01Z")
        self.m.feed(e)
        self.m.feed(e)
        self.m.feed(event("token_count", info={"total_token_usage":e["payload"]["usage"],
            "last_token_usage": e["payload"]["usage"], "model_context_window":10000}))
        s = self.m.snapshot()
        self.assertEqual(s["responses"], 1)
        self.assertEqual(s["context_tokens"], 1100)
        self.assertEqual(s["total"]["total_tokens"], 1100)
        self.assertEqual(s["cache_hit_percent"], 80)

    def test_new_turn_clears_latest_preserves_average(self):
        self.m.feed(item(self.base, self.base + 900))
        self.m.feed(usage("r", 100, "2026-01-01T00:00:01Z"))
        self.m.feed(event("task_complete", duration_ms=2000, time_to_first_token_ms=400))
        self.assertEqual(self.m.snapshot()["ttft_ms"], 400)
        self.m.feed(event("task_started", turn_id="turn2"))
        self.assertIsNone(self.m.snapshot()["latest_tps"])
        self.assertIsNone(self.m.snapshot()["ttft_ms"])
        self.assertEqual(self.m.snapshot()["average_tps"], 100)

    def test_legacy_and_malformed_events(self):
        self.m.feed({"type":"event_msg", "payload":None})
        self.m.feed(item(self.base+2000, self.base))
        self.m.feed(event("token_count", info={"last_token_usage":{"output_tokens":50},
            "total_token_usage":{"input_tokens":100, "output_tokens":50, "total_tokens":150}}))
        self.assertIsNone(self.m.snapshot()["latest_tps"])
        self.assertEqual(self.m.snapshot()["responses"], 1)

    def test_usage_before_compatibility_record_is_only_one_response(self):
        self.m.feed(item(self.base, self.base+900))
        e=usage("r",100,"2026-01-01T00:00:01Z")
        compat=event("token_count",info={"last_token_usage":e["payload"]["usage"],
           "total_token_usage":e["payload"]["usage"]})
        compat["timestamp"]=e["timestamp"]
        self.m.feed(compat)
        self.m.feed(e)
        self.assertEqual(self.m.snapshot()["responses"],1)

    def test_missing_usage_before_tool_cannot_include_tool_runtime(self):
        self.m.feed(item(self.base,self.base+900))
        self.m.feed(item(self.base+1000,self.base+50000,"CommandExecution","tool"))
        self.m.feed(item(self.base+50000,self.base+53000,ident="later"))
        self.m.feed(usage("r",600,"2026-01-01T00:00:53Z"))
        self.assertEqual(self.m.snapshot()["latest_tps"],200)

    def test_replayed_item_cannot_move_next_response_start_backwards(self):
        first=item(self.base,self.base+900)
        self.m.feed(first)
        self.m.feed(usage("r1",100,"2026-01-01T00:00:01Z"))
        self.m.feed(first)
        self.m.feed(item(self.base+50000,self.base+53000,ident="next"))
        self.m.feed(usage("r2",600,"2026-01-01T00:00:53Z"))
        self.assertEqual(self.m.snapshot()["latest_tps"],200)


if __name__ == "__main__":
    unittest.main()
