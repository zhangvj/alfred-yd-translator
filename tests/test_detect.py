"""detect 模块测试。"""
import unittest

from workflow.lib.detect import (
    has_cjk,
    has_han,
    is_latin_dominant,
    target_lang,
)

# 真实触发过问题的文本：英文错误日志里嵌了一个中文词（公司）
MIXED_LOG = (
    "CC Switch local proxy failed while handling Codex endpoint /responses. "
    "Provider: 公司; model: ccs-qianwenai/deepseek-v4.1-flash-1017; "
    "upstream_status: HTTP 400; cause: Invalid 'call_id': call_id is required for "
    "function_call_output"
)


class TestDetect(unittest.TestCase):
    def test_has_han(self):
        self.assertTrue(has_han("你好世界"))
        self.assertTrue(has_han("Hello 世界"))
        self.assertFalse(has_han("hello world"))
        self.assertFalse(has_han("こんにちは"))
        self.assertFalse(has_han("안녕하세요"))

    def test_has_cjk(self):
        self.assertTrue(has_cjk("你好"))
        self.assertTrue(has_cjk("こんにちは"))
        self.assertTrue(has_cjk("안녕하세요"))
        self.assertFalse(has_cjk("hello"))

    def test_target_lang(self):
        self.assertEqual(target_lang("你好世界"), "en")
        self.assertEqual(target_lang("hello world"), "zh-CHS")
        self.assertEqual(target_lang("こんにちは"), "zh-CHS")
        self.assertEqual(target_lang("안녕하세요"), "zh-CHS")
        self.assertEqual(target_lang("你好世界", cn_to="ja"), "ja")
        self.assertEqual(target_lang("hello", to="fr"), "fr")

    def test_latin_dominant_long_log_targets_chinese(self):
        # 曾经的线上 bug：英文日志里含 2 个汉字 → 误判成中文 → to=en → en2en 回显
        self.assertTrue(is_latin_dominant(MIXED_LOG))
        self.assertEqual(target_lang(MIXED_LOG), "zh-CHS")

    def test_short_mixed_text_keeps_chinese_target(self):
        # 短混排查询仍按「含汉字 → cn_to」，如 you are 大牛 → en
        self.assertFalse(is_latin_dominant("you are 大牛"))
        self.assertEqual(target_lang("you are 大牛"), "en")

    def test_long_chinese_text_keeps_chinese_target(self):
        text = "请帮我把下面这段关于数据库连接池配置的说明整理成英文并保持专业术语准确"
        self.assertFalse(is_latin_dominant(text))
        self.assertEqual(target_lang(text), "en")

    def test_latin_dominant_needs_latin_majority(self):
        self.assertFalse(is_latin_dominant("公司"))                 # 无拉丁字母
        self.assertFalse(is_latin_dominant("hello"))                # 无汉字
        self.assertFalse(is_latin_dominant("hello world"))          # 太短
        text = "please review this configuration carefully 公司 and report back tomorrow afternoon"
        self.assertTrue(is_latin_dominant(text))


if __name__ == "__main__":
    unittest.main()
