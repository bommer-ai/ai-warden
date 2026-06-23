"""
Distributed spend tracker — atomic budget enforcement across pods/processes.

Uses Redis Lua scripts for atomic check-and-increment operations.
Falls back to in-memory tracking when Redis is unavailable.
"""
import logging
import threading

log = logging.getLogger(__name__)

_RECORD_SPEND_LUA = """
local new_total = redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return new_total
"""

_TTL_BY_PERIOD = {
    "daily": 172800,      # 2 days
    "weekly": 691200,     # 8 days
    "monthly": 3024000,   # 35 days
}


class DistributedSpendTracker:
    """
    Tracks LLM spend using Redis for distributed enforcement,
    with automatic fallback to per-process in-memory tracking.

    Thread-safe for both Redis and in-memory modes.
    """

    def __init__(self, reset_period: str = "monthly"):
        self._reset_period = reset_period
        self._local_spend: dict[str, float] = {}
        self._lock = threading.Lock()
        self._record_script = None

    @property
    def _ttl(self) -> int:
        return _TTL_BY_PERIOD.get(self._reset_period, 3024000)

    def _get_redis(self):
        from aiwarden.redis_client import redis_client
        if not redis_client.available:
            return None
        return redis_client.conn

    def _get_record_script(self, conn):
        if self._record_script is None:
            self._record_script = conn.register_script(_RECORD_SPEND_LUA)
        return self._record_script

    def get_spend(self, key: str) -> float:
        """Return current spend for a budget key."""
        conn = self._get_redis()
        if conn is not None:
            try:
                val = conn.get(key)
                return float(val) if val else 0.0
            except Exception as e:
                log.warning("[aiwarden] Redis get_spend failed: %s — using local", e)
        with self._lock:
            return self._local_spend.get(key, 0.0)

    def check_budget(self, key: str, limit: float) -> tuple[bool, float]:
        """
        Check if current spend is within budget.

        Returns (allowed, current_spend).
        Does NOT modify the spend — use record_spend() after the LLM call.
        """
        spend = self.get_spend(key)
        return spend < limit, spend

    def record_spend(self, key: str, cost: float) -> float:
        """
        Atomically increment spend by `cost`.

        Returns the new total spend after increment.
        """
        if cost <= 0:
            return self.get_spend(key)

        conn = self._get_redis()
        if conn is not None:
            try:
                script = self._get_record_script(conn)
                new_total = script(keys=[key], args=[str(cost), str(self._ttl)])
                return float(new_total)
            except Exception as e:
                log.warning("[aiwarden] Redis record_spend failed: %s — using local", e)

        with self._lock:
            current = self._local_spend.get(key, 0.0)
            self._local_spend[key] = current + cost
            return self._local_spend[key]

    def get_all_spend(self, key_prefix: str) -> dict[str, float]:
        """
        Return all spend entries matching a prefix.

        In Redis mode, uses SCAN to find matching keys.
        In local mode, returns all keys with the given prefix.
        """
        conn = self._get_redis()
        if conn is not None:
            try:
                result = {}
                cursor = 0
                pattern = f"{key_prefix}*"
                while True:
                    cursor, keys = conn.scan(cursor=cursor, match=pattern, count=100)
                    for k in keys:
                        val = conn.get(k)
                        if val:
                            result[k] = float(val)
                    if cursor == 0:
                        break
                return result
            except Exception as e:
                log.warning("[aiwarden] Redis get_all_spend failed: %s — using local", e)

        with self._lock:
            return {
                k: v for k, v in self._local_spend.items()
                if k.startswith(key_prefix)
            }

    def reset(self, key: str):
        """Reset spend for a specific key (primarily for testing)."""
        conn = self._get_redis()
        if conn is not None:
            try:
                conn.delete(key)
            except Exception:
                pass
        with self._lock:
            self._local_spend.pop(key, None)
