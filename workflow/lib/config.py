"""工作流配置：环境变量 + 数据目录持久化（更新工作流时保留 key/secret）。

读取优先级（高 → 低）：
    1. 环境变量（Alfred 工作流配置界面 [X] 注入，如 yd_key / yd_secret）
    2. 数据目录中的 config.json（由 `yd setkey` / `yd setsecret` 写入，
       位于 Alfred Workflow Data 目录，卸载/更新工作流时均会保留）
    3. 默认值

环境变量:
    yd_key      有道开放平台应用 ID (appKey)
    yd_secret   有道开放平台应用密钥 (secret)
    yd_to       非中文文本的目标语言，默认 zh-CHS
    yd_cn_to    中文文本的目标语言，默认 en
    yd_voice    在线发音音色: en(美音 speakUrl) / uk(英音 tSpeakUrl)，默认 en
    yd_sign     签名方式: auto(默认, v3 失败自动回退 v1) / v3 / v1

    —— 防刷量守卫（guard.py），默认值即安全值 ——
    yd_pinyin_guard    拼音组词中间态检测开关: 1(默认) / 0
    yd_min_len         非 CJK 查询的最短长度，默认 2（0 关闭）
    yd_min_interval    两次真实 API 调用最小间隔（秒），默认 1.0
    yd_rate_window     限速滑动窗口长度（秒），默认 60
    yd_max_per_window  窗口内最大 API 调用次数，默认 30
    yd_cache_ttl       翻译结果缓存有效期（秒），默认 600
    yd_cooldown        收到 411 后的冷却基准秒数（指数退避 60→120→…→960）
    yd_defer_delay     疑似"输入中"时延后翻译的秒数（Alfred rerun），默认 1.0
    yd_chain_window    逐词上屏链式合并的判定窗口（秒），默认 3.5

    alfred_workflow_data   Alfred 注入的工作流数据目录（跨更新保留）
    YD_DATA_DIR            命令行调试/测试用覆盖目录（无 Alfred 时兜底）
"""
import json
import os
import tempfile

from .guard import (
    DEFAULT_CHAIN_WINDOW,
    DEFAULT_COOLDOWN,
    DEFAULT_DEFER_DELAY,
    DEFAULT_MAX_PER_WINDOW,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_TTL,
    DEFAULT_WINDOW,
)

CONFIG_FILENAME = "config.json"

# 兜底数据目录（仅在非 Alfred 环境且未设置 YD_DATA_DIR 时使用）
_FALLBACK_DATA_DIR = os.path.join(
    os.path.expanduser("~"),
    "Library", "Application Support", "Alfred",
    "Workflow Data", "com.zvj.yd-translator",
)


def get_data_dir(env=None):
    """返回工作流数据目录。"""
    env = os.environ if env is None else env
    data_dir = env.get("alfred_workflow_data") or env.get("YD_DATA_DIR")
    return data_dir or _FALLBACK_DATA_DIR


def config_path(env=None):
    return os.path.join(get_data_dir(env), CONFIG_FILENAME)


def load_saved(env=None):
    """读取数据目录 config.json；不存在或损坏返回空 dict。"""
    try:
        with open(config_path(env), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(updates, env=None):
    """合并写入 config.json（保留已有字段），权限 600。返回写入路径。

    原子写入：同目录临时文件 + os.replace，避免进程中断留下半截 JSON
    （config.json 里存着 key/secret，损坏会导致下次查询报"未配置"）。
    """
    env = os.environ if env is None else env
    data_dir = get_data_dir(env)
    os.makedirs(data_dir, exist_ok=True)
    data = load_saved(env)
    data.update(updates)
    path = os.path.join(data_dir, CONFIG_FILENAME)
    tmp = ""
    try:
        fd, tmp = tempfile.mkstemp(dir=data_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def clear_config(env=None):
    """删除数据目录 config.json；返回是否删除成功。"""
    try:
        os.remove(config_path(env))
        return True
    except OSError:
        return False


def _pick(env, saved, name, default=""):
    """优先级: 环境变量 > 数据文件 > 默认值。"""
    value = env.get(name)
    if value is None or value == "":
        value = saved.get(name)
    value = str(value or default).strip()
    return value or str(default)


def _pick_num(env, saved, name, default, minimum=None):
    """数值型配置：解析失败回退默认值，可设下限。统一返回 float。"""
    try:
        value = float(_pick(env, saved, name, str(default)))
    except (TypeError, ValueError):
        value = float(default)
    if minimum is not None:
        value = max(value, minimum)
    return value


class Config:
    """有道翻译工作流配置。"""

    def __init__(self, env=None):
        env = os.environ if env is None else env
        saved = load_saved(env)
        self.key = _pick(env, saved, "yd_key")
        self.secret = _pick(env, saved, "yd_secret")
        self.to = _pick(env, saved, "yd_to", "zh-CHS")
        self.cn_to = _pick(env, saved, "yd_cn_to", "en")
        self.voice = _pick(env, saved, "yd_voice", "en")
        self.sign = _pick(env, saved, "yd_sign", "auto")
        # 防刷量守卫参数（见 guard.py / README）
        self.pinyin_guard = _pick(
            env, saved, "yd_pinyin_guard", "1"
        ).lower() not in ("0", "false", "off", "no")
        self.min_len = _pick_num(env, saved, "yd_min_len", 2, minimum=0)
        self.min_interval = _pick_num(
            env, saved, "yd_min_interval", DEFAULT_MIN_INTERVAL, minimum=0)
        self.rate_window = _pick_num(
            env, saved, "yd_rate_window", DEFAULT_WINDOW, minimum=1)
        self.max_per_window = _pick_num(
            env, saved, "yd_max_per_window", DEFAULT_MAX_PER_WINDOW, minimum=0)
        self.cache_ttl = _pick_num(
            env, saved, "yd_cache_ttl", DEFAULT_TTL, minimum=0)
        self.cooldown = _pick_num(
            env, saved, "yd_cooldown", DEFAULT_COOLDOWN, minimum=0)
        self.defer_delay = _pick_num(
            env, saved, "yd_defer_delay", DEFAULT_DEFER_DELAY, minimum=0)
        self.chain_window = _pick_num(
            env, saved, "yd_chain_window", DEFAULT_CHAIN_WINDOW, minimum=0)
        self._saved = saved

    @property
    def configured(self):
        """是否已配置 key 与 secret。"""
        return bool(self.key and self.secret)

    @property
    def key_source(self):
        """key 的来源说明（环境变量 / 数据文件 / 未配置）。"""
        if self.key:
            env = os.environ
            return "环境变量" if env.get("yd_key") else "数据文件(更新保留)"
        return "未配置"
