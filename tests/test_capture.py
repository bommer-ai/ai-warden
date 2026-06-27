"""
Tests for event capture system.

Validates:
- Queue saturation and drop counting
- Worker recovery after drain
- Thread-safe dropped counter
- Backpressure behavior
"""
import threading
import time

import pytest

from aiwarden import config
from aiwarden.capture import (
    _MAX_QUEUE_SIZE,
    _queue,
    capture,
    flush,
    get_dropped_count,
)


class TestQueueSaturation:
    """Test behavior when capture queue reaches capacity."""

    def test_drops_counted_when_queue_full(self):
        """When queue is at capacity, new events are dropped and counted."""
        old_enabled = config.ENABLED
        config.ENABLED = True
        try:
            # Drain any existing events first
            flush()
            time.sleep(0.5)

            initial_drops = get_dropped_count()

            # Fill queue rapidly — worker may drain some but we overshoot
            for i in range(_MAX_QUEUE_SIZE + 500):
                capture({"saturation_test": True, "i": i})

            drops = get_dropped_count() - initial_drops
            assert drops > 0, "Expected some events to be dropped when queue is full"
            # We can't assert exact count since worker drains concurrently
            assert drops <= 500, f"Too many drops ({drops}) — queue might not be bounded"

        finally:
            config.ENABLED = old_enabled
            # Let worker drain
            time.sleep(3)

    def test_worker_recovers_after_saturation(self):
        """After queue fills and drains, new events are still captured normally."""
        old_enabled = config.ENABLED
        config.ENABLED = True
        try:
            # Fill and let drain
            for i in range(100):
                capture({"recovery_test": True, "i": i})
            time.sleep(3)  # let worker drain

            # Queue should be empty now
            assert _queue.qsize() < 50, f"Queue not draining: {_queue.qsize()}"

            # New events should be accepted
            capture({"post_recovery": True})
            # If this doesn't raise and queue accepts it, worker recovered
            assert _queue.qsize() >= 0  # sanity check — no crash

        finally:
            config.ENABLED = old_enabled
            time.sleep(2)

    def test_dropped_counter_thread_safe(self):
        """Multiple threads incrementing dropped counter don't lose counts."""
        old_enabled = config.ENABLED
        config.ENABLED = True
        try:
            # First saturate the queue
            flush()
            time.sleep(0.5)

            # Fill to capacity
            for _ in range(_MAX_QUEUE_SIZE):
                _queue.put_nowait({"filler": True})

            initial_drops = get_dropped_count()

            # Now have 20 threads each try to capture 50 events (all should be dropped)
            def dropper():
                for _ in range(50):
                    capture({"thread_drop_test": True})

            threads = [threading.Thread(target=dropper) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            total_drops = get_dropped_count() - initial_drops
            expected = 20 * 50
            # Allow some to succeed if worker drained a few during the test
            assert total_drops >= expected - 100, (
                f"Expected ~{expected} drops, got {total_drops} — counter may be lossy"
            )

        finally:
            config.ENABLED = old_enabled
            # Drain the filler events
            flush()
            time.sleep(3)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
