#!/usr/bin/env python3
"""本地 say 发音动作：独立的工作流画布节点。

Cmd+Enter 时 Alfred 把发音词作为参数传给本脚本，后台 say 发音，
不阻塞 Alfred（窗口保持打开）。"""
import subprocess
import sys


def speak(word):
    """后台执行 macOS say 发音，不阻塞。"""
    word = (word or "").strip()
    if not word:
        return
    # "--" 终止选项解析：否则以 "-" 开头的词（如 "-n"）会被 say 当作命令行参数
    subprocess.Popen(
        ["say", "--", word],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    word = sys.argv[1] if len(sys.argv) > 1 else ""
    speak(word)


if __name__ == "__main__":
    main()
