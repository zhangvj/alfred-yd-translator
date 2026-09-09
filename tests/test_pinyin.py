"""拼音组词检测测试：音节切分、混合态/纯拼音态判定、放行边界。"""
import unittest

from workflow.lib.pinyin import _parse_stats, is_composition, is_pinyin_suspect


class TestParse(unittest.TestCase):
    def test_parse_stats_basic(self):
        ok, count = _parse_stats("nihao")
        self.assertTrue(ok)
        self.assertEqual(count, 2)          # ni + hao

    def test_parse_stats_long_syllable(self):
        ok, count = _parse_stats("zhuangzhuang")
        self.assertTrue(ok)
        self.assertEqual(count, 2)          # zhuang + zhuang（6 字最长音节）

    def test_parse_stats_not_pinyin(self):
        ok, count = _parse_stats("hello")
        self.assertFalse(ok)
        self.assertEqual(count, 0)

    def test_parse_stats_empty(self):
        ok, count = _parse_stats("")
        self.assertFalse(ok)
        self.assertEqual(count, 0)


class TestCompositionTrue(unittest.TestCase):
    """应判定为组词中间态（拦截，不调用 API）。"""

    def test_mixed_cjk_tail(self):
        self.assertTrue(is_composition("你好shijie"))

    def test_mixed_short_tail(self):
        self.assertTrue(is_composition("你hao"))

    def test_pure_pinyin_multi_syllable(self):
        self.assertTrue(is_composition("nihao"))
        self.assertTrue(is_composition("shijie"))
        self.assertTrue(is_composition("nihaoshijie"))
        self.assertTrue(is_composition("xihuan"))
        self.assertTrue(is_composition("chuanglian"))

    def test_repeated_syllable(self):
        self.assertTrue(is_composition("mama"))   # ma+ma，典型组词态

    def test_whitespace_stripped(self):
        self.assertTrue(is_composition("  nihao  "))


class TestCompositionFalse(unittest.TestCase):
    """应放行（正常查询，照常调用 API）。"""

    def test_english_words(self):
        self.assertFalse(is_composition("hello"))
        self.assertFalse(is_composition("apple"))
        self.assertFalse(is_composition("iphone"))

    def test_uppercase_is_intentional(self):
        self.assertFalse(is_composition("API"))
        self.assertFalse(is_composition("USER_NAME"))
        self.assertFalse(is_composition("你好OK"))
        self.assertFalse(is_composition("NIhao"))

    def test_digits_and_punctuation(self):
        self.assertFalse(is_composition("你好123"))
        self.assertFalse(is_composition("nihao3"))
        self.assertFalse(is_composition("你好，世界"))
        self.assertFalse(is_composition("user_name"))

    def test_space_breaks_pure_pinyin(self):
        # 带空格是多词英文/手动输入，不是组词中间态
        self.assertFalse(is_composition("ni hao"))
        self.assertFalse(is_composition("hello world"))

    def test_single_syllable_allowed(self):
        # 单音节放行，避免误伤短查询（ma / shi / xian 都只算 1 个音节）
        self.assertFalse(is_composition("ma"))
        self.assertFalse(is_composition("shi"))
        self.assertFalse(is_composition("xian"))
        self.assertFalse(is_composition("a"))

    def test_single_syllable_not_oversegmented(self):
        # zhuang/xian 可被过度切分（zhu+ang / xi+an），但按最少音节仍是
        # 单音节的正常查询，必须放行
        self.assertFalse(is_composition("zhuang"))
        self.assertFalse(is_composition("chuang"))
        self.assertFalse(is_composition("shuang"))

    def test_short_mixed_tail_allowed(self):
        self.assertFalse(is_composition("你好a"))       # 尾巴 <2 字符
        self.assertFalse(is_composition("你好 世界"))    # 尾部带空格，非组词态

    def test_pure_cjk(self):
        self.assertFalse(is_composition("你好世界"))

    def test_empty(self):
        self.assertFalse(is_composition(""))
        self.assertFalse(is_composition(None))

    def test_cjk_other_scripts(self):
        # 假名/谚文直接上屏，不参与拼音组词判定
        self.assertFalse(is_composition("こんにちは"))
        self.assertFalse(is_composition("안녕"))


class TestSuspect(unittest.TestCase):
    """软判定 is_pinyin_suspect：命中 → 延迟重跑（rerun），而非拒绝。"""

    def test_single_syllable_suspect(self):
        # v1.2.0 放行的单音节组词态（'da' 泄漏过真实调用），现在软判定命中
        self.assertTrue(is_pinyin_suspect("da"))
        self.assertTrue(is_pinyin_suspect("ni"))
        self.assertTrue(is_pinyin_suspect("hao"))

    def test_multi_syllable_suspect(self):
        self.assertTrue(is_pinyin_suspect("nihao"))
        self.assertTrue(is_pinyin_suspect("shijie"))

    def test_extendable_prefix_suspect(self):
        self.assertTrue(is_pinyin_suspect("nih"))     # ni + h(ao)
        self.assertTrue(is_pinyin_suspect("shij"))    # shi + j(ie)

    def test_english_not_suspect(self):
        for q in ("hello", "apple", "iphone", "xyz", "abc", "int"):
            self.assertFalse(is_pinyin_suspect(q), q)

    def test_short_and_symbols_not_suspect(self):
        self.assertFalse(is_pinyin_suspect("a"))          # 交给 min_len 规则
        self.assertFalse(is_pinyin_suspect("sh"))         # <3 字符不判延展
        self.assertFalse(is_pinyin_suspect("nihao."))     # 标点（force 逃逸口）
        self.assertFalse(is_pinyin_suspect("nihao3"))     # 数字
        self.assertFalse(is_pinyin_suspect("nih ao"))     # 空格
        self.assertFalse(is_pinyin_suspect("NIHAO"))      # 大写
        self.assertFalse(is_pinyin_suspect("你好"))        # 汉字（is_composition 负责）
        self.assertFalse(is_pinyin_suspect(""))
        self.assertFalse(is_pinyin_suspect(None))


if __name__ == "__main__":
    unittest.main()
