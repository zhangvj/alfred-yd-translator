"""防刷量守卫：响应缓存 + 请求限速 + 输入演进检测 + 411 指数冷却。

状态持久化在 Alfred 工作流数据目录（跨进程生效——Alfred 每次防抖触发都是
新进程，内存态无效）：
    cache.json  查询 -> API 响应缓存（TTL + 容量上限，只存成功响应）
    state.json  最近 API 调用时间戳（滑动窗口限速）+ 上一次查询及时间
                （逐词上屏链式合并用）+ 连续 411 计数（指数退避）

文件读取沿用 config.load_saved 的容错模式（缺失/损坏返回空），
写入用同目录临时文件 + os.replace 原子替换，避免并发写坏。
时间一律由调用方注入（now 参数）以便测试。
"""
import hashlib
import json
import os
import tempfile
import time

CACHE_FILENAME = "cache.json"
STATE_FILENAME = "state.json"

# 默认参数（config.py 会用环境变量覆盖这些值）
DEFAULT_TTL = 600.0            # 缓存有效期（秒）
DEFAULT_MAX_ENTRIES = 200      # 缓存条目上限
DEFAULT_MIN_INTERVAL = 1.0     # 两次真实 API 调用的最小间隔（秒）
DEFAULT_WINDOW = 60.0          # 滑动窗口长度（秒）
DEFAULT_MAX_PER_WINDOW = 30    # 窗口内最大调用次数
DEFAULT_COOLDOWN = 60.0        # 411 首次冷却基准（秒），指数退避 60→120→…→960
DEFAULT_DEFER_DELAY = 1.0      # 疑似输入中：延后多少秒重跑翻译（Alfred rerun）
DEFAULT_CHAIN_WINDOW = 3.5     # 逐词上屏链式合并的判定窗口（秒）


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_json(path, data):
    """原子写入：同目录临时文件 + os.replace。"""
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except (OSError, NameError):
            pass


def cache_key(norm, to):
    """缓存键：规范化查询 + 目标语言（同一查询中↔英结果不同）。"""
    return hashlib.sha1("{}\x00{}".format(norm, to).encode("utf-8")).hexdigest()


class ResponseCache:
    """API 响应缓存：只缓存成功响应，TTL 过期 + 容量上限时淘汰最旧。"""

    def __init__(self, data_dir, ttl=DEFAULT_TTL, max_entries=DEFAULT_MAX_ENTRIES):
        self.path = os.path.join(data_dir, CACHE_FILENAME)
        self.ttl = ttl
        self.max_entries = max_entries

    def _entries(self):
        entries = _load_json(self.path).get("entries")
        return entries if isinstance(entries, dict) else {}

    def get(self, key, now=None):
        """命中返回缓存的 API 响应 dict；未命中/过期返回 None。"""
        now = time.time() if now is None else now
        entry = self._entries().get(key)
        if not isinstance(entry, dict):
            return None
        if now - entry.get("ts", 0) > self.ttl:
            return None
        return entry.get("data")

    def put(self, key, data, now=None):
        now = time.time() if now is None else now
        entries = self._entries()
        entries[key] = {"ts": now, "data": data}
        # 惰性清理过期条目
        entries = {
            k: v for k, v in entries.items()
            if isinstance(v, dict) and now - v.get("ts", 0) <= self.ttl
        }
        # 容量上限：按时间戳淘汰最旧
        if len(entries) > self.max_entries:
            ordered = sorted(entries.items(), key=lambda kv: kv[1].get("ts", 0))
            for stale, _ in ordered[: len(entries) - self.max_entries]:
                entries.pop(stale, None)
        _save_json(self.path, {"version": 1, "entries": entries})

    def __len__(self):
        return len(self._entries())


