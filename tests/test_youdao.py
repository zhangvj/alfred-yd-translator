"""youdao API 客户端测试：v1/v3 签名、参数、解析、错误映射、回退逻辑。"""
import hashlib
import unittest
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
        ):
            with self.assertRaises(YoudaoError) as ctx:
                YoudaoClient("k", "s", sign_mode="v3").translate("api", "zh-CHS")
        self.assertIn("网络", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
