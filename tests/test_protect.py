"""protect 模块测试：中文片段掩码 / 还原 / 生效条件。"""
import unittest

from workflow.lib.protect import (
    HAN_RUN_RE,
    mask_han,
    placeholders_intact,
    should_mask,
    unmask_text,
)


class TestMask(unittest.TestCase):
    def test_mask_single_run(self):
        masked, runs = mask_han("Provider: 公司; model: x")
        self.assertEqual(masked, "Provider: [[C0]]; model: x")
        self.assertEqual(runs, ["公司"])

    def test_mask_multiple_runs_keep_order(self):
        masked, runs = mask_han("a 你好 b 世界 c")
        self.assertEqual(masked, "a [[C0]] b [[C1]] c")
        self.assertEqual(runs, ["你好", "世界"])

    def test_mask_no_han(self):
        masked, runs = mask_han("hello world")
        self.assertEqual(masked, "hello world")
        self.assertEqual(runs, [])

    def test_mask_empty_and_none(self):
        self.assertEqual(mask_han(""), ("", []))
        self.assertEqual(mask_han(None), ("", []))

    def test_mask_adjacent_punctuation(self):
        masked, runs = mask_han("Provider: 公司;model,x")
        self.assertEqual(masked, "Provider: [[C0]];model,x")
        self.assertEqual(runs, ["公司"])

    def test_mask_only_han(self):
        masked, runs = mask_han("你好世界")
        self.assertEqual(masked, "[[C0]]")
        self.assertEqual(runs, ["你好世界"])

    def test_round_trip(self):
        text = "Provider: 公司; model: 模型; note: 你好"
        masked, runs = mask_han(text)
        self.assertEqual(unmask_text(masked, runs), text)


class TestUnmask(unittest.TestCase):
    def test_unmask_restores_in_order(self):
        self.assertEqual(
            unmask_text("提供方：[[C0]]；模型：[[C1]]", ["公司", "模型"]),
            "提供方：公司；模型：模型",
        )

    def test_unmask_strips_orphan_markers(self):
        # 模型改写/丢失标记时不泄漏占位符
        self.assertEqual(unmask_text("提供方：[[C0]]", []), "提供方：")
        self.assertEqual(unmask_text("a [[C9]] b", ["公司"]), "a  b")

    def test_unmask_is_tolerant_and_idempotent(self):
        self.assertEqual(unmask_text("", ["公司"]), "")
        self.assertEqual(unmask_text(None, ["公司"]), "")


class TestPlaceholdersIntact(unittest.TestCase):
    def test_intact(self):
        self.assertTrue(placeholders_intact("a [[C0]] b [[C1]]", ["公司", "模型"]))
        self.assertTrue(placeholders_intact("anything", []))       # 无保护视为完整
        self.assertTrue(placeholders_intact("", []))

    def test_missing_marker(self):
        self.assertFalse(placeholders_intact("a [[C0]] b", ["公司", "模型"]))

    def test_marker_reordered_still_intact(self):
        # 模型调整语序不影响还原能力
        self.assertTrue(placeholders_intact("b [[C1]] a [[C0]]", ["公司", "模型"]))


class TestShouldMask(unittest.TestCase):
    LOG = (
        "CC Switch local proxy failed while handling Codex endpoint /responses. "
        "Provider: 公司; model: ccs-qianwenai/deepseek-v4.1-flash-1017; "
        "upstream_status: HTTP 400; cause: Invalid 'call_id': call_id is required for "
        "function_call_output"
    )

    def test_masks_latin_dominant_to_chinese(self):
        self.assertTrue(should_mask(self.LOG, "zh-CHS"))
        self.assertTrue(should_mask(self.LOG, "zh-CHT"))

    def test_no_mask_for_non_chinese_target(self):
        for to in ("en", "ja", "fr", "ru", "ko"):
            self.assertFalse(should_mask(self.LOG, to), to)

    def test_no_mask_for_short_mixed_text(self):
        self.assertFalse(should_mask("Provider: 公司; model: x", "zh-CHS"))

    def test_no_mask_without_han(self):
        latin = "CC Switch local proxy failed while handling a very long English log line here"
        self.assertFalse(should_mask(latin, "zh-CHS"))

    def test_no_mask_for_chinese_heavy_text(self):
        self.assertFalse(should_mask("请把这段关于数据库连接池配置的说明翻译成英文并保持术语准确", "zh-CHS"))


class TestHanRunRegex(unittest.TestCase):
    def test_matches_extensions(self):
        self.assertTrue(HAN_RUN_RE.search("\u3400"))   # CJK 扩展 A
        self.assertTrue(HAN_RUN_RE.search("公"))
        self.assertFalse(HAN_RUN_RE.search("こ"))      # 假名不保护
        self.assertFalse(HAN_RUN_RE.search("한"))      # 谚文不保护


if __name__ == "__main__":
    unittest.main()
