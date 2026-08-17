"""yd_action 分发器测试：按 arg 前缀路由到正确的动作（mock subprocess）。"""
import os
import sys
import unittest
from unittest import mock

WORKFLOW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workflow")
sys.path.insert(0, os.path.abspath(WORKFLOW_DIR))

import yd_action  # noqa: E402


class _FakeConfig:
    voice = "en"


class TestDispatch(unittest.TestCase):
    def setUp(self):
        self.popen = mock.patch.object(yd_action.subprocess, "Popen").start()
        self.addCleanup(mock.patch.stopall)

    def test_local_speak(self):
        yd_action.dispatch("speak:local:hello", _FakeConfig())
        args = self.popen.call_args[0][0]
        self.assertEqual(args, ["say", "hello"])

    def test_tts_opens_url(self):
        yd_action.dispatch("speak:tts:https://example.com/audio.mp3", _FakeConfig())
        args = self.popen.call_args[0][0]
        self.assertEqual(args, ["open", "https://example.com/audio.mp3"])

    def test_plain_arg_copies_to_clipboard(self):
        yd_action.dispatch("译文内容", _FakeConfig())
        self.popen.assert_called_once()
        args = self.popen.call_args[0][0]
        self.assertEqual(args, ["pbcopy"])
        communicate = self.popen.return_value.communicate
        self.assertEqual(communicate.call_args[0][0], "译文内容".encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
