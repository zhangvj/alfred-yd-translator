"""端到端冒烟测试：mock 网络层后运行 yd.py 入口，验证 Alfred JSON 结构。"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

WORKFLOW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workflow")
sys.path.insert(0, os.path.abspath(WORKFLOW_DIR))

import yd  # noqa: E402  (导入 workflow/yd.py 入口)

FAKE_RESPONSE = {
    "errorCode": "0",
    "query": "api",
    "language": "en2zh-CHS",
    "translation": ["应用程序编程接口"],
    "basic": {
        "phonetic": "ˌeɪpiːˈaɪ",
        "us-phonetic": "ˌeɪpiːˈaɪ",
        "uk-phonetic": "ˌeɪpiːˈaɪ",
        "explains": ["n. 应用程序编程接口（Application Programming Interface）"],
    },
    "web": [{"key": "API", "value": ["应用程序接口"]}],
    "speakUrl": "https://dict.youdao.com/dictvoice?audio=api&type=2",
    "tSpeakUrl": "https://dict.youdao.com/dictvoice?audio=api&type=1",
}

ENV = {
    "yd_key": "test-key",
    "yd_secret": "test-secret",
    "yd_to": "zh-CHS",
    "yd_cn_to": "en",
    "yd_voice": "en",
}


def run_yd(argv, env=None, response=FAKE_RESPONSE):
    """以给定 argv 运行 yd.main，mock translate，返回 (exit_json, translate_call)。"""
    calls = {}

    def fake_translate(client_self, q, to, from_lang="auto"):
        calls["q"] = q
        calls["to"] = to
        # 真实 API 会在响应中回显 query
        return dict(response, query=q)

    buf = io.StringIO()
    with mock.patch.dict(os.environ, env or {}, clear=False):
        with mock.patch.object(yd.YoudaoClient, "translate", new=fake_translate):
            with redirect_stdout(buf):
                yd.main(argv)
    return json.loads(buf.getvalue()), calls


class TestSmoke(unittest.TestCase):
    def test_empty_query_hint(self):
        result, _ = run_yd([""])
        self.assertEqual(len(result["items"]), 1)
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("输入要翻译", result["items"][0]["title"])

    def test_missing_key_hint(self):
        result, _ = run_yd(["hello"], env={})
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("Key", result["items"][0]["title"])

    def test_untranslatable_hint(self):
        result, _ = run_yd(["!!!"], env=ENV)
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("无法翻译", result["items"][0]["title"])

    def test_translation_structure(self):
        result, calls = run_yd(["API"], env=ENV)
        self.assertEqual(calls["q"], "API")          # 全大写缩写保留原样
        self.assertEqual(calls["to"], "zh-CHS")
        items = result["items"]
        self.assertGreaterEqual(len(items), 3)
        first = items[0]
        self.assertEqual(first["arg"], "应用程序编程接口")
        self.assertEqual(first["text"]["copy"], "应用程序编程接口")
        self.assertIn("youdao.com/w/API", first["quicklookurl"])  # 网页预览用原词
        self.assertIn("cmd", first["mods"])
        self.assertIn("alt", first["mods"])
        self.assertIn("shift", first["mods"])
        self.assertEqual(first["mods"]["cmd"]["arg"], "API")   # Cmd 发音词 = 原词
        self.assertIn("https://", first["mods"]["alt"]["arg"])  # Alt 在线发音 = TTS URL
        self.assertIn("youdao.com/w/API", first["mods"]["shift"]["arg"])  # Shift 打开网页

    def test_chinese_to_english(self):
        result, calls = run_yd(["你好世界"], env=ENV)
        self.assertEqual(calls["q"], "你好世界")
        self.assertEqual(calls["to"], "en")

    def test_snake_case_normalized(self):
        _, calls = run_yd(["USER_NAME"], env=ENV)
        self.assertEqual(calls["q"], "USER NAME")

    def test_uk_voice_picks_tspeak(self):
        result, _ = run_yd(["hello"], env=dict(ENV, yd_voice="uk"))
        self.assertIn("英音", result["items"][0]["mods"]["alt"]["subtitle"])

    def test_en_query_speaks_original_word(self):
        # 英文查询：Cmd 发音应读用户输入的原词
        result, _ = run_yd(["hello"], env=ENV)
        self.assertEqual(result["items"][0]["mods"]["cmd"]["arg"], "hello")

    def test_cn_query_speaks_translation(self):
        # 中文查询：Cmd 发音应读英文译文
        result, _ = run_yd(["你好世界"], env=ENV)
        self.assertEqual(
            result["items"][0]["mods"]["cmd"]["arg"],
            "应用程序编程接口",
        )

    def test_setkey_persists_to_data_dir(self):
        # yd setkey 写入数据目录，且不经过翻译 API（环境变量不含 key，避免覆盖）
        cmd_env = {"yd_to": "zh-CHS", "yd_cn_to": "en", "yd_voice": "en", "yd_sign": "auto"}
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(cmd_env, YD_DATA_DIR=tmp)
            result, _ = run_yd(["setkey", "TESTKEY123"], env=env)
            self.assertIn("已保存", result["items"][0]["title"])
            with open(os.path.join(tmp, "config.json")) as f:
                saved = json.load(f)
            self.assertEqual(saved["yd_key"], "TESTKEY123")

    def test_config_reads_saved_key(self):
        cmd_env = {"yd_to": "zh-CHS", "yd_cn_to": "en", "yd_voice": "en", "yd_sign": "auto"}
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(cmd_env, YD_DATA_DIR=tmp)
            run_yd(["setkey", "TESTKEY123"], env=env)
            run_yd(["setsecret", "TESTSECRET"], env=env)
            result, _ = run_yd(["config"], env=env)
            titles = " | ".join(
                it["title"] + " " + it.get("subtitle", "") for it in result["items"]
            )
            self.assertIn("TEST****23", titles)   # 掩码显示
            self.assertIn("数据文件(更新保留)", titles)

    def test_reset_clears_config(self):
        cmd_env = {"yd_to": "zh-CHS", "yd_cn_to": "en", "yd_voice": "en", "yd_sign": "auto"}
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(cmd_env, YD_DATA_DIR=tmp)
            run_yd(["setkey", "K"], env=env)
            result, _ = run_yd(["reset"], env=env)
            self.assertIn("已清除", result["items"][0]["title"])
            self.assertFalse(os.path.exists(os.path.join(tmp, "config.json")))

    def test_version_command(self):
        result, _ = run_yd(["version"], env=ENV)
        self.assertIn("yd-translator v", result["items"][0]["title"])


if __name__ == "__main__":
    unittest.main()
