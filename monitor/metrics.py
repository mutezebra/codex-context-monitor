"""从日志中的结构化计数与时间计算指标；不读取或导出消息正文。"""

from collections import deque
from datetime import datetime
import math
import time


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return value
    return None


def millis(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
    except (ValueError, TypeError, AttributeError):
        return None


def counts(value):
    if not isinstance(value, dict):
        return {}
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
    result = {k: number(value.get(k)) for k in keys}
    # 缓存和推理分别属于输入、输出，不能在总量里再次相加。
    if result["input_tokens"] is not None and result["output_tokens"] is not None:
        result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    return result


class Metrics:
    def __init__(self):
        self.total = {}
        self.last = {}
        self.context_window = None
        self.model = None
        self.effort = None
        self.turn_id = None
        self.phase = "unknown"
        self.pending_start = None
        self.latest_tps = None
        self.measured_tokens = 0
        self.measured_seconds = 0
        self.responses = 0
        self.measured_responses = 0
        self.ttft_ms = None
        self.duration_ms = None
        self.turn_started_at = None
        self.turn_finished_at = None
        self.turn_status = "unknown"
        self.limits = None
        self.compactions = 0
        self.last_signature = None
        self.seen = deque(maxlen=4096)
        self.seen_items = deque(maxlen=4096)
        self.history = deque(maxlen=60)
        self.updated_at = None

    def feed(self, record):
        if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
            return
        p = record["payload"]
        kind = record.get("type")
        stamp = millis(record.get("timestamp"))
        if kind == "turn_context":
            self.model = p.get("model")
            self.effort = p.get("effort")
        elif kind == "token_usage_record":
            self._usage(p.get("usage"), p.get("thread_token_usage"), stamp, p.get("response_id"))
        elif kind == "event_msg":
            t = p.get("type")
            if t == "task_started":
                if p.get("turn_id") and p.get("turn_id") == self.turn_id:
                    return
                self.turn_id = p.get("turn_id")
                self.turn_started_at = stamp
                if self.turn_started_at is None and number(p.get("started_at")) is not None:
                    self.turn_started_at = p["started_at"] * 1000
                self.turn_finished_at = None
                self.turn_status = "active"
                self.phase = "waiting"
                self.latest_tps = self.pending_start = self.ttft_ms = self.duration_ms = None
                self.context_window = number(p.get("model_context_window")) or self.context_window
            elif t == "item_completed":
                item = p.get("item") or {}
                item_id = item.get("id")
                if item_id and item_id in self.seen_items:
                    return
                if item_id:
                    self.seen_items.append(item_id)
                if item.get("type") in ("AgentMessage", "Reasoning"):
                    start, end = number(p.get("started_at_ms")), number(p.get("completed_at_ms"))
                    if start is not None and end is not None and end > start:
                        self.pending_start = min(start, self.pending_start) if self.pending_start is not None else start
                        self.phase = "generating"
                elif item.get("type"):
                    # 缺少 usage 的响应不能跨越工具执行拼接到下一次响应。
                    self.pending_start = None
                    if item.get("type") != "UserMessage":
                        self.phase = "tool"
            elif t == "token_count":
                if isinstance(p.get("rate_limits"), dict):
                    # 只保留额度数字，不把其他账户信息传递给 UI。
                    self.limits = {k: p["rate_limits"].get(k) for k in ("primary", "secondary", "plan_type")}
                info = p.get("info")
                if isinstance(info, dict):
                    self.context_window = number(info.get("model_context_window")) or self.context_window
                    self._usage(info.get("last_token_usage"), info.get("total_token_usage"), stamp)
            elif t == "task_complete":
                if p.get("turn_id") and self.turn_id and p["turn_id"] != self.turn_id:
                    return
                self.phase = "completed"
                self.ttft_ms = number(p.get("time_to_first_token_ms"))
                self.duration_ms = number(p.get("duration_ms"))
                self._finish_turn("completed", stamp)
                self.pending_start = None
            elif t in ("turn_aborted", "task_interrupted"):
                if p.get("turn_id") and self.turn_id and p["turn_id"] != self.turn_id:
                    return
                self.phase = "interrupted"
                self._finish_turn("interrupted", stamp)
                self.pending_start = None
            elif t == "context_compacted":
                self.compactions += 1

    def _usage(self, raw, total, stamp, response_id=None):
        if not isinstance(raw, dict):
            return
        last, cumulative = counts(raw), counts(total)
        signature = tuple(cumulative.get(k) for k in ("input_tokens", "output_tokens", "total_tokens"))
        has_signature = any(v is not None for v in signature)
        if response_id and response_id in self.seen:
            return
        if response_id:
            self.seen.append(response_id)
        # 新旧两种事件会连续写入同一累计快照，不能把它们视为两次响应。
        if has_signature and signature == self.last_signature:
            return
        self.last_signature = signature if has_signature else None
        self.last = last
        if cumulative:
            self.total = cumulative
        self.updated_at = stamp
        self.responses += 1
        self.latest_tps = None
        output = last.get("output_tokens")
        if output is not None and self.pending_start is not None and stamp is not None:
            seconds = (stamp - self.pending_start) / 1000
            if seconds > 0 and output / seconds <= 100000:
                self.latest_tps = output / seconds
                self.measured_tokens += output
                self.measured_seconds += seconds
                self.measured_responses += 1
                self.history.append({"tps": self.latest_tps, "timestamp": stamp})
        self.pending_start = None
        self.phase = "running"

    def _finish_turn(self, status, stamp):
        self.turn_status = status
        self.turn_finished_at = stamp
        if self.duration_ms is None and stamp is not None and self.turn_started_at is not None:
            self.duration_ms = max(0, stamp - self.turn_started_at)

    def snapshot(self, now_ms=None):
        inp, cached = self.total.get("input_tokens"), self.total.get("cached_input_tokens")
        context = self.last.get("total_tokens")
        elapsed = self.duration_ms
        if self.turn_status == "active" and self.turn_started_at is not None:
            elapsed = max(0, (time.time()*1000 if now_ms is None else now_ms) - self.turn_started_at)
        return {
            "model": self.model, "effort": self.effort, "turn_id": self.turn_id,
            "phase": self.phase, "latest_tps": self.latest_tps,
            "average_tps": self.measured_tokens / self.measured_seconds if self.measured_seconds else None,
            "measured_seconds": self.measured_seconds, "measured_tokens": self.measured_tokens,
            "responses": self.responses, "measured_responses": self.measured_responses,
            "unmeasured_responses": self.responses - self.measured_responses,
            "context_tokens": context, "context_window": self.context_window,
            "context_percent": context / self.context_window * 100 if context is not None and self.context_window else None,
            "cache_hit_percent": cached / inp * 100 if inp and cached is not None and cached <= inp else None,
            "total": self.total.copy(), "last": self.last.copy(), "limits": self.limits,
            "ttft_ms": self.ttft_ms, "duration_ms": self.duration_ms,
            "turn_started_at": self.turn_started_at, "turn_finished_at": self.turn_finished_at,
            "turn_status": self.turn_status, "elapsed_ms": elapsed,
            "compactions": self.compactions, "history": list(self.history), "updated_at": self.updated_at,
        }
