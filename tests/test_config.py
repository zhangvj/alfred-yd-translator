"""config 模块测试：数据目录持久化、优先级、权限。"""
import json
import os
import stat
import tempfile
import unittest

from workflow.lib import config as cfgmod
from workflow.lib.config import Config, clear_config, load_saved, save_config


class TestConfigStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {"YD_DATA_DIR": self.tmp.name}

    def test_save_and_load_roundtrip(self):
        path = save_config({"yd_key": "K1", "yd_secret": "S1"}, env=self.env)
        self.assertEqual(path, os.path.join(self.tmp.name, "config.json"))
        saved = load_saved(self.env)
        self.assertEqual(saved["yd_key"], "K1")
        self.assertEqual(saved["yd_secret"], "S1")

    def test_save_merges_not_overwrites(self):
        save_config({"yd_key": "K1"}, env=self.env)
        save_config({"yd_secret": "S1"}, env=self.env)
        saved = load_saved(self.env)
        self.assertEqual(saved, {"yd_key": "K1", "yd_secret": "S1"})

    def test_file_permissions_600(self):
        path = save_config({"yd_key": "K1"}, env=self.env)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_clear(self):
        save_config({"yd_key": "K1"}, env=self.env)
        self.assertTrue(clear_config(self.env))
        self.assertFalse(clear_config(self.env))
        self.assertEqual(load_saved(self.env), {})

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_saved(self.env), {})

    def test_load_corrupt_returns_empty(self):
        with open(os.path.join(self.tmp.name, "config.json"), "w") as f:
            f.write("{broken")
        self.assertEqual(load_saved(self.env), {})

    def test_precedence_env_over_file(self):
        save_config({"yd_key": "FILE", "yd_to": "fr"}, env=self.env)
        env = dict(self.env, yd_key="ENV", yd_secret="S", yd_to="")
        cfg = Config(env)
        self.assertEqual(cfg.key, "ENV")          # 环境变量优先
        self.assertEqual(cfg.secret, "S")
        self.assertEqual(cfg.to, "fr")            # 文件兜底（env 为空串）
        self.assertEqual(cfg.voice, "en")         # 默认值
        self.assertTrue(cfg.configured)

    def test_defaults_when_nothing_set(self):
        cfg = Config(dict(self.env))
        self.assertFalse(cfg.configured)
        self.assertEqual(cfg.to, "zh-CHS")
        self.assertEqual(cfg.cn_to, "en")
        self.assertEqual(cfg.sign, "auto")


if __name__ == "__main__":
    unittest.main()
