import json
import threading
from pathlib import Path
from queue import Empty, Queue

from aiwarden import config

_queue: Queue = Queue()
_worker_started = False
_lock = threading.Lock()


def capture(event: dict):
    """Enqueue event — non-blocking, never raises."""
    if not config.ENABLED:
        return
    try:
        _queue.put_nowait(event)
        _ensure_worker()
    except Exception:
        pass


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
    with _lock:
        if not _worker_started:
            _worker_started = True
            t = threading.Thread(target=_worker, daemon=True, name="aiwarden-worker")
            t.start()


def _worker():
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
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def _print_event(event: dict):
    print(f"\n{'─'*60}")
    print(f"[aiwarden] {event.get('timestamp', '')}")
    print(f"  id         : {event.get('id', '')}")
    print(f"  provider   : {event.get('provider', '')}  type: {event.get('type', '')}")
    print(f"  model      : {event.get('model', 'unknown')}")
    print(f"  session_id : {event.get('session_id', '')}  turn: {event.get('turn', 0)}")
    print(f"  tokens     : prompt={event.get('prompt_tokens',0)}  completion={event.get('completion_tokens',0)}")
    print(f"  cost       : ${event.get('cost', 0):.6f}")
    print(f"  latency_ms : {event.get('latency_ms', 0)} ms")
    print(f"  finish     : {event.get('finish_reason', '')}  streamed: {event.get('streamed', False)}")
    print(f"  caller     : {event.get('caller_file','?')}:{event.get('caller_line','?')} in {event.get('caller_function','?')}")
    if event.get("tags"):
        print(f"  tags       : {event['tags']}")
    if event.get("tool_calls"):
        print(f"  tool_calls : {event['tool_calls']}")
    if event.get("pii_redacted"):
        print(f"  pii_found  : {event.get('pii_types_found', [])}")
    if event.get("request_messages"):
        print(f"  messages   :")
        for msg in event.get("request_messages", []):
            role    = msg.get("role", "")
            content = str(msg.get("content", ""))[:200]
            print(f"    [{role}] {content}")
        print(f"  response   : {str(event.get('response_content', ''))[:200]}")
    print(f"{'─'*60}")
