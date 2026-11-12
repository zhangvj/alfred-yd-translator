#!/usr/bin/env python3
"""yd-translator Script Filter 入口。

用法: yd.py "<query>"
从 Alfred 工作流配置的环境变量读取 yd_key/yd_secret 等，输出 Alfred JSON。
也可在终端直接调试: python3 workflow/yd.py "API"
"""
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import __version__                                  # noqa: E402
from lib.config import (                                     # noqa: E402
    Config, config_path, clear_config, get_data_dir, save_config,
)
from lib.detect import has_cjk, target_lang                  # noqa: E402
from lib.guard import RateLimiter, ResponseCache, cache_key  # noqa: E402
from lib.normalizer import normalize                         # noqa: E402
from lib.output import Item, error_item, output              # noqa: E402
from lib.pinyin import is_composition, is_pinyin_suspect      # noqa: E402
from lib.protect import (                                    # noqa: E402
    mask_han, placeholders_intact, should_mask, unmask_text,
)
from lib.tts import fallback_speak_url, pick_speak_url        # noqa: E402
from lib.youdao import (                                    # noqa: E402
    API_QUERY_MAX_CHARS, YoudaoClient, YoudaoError, extract_rows,
    is_passthrough, response_lang_pair,
)

# 限速等待超过该秒数时不再 sleep，直接提示用户稍候（避免卡住 Alfred 界面）
MAX_SLEEP = 2.0


def _mask(value):
    """掩码显示敏感值，避免回显完整 key/secret。"""
    if not value:
        return "(空)"
    if len(value) <= 6:
        return value[0] + "****"
    return value[:4] + "****" + value[-2:]


def _stdout_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def build_items(cfg, orig, norm, data):
    """把 API 响应组装为 Alfred 结果行。"""
    items = []
    quicklook = "https://www.youdao.com/w/" + urllib.parse.quote(orig, safe="")
    tts_url, tts_label = pick_speak_url(data, voice=cfg.voice)
    subtitle = orig if orig == norm else "{} → {}".format(orig, norm)

    for row in extract_rows(data):
        # 发音词：英文查询发音原词（hello）；中文查询发音英文译文/释义
        speak_word = row["speak_word"]
        if has_cjk(orig) and row["kind"] in ("translation", "explain"):
            speak_word = row["title"]
        item = (
            Item()
            .title(row["title"])
            .subtitle(subtitle if row["kind"] == "translation" else row["subtitle"])
            .arg(row["title"])
            .text(copy=row["title"], largetype=row["title"])
            .quicklookurl(quicklook)
            .icon("assets/translate.png")
            # mods 的 arg 直接交给工作流画布上的独立动作节点：
            #   Enter → 复制到剪贴板（arg=译文）；Cmd → 本地发音（arg=词）；
            #   Alt → 在线发音（arg=TTS URL）；Shift → 打开有道网页（arg=网页 URL）
            .mod("cmd", "🔊 本地发音 {}".format(speak_word), speak_word)
            .mod("alt", "📣 有道{}发音 {}".format(tts_label, speak_word), tts_url)
            .mod("shift", "🌐 打开有道网页 {}".format(orig), quicklook)
        )
        items.append(item.result())
    return items


def passthrough_item(data):
    """回显响应（源语言 == 目标语言）的可操作提示。"""
    src, dst = response_lang_pair(data)
    pair = "{} → {}".format(src, dst) if src and dst else "同一语种"
    return error_item(
        "⚠️ 未能翻译该文本（源语言与目标语言相同）",
        "有道判定为 {}，原样返回；可在工作流 [X] 面板调整 yd_to / yd_cn_to，或换个写法".format(pair),
    )


def render(cfg, orig, norm, data):
    """把 API 响应渲染成 Alfred JSON（含回显提示与空结果兜底）。"""
    if is_passthrough(data):
        return output([passthrough_item(data)])
    items = build_items(cfg, orig, norm, data)
    if not items:
        return output([error_item(
            "未获取到翻译结果",
            "有道未返回可展示的内容（无译文/释义），可稍后重试或换个说法",
        )])
    return output(items)


