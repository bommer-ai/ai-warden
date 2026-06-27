import atexit
import json
import logging
import threading
from pathlib import Path
from queue import Empty, Full, Queue

from aiwarden import config

log = logging.getLogger(__name__)

_MAX_QUEUE_SIZE = 10_000
_queue: Queue = Queue(maxsize=_MAX_QUEUE_SIZE)
_worker_started = False
_lock = threading.Lock()
_dropped_lock = threading.Lock()
_dropped_events = 0


def capture(event: dict):
    """Enqueue event — non-blocking, never raises. Drops events if queue is full."""
    if not config.ENABLED:
        return
    try:
        _queue.put_nowait(event)
        _ensure_worker()
    except Full:
        global _dropped_events
        with _dropped_lock:
            _dropped_events += 1
    except Exception:
        pass


def get_dropped_count() -> int:
    """Return the number of events dropped due to queue backpressure (thread-safe)."""
    with _dropped_lock:
        return _dropped_events


def flush():
    """Force immediate flush — useful in tests or on shutdown."""
    events = []
    while not _queue.empty():
        try:
            events.append(_queue.get_nowait())
        except Exception:
            break
    if events:
        _flush(events)


def _ensure_worker():
    global _worker_started
    if _worker_started:
        return
    with _lock:
        if not _worker_started:
            _worker_started = True
            t = threading.Thread(target=_worker, daemon=True, name="aiwarden-worker")
            t.start()
            atexit.register(flush)


def _worker():
    """Outer loop with crash recovery — thread never dies until process exits."""
    while True:
        try:
            _worker_inner()
        except BaseException:
            pass


def _worker_inner():
    buffer = []
    while True:
        try:
            event = _queue.get(timeout=2.0)
            buffer.append(event)
            if len(buffer) >= 50:
                _flush(buffer)
                buffer = []
        except Empty:
            if buffer:
                _flush(buffer)
                buffer = []
        except Exception:
            if buffer:
                _flush(buffer)
            buffer = []


def _flush(events: list):
    for event in events:
        if config.DEBUG:
            _print_event(event)
        _write_event(event)


def _write_event(event: dict):
    """Append event as a single JSON line to the log file."""
    try:
        log_path = Path(config.LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass


def _print_event(event: dict):
    try:
        print(f"\n{'─'*60}")
        print(f"[aiwarden] {event.get('timestamp', '')}")
        print(f"  provider   : {event.get('provider', '')}  model: {event.get('model', 'unknown')}")
        print(f"  run_id     : {event.get('run_id', '')}  turn: {event.get('turn', 0)}")
        print(f"  tokens     : prompt={event.get('prompt_tokens',0)}  completion={event.get('completion_tokens',0)}")
        print(f"  cost       : ${event.get('cost', 0):.6f}")
        print(f"  latency_ms : {event.get('latency_ms', 0)} ms")
        print(f"  finish     : {event.get('finish_reason', '')}  streamed: {event.get('streamed', False)}")
        if event.get("policy_fired"):
            print(f"  policies   : {event.get('policies', [])}")
        if event.get("policy_blocked"):
            print(f"  !! BLOCKED")
        if event.get("tool_calls"):
            print(f"  tool_calls : {[tc.get('name') for tc in event.get('tool_calls', [])]}")
        print(f"{'─'*60}")
    except Exception:
        pass
