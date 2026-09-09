"""guard 模块单元测试：响应缓存（TTL/容量/容错）与限速器（间隔/窗口/冷却）。

时间全部显式注入（now 参数），不依赖真实时钟。
"""
import os
import tempfile
import unittest

from workflow.lib.guard import (
    ResponseCache,
    RateLimiter,
    cache_key,
)

DATA = {"errorCode": "0", "translation": ["测试"]}


class TestCacheKey(unittest.TestCase):
    def test_differs_by_query_and_target(self):
        self.assertEqual(cache_key("api", "zh-CHS"), cache_key("api", "zh-CHS"))
        self.assertNotEqual(cache_key("api", "zh-CHS"), cache_key("API", "zh-CHS"))
        self.assertNotEqual(cache_key("api", "zh-CHS"), cache_key("api", "en"))

    def test_sha1_hex(self):
        self.assertEqual(len(cache_key("x", "en")), 40)


class TestResponseCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def test_miss_then_hit(self):
        cache = ResponseCache(self.dir)
        self.assertIsNone(cache.get("k"))
        cache.put("k", DATA, now=100.0)
        self.assertEqual(cache.get("k", now=100.5), DATA)

    def test_ttl_expiry(self):
        cache = ResponseCache(self.dir, ttl=600)
        cache.put("k", DATA, now=100.0)
        self.assertEqual(cache.get("k", now=699.9), DATA)
        self.assertIsNone(cache.get("k", now=700.1))  # 100 + 600 = 700 过期

    def test_corrupt_file_tolerated(self):
        path = os.path.join(self.dir, "cache.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        cache = ResponseCache(self.dir)
        self.assertIsNone(cache.get("k"))
        cache.put("k", DATA)          # 损坏后仍可写入并恢复
        self.assertEqual(cache.get("k"), DATA)

    def test_max_entries_evicts_oldest(self):
        cache = ResponseCache(self.dir, max_entries=2)
        cache.put("a", {"v": 1}, now=1.0)
        cache.put("b", {"v": 2}, now=2.0)
        cache.put("c", {"v": 3}, now=3.0)   # 淘汰最旧的 a
        self.assertIsNone(cache.get("a", now=3.0))
        self.assertEqual(cache.get("b", now=3.0), {"v": 2})
        self.assertEqual(cache.get("c", now=3.0), {"v": 3})
        self.assertEqual(len(cache), 2)

    def test_expired_entries_pruned_on_put(self):
        cache = ResponseCache(self.dir, ttl=100)
        cache.put("old", {"v": 0}, now=0.0)
        cache.put("new", {"v": 1}, now=1000.0)  # old 已过期，被惰性清理
        self.assertEqual(len(cache), 1)


class TestRateLimiter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def _limiter(self, **kw):
        return RateLimiter(self.dir, **kw)

    def test_ok_when_empty(self):
        action, wait = self._limiter().wait_time(now=1000.0)
        self.assertEqual(action, RateLimiter.OK)
        self.assertEqual(wait, 0.0)

    def test_min_interval_wait(self):
        limiter = self._limiter(min_interval=1.0)
        limiter.record(now=1000.0)
        action, wait = limiter.wait_time(now=1000.4)
        self.assertEqual(action, RateLimiter.WAIT)
        self.assertAlmostEqual(wait, 0.6)
        action, _ = limiter.wait_time(now=1001.0)
        self.assertEqual(action, RateLimiter.OK)

    def test_window_blocked_until_oldest_slides(self):
        limiter = self._limiter(min_interval=0.0, window=10.0, max_per_window=2)
        limiter.record(now=100.0)
        limiter.record(now=102.0)
        action, wait = limiter.wait_time(now=103.0)
        self.assertEqual(action, RateLimiter.BLOCKED)
        self.assertAlmostEqual(wait, 7.0)   # 100 + 10 - 103
        # 窗口滑动后放行
        action, _ = limiter.wait_time(now=110.5)
        self.assertEqual(action, RateLimiter.OK)

    def test_state_persists_across_instances(self):
        self._limiter(min_interval=1.0).record(now=500.0)
        action, wait = self._limiter(min_interval=1.0).wait_time(now=500.5)
        self.assertEqual(action, RateLimiter.WAIT)   # 新进程读取同一 state.json
        self.assertAlmostEqual(wait, 0.5)

    def test_corrupt_state_tolerated(self):
        path = os.path.join(self.dir, "state.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("oops")
        action, wait = self._limiter().wait_time(now=1.0)
        self.assertEqual(action, RateLimiter.OK)

    def test_cooldown(self):
        limiter = self._limiter()
        self.assertLessEqual(limiter.cooldown_remaining(now=100.0), 0)
        limiter.set_cooldown(60, now=100.0)
        self.assertAlmostEqual(limiter.cooldown_remaining(now=130.0), 30.0)
        self.assertLessEqual(limiter.cooldown_remaining(now=160.1), 0)
        # 冷却设置保留既有调用时间戳（结束后限速仍生效）
        limiter.record(now=100.0)
        limiter.set_cooldown(60, now=100.0)
        other = self._limiter(min_interval=1.0)
        self.assertEqual(other.wait_time(now=200.0)[0], RateLimiter.OK)


class TestQueryChain(unittest.TestCase):
    """输入演进检测：逐词上屏 / 退格编辑 / rerun 回访。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def test_note_and_last_visit(self):
        limiter = RateLimiter(self.dir)
        self.assertEqual(limiter.last_visit(), ("", 0.0))
        limiter.note_query("你", now=1000.0)
        self.assertEqual(limiter.last_visit(), ("你", 1000.0))

    def test_chain_related_extension_and_truncation(self):
        limiter = RateLimiter(self.dir)
        limiter.note_query("你", now=1000.0)
        self.assertTrue(limiter.chain_related("你在", now=1001.0))        # 前缀扩展
        limiter.note_query("你在干什么", now=1002.0)
        self.assertTrue(limiter.chain_related("你在", now=1003.0))        # 截断（退格）
        self.assertFalse(limiter.chain_related("你喜欢", now=1003.0))     # 非前缀关系

    def test_chain_window_expiry(self):
        limiter = RateLimiter(self.dir)
        limiter.note_query("你在", now=1000.0)
        self.assertFalse(limiter.chain_related("你在干什么", now=1004.0))  # 超过 3.5s

    def test_chain_same_query_not_related(self):
        limiter = RateLimiter(self.dir)
        limiter.note_query("你在", now=1000.0)
        self.assertFalse(limiter.chain_related("你在", now=1001.0))

    def test_stable_visit_with_jitter_margin(self):
        limiter = RateLimiter(self.dir)
        limiter.note_query("nihao", now=1000.0)
        self.assertFalse(limiter.stable_visit("nihao", now=1000.5, delay=1.0))
        self.assertTrue(limiter.stable_visit("nihao", now=1000.9, delay=1.0))  # 0.8 余量
        self.assertFalse(limiter.stable_visit("nihao2", now=1000.9, delay=1.0))

    def test_note_preserves_rate_timestamps(self):
        limiter = RateLimiter(self.dir)
        limiter.record(now=1000.0)
        limiter.note_query("你在", now=1000.5)
        action, _ = limiter.wait_time(now=1000.8)   # 调用时间戳未被覆盖
        self.assertEqual(action, RateLimiter.WAIT)
        self.assertEqual(limiter.last_visit(), ("你在", 1000.5))


class TestExponentialCooldown(unittest.TestCase):
    """411 指数退避：60 → 120 → 240 → 480 → 960（封顶），成功后复位。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def test_doubles_each_411(self):
        limiter = RateLimiter(self.dir)
        self.assertEqual(limiter.set_cooldown(60, now=1000), 60)
        self.assertAlmostEqual(limiter.cooldown_remaining(now=1000), 60)
        self.assertEqual(limiter.set_cooldown(60, now=1001), 120)
        self.assertEqual(limiter.set_cooldown(60, now=1002), 240)
        self.assertEqual(limiter.set_cooldown(60, now=1003), 480)
        self.assertEqual(limiter.set_cooldown(60, now=1004), 960)
        self.assertEqual(limiter.set_cooldown(60, now=1005), 960)   # 封顶

    def test_success_resets(self):
        limiter = RateLimiter(self.dir)
        limiter.set_cooldown(60, now=1000)
        limiter.set_cooldown(60, now=1001)
        limiter.note_success(now=1002)
        self.assertEqual(limiter.set_cooldown(60, now=1003), 60)    # 从基准重新开始

    def test_other_state_preserved(self):
        limiter = RateLimiter(self.dir)
        limiter.record(now=1000.0)
        limiter.note_query("你在", now=1000.5)
        limiter.set_cooldown(60, now=1001)
        self.assertEqual(limiter.last_visit(), ("你在", 1000.5))
        action, _ = limiter.wait_time(now=1000.9)
        self.assertEqual(action, RateLimiter.WAIT)   # 时间戳与链路状态均保留


if __name__ == "__main__":
    unittest.main()
