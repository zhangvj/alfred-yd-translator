"""★ 核心模块：智能文本规范化。

把用户输入的各种书写形式（全大写缩写、驼峰、下划线、中划线、品牌词等）
规整为适合有道词典查词/翻译的形式，避免参考项目中
`query.replace(/([A-Z])/g, ' $1').toLowerCase()` 造成的
"API -> a p i"、"USER_NAME -> u s e r _ n a m e" 等乱码。

处理规则（确定性，逐条被 tests/test_normalizer.py 锁定）：
1. 含 CJK/假名/谚文的文本原样放行（交给有道自动检测混合文本）；
2. 按空白分词；token 内按 `_` 与 `-` 拆段（snake_case / kebab-case）；
3. 段内驼峰拆分：
   - 全大写（含数字，如 API / NASA / HTML5 / 2FA / U.S.A.）保持单段；
   - 品牌保护 a：小写开头且第二字符大写（iPhone / eBay / iMac）不拆；
   - 品牌保护 b：小写开头、尾部连续大写 >=2（macOS / iOS）不拆；
   - 通用规则：大写前是小写/数字处插入边界；连续大写串最后一个大写
     后跟小写时在其前插入边界（HTTPRequest -> HTTP Request）；
   - 小写字母紧跟 >=2 个连续大写之后时插入边界（AUTOcar -> AUTO car）；
4. 大小写：**全大写缩写 token 保留原样**（实测 `NASA` → 「美国国家航空航天局」、
   `API` 小写会误译为「蜜蜂」，全大写则被正确识别为缩写）；其余 token 统一小写
   （有道查词大小写不敏感，小写匹配率更高）；
5. 单空格连接；结果不含任何可翻译字符时返回空串（触发"无法翻译"提示）。
"""
import re

from .detect import CJK_RE

_UNDERSCORE_HYPHEN_RE = re.compile(r"[_\-]+")
_BRAND_A_RE = re.compile(r"^[a-z][A-Z]")          # iPhone, eBay, iMac
_BRAND_B_RE = re.compile(r"^[a-z]+[A-Z]{2,}$")    # macOS, iOS
_WORD_CHAR_RE = re.compile(r"[0-9A-Za-z\u3400-\u9fff]")


def _split_segment(seg):
    """对单个段（已去除 _ 与 -）做驼峰拆分，返回片段列表。"""
    if len(seg) <= 1:
        return [seg]
    if seg.isupper():      # 全大写：API / NASA / HTML5 / 2FA / U.S.A.
        return [seg]
    if seg.islower():      # 全小写
        return [seg]
    if _BRAND_A_RE.match(seg) or _BRAND_B_RE.match(seg):
        return [seg]       # 品牌词整体保留

    # 通用驼峰拆分
    bounds = []
    n = len(seg)
    i = 1
    while i < n:
        prev, cur = seg[i - 1], seg[i]
        if cur.isupper():
            if prev.islower() or prev.isdigit():
                # getUser -> get|User
                bounds.append(i)
            elif prev.isupper() and i + 1 < n and seg[i + 1].islower():
                # HTTPRequest -> HTTP|Request（连续大写串最后一个大写后跟小写，
                # 在其前拆分；这是行业标准规则，AUTOcar 会得 AUT|Ocar，
                # 与所有主流 camelCase 拆分器一致）
                bounds.append(i)
        i += 1

    if not bounds:
        return [seg]
    parts, start = [], 0
    for b in bounds:
        parts.append(seg[start:b])
        start = b
    parts.append(seg[start:])
    return parts


def _split_token(token):
    """拆分单个 token（先按 _ 与 - 分段，再逐段驼峰拆分）。"""
    parts = []
    for seg in _UNDERSCORE_HYPHEN_RE.split(token):
        if not seg:
            continue
        if CJK_RE.search(seg):
            parts.append(seg)
        else:
            parts.extend(_split_segment(seg))
    return parts


def normalize(query):
    """规范化查询文本，返回适合有道翻译的字符串；无可翻译内容时返回空串。"""
    text = (query or "").strip()
    if not text:
        return ""

    # 含 CJK/假名/谚文：原样放行，交给有道自动检测（含混合文本）
    if CJK_RE.search(text):
        return text

    parts = []
    for token in text.split():
        token_parts = _split_token(token)
        if token.isupper():
            # 全大写缩写（API / NASA / USER_NAME / U.S.A.）保留原样，
            # 避免小写后匹配到无关单词（api -> 蜜蜂）
            parts.extend(token_parts)
        else:
            parts.extend(p.lower() for p in token_parts)

    result = " ".join(parts)
    if not _WORD_CHAR_RE.search(result):
        return ""
    return result