def alternate_target(to, cfg):
    """换一个目标语言（在 yd_to / yd_cn_to 中取与当前不同的那个）。

    两者配置相同时返回空串，调用方据此跳过重试，避免死循环。
    """
    for candidate in (cfg.to, cfg.cn_to):
        if candidate and candidate != to:
            return candidate
    return ""


def api_text_for(text, to):
    """按目标语言决定发送给 API 的文本：中文目标下先保护已有中文片段。

    返回 (发送文本, 被保护的片段列表)；不需要保护时原样返回，列表为空。
    """
    if should_mask(text, to):
        return mask_han(text)
    return text, []


def _first_translation(data):
    """响应里的首条译文（无则空串）。"""
    translation = (data or {}).get("translation") or []
    if translation and isinstance(translation[0], str):
        return translation[0]
    return ""


def restore_masked(data, original, runs):
    """把响应里被打码的中文片段还原（译文、query 回显、发音 URL）。"""
    if not runs:
        return data
    data = dict(data)
    translation = data.get("translation")
    if isinstance(translation, list):
        data["translation"] = [
            unmask_text(item, runs) if isinstance(item, str) else item
            for item in translation
        ]
    # 有道会回显 query；改回用户原文，避免字幕里出现占位符
    if isinstance(data.get("query"), str):
        data["query"] = original
    # 发音 URL 若带标记，用还原后的词重建（避免 %5B%5BC0%5D%5D 这类编码）
    word = _first_translation(data) or original
    for field, voice in (("speakUrl", "en"), ("tSpeakUrl", "uk")):
        url = data.get(field)
        if isinstance(url, str) and "[[C" in url:
            data[field] = fallback_speak_url(word, voice)
    return data


def _wait_or_skip(limiter):
    """过限速闸门：可等则 sleep 并返回 True；不可等返回 False（本次跳过）。"""
    action, wait = limiter.wait_time()
    if action == RateLimiter.BLOCKED or (action == RateLimiter.WAIT and wait > MAX_SLEEP):
        return False
    if action == RateLimiter.WAIT:
        time.sleep(wait)
    return True


def translate_once(client, text, to, limiter):
    """发起一次真实翻译（带中文片段保护），返回已还原的响应 dict。

    若模型吞掉占位符（实测未发生），降级为未掩码请求以保证内容完整——宁可
    退化成「公司→五星」也不丢字；降级请求受限速闸门约束，闸门不放行则沿用
    掩码结果。YoudaoError 由调用方处理。
    """
    api_text, runs = api_text_for(text, to)
    limiter.record()
    raw = client.translate(api_text, to)
    data = restore_masked(raw, text, runs)
    if runs and not placeholders_intact(_first_translation(raw), runs) and _wait_or_skip(limiter):
        limiter.record()
        data = client.translate(text, to)
    return data


def rate_limited_item(limiter, cooldown):
    """411 冷却提示行（进入指数冷却）。"""
    seconds = limiter.set_cooldown(cooldown)
    return error_item(
        "👻 访问频率受限（411）",
        "已进入 {} 秒冷却期（连续 411 会指数延长），期间不再调用 API".format(int(seconds)),
    )


