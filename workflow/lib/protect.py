"""中文片段保护：翻译前把文本里已有的汉字串替换为占位符，翻译后原样还原。

背景（v1.5.0，实测取证）：
    目标语言是中文时，文本中本来就已经是中文的片段（如英文错误日志里的
    `Provider: 公司; model: …`）无需翻译。但有道模型在"英文长句里嵌中文"的
    混排输入上会把这类片段当作外语异物重新"翻译"，产出「公司 → 五星」这类
    失真——源语言识别其实是对的（`l=en2zh-CHS`），强制 `from=en` 也无变化，
    短片段单独送反而能翻成 `Company`，说明这是上下文相关的模型行为，无法靠
    请求参数修正。

    实测有道会**原样保留** `[[C0]]` 形式的标记，因此采用「掩码 → 翻译 → 还原」：
    既不丢内容，也不需要多花请求（对比"分段翻译"需要 2~3 次调用）。

生效条件（should_mask，三条同时满足，避免误伤）：
    1. 目标语言是中文（`to` 以 zh 开头，如 zh-CHS / zh-CHT）；
    2. 文本判定为「拉丁主导」（复用 detect.is_latin_dominant：≥40 字符且
       汉字占「汉字+拉丁字母」比例 <5%）；
    3. 文本中确有汉字串。

    推论：短混排（`Provider: 公司; model: x`）通常目标为 en → 不掩码，照旧
    翻成 Company；`yd_to=ja/fr` 等非中文目标 → 不掩码；纯中文/英文/日文/韩文
    行为完全不变。
"""
import re

from .detect import is_latin_dominant

# 最大连续汉字串（码点范围与 detect._HAN_RE 一致）
HAN_RUN_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]+")
# 占位符标记：[[C0]]、[[C1]]…（实测有道原样保留）
MARKER_RE = re.compile(r"\[\[C(\d+)\]\]")


def _marker(index):
    return "[[C{}]]".format(index)


def mask_han(text):
    """把文本中的最大连续汉字串替换为占位符。

    返回 (掩码后文本, 被保护的片段列表)；无汉字时返回 (text, [])。
    """
    text = text or ""
    runs, parts, pos = [], [], 0
    for match in HAN_RUN_RE.finditer(text):
        parts.append(text[pos:match.start()])
        parts.append(_marker(len(runs)))
        runs.append(match.group(0))
        pos = match.end()
    parts.append(text[pos:])
    return "".join(parts), runs


def unmask_text(text, runs):
    """把占位符按序还原为原片段。

    容错：标记被模型改写/丢失时不报错，残留的 `[[C` 标记一律清掉，
    保证任何情况下都不把占位符泄漏给用户。
    """
    text = text or ""
    for index, run in enumerate(runs or []):
        text = text.replace(_marker(index), run)
    return MARKER_RE.sub("", text)


def placeholders_intact(text, runs):
    """所有占位符是否都还在（用于判断是否需要降级为未掩码请求）。"""
    runs = runs or []
    text = text or ""
    if not runs:
        return True
    return all(_marker(index) in text for index in range(len(runs)))


def should_mask(text, to):
    """是否对文本中的汉字片段做保护（三条生效条件同时满足）。"""
    text = text or ""
    return (
        str(to or "").lower().startswith("zh")
        and bool(HAN_RUN_RE.search(text))
        and is_latin_dominant(text)
    )
