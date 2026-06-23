"""
Tests for distributed budget policy enforcement.

Covers:
  - DistributedSpendTracker: Redis mode, local fallback, atomic operations
  - BudgetPolicy integration: pre/post hooks with distributed tracker
  - Concurrent access: thread safety under contention
  - Graceful degradation: Redis unavailable scenarios
  - TTL management: period-appropriate expiry times
"""
import threading
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from aiwarden.policies.builtin.budget import BudgetPolicy
from aiwarden.policies.builtin._distributed_tracker import (
    DistributedSpendTracker,
    _TTL_BY_PERIOD,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_response(prompt_tokens=100, completion_tokens=50):
    return SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )
    )


def _policy(limit=10.0, reset="monthly", group_by=""):
    config = {"limit": limit, "reset": reset}
    if group_by:
        config["group_by"] = group_by
    return BudgetPolicy(config)


# ── DistributedSpendTracker — local fallback mode ────────────────────────────

class TestTrackerLocalMode:
    def setup_method(self):
        self.tracker = DistributedSpendTracker(reset_period="monthly")

    def test_initial_spend_is_zero(self):
        assert self.tracker.get_spend("budget:test:2026-06") == 0.0

    def test_record_spend_increments(self):
        self.tracker.record_spend("k1", 1.5)
        self.tracker.record_spend("k1", 2.5)
        assert self.tracker.get_spend("k1") == 4.0

    def test_check_budget_allows_under_limit(self):
        self.tracker.record_spend("k1", 5.0)
        allowed, spend = self.tracker.check_budget("k1", 10.0)
        assert allowed is True
        assert spend == 5.0

    def test_check_budget_blocks_at_limit(self):
        self.tracker.record_spend("k1", 10.0)
        allowed, spend = self.tracker.check_budget("k1", 10.0)
        assert allowed is False
        assert spend == 10.0

    def test_check_budget_blocks_over_limit(self):
        self.tracker.record_spend("k1", 15.0)
        allowed, spend = self.tracker.check_budget("k1", 10.0)
        assert allowed is False
        assert spend == 15.0

    def test_zero_cost_does_not_increment(self):
        self.tracker.record_spend("k1", 5.0)
        self.tracker.record_spend("k1", 0.0)
        assert self.tracker.get_spend("k1") == 5.0

    def test_negative_cost_does_not_increment(self):
        self.tracker.record_spend("k1", 5.0)
        self.tracker.record_spend("k1", -1.0)
        assert self.tracker.get_spend("k1") == 5.0

    def test_separate_keys_are_independent(self):
        self.tracker.record_spend("k1", 5.0)
        self.tracker.record_spend("k2", 3.0)
        assert self.tracker.get_spend("k1") == 5.0
        assert self.tracker.get_spend("k2") == 3.0

    def test_get_all_spend_filters_by_prefix(self):
        self.tracker.record_spend("aiwarden:budget:eng:2026-06", 5.0)
        self.tracker.record_spend("aiwarden:budget:sales:2026-06", 3.0)
        self.tracker.record_spend("other:key", 99.0)
        result = self.tracker.get_all_spend("aiwarden:budget:")
        assert len(result) == 2
        assert result["aiwarden:budget:eng:2026-06"] == 5.0
        assert result["aiwarden:budget:sales:2026-06"] == 3.0

    def test_reset_clears_key(self):
        self.tracker.record_spend("k1", 10.0)
        self.tracker.reset("k1")
        assert self.tracker.get_spend("k1") == 0.0


# ── DistributedSpendTracker — Redis mode ─────────────────────────────────────