def handle_command(cmd, rest, cfg):
    """处理管理命令（setkey / setsecret / config / reset），返回是否已处理。"""
    if cmd == "setkey" or cmd == "setsecret":
        if not rest:
            print(output([error_item(
                "用法", "yd {} <值>（例如: yd {} 55033dc0…）".format(cmd, cmd),
            )]))
            return True
        var = "yd_key" if cmd == "setkey" else "yd_secret"
        path = save_config({var: rest})
        print(output([error_item(
            "✅ 已保存 {}（不再显示）".format(_mask(rest)),
            "已写入: {}（更新工作流时自动保留）".format(path),
        )]))
        return True

    if cmd == "config":
        items = [
            Item().title("yd_key: {}".format(_mask(cfg.key)))
                   .subtitle("来源: {}".format(cfg.key_source)).valid(False),
            Item().title("yd_secret: {}".format(_mask(cfg.secret)))
                   .subtitle("来源: {}".format(
                       "环境变量" if cfg.secret and os.environ.get("yd_secret") else
                       ("数据文件(更新保留)" if cfg.secret else "未配置"))).valid(False),
            Item().title("yd_to: {} / yd_cn_to: {}".format(cfg.to, cfg.cn_to))
                   .subtitle("目标语言（可去工作流 [X] 面板修改）").valid(False),
            Item().title("yd_voice: {} / yd_sign: {}".format(cfg.voice, cfg.sign))
                   .subtitle("发音音色 / 签名方式").valid(False),
            Item().title(
                "防刷量: 组词检测{} · 链式合并 {:.1f}s · 限速 {:.1f}s".format(
                    "开" if cfg.pinyin_guard else "关",
                    cfg.chain_window, cfg.min_interval,
                ))
                   .subtitle("缓存 {:.0f}s · 窗口上限 {}/{}s · 411冷却基准 {}s · 最短 {} 字符".format(
                       cfg.cache_ttl, int(cfg.max_per_window), int(cfg.rate_window),
                       int(cfg.cooldown), int(cfg.min_len))).valid(False),
            Item().title("数据目录: {}".format(config_path()))
                   .subtitle("更新工作流后 key/secret 依然在此保留").valid(False),
        ]
        print(output([i.result() for i in items]))
        return True

    if cmd == "version":
        print(output([error_item(
            "yd-translator v{}".format(__version__),
            "MIT License · 版本来源: workflow/lib/__init__.py",
        )]))
        return True

    if cmd == "reset":
        cleared = clear_config()
        print(output([error_item(
            "✅ 已清除数据目录中的 key/secret" if cleared else "数据目录中无已保存的配置",
            "可用 yd setkey / yd setsecret 重新设置",
        )]))
        return True

    return False