class RateLimiter:
    """滑动窗口 + 最小间隔的客户端限速器，兼做输入演进检测。

    wait_time() 返回 (action, seconds)：
        OK       直接放行；
        WAIT     距上次调用不足 min_interval，sleep(seconds) 后放行；
        BLOCKED  窗口内调用数已达上限，seconds 为最近一个空位出现前的等待，
                 调用方应放弃本次请求并给出提示。
    """

    OK, WAIT, BLOCKED = "ok", "wait", "blocked"

    def __init__(self, data_dir, min_interval=DEFAULT_MIN_INTERVAL,
                 window=DEFAULT_WINDOW, max_per_window=DEFAULT_MAX_PER_WINDOW):
        self.path = os.path.join(data_dir, STATE_FILENAME)
        self.min_interval = min_interval
        self.window = window
        self.max_per_window = max_per_window

    def _state(self):
        data = _load_json(self.path)
        raw = data.get("timestamps")
        ts = [t for t in raw if isinstance(t, (int, float))] if isinstance(raw, list) else []
        try:
            cooldown_until = float(data.get("cooldown_until") or 0)
        except (TypeError, ValueError):
            cooldown_until = 0.0
        last_query = data.get("last_query")
        last_query = last_query if isinstance(last_query, str) else ""
        try:
            last_query_ts = float(data.get("last_query_ts") or 0)
        except (TypeError, ValueError):
            last_query_ts = 0.0
        try:
            consecutive_411 = int(data.get("consecutive_411") or 0)
        except (TypeError, ValueError):
            consecutive_411 = 0
        return ts, cooldown_until, last_query, last_query_ts, consecutive_411

    def _save(self, timestamps, cooldown_until,
              last_query="", last_query_ts=0.0, consecutive_411=0):
        _save_json(self.path, {
            "version": 1,
            "timestamps": timestamps,
            "cooldown_until": cooldown_until,
            "last_query": last_query,
            "last_query_ts": last_query_ts,
            "consecutive_411": consecutive_411,
        })

    @staticmethod
    def _prune(timestamps, now, window):
        return [t for t in timestamps if now - t < window]

    # ---- 限速 ----

    def wait_time(self, now=None):
        now = time.time() if now is None else now
        ts = self._prune(self._state()[0], now, self.window)
        if len(ts) >= self.max_per_window:
            return self.BLOCKED, max(ts[0] + self.window - now, 0.0)
        if ts and now - ts[-1] < self.min_interval:
            return self.WAIT, ts[-1] + self.min_interval - now
        return self.OK, 0.0

    def record(self, now=None):
        """记录一次真实 API 调用（在发起请求时调用）。"""
        now = time.time() if now is None else now
        ts, cooldown_until, last_query, last_query_ts, n411 = self._state()
        ts = self._prune(ts, now, self.window)
        ts.append(now)
        self._save(ts, cooldown_until, last_query, last_query_ts, n411)

    # ---- 输入演进检测（逐词上屏 / 退格编辑 / rerun 回访）----

    def last_visit(self):
        """返回上一次记录的 (查询, 时间)；无记录返回 ("", 0.0)。"""
        _, _, last_query, last_query_ts, _ = self._state()
        return last_query, last_query_ts

    def note_query(self, q, now=None):
        """记录本次访问的查询（调用方需先做 stable/chain 判定再记录）。"""
        now = time.time() if now is None else now
        ts, cooldown_until, _, _, n411 = self._state()
        self._save(self._prune(ts, now, self.window), cooldown_until, q, now, n411)

    def stable_visit(self, q, now=None, delay=DEFAULT_DEFER_DELAY):
        """rerun 回访判定：同一查询、距上次记录 >= 0.8*delay（含调度抖动余量）。"""
        now = time.time() if now is None else now
        _, _, last_query, last_query_ts, _ = self._state()
        return bool(last_query) and q == last_query and now - last_query_ts >= delay * 0.8

    def chain_related(self, q, now=None, window=DEFAULT_CHAIN_WINDOW):
        """输入演进判定：与上一查询呈严格前缀扩展/截断关系且间隔 <= window。

        命中场景：逐词上屏（`你`→`你在`→`你在干什么`）、退格编辑
        （`...damk a`→`...damk`）。中间态不值得各打一次 API。
        """
        now = time.time() if now is None else now
        _, _, last_query, last_query_ts, _ = self._state()
        if not last_query or last_query == q or now - last_query_ts > window:
            return False
        return last_query.startswith(q) or q.startswith(last_query)

    # ---- 411 指数冷却 ----

    def cooldown_remaining(self, now=None):
        """冷却剩余秒数（<=0 表示不在冷却期）。"""
        now = time.time() if now is None else now
        return self._state()[1] - now

    def set_cooldown(self, base=DEFAULT_COOLDOWN, now=None):
        """收到 411 → 指数退避：base × 2^n（n=连续次数-1，封顶 16 倍=960s）。

        返回本次设置的冷却秒数。
        """
        now = time.time() if now is None else now
        ts, _, last_query, last_query_ts, n411 = self._state()
        n411 = min(n411 + 1, 5)
        seconds = base * (2 ** min(n411 - 1, 4))
        self._save(self._prune(ts, now, self.window),
                   now + seconds, last_query, last_query_ts, n411)
        return seconds

    def note_success(self, now=None):
        """翻译成功：连续 411 计数复位（下次 411 从基准冷却重新开始）。"""
        now = time.time() if now is None else now
        ts, cooldown_until, last_query, last_query_ts, n411 = self._state()
        if n411:
            self._save(self._prune(ts, now, self.window),
                       cooldown_until, last_query, last_query_ts, 0)
