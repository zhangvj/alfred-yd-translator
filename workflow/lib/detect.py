"""语言检测：判断查询文本是否为中文（汉字），供目标语言选择使用。

有道 API 的 from 固定为 auto（自动识别源语言），这里只需要决定 to：
    - 含汉字          -> 翻译成 cn_to（默认 en）
    - 其他（英文/日文/韩文/法文等）-> 翻译成 to（默认 zh-CHS）

特例（v1.4.0）：**长文本里汉字占比极低**（如英文错误日志中嵌了一个中文词
「Provider: 公司; ...」）时，整体仍以拉丁文本为主，若按"有汉字 → cn_to"
判定会把 to 设成 en，而有道识别源语言也是 en → en2en 原样回显（等于没翻译）。
因此长文本按「拉丁字母主导」判定，仍翻译成 to（默认中文）。
"""
import re

# CJK 统一表意文字（含扩展 A、兼容区）
_HAN_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")
# 拉丁字母（判定文本主体是否为英文/拉丁文本）
_LATIN_RE = re.compile(r"[A-Za-z]")

# 拉丁主导判定阈值：文本长度 >= 40 且 汉字占「汉字+拉丁字母」比例 < 5%
LATIN_DOMINANT_MIN_LEN = 40
LATIN_DOMINANT_HAN_RATIO = 0.05
# 平假名 / 片假名
_KANA_RE = re.compile(r"[\u3040-\u30FF]")
# 谚文
_HANGUL_RE = re.compile(r"[\uAC00-\uD7AF]")
# 三者合集（normalizer 也复用）
CJK_RE = re.compile(
    r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u30FF\uAC00-\uD7AF]"
)


def has_han(text):
    """是否包含汉字。"""
    return bool(_HAN_RE.search(text))


def has_kana(text):
    """是否包含假名（日文）。"""
    return bool(_KANA_RE.search(text))


def has_hangul(text):
    """是否包含谚文（韩文）。"""
    return bool(_HANGUL_RE.search(text))


def has_cjk(text):
    """是否包含任何 CJK 字符（汉字/假名/谚文）。"""
    return bool(CJK_RE.search(text))


def han_latin_stats(text):
    """返回 (汉字数, 拉丁字母数)。"""
    text = text or ""
    return len(_HAN_RE.findall(text)), len(_LATIN_RE.findall(text))


def is_latin_dominant(text):
    """长文本是否「以拉丁文本为主」：长度 >= 40 且汉字占比 < 5%。

    例：英文错误日志里出现 1~2 个中文词（`Provider: 公司; model: …`）。
    """
    text = text or ""
    if len(text) < LATIN_DOMINANT_MIN_LEN:
        return False
    han, latin = han_latin_stats(text)
    total = han + latin
    return bool(han) and bool(total) and han < total * LATIN_DOMINANT_HAN_RATIO


def target_lang(text, to="zh-CHS", cn_to="en"):
    """根据文本内容返回有道 API 的 to 参数。"""
    text = text or ""
    if not _HAN_RE.search(text):
        return to
    # 长文本里的零星汉字（英文日志等）→ 按拉丁文本为主，翻译成 to
    if is_latin_dominant(text):
        return to
    return cn_to
