"""youdao API 客户端测试：v1/v3 签名、参数、解析、错误映射、回退逻辑。"""
import hashlib
import io
import unittest
import urllib.error
from unittest import mock

from workflow.lib import youdao
from workflow.lib.youdao import (
    YoudaoClient,
    YoudaoError,
    build_params_v1,
    build_params_v3,
    build_sign_v1,
    build_sign_v3,
    extract_rows,
    input_text,
    is_passthrough,
    response_lang_pair,
)

FAKE_RESPONSE = {
    "errorCode": "0",
    "query": "api",
    "language": "en2zh-CHS",
    "translation": ["应用程序编程接口"],
    "basic": {
        "phonetic": "ˌeɪpiːˈaɪ",
        "us-phonetic": "ˌeɪpiːˈaɪ",
        "uk-phonetic": "ˌeɪpiːˈaɪ",
        "explains": ["n. 应用程序编程接口（Application Programming Interface）"],
    },
    "web": [{"key": "API", "value": ["应用程序接口", "应用程序编程接口"]}],
    "speakUrl": "https://dict.youdao.com/dictvoice?audio=api&type=2",
    "tSpeakUrl": "https://dict.youdao.com/dictvoice?audio=api&type=1",
}


class TestSign(unittest.TestCase):
    def test_build_sign_v3_known_value(self):
        # md5("appkey" + "hello" + "123" + "1000" + "secret")
        expected = hashlib.md5(b"appkeyhello1231000secret").hexdigest()
        self.assertEqual(build_sign_v3("appkey", "hello", "123", "1000", "secret"), expected)

    def test_build_sign_v1_known_value(self):
        # md5("appkey" + "hello" + "123" + "secret")
        expected = hashlib.md5(b"appkeyhello123secret").hexdigest()
        self.assertEqual(build_sign_v1("appkey", "hello", "123", "secret"), expected)

    def test_input_text_short(self):
        self.assertEqual(input_text("hello"), "hello")
        self.assertEqual(input_text("a" * 20), "a" * 20)

    def test_input_text_long_truncated(self):
        q = "x" * 100
        expected = q[:10] + "100" + q[-10:]
        self.assertEqual(input_text(q), expected)

    def test_build_params_v3(self):
        params = build_params_v3("k", "s", "hi", "zh-CHS", salt="1", curtime="2")
        self.assertEqual(params["appKey"], "k")
        self.assertEqual(params["from"], "auto")
        self.assertEqual(params["to"], "zh-CHS")
        self.assertEqual(params["signType"], "v3")
        self.assertEqual(params["curtime"], "2")
        self.assertEqual(params["salt"], "1")
        self.assertEqual(params["sign"], build_sign_v3("k", "hi", "1", "2", "s"))
        self.assertIn("signType", params)

    def test_build_params_v1(self):
        params = build_params_v1("k", "s", "hi", "zh-CHS", salt="1")
        self.assertEqual(params["sign"], build_sign_v1("k", "hi", "1", "s"))
        self.assertNotIn("signType", params)
        self.assertNotIn("curtime", params)


class TestParse(unittest.TestCase):
    def test_extract_rows_order(self):
        rows = extract_rows(FAKE_RESPONSE)
        kinds = [r["kind"] for r in rows]
        self.assertEqual(kinds, ["translation", "phonetic", "explain", "web"])
        self.assertEqual(rows[0]["title"], "应用程序编程接口")
        self.assertIn("美", rows[1]["title"])
        self.assertEqual(rows[3]["title"], "应用程序接口, 应用程序编程接口")

    def test_extract_rows_empty(self):
        self.assertEqual(extract_rows({"errorCode": "0"}), [])


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        import json
        return json.dumps(self._payload).encode("utf-8")


def _patch_urlopen(payloads):
    """按调用顺序依次返回不同响应。"""
    responses = [mock.MagicMock() for _ in payloads]
    for resp, payload in zip(responses, payloads):
        resp.__enter__.return_value = resp
        resp.read.return_value = __import__("json").dumps(payload).encode("utf-8")
    return mock.patch.object(
        youdao.urllib.request, "urlopen", side_effect=responses
    )


