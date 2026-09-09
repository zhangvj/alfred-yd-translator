"""Alfred Script Filter JSON 输出构建器。

输出格式参考:
https://www.alfredapp.com/help/workflows/inputs/script-filter/json/
"""
import json


class Item:
    """单个结果行（与参考项目 Item 类思路一致，链式调用）。"""

    def __init__(self):
        self._data = {}

    def _set(self, key, value):
        if value not in (None, "", [], {}):
            self._data[key] = value
        return self

    def title(self, value):
        return self._set("title", value)

    def subtitle(self, value):
        return self._set("subtitle", value)

    def arg(self, value):
        return self._set("arg", value)

    def uid(self, value):
        return self._set("uid", value)

    def autocomplete(self, value):
        return self._set("autocomplete", value)

    def quicklookurl(self, value):
        return self._set("quicklookurl", value)

    def icon(self, path):
        return self._set("icon", {"path": path})

    def text(self, copy=None, largetype=None):
        text = {}
        if copy:
            text["copy"] = copy
        if largetype:
            text["largetype"] = largetype
        return self._set("text", text)

    def mod(self, key, subtitle, arg, valid=True):
        self._data.setdefault("mods", {})[key] = {
            "subtitle": subtitle,
            "arg": arg,
            "valid": valid,
        }
        return self

    def valid(self, value=True):
        self._data["valid"] = value
        return self

    def result(self):
        return self._data


def output(items, rerun=None):
    """输出 Alfred Script Filter JSON 字符串。

    rerun 为秒数时，Alfred 会在该时间后以当前输入自动重跑本脚本
    （用户继续打字则被新输入取代），用于"等待输入完成"的延迟翻译。
    """
    data = {"items": items}
    if rerun:
        data["rerun"] = round(float(rerun), 2)
    return json.dumps(data, ensure_ascii=False)


def error_item(title, subtitle):
    """不可执行的提示行。"""
    return Item().title(title).subtitle(subtitle).valid(False).result()