class TestTrackerRedisMode:
    @pytest.fixture(autouse=True)
    def setup_fakeredis(self):
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed — install with: pip install fakeredis[lua]")
        self.fake_redis = fakeredis.FakeRedis(decode_responses=True)
        self.tracker = DistributedSpendTracker(reset_period="daily")
        self._patcher = patch.object(self.tracker, "_get_redis", return_value=self.fake_redis)
        self._patcher.start()
        yield
        self._patcher.stop()
        self.fake_redis.flushall()

    def test_record_and_get_spend(self):
        self.tracker.record_spend("k1", 2.5)
        self.tracker.record_spend("k1", 3.5)
        assert self.tracker.get_spend("k1") == pytest.approx(6.0)

    def test_atomic_increment(self):
        new_total = self.tracker.record_spend("k1", 7.77)
        assert new_total == pytest.approx(7.77)
        new_total = self.tracker.record_spend("k1", 2.23)
        assert new_total == pytest.approx(10.0)

    def test_ttl_is_set_on_key(self):
        self.tracker.record_spend("k1", 1.0)
        ttl = self.fake_redis.ttl("k1")
        assert ttl == _TTL_BY_PERIOD["daily"]

    def test_check_budget_reads_from_redis(self):
        self.tracker.record_spend("k1", 8.0)
        allowed, spend = self.tracker.check_budget("k1", 10.0)
        assert allowed is True
        assert spend == pytest.approx(8.0)

    def test_check_budget_blocks_when_over(self):
        self.tracker.record_spend("k1", 11.0)
        allowed, spend = self.tracker.check_budget("k1", 10.0)
        assert allowed is False

    def test_get_all_spend_scans_keys(self):
        self.tracker.record_spend("aiwarden:budget:eng:2026-06", 5.0)
        self.tracker.record_spend("aiwarden:budget:sales:2026-06", 3.0)
        self.tracker.record_spend("unrelated:key", 99.0)
        result = self.tracker.get_all_spend("aiwarden:budget:")
        assert len(result) == 2

    def test_reset_deletes_redis_key(self):
        self.tracker.record_spend("k1", 10.0)
        self.tracker.reset("k1")
        assert self.tracker.get_spend("k1") == 0.0


# ── DistributedSpendTracker — fallback on Redis failure ──────────────────────

class TestTrackerFallback:
    def setup_method(self):
        self.tracker = DistributedSpendTracker(reset_period="weekly")

    def test_falls_back_on_redis_exception(self):
        broken_redis = MagicMock()
        broken_redis.get.side_effect = ConnectionError("connection lost")
        broken_redis.register_script.return_value = MagicMock(
            side_effect=ConnectionError("connection lost")
        )

        with patch.object(self.tracker, "_get_redis", return_value=broken_redis):
            self.tracker.record_spend("k1", 5.0)
            spend = self.tracker.get_spend("k1")
            assert spend == 5.0

    def test_falls_back_when_redis_none(self):
        with patch.object(self.tracker, "_get_redis", return_value=None):
            self.tracker.record_spend("k1", 3.0)
            allowed, spend = self.tracker.check_budget("k1", 10.0)
            assert allowed is True
            assert spend == 3.0


# ── TTL configuration ────────────────────────────────────────────────────────

class TestTTLPeriods:
    def test_daily_ttl(self):
        t = DistributedSpendTracker(reset_period="daily")
        assert t._ttl == 172800

    def test_weekly_ttl(self):
        t = DistributedSpendTracker(reset_period="weekly")
        assert t._ttl == 691200

    def test_monthly_ttl(self):
        t = DistributedSpendTracker(reset_period="monthly")
        assert t._ttl == 3024000

    def test_unknown_period_defaults_to_monthly(self):
        t = DistributedSpendTracker(reset_period="yearly")
        assert t._ttl == 3024000


# ── BudgetPolicy integration ─────────────────────────────────────────────────

