"""
Redis client singleton with graceful degradation.

Initializes lazily from AIWARDEN_REDIS_URL on first access.
If Redis is unavailable or the env var is unset, all operations
degrade gracefully — callers check `client.available` before use.
"""
import logging
import os

log = logging.getLogger(__name__)

_REDIS_URL_ENV = "AIWARDEN_REDIS_URL"


class RedisClient:
    """
    Lazy-initialized Redis wrapper with connection pooling.

    Usage:
        from aiwarden.redis_client import redis_client

        if redis_client.available:
            redis_client.conn.get("key")
    """

    def __init__(self):
        self._conn = None
        self._initialized = False
        self._available = False

    @property
    def available(self) -> bool:
        if not self._initialized:
            self._initialize()
        return self._available

    @property
    def conn(self):
        if not self._initialized:
            self._initialize()
        return self._conn

    def _initialize(self):
        self._initialized = True
        url = os.getenv(_REDIS_URL_ENV)
        if not url:
            log.debug("[aiwarden] %s not set — Redis disabled", _REDIS_URL_ENV)
            return

        try:
            import redis
        except ImportError:
            log.warning(
                "[aiwarden] redis package not installed. "
                "Install with: pip install ai-warden[redis]"
            )
            return

        try:
            self._conn = redis.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=0.5,
                retry_on_timeout=True,
            )
            self._conn.ping()
            self._available = True
            log.info("[aiwarden] Redis connected: %s", _mask_url(url))
        except Exception as e:
            log.warning("[aiwarden] Redis connection failed: %s — falling back to in-memory", e)
            self._conn = None

    def reset(self):
        """Reset state — primarily for testing."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
        self._initialized = False
        self._available = False


def _mask_url(url: str) -> str:
    """Mask password in Redis URL for safe logging."""
    if "@" in url:
        prefix, rest = url.rsplit("@", 1)
        scheme_end = prefix.find("://")
        if scheme_end != -1:
            return prefix[: scheme_end + 3] + "***@" + rest
    return url


redis_client = RedisClient()
