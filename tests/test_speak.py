"""yd_speak 本地发音测试：后台 say 发音，不阻塞（mock subprocess）。"""
import os
import sys
import unittest
from unittest import mock

WORKFLOW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workflow")
sys.path.insert(0, os.path.abspath(WORKFLOW_DIR))

import yd_speak  # noqa: E402


class TestSpeak(unittest.TestCase):
    def test_speak_word_via_say(self):
        with mock.patch.object(yd_speak.subprocess, "Popen") as popen:
            yd_speak.speak("hello")
        args = popen.call_args[0][0]
        # "--" 终止选项解析，避免以 "-" 开头的词被 say 当成参数
        self.assertEqual(args, ["say", "--", "hello"])
        # 非阻塞：不等待 say 结束（communicate 不应被调用）
        self.assertEqual(popen.return_value.communicate.call_count, 0)

    def test_leading_dash_word_not_treated_as_option(self):
        with mock.patch.object(yd_speak.subprocess, "Popen") as popen:
            yd_speak.speak("-n")
        self.assertEqual(popen.call_args[0][0], ["say", "--", "-n"])

    def test_empty_word_does_not_call_say(self):
        with mock.patch.object(yd_speak.subprocess, "Popen") as popen:
            yd_speak.speak("")
        self.assertEqual(popen.call_count, 0)

    def test_main_reads_argv(self):
        with mock.patch.object(yd_speak, "speak") as speak, \
             mock.patch.object(yd_speak.sys, "argv", ["yd_speak.py", "world"]):
            yd_speak.main()
        speak.assert_called_once_with("world")

    def test_main_empty_argv_speaks_empty(self):
        with mock.patch.object(yd_speak, "speak") as speak, \
             mock.patch.object(yd_speak.sys, "argv", ["yd_speak.py"]):
            yd_speak.main()
        speak.assert_called_once_with("")


if __name__ == "__main__":
    unittest.main()
