"""normalizer 规格表测试：计划第四节的示例表逐条断言。"""
import unittest

from workflow.lib.normalizer import normalize


class TestNormalize(unittest.TestCase):
    CASES = [
        # (输入, 期望规范化结果)
        # 全大写缩写保留原样（实测 NASA -> 美国国家航空航天局；api 小写会误译为蜜蜂）
        ("API", "API"),
        ("NASA", "NASA"),
        ("HTML5", "HTML5"),
        ("2FA", "2FA"),
        ("U.S.A.", "U.S.A."),
        # 驼峰 / snake / kebab：拆分后小写（仅"整个 token 全大写"保留原样；
        # HTTPRequest 不是全大写 token，整体小写，实测与 HTTP request 翻译结果一致）
        ("HTTPRequest", "http request"),
        ("getUserName", "get user name"),
        ("user_name", "user name"),
        ("USER_NAME", "USER NAME"),
        ("well-known", "well known"),
        ("USER-FRIENDLY", "USER FRIENDLY"),
        ("getUser_ID", "get user id"),
        ("getUser", "get user"),
        # 连续大写串的行业标准行为：在最后一个大写前拆分
        # （"AUTOcar" 这类全大写前缀+小写词是罕见写法；常见写法 AutoCar 正确拆分）
        ("AUTOcar", "aut ocar"),
        ("AutoCar", "auto car"),
        ("HTMLParser", "html parser"),
        ("user2Name", "user2 name"),
        # 品牌保护
        ("iPhone", "iphone"),
        ("iOS", "ios"),
        ("macOS", "macos"),
        ("eBay", "ebay"),
        # CJK 放行
        ("你好世界", "你好世界"),
        ("こんにちは", "こんにちは"),
        ("안녕하세요", "안녕하세요"),
        # 其他
        ("don't", "don't"),
        ("OpenAI", "open ai"),
    ]

    def test_cases(self):
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(normalize(raw), expected)

    def test_empty_and_whitespace(self):
        for raw in ("", "   ", "\t\n"):
            self.assertEqual(normalize(raw), "")

    def test_pure_punctuation(self):
        for raw in ("!!!", "---", "...", "？？？"):
            self.assertEqual(normalize(raw), "")

    def test_mixed_cjk_and_latin_passthrough(self):
        # 含 CJK 的混合文本原样放行
        self.assertEqual(normalize("API 参考"), "API 参考")
        self.assertEqual(normalize("你好 world"), "你好 world")

    def test_extra_whitespace_collapsed(self):
        self.assertEqual(normalize("  hello    world  "), "hello world")


if __name__ == "__main__":
    unittest.main()
