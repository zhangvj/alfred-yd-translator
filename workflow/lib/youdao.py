"""有道开放平台文本翻译 API 客户端（v3 签名）。

官方文档: https://ai.youdao.com/DOCSIRMA/html/trans/api/wbfy/index.html
- 端点: POST https://openapi.youdao.com/api
- 签名: sign = md5(appKey + input(q) + salt + curtime + secret)
  input(q) = q 长度 <= 20 时取 q 本身；否则 q[:10] + str(len(q)) + q[-10:]
"""
import hashlib
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

API_URL = "https://openapi.youdao.com/api"

# 有道文本翻译单次 query 上限（字符）。超过时提前拦截，省掉注定失败的一次调用。
API_QUERY_MAX_CHARS = 5000
# 网络层瞬时失败（非 API 错误码）的自动重试：仅"快速失败"时重试，避免超时叠加成
# 长时间阻塞 Alfred 界面。API 返回的错误码（如 202/411）不走这里。
DEFAULT_RETRIES = 1
DEFAULT_RETRY_BACKOFF = 0.2
DEFAULT_FAIL_FAST_WINDOW = 3.0

# 错误码 -> 友好中文提示（有道开放平台文本翻译接口文档的错误码表）
ERROR_MESSAGES = {
    "101": "缺少必填的参数",
    "102": "不支持的语言类型（请检查 yd_to / yd_cn_to 的语言代码）",
    "103": "翻译文本过长（单次上限 {} 字符）".format(API_QUERY_MAX_CHARS),
    "104": "不支持的 API 类型",
    "105": "不支持的签名类型（请检查 yd_sign 设置）",
    "106": "不支持的响应类型",
    "107": "不支持的传输加密类型",
    "108": "应用 ID 无效（请检查 yd_key）",
    "109": "batchLog 格式不正确",
    "110": "无相关服务的有效实例（请确认应用已绑定「文本翻译」服务）",
    "111": "开发者账号无效（请到有道智云控制台检查账号状态）",
    "112": "请求服务无效",
    "113": "查询内容为空",
    "201": "解密失败（BASE64 格式错误）",
    "202": "签名检验失败（请检查 yd_key / yd_secret；旧版应用可设 yd_sign=v1）",
    "203": "访问 IP 不在应用的 IP 白名单中",
    "205": "请求的接口与应用平台类型不一致",
    "206": "时间戳无效（请检查系统时间）",
    "207": "重放请求（同一请求被重复提交）",
    "301": "词典查询失败",
    "302": "翻译查询失败",
    "303": "服务端异常，请稍后重试",
    "304": "会话闲置超时，请稍后重试",
    "308": "请求参数不正确",
    "309": "账户请求超限，请稍后重试",
    "310": "访问频率受限，请稍后重试",
    "401": "账户已经欠费（请到有道智云控制台充值）",
    "411": "访问频率受限，请稍后重试",
    "412": "长请求过于频繁，请稍后重试",
}


def network_error_message(exc, retried=0):
    """把网络层异常转成用户能看懂的一句话（附重试次数）。"""
    prefix = "网络超时" if isinstance(exc, TimeoutError) else "网络请求失败"
    if retried:
        prefix += "（已自动重试 {} 次）".format(retried)
    return "{}: {}".format(prefix, exc)