def main(argv=None):
    _stdout_utf8()
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    query = " ".join(argv).strip()
    cfg = Config()

    if not query:
        print(output([error_item(
            "输入要翻译的内容",
            "例如: yd API / yd 你好世界 / yd user_name",
        )]))
        return

    cmd, _, rest = query.partition(" ")
    if cmd in ("setkey", "setsecret", "config", "reset", "version"):
        handle_command(cmd, rest.strip(), cfg)
        return

    if not cfg.configured:
        print(output([error_item(
            "❌ 未配置有道 API Key",
            "请在工作流配置中填写 yd_key 与 yd_secret，并确保网络可访问 openapi.youdao.com",
        )]))
        return

    # ---- 防刷量守卫（详见 lib/guard.py / lib/pinyin.py）----
    # 先建对象：下面的"逃逸口"判定需要读取上一次查询（链式合并）
    data_dir = get_data_dir()
    cache = ResponseCache(data_dir, ttl=cfg.cache_ttl)
    limiter = RateLimiter(
        data_dir,
        min_interval=cfg.min_interval,
        window=cfg.rate_window,
        max_per_window=cfg.max_per_window,
    )
    now = time.time()

    # 逃逸口：末尾 "." / "。" 表示"确要立即翻译"（如拼音 `nihao.`），跳过延迟判定。
    # 只有句点确实用于绕开"输入中"判定时才剥掉；普通句末标点（`Hello world.`）
    # 原样保留，避免翻译时丢失标点。
    force = False
    core = query.rstrip(".。")
    if core.strip() and core != query:
        candidate = core.strip()
        suspected = cfg.pinyin_guard and (
            is_composition(candidate) or is_pinyin_suspect(candidate))
        last_query, _ = limiter.last_visit()
        if (suspected
                or last_query == candidate
                or limiter.chain_related(candidate, now, cfg.chain_window)):
            query = candidate
            force = True

    norm = normalize(query)
    if not norm:
        print(output([error_item("无法翻译该内容", "未识别到可翻译的文字")]))
        return

    to = target_lang(norm, to=cfg.to, cn_to=cfg.cn_to)
    key = cache_key(norm, to)

    # 1) 411 指数冷却期：完全不调用 API，有缓存则附带缓存结果
    remaining = limiter.cooldown_remaining(now)
    if remaining > 0:
        items = [error_item(
            "⛔ 访问频率受限中",
            "约 {} 秒后自动恢复，期间不再调用 API".format(int(remaining) + 1),
        )]
        cached = cache.get(key, now)
        # 回显式缓存不贴到"冷却中"提示下面（它等于没翻译）
        if cached is not None and not is_passthrough(cached):
            items += build_items(cfg, query, norm, cached)
        print(output(items))
        return

    # 2) 输入演进 / 疑似组词 → 延后翻译（Alfred rerun 自动重跑；继续输入则
    #    被新查询取代，中间态零调用；停止输入 1 秒后回访翻译）
    #    - 链式合并：与上一查询呈前缀扩展/截断（你→你在→你在干什么、退格删字）
    #    - 疑似拼音组词：裸拼音 da/nihao/nih、混合态 你好shijie
    stable = limiter.stable_visit(query, now, cfg.defer_delay)
    suspect = cfg.pinyin_guard and (is_composition(query) or is_pinyin_suspect(query))
    if not stable and not force and (
            limiter.chain_related(query, now, cfg.chain_window) or suspect):
        limiter.note_query(query, now)
        print(output([error_item(
            "⌨️ 正在等待输入完成···",
            "停止输入 {:.1g} 秒后自动翻译；末尾加 . 可立即翻译".format(cfg.defer_delay),
        )], rerun=cfg.defer_delay))
        return
    limiter.note_query(query, now)

    # 3) 缓存命中：直接重建结果，零调用
    cached = cache.get(key, now)
    if cached is not None:
        print(render(cfg, query, norm, cached))
        return

    # 4) 单次上限 5000 字符：提前拦截，避免注定失败的一次调用
    if len(norm) > API_QUERY_MAX_CHARS:
        print(output([error_item(
            "文本太长（{} 字符）".format(len(norm)),
            "有道单次翻译上限 {} 字符；请拆成多段再分别翻译".format(API_QUERY_MAX_CHARS),
        )]))
        return

    # 5) 最短长度：单个 ASCII 字符查询基本无意义，纯耗免费额度
    if cfg.min_len > 0 and len(norm) < cfg.min_len and not has_cjk(norm):
        print(output([error_item(
            "再多输入几个字符",
            "过短查询也消耗额度，至少 {} 个字符（yd_min_len 可调）".format(int(cfg.min_len)),
        )]))
        return

    # 6) 限速：距上次调用过近则补足间隔；窗口内超限则放弃本次请求
    action, wait = limiter.wait_time()
    if action == RateLimiter.BLOCKED or (action == RateLimiter.WAIT and wait > MAX_SLEEP):
        print(output([error_item(
            "🚦 请求太频繁",
            "短时调用已达上限，约 {} 秒后再试".format(int(wait) + 1 if wait > 0 else int(cfg.rate_window)),
        )]))
        return
    if action == RateLimiter.WAIT:
        time.sleep(wait)

    client = YoudaoClient(cfg.key, cfg.secret, sign_mode=cfg.sign)
    try:
        data = translate_once(client, norm, to, limiter)
    except YoudaoError as exc:
        if str(exc.code) == "411":
            print(output([rate_limited_item(limiter, cfg.cooldown)]))
        elif str(exc.code) == "-1":
            print(output([error_item("🌐 网络请求失败", exc.message)]))
        else:
            print(output([error_item("👻 翻译出错啦", exc.message)]))
        return

    # 回显兜底：源语言 == 目标语言（如 en2en）等于没翻译，换另一个目标语言重试一次
    alt = alternate_target(to, cfg)
    if is_passthrough(data) and alt and _wait_or_skip(limiter):
        retry_error = None
        try:
            alt_data = translate_once(client, norm, alt, limiter)
        except YoudaoError as exc:
            retry_error = exc
            alt_data = None
            if str(exc.code) == "411":
                limiter.set_cooldown(cfg.cooldown)
        if alt_data is not None and not is_passthrough(alt_data):
            data, to = alt_data, alt
        if retry_error is not None and str(retry_error.code) == "411":
            print(output([rate_limited_item(limiter, cfg.cooldown)]))
            return

    limiter.note_success()
    # 签名回退记忆：auto 模式下 v3 被拒(202)、v1 成功 → 持久化有效签名方式，
    # 此后每次查询单请求直达（省掉注定失败的 v3 请求，请求量减半）
    if cfg.sign == "auto" and client.effective_sign == "v1":
        save_config({"yd_sign": "v1"})

    # 缓存键按「重试前」计算的目标语言，保证后续同查询稳定命中
    cache.put(key, data)
    print(render(cfg, query, norm, data))


if __name__ == "__main__":
    main()
