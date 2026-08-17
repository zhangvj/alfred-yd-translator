#!/usr/bin/env python3
"""yd-translator Script Filter 入口。

用法: yd.py "<query>"
从 Alfred 工作流配置的环境变量读取 yd_key/yd_secret 等，输出 Alfred JSON。
也可在终端直接调试: python3 workflow/yd.py "API"
"""
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import Config, config_path, clear_config, save_config  # noqa: E402
from lib.detect import has_cjk, target_lang                 # noqa: E402
from lib.normalizer import normalize               # noqa: E402
from lib.output import Item, error_item, output    # noqa: E402
from lib.tts import pick_speak_url                 # noqa: E402
from lib.youdao import YoudaoClient, YoudaoError, extract_rows  # noqa: E402


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
    quicklook = "https://www.youdao.com/w/" + urllib.parse.quote(orig)
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
            .mod("cmd", "🔊 本地发音 {}".format(speak_word), "speak:local:" + speak_word)
            .mod("alt", "📣 有道{}发音 {}".format(tts_label, speak_word),
                 "speak:tts:" + tts_url)
        )
        items.append(item.result())
    return items


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
            Item().title("数据目录: {}".format(config_path()))
                   .subtitle("更新工作流后 key/secret 依然在此保留").valid(False),
        ]
        print(output([i.result() for i in items]))
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
    if cmd in ("setkey", "setsecret", "config", "reset"):
        handle_command(cmd, rest.strip(), cfg)
        return

    if not cfg.configured:
        print(output([error_item(
            "❌ 未配置有道 API Key",
            "请在工作流配置中填写 yd_key 与 yd_secret，并确保网络可访问 openapi.youdao.com",
        )]))
        return

    norm = normalize(query)
    if not norm:
        print(output([error_item("无法翻译该内容", "未识别到可翻译的文字")]))
        return

    to = target_lang(norm, to=cfg.to, cn_to=cfg.cn_to)
    client = YoudaoClient(cfg.key, cfg.secret, sign_mode=cfg.sign)
    try:
        data = client.translate(norm, to)
    except YoudaoError as exc:
        print(output([error_item("👻 翻译出错啦", exc.message)]))
        return

    print(output(build_items(cfg, query, norm, data)))


if __name__ == "__main__":
    main()