class YoudaoError(Exception):
    """有道 API 返回错误码。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def input_text(q):
    """v3 签名的 input(q) 截断规则。"""
    if len(q) <= 20:
        return q
    return q[:10] + str(len(q)) + q[-10:]


def build_sign_v3(app_key, q, salt, curtime, secret):
    """v3 签名: md5(appKey + input(q) + salt + curtime + secret)。"""
    raw = app_key + input_text(q) + salt + curtime + secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def build_sign_v1(app_key, q, salt, secret):
    """旧版 v1 签名: md5(appKey + q + salt + secret)。

    仍有大量早期创建的有道应用只支持 v1 签名（如参考项目 V2.7.0 用户的 key），
    实测 v3 会返回 202 签名失败。自动回退可同时兼容新旧应用。
    """
    raw = app_key + q + salt + secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def build_params_v1(app_key, secret, q, to, from_lang="auto", salt=None):
    salt = salt if salt is not None else str(random.randint(1, 10 ** 9))
    sign = build_sign_v1(app_key, q, salt, secret)
    return {
        "q": q,
        "from": from_lang,
        "to": to,
        "appKey": app_key,
        "salt": salt,
        "sign": sign,
    }


def build_params_v3(app_key, secret, q, to, from_lang="auto", salt=None, curtime=None):
    """构造 v3 签名请求参数。salt/curtime 可注入以便测试。"""
    salt = salt if salt is not None else str(random.randint(1, 10 ** 9))
    curtime = curtime if curtime is not None else str(int(time.time()))
    sign = build_sign_v3(app_key, q, salt, curtime, secret)
    return {
        "q": q,
        "from": from_lang,
        "to": to,
        "appKey": app_key,
        "salt": salt,
        "sign": sign,
        "signType": "v3",
        "curtime": curtime,
    }


class YoudaoClient:
    """有道翻译 API 客户端。

    sign_mode:
        auto - 默认。先按 v3 签名请求，遇 202（签名失败）自动回退 v1 重试；
              兼容新旧两种有道应用。实际生效的签名方式记录在
              self.effective_sign，调用方可据此持久化（签名回退记忆），
              避免此后每次查询都多发一个注定失败的 v3 请求（请求量翻倍）。
        v3   - 仅 v3 签名（新应用）。
        v1   - 仅 v1 签名（早期创建的应用，可避免 auto 模式多余的失败重试）。
    """

    def __init__(self, key, secret, timeout=10, sign_mode="auto",
                 retries=DEFAULT_RETRIES, retry_backoff=DEFAULT_RETRY_BACKOFF,
                 fail_fast_window=DEFAULT_FAIL_FAST_WINDOW):
        self.key = key
        self.secret = secret
        self.timeout = timeout
        self.sign_mode = sign_mode
        self.retries = max(int(retries), 0)
        self.retry_backoff = max(float(retry_backoff), 0.0)
        self.fail_fast_window = max(float(fail_fast_window), 0.0)
        self.effective_sign = None   # 本次实际成功的签名方式："v3" / "v1"

    def translate(self, q, to, from_lang="auto"):
        """调用 API 并返回解析后的结果字典（原始 JSON）。"""
        try:
            data = self._request(q, to, from_lang, sign_mode="v1" if self.sign_mode == "v1" else "v3")
            self.effective_sign = "v1" if self.sign_mode == "v1" else "v3"
        except YoudaoError as exc:
            if self.sign_mode == "auto" and str(exc.code) == "202":
                # v3 签名不被该应用接受（旧版应用），回退 v1 重试
                data = self._request(q, to, from_lang, sign_mode="v1")
                self.effective_sign = "v1"
            else:
                raise
        return data

    def _request(self, q, to, from_lang, sign_mode):
        if sign_mode == "v1":
            params = build_params_v1(self.key, self.secret, q, to, from_lang=from_lang)
        else:
            params = build_params_v3(self.key, self.secret, q, to, from_lang=from_lang)
        body = urllib.parse.urlencode(params).encode("utf-8")
        started = time.time()
        data = None

        for attempt in range(self.retries + 1):
            request = urllib.request.Request(
                API_URL, data=body, method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "yd-translator/{} (Alfred workflow)".format(__version__),
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except Exception as exc:  # 网络/超时/JSON 解析异常
                # 4xx 是确定性失败（如 IP 白名单/HTTP 限流），重试没有意义；
                # 只在"快速失败"（耗时短）时重试，避免读超时叠加成 2 倍等待。
                permanent = isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500
                fast_failure = time.time() - started < self.fail_fast_window
                if attempt < self.retries and fast_failure and not permanent:
                    time.sleep(self.retry_backoff)
                    continue
                raise YoudaoError(-1, network_error_message(exc, attempt)) from exc

        if not isinstance(data, dict):
            raise YoudaoError(-1, "响应格式异常（不是 JSON 对象）")
        if "errorCode" not in data:
            raise YoudaoError(-1, "响应缺少 errorCode 字段")
        # 部分网关/代理会返回整数 0，统一转字符串再比较
        code = str(data.get("errorCode"))
        if code != "0":
            raise YoudaoError(code, ERROR_MESSAGES.get(code, "请参考错误码: {}".format(code)))
        return data


def response_lang_pair(data):
    """从响应中取出有道判定的 (源语言, 目标语言)。

    真实 API 字段为 `l`（如 `en2zh-CHS` / `en2en`），部分响应/测试用 `language`。
    缺失或格式异常时返回 ("", "")。
    """
    raw = (data or {}).get("l") or (data or {}).get("language") or ""
    if not isinstance(raw, str):
        return "", ""
    parts = raw.split("2", 1)
    if len(parts) != 2:
        return "", ""
    return parts[0].strip(), parts[1].strip()


def is_passthrough(data):
    """响应是否为「原样回显」——源语言 == 目标语言，等于没有翻译。

    典型场景：用户把 `to` 设成了文本自身的语言（如英文明细日志被判定为
    en2en），有道直接把原文返回。优先采用权威信号 `l` 的语种对；无该字段
    时退回「译文与原文逐字相同」的比较，但**排除**已明确给出异语种的响应
    （`OK → OK`、URL、哈希等本就同形的短文本不应触发重试）。

    v1.4.0 引入：yd.py 据此自动换另一个目标语言重试一次。
    """
    src, dst = response_lang_pair(data)
    if src and dst:
        return src.lower() == dst.lower()
    query = (data or {}).get("query") or ""
    translation = (data or {}).get("translation") or []
    if not query or not translation:
        return False
    first = translation[0] if isinstance(translation[0], str) else ""
    return bool(first.strip()) and first.strip() == query.strip()


def extract_rows(data):
    """把 API 响应解析为结构化的结果行列表。

    每行: {kind, title, subtitle, speak_word}
    kind: translation / phonetic / explain / web
    """
    rows = []
    query = data.get("query", "")
    translation = data.get("translation") or []
    basic = data.get("basic") or {}
    web = data.get("web") or []

    # 主翻译（speak_word 默认用查询词，发音用户输入的内容；
    # 中文查询时由 yd.py 覆盖为英文译文）
    if translation:
        rows.append({
            "kind": "translation",
            "title": translation[0],
            "subtitle": query,
            "speak_word": query,
        })

    # 音标
    phonetic = ""
    if basic.get("phonetic"):
        phonetic += "[{}] ".format(basic["phonetic"])
    if basic.get("us-phonetic"):
        phonetic += "[美: {}] ".format(basic["us-phonetic"])
    if basic.get("uk-phonetic"):
        phonetic += "[英: {}]".format(basic["uk-phonetic"])
    if phonetic.strip():
        rows.append({
            "kind": "phonetic",
            "title": phonetic.strip(),
            "subtitle": "回车复制 · Cmd 发音 · Alt 在线发音",
            "speak_word": query,
        })

    # 基本释义
    for explain in basic.get("explains") or []:
        rows.append({
            "kind": "explain",
            "title": explain,
            "subtitle": query,
            "speak_word": query,
        })

    # 网络释义
    for item in web:
        rows.append({
            "kind": "web",
            "title": ", ".join(item.get("value") or []),
            "subtitle": item.get("key", ""),
            "speak_word": item.get("key", ""),
        })

    return rows