class TestBudgetPolicyIntegration:
    def test_pre_allows_under_budget(self):
        policy = _policy(limit=100.0)
        request = {"model": "claude-sonnet-4-6", "messages": []}
        result_req, block = policy.pre(request)
        assert block is None
        assert result_req is request

    def test_pre_blocks_over_budget(self):
        policy = _policy(limit=1.0)
        policy._tracker.record_spend(policy._budget_key("__global__"), 1.5)
        request = {"model": "claude-sonnet-4-6", "messages": []}
        _, block = policy.pre(request)
        assert block is not None
        assert "Budget exceeded" in block.reason

    def test_post_records_cost(self):
        policy = _policy(limit=100.0)
        request = {"model": "claude-sonnet-4-6", "messages": []}
        response = _make_response(prompt_tokens=1000, completion_tokens=500)
        policy.post(request, response)
        spend = policy.get_spend("__global__")
        assert spend > 0

    def test_pre_and_post_full_cycle(self):
        policy = _policy(limit=100.0)
        request = {"model": "claude-sonnet-4-6", "messages": []}

        _, block = policy.pre(request)
        assert block is None

        response = _make_response(prompt_tokens=1000, completion_tokens=500)
        policy.post(request, response)

        spend = policy.get_spend("__global__")
        assert spend > 0

    def test_group_by_separates_budgets(self):
        policy = _policy(limit=10.0, group_by="metadata.team")
        req_eng = {"model": "claude-sonnet-4-6", "messages": [], "metadata": {"team": "engineering"}}
        req_sales = {"model": "claude-sonnet-4-6", "messages": [], "metadata": {"team": "sales"}}

        policy._tracker.record_spend(policy._budget_key("engineering"), 10.0)

        _, block_eng = policy.pre(req_eng)
        _, block_sales = policy.pre(req_sales)

        assert block_eng is not None
        assert block_sales is None

    def test_budget_key_includes_period(self):
        policy = _policy(limit=10.0, reset="daily")
        key = policy._budget_key("__global__")
        assert "aiwarden:budget:__global__:" in key
        assert key.count(":") == 3

    def test_get_all_spend_returns_current_period_only(self):
        policy = _policy(limit=100.0)
        key = policy._budget_key("engineering")
        policy._tracker.record_spend(key, 5.0)
        old_key = "aiwarden:budget:engineering:1999-01"
        policy._tracker.record_spend(old_key, 99.0)
        result = policy.get_all_spend()
        assert "engineering" in result
        assert result["engineering"] == 5.0

    def test_post_handles_missing_usage_gracefully(self):
        policy = _policy(limit=100.0)
        request = {"model": "claude-sonnet-4-6", "messages": []}
        response = SimpleNamespace()
        policy.post(request, response)
        assert policy.get_spend("__global__") == 0.0

    def test_post_handles_openai_usage_format(self):
        policy = _policy(limit=100.0)
        request = {"model": "gpt-4o", "messages": []}
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500)
        )
        policy.post(request, response)
        assert policy.get_spend("__global__") > 0


# ── Concurrent access ────────────────────────────────────────────────────────

class TestConcurrency:
    def test_concurrent_record_spend_local(self):
        tracker = DistributedSpendTracker(reset_period="monthly")
        num_threads = 50
        spend_per_thread = 1.0
        barrier = threading.Barrier(num_threads)

        def worker():
            barrier.wait()
            tracker.record_spend("concurrent_key", spend_per_thread)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = tracker.get_spend("concurrent_key")
        assert total == pytest.approx(num_threads * spend_per_thread)

    def test_concurrent_check_and_record(self):
        tracker = DistributedSpendTracker(reset_period="monthly")
        limit = 10.0
        allowed_count = 0
        lock = threading.Lock()
        barrier = threading.Barrier(20)

        def worker():
            nonlocal allowed_count
            barrier.wait()
            allowed, _ = tracker.check_budget("key", limit)
            if allowed:
                tracker.record_spend("key", 1.0)
                with lock:
                    allowed_count += 1

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert tracker.get_spend("key") <= limit + 1.0


# ── Redis client module ──────────────────────────────────────────────────────

class TestRedisClient:
    def test_not_available_without_env_var(self):
        from aiwarden.redis_client import RedisClient
        with patch.dict("os.environ", {}, clear=True):
            client = RedisClient()
            assert client.available is False
            assert client.conn is None

    def test_not_available_without_redis_package(self):
        from aiwarden.redis_client import RedisClient
        with patch.dict("os.environ", {"AIWARDEN_REDIS_URL": "redis://localhost:6379"}):
            with patch.dict("sys.modules", {"redis": None}):
                client = RedisClient()
                assert client.available is False

    def test_reset_clears_state(self):
        from aiwarden.redis_client import RedisClient
        client = RedisClient()
        client._initialized = True
        client._available = True
        client.reset()
        assert client._initialized is False
        assert client._available is False

    def test_mask_url_hides_password(self):
        from aiwarden.redis_client import _mask_url
        assert _mask_url("redis://:secret@host:6379/0") == "redis://***@host:6379/0"
        assert _mask_url("redis://user:pass@host:6379") == "redis://***@host:6379"

    def test_mask_url_no_password(self):
        from aiwarden.redis_client import _mask_url
        assert _mask_url("redis://localhost:6379") == "redis://localhost:6379"
