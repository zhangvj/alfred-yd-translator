"""info.plist 回归测试：Alfred 对象/连接/编码配置与版本同步。

这类问题不会在 Python 单测里暴露，但会直接导致 Alfred 行为异常：
  - 对象 `version` 过高 → "incompatible with this version of Alfred"（v1.1.0 事故）
  - Open URL 未跳过变量编码 → 传入的完整 URL 被二次编码（打不开）
  - JSON `mods` 有快捷键文案，但画布连接缺少对应 modifiers → 按了没反应
  - 版本号没同步到 plist → 工作流列表显示旧版本
"""
import os
import plistlib
import sys
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
WORKFLOW_DIR = os.path.join(ROOT, "workflow")
PLIST = os.path.join(WORKFLOW_DIR, "info.plist")

sys.path.insert(0, WORKFLOW_DIR)
sys.path.insert(0, ROOT)

import yd  # noqa: E402
from workflow.lib import __version__  # noqa: E402

MOD_CMD = 1048576
MOD_ALT = 524288
MOD_SHIFT = 131072
MOD_NAMES = {"cmd": MOD_CMD, "alt": MOD_ALT, "shift": MOD_SHIFT}

FAKE_DATA = {
    "errorCode": "0",
    "query": "API",
    "l": "en2zh-CHS",
    "translation": ["应用程序编程接口"],
    "speakUrl": "https://dict.youdao.com/dictvoice?audio=api&type=2",
    "tSpeakUrl": "https://dict.youdao.com/dictvoice?audio=api&type=1",
}


class TestPlist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PLIST, "rb") as f:
            cls.plist = plistlib.load(f)
        cls.objs = {o["uid"]: o for o in cls.plist["objects"]}
        cls.connections = cls.plist["connections"]

    def by_type(self, type_name):
        return [o for o in self.objs.values() if o["type"] == type_name]

    def _edges(self, uid):
        return self.connections.get(uid, [])

    # ---- 版本 / 标识 ----
    def test_version_matches_single_source(self):
        self.assertEqual(str(self.plist.get("version")), __version__)

    def test_bundle_id_stable(self):
        self.assertEqual(self.plist.get("bundleid"), "com.zvj.yd-translator")

    def test_object_versions_compatible_with_alfred_5(self):
        # Alfred 5 已知兼容的对象版本：hotkey=2, scriptfilter=3, clipboard=3,
        # script=2, openurl=1, hidealfred=1。声明过高会导致导入时报不兼容。
        expected = {
            "alfred.workflow.trigger.hotkey": 2,
            "alfred.workflow.input.scriptfilter": 3,
            "alfred.workflow.output.clipboard": 3,
            "alfred.workflow.action.script": 2,
            "alfred.workflow.action.openurl": 1,
            "alfred.workflow.utility.hidealfred": 1,
        }
        for obj in self.plist["objects"]:
            self.assertEqual(obj.get("version"), expected[obj["type"]],
                             "{} 的对象版本变了".format(obj["type"]))

    # ---- Script Filter ----
    def test_script_filter_entry(self):
        sf = self.by_type("alfred.workflow.input.scriptfilter")[0]
        cfg = sf["config"]
        self.assertEqual(cfg["keyword"], "yd")
        self.assertIn("yd.py", cfg["script"])
        self.assertFalse(cfg["alfredfiltersresults"])
        self.assertEqual(cfg["queuemode"], 2)          # 终止上一次运行（输入法场景）
        self.assertGreaterEqual(cfg["queuedelaycustom"], 1)  # 0.1s 单位的防抖

    def test_script_files_exist(self):
        sf = self.by_type("alfred.workflow.input.scriptfilter")[0]["config"]
        for filename in ("yd.py", "yd_speak.py"):
            self.assertTrue(os.path.exists(os.path.join(WORKFLOW_DIR, filename)), filename)
        self.assertIn("yd_speak.py",
                      self.by_type("alfred.workflow.action.script")[0]["config"]["script"])
        self.assertTrue(os.path.exists(
            os.path.join(WORKFLOW_DIR, "lib", "protect.py")))

    # ---- Hotkey ----
    def test_hotkey_presets_selection_argument(self):
        # 预置「Selection in macOS」，用户只需录键；否则热键拿不到选中文本
        hk = self.by_type("alfred.workflow.trigger.hotkey")[0]
        self.assertEqual(hk["config"]["argument"], 1)
        self.assertEqual(len(self._edges(hk["uid"])), 1)
        dest = self.objs[self._edges(hk["uid"])[0]["destinationuid"]]
        self.assertEqual(dest["type"], "alfred.workflow.input.scriptfilter")

    # ---- Open URL 编码 ----
    def test_openurl_does_not_double_encode(self):
        # Shift（打开网页）/ Alt（在线发音）传入的是【已编码的完整 URL】，
        # 若 Alfred 再把 {query} 当参数编码一次，会变成 https%3A%2F%2F… 打不开。
        urls = self.by_type("alfred.workflow.action.openurl")
        self.assertEqual(len(urls), 2)
        for obj in urls:
            cfg = obj["config"]
            self.assertEqual(cfg["url"], "{query}")
            self.assertTrue(cfg["skipqueryencode"])
            self.assertTrue(cfg["skipvarencode"])

    # ---- 画布连接 / 快捷键分发 ----
    def test_modifier_connections_complete(self):
        sf = self.by_type("alfred.workflow.input.scriptfilter")[0]
        edges = self._edges(sf["uid"])
        by_mod = {e["modifiers"]: self.objs[e["destinationuid"]]["type"] for e in edges}
        self.assertEqual(set(by_mod), {0, MOD_CMD, MOD_ALT, MOD_SHIFT})
        self.assertEqual(by_mod[0], "alfred.workflow.output.clipboard")
        self.assertEqual(by_mod[MOD_CMD], "alfred.workflow.action.script")
        self.assertEqual(by_mod[MOD_ALT], "alfred.workflow.action.openurl")
        self.assertEqual(by_mod[MOD_SHIFT], "alfred.workflow.action.openurl")

    def test_enter_copies_then_hides_alfred(self):
        clip = self.by_type("alfred.workflow.output.clipboard")[0]
        self.assertEqual(clip["config"]["clipboardtext"], "{query}")
        dests = [self.objs[e["destinationuid"]]["type"]
                 for e in self._edges(clip["uid"])]
        self.assertEqual(dests, ["alfred.workflow.utility.hidealfred"])

    def test_item_mods_match_connection_modifiers(self):
        # JSON 里的 mods 文案必须与画布上的 modifiers 连接一一对应，
        # 否则 Alfred 显示"Cmd 发音"但按下无反应。
        items = yd.build_items(
            types.SimpleNamespace(voice="en"), "API", "API", FAKE_DATA)
        self.assertTrue(items)
        mod_keys = set(items[0]["mods"])
        self.assertEqual(set(MOD_NAMES), mod_keys)
        sf = self.by_type("alfred.workflow.input.scriptfilter")[0]
        edge_mods = {e["modifiers"] for e in self._edges(sf["uid"])} - {0}
        self.assertEqual({MOD_NAMES[k] for k in mod_keys}, edge_mods)

    def test_all_connections_reference_existing_objects(self):
        for src, edges in self.connections.items():
            self.assertIn(src, self.objs)
            for edge in edges:
                self.assertIn(edge["destinationuid"], self.objs)

    def test_variables_dont_export_credentials(self):
        self.assertEqual(self.plist.get("variablesdontexport"), ["yd_key", "yd_secret"])


if __name__ == "__main__":
    unittest.main()
