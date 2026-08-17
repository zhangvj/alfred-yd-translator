"""detect 模块测试。"""
import unittest

from workflow.lib.detect import has_cjk, has_han, target_lang


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


if __name__ == "__main__":
    unittest.main()