class TestClient(unittest.TestCase):
    def test_translate_success_v3(self):
        with _patch_urlopen([FAKE_RESPONSE]):
            data = YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertEqual(data["translation"], ["应用程序编程接口"])

    def test_translate_success_v1(self):
        with _patch_urlopen([FAKE_RESPONSE]):
            data = YoudaoClient("k", "s", sign_mode="v1").translate("api", "zh-CHS")
        self.assertEqual(data["translation"], ["应用程序编程接口"])

    def test_auto_fallback_v3_to_v1_on_202(self):
        """auto 模式：v3 返回 202 后自动用 v1 重试并成功。"""
        calls = []

        def fake_urlopen(req, timeout=None):
            body = req.data.decode("utf-8")
            calls.append(body)
            payload = {"errorCode": "202"} if "signType" in body else FAKE_RESPONSE
            resp = mock.MagicMock()
            resp.__enter__.return_value = resp
            resp.read.return_value = __import__("json").dumps(payload).encode("utf-8")
            return resp

        with mock.patch.object(youdao.urllib.request, "urlopen", side_effect=fake_urlopen):
            data = YoudaoClient("k", "s", sign_mode="auto").translate("api", "zh-CHS")
        self.assertEqual(len(calls), 2)
        self.assertIn("signType=v3", calls[0])
        self.assertNotIn("signType", calls[1])
        self.assertEqual(data["translation"], ["应用程序编程接口"])

    def test_auto_no_fallback_on_other_error(self):
        with _patch_urlopen([{"errorCode": "108"}]):
            with self.assertRaises(YoudaoError) as ctx:
                YoudaoClient("k", "s", sign_mode="auto").translate("api", "zh-CHS")
        self.assertEqual(ctx.exception.code, "108")

    def test_v3_mode_raises_202_without_fallback(self):
        with _patch_urlopen([{"errorCode": "202"}]):
            with self.assertRaises(YoudaoError) as ctx:
                YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertEqual(ctx.exception.code, "202")

    def test_translate_error_code(self):
        with _patch_urlopen([{"errorCode": "202", "message": "bad sign"}]):
            with self.assertRaises(YoudaoError) as ctx:
                YoudaoClient("k", "s", sign_mode="v1").translate("api", "zh-CHS")
        self.assertEqual(ctx.exception.code, "202")
        self.assertIn("签名", ctx.exception.message)

    def test_translate_unknown_error_code(self):
        with _patch_urlopen([{"errorCode": "999"}]):
            with self.assertRaises(YoudaoError) as ctx:
                YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertIn("999", ctx.exception.message)

    def test_translate_network_error(self):
        with mock.patch.object(
            youdao.urllib.request, "urlopen", side_effect=OSError("boom")
        ), mock.patch.object(youdao.time, "sleep"):
            with self.assertRaises(YoudaoError) as ctx:
                YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertEqual(ctx.exception.code, -1)
        self.assertIn("网络", ctx.exception.message)
        self.assertIn("已自动重试 1 次", ctx.exception.message)

    def test_integer_error_code_zero_is_success(self):
        """部分网关把 errorCode 返回成整数 0，不应被误判为失败。"""
        with _patch_urlopen([dict(FAKE_RESPONSE, errorCode=0)]):
            data = YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertEqual(data["translation"], ["应用程序编程接口"])

    def test_missing_error_code_field(self):
        with _patch_urlopen([{"translation": ["x"], "query": "x"}]):
            with self.assertRaises(YoudaoError) as ctx:
                YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertEqual(ctx.exception.code, -1)
        self.assertIn("errorCode", ctx.exception.message)

    def test_network_error_retries_once_when_fast(self):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            if len(calls) == 1:
                raise OSError("boom")
            resp = mock.MagicMock()
            resp.__enter__.return_value = resp
            resp.read.return_value = __import__("json").dumps(
                FAKE_RESPONSE).encode("utf-8")
            return resp

        with mock.patch.object(
            youdao.urllib.request, "urlopen", side_effect=fake_urlopen
        ), mock.patch.object(youdao.time, "sleep"):
            data = YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertEqual(len(calls), 2)          # 快速失败 → 自动重试一次
        self.assertEqual(data["translation"], ["应用程序编程接口"])

    def test_network_error_no_retry_when_slow(self):
        # fail_fast_window=0 视为慢失败：不重试，避免读超时叠加成 2 倍等待
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            raise OSError("boom")

        with mock.patch.object(
            youdao.urllib.request, "urlopen", side_effect=fake_urlopen
        ), mock.patch.object(youdao.time, "sleep"):
            client = YoudaoClient("k", "s", sign_mode="v3", fail_fast_window=0)
            with self.assertRaises(YoudaoError):
                client.translate("api", "zh-CHS")
        self.assertEqual(len(calls), 1)

    def test_http_4xx_not_retried(self):
        err = urllib.error.HTTPError(
            "https://openapi.youdao.com/api", 403, "Forbidden", {}, io.BytesIO(b""))
        self.addCleanup(err.close)
        with mock.patch.object(
            youdao.urllib.request, "urlopen", side_effect=err
        ), mock.patch.object(youdao.time, "sleep"):
            with self.assertRaises(YoudaoError) as ctx:
                YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertIn("403", ctx.exception.message)

    def test_user_agent_carries_version(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["ua"] = [
                v for k, v in req.header_items() if k.lower() == "user-agent"
            ][0]
            resp = mock.MagicMock()
            resp.__enter__.return_value = resp
            resp.read.return_value = __import__("json").dumps(
                FAKE_RESPONSE).encode("utf-8")
            return resp

        with mock.patch.object(
            youdao.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertIn("yd-translator/{}".format(youdao.__version__), captured["ua"])

    def test_error_message_table_covers_common_codes(self):
        with _patch_urlopen([{"errorCode": "203"}]):
            with self.assertRaises(YoudaoError) as ctx:
                YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertIn("IP", ctx.exception.message)


class TestPassthrough(unittest.TestCase):
    """回显检测：源语言 == 目标语言时 API 原样返回，等于没翻译。"""

    def test_same_pair_is_passthrough(self):
        self.assertTrue(is_passthrough({"l": "en2en", "query": "hi", "translation": ["hi"]}))
        self.assertTrue(is_passthrough({"l": "zh-CHS2zh-CHS"}))

    def test_different_pair_is_not_passthrough(self):
        self.assertFalse(is_passthrough({"l": "en2zh-CHS", "query": "hi", "translation": ["你好"]}))

    def test_language_alias_supported(self):
        # 部分响应/测试 fixture 用 language 而非 l
        self.assertTrue(is_passthrough({"language": "en2en"}))
        self.assertFalse(is_passthrough({"language": "en2zh-CHS"}))

    def test_pair_case_insensitive(self):
        self.assertTrue(is_passthrough({"l": "EN2EN"}))

    def test_missing_pair_falls_back_to_text_compare(self):
        self.assertTrue(is_passthrough({"query": "hello world", "translation": ["hello world"]}))
        self.assertFalse(is_passthrough({"query": "hello", "translation": ["你好"]}))

    def test_identical_text_but_explicit_other_pair_is_not_passthrough(self):
        # 「OK → OK」这类同形短词/URL/哈希：l 明示异语种，不该误触重试
        data = {"l": "en2zh-CHS", "query": "OK", "translation": ["OK"]}
        self.assertFalse(is_passthrough(data))

    def test_empty_or_missing_translation(self):
        self.assertFalse(is_passthrough({}))
        self.assertFalse(is_passthrough({"query": "hi", "translation": []}))
        self.assertFalse(is_passthrough(None))

    def test_response_lang_pair_parsing(self):
        self.assertEqual(response_lang_pair({"l": "en2zh-CHS"}), ("en", "zh-CHS"))
        self.assertEqual(response_lang_pair({"l": "en2en"}), ("en", "en"))
        self.assertEqual(response_lang_pair({"l": "garbage"}), ("", ""))
        self.assertEqual(response_lang_pair({}), ("", ""))


if __name__ == "__main__":
    unittest.main()
