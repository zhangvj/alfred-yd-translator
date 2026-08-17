"""语言检测：判断查询文本是否为中文（汉字），供目标语言选择使用。

有道 API 的 from 固定为 auto（自动识别源语言），这里只需要决定 to：
    - 含汉字          -> 翻译成 cn_to（默认 en）
    - 其他（英文/日文/韩文/法文等）-> 翻译成 to（默认 zh-CHS）
"""
import re

# CJK 统一表意文字（含扩展 A、兼容区）
_HAN_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")
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


def target_lang(text, to="zh-CHS", cn_to="en"):
    """根据文本内容返回有道 API 的 to 参数。"""
    return cn_to if has_han(text) else to
