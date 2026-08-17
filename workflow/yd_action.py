#!/usr/bin/env python3
"""yd-translator 动作分发器：Script Filter 的唯一下游。

Script Filter 输出的 arg 通过 mods 携带动作前缀，这里按前缀分支：
    speak:local:<word>   -> macOS 本地 say 发音（不阻塞）
    speak:tts:<word>     -> 打开有道发音 URL（美音/英音由 yd_voice 决定）
    其他                 -> 复制到剪贴板（Enter 默认行为）
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import Config  # noqa: E402


def _local_speak(word):
    """本地 say 发音，后台执行不阻塞 Alfred。"""
    subprocess.Popen(["say", word], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _open_url(url):
    subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def dispatch(arg, cfg):
    """按 arg 前缀执行对应动作。"""
    if arg.startswith("speak:local:"):
        _local_speak(arg[len("speak:local:"):])
    elif arg.startswith("speak:tts:"):
        # arg 中携带的是 API 返回的准确发音 URL（speakUrl / tSpeakUrl）
        _open_url(arg[len("speak:tts:"):])
    else:
        subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE).communicate(arg.encode("utf-8"))


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    dispatch(arg, Config())


if __name__ == "__main__":
    main()
