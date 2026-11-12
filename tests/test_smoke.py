"""端到端冒烟测试：mock 网络层后运行 yd.py 入口，验证 Alfred JSON 结构。"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

WORKFLOW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workflow")
sys.path.insert(0, os.path.abspath(WORKFLOW_DIR))

import yd  # noqa: E402  (导入 workflow/yd.py 入口)

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
    "web": [{"key": "API", "value": ["应用程序接口"]}],
    "speakUrl": "https://dict.youdao.com/dictvoice?audio=api&type=2",
    "tSpeakUrl": "https://dict.youdao.com/dictvoice?audio=api&type=1",
}

ENV = {
    "yd_key": "test-key",
    "yd_secret": "test-secret",
    "yd_to": "zh-CHS",
    "yd_cn_to": "en",
    "yd_voice": "en",
}


def run_yd(argv, env=None, response=FAKE_RESPONSE, translate_side_effect=None,
           translate_impl=None):
    """以给定 argv 运行 yd.main，mock translate，返回 (exit_json, translate_call)。

    - 默认注入独立临时 YD_DATA_DIR，避免污染真实数据目录、用例间互不影响；
      传入 env["YD_DATA_DIR"] 可让多次调用共享状态（测缓存/限速/冷却/链式）。
    - time.sleep 被打桩，限速等待不会真正阻塞。
    - translate_side_effect(q, to) 可注入异常（如 411）等自定义行为。
    - translate_impl(client_self, q, to, from_lang) 完全替换 translate 实现
      （如模拟签名回退：设置 client.effective_sign）。
    """
    calls = {}

    def fake_translate(client_self, q, to, from_lang="auto"):
        calls["q"] = q
        calls["to"] = to
        calls["n"] = calls.get("n", 0) + 1
        calls.setdefault("qs", []).append(q)       # 调用历史（每次真实请求的 q）
        calls.setdefault("tos", []).append(to)
        if translate_impl is not None:
            return translate_impl(client_self, q, to, from_lang)
        if translate_side_effect is not None:
            return translate_side_effect(q, to)
        # 真实 API 会在响应中回显 query
        return dict(response, query=q)

    data_dir = tempfile.mkdtemp(prefix="yd-test-")
    env = dict(env or {})
    env.setdefault("YD_DATA_DIR", data_dir)
    buf = io.StringIO()
    try:
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(yd.YoudaoClient, "translate", new=fake_translate):
                with mock.patch.object(yd.time, "sleep"):
                    with redirect_stdout(buf):
                        yd.main(argv)
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    return json.loads(buf.getvalue()), calls


class TestSmoke(unittest.TestCase):
    def test_empty_query_hint(self):
        result, _ = run_yd([""])
        self.assertEqual(len(result["items"]), 1)
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("输入要翻译", result["items"][0]["title"])

    def test_missing_key_hint(self):
        result, _ = run_yd(["hello"], env={})
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("Key", result["items"][0]["title"])

    def test_untranslatable_hint(self):
        result, _ = run_yd(["!!!"], env=ENV)
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("无法翻译", result["items"][0]["title"])

    def test_translation_structure(self):
        result, calls = run_yd(["API"], env=ENV)
        self.assertEqual(calls["q"], "API")          # 全大写缩写保留原样
        self.assertEqual(calls["to"], "zh-CHS")
        items = result["items"]
        self.assertGreaterEqual(len(items), 3)
        first = items[0]
        self.assertEqual(first["arg"], "应用程序编程接口")
        self.assertEqual(first["text"]["copy"], "应用程序编程接口")
        self.assertIn("youdao.com/w/API", first["quicklookurl"])  # 网页预览用原词
        self.assertIn("cmd", first["mods"])
        self.assertIn("alt", first["mods"])
        self.assertIn("shift", first["mods"])
        self.assertEqual(first["mods"]["cmd"]["arg"], "API")   # Cmd 发音词 = 原词
        self.assertIn("https://", first["mods"]["alt"]["arg"])  # Alt 在线发音 = TTS URL
        self.assertIn("youdao.com/w/API", first["mods"]["shift"]["arg"])  # Shift 打开网页

    def test_chinese_to_english(self):
        result, calls = run_yd(["你好世界"], env=ENV)
        self.assertEqual(calls["q"], "你好世界")
        self.assertEqual(calls["to"], "en")

    def test_snake_case_normalized(self):
        _, calls = run_yd(["USER_NAME"], env=ENV)
        self.assertEqual(calls["q"], "USER NAME")

    def test_uk_voice_picks_tspeak(self):
        result, _ = run_yd(["hello"], env=dict(ENV, yd_voice="uk"))
        self.assertIn("英音", result["items"][0]["mods"]["alt"]["subtitle"])

    def test_en_query_speaks_original_word(self):
        # 英文查询：Cmd 发音应读用户输入的原词
        result, _ = run_yd(["hello"], env=ENV)
        self.assertEqual(result["items"][0]["mods"]["cmd"]["arg"], "hello")

    def test_cn_query_speaks_translation(self):
        # 中文查询：Cmd 发音应读英文译文
        result, _ = run_yd(["你好世界"], env=ENV)
        self.assertEqual(
            result["items"][0]["mods"]["cmd"]["arg"],
            "应用程序编程接口",
        )

    def test_setkey_persists_to_data_dir(self):
        # yd setkey 写入数据目录，且不经过翻译 API（环境变量不含 key，避免覆盖）
        cmd_env = {"yd_to": "zh-CHS", "yd_cn_to": "en", "yd_voice": "en", "yd_sign": "auto"}
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(cmd_env, YD_DATA_DIR=tmp)
            result, _ = run_yd(["setkey", "TESTKEY123"], env=env)
            self.assertIn("已保存", result["items"][0]["title"])
            with open(os.path.join(tmp, "config.json")) as f:
                saved = json.load(f)
            self.assertEqual(saved["yd_key"], "TESTKEY123")

    def test_config_reads_saved_key(self):
        cmd_env = {"yd_to": "zh-CHS", "yd_cn_to": "en", "yd_voice": "en", "yd_sign": "auto"}
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(cmd_env, YD_DATA_DIR=tmp)
            run_yd(["setkey", "TESTKEY123"], env=env)
            run_yd(["setsecret", "TESTSECRET"], env=env)
            result, _ = run_yd(["config"], env=env)
            titles = " | ".join(
                it["title"] + " " + it.get("subtitle", "") for it in result["items"]
            )
            self.assertIn("TEST****23", titles)   # 掩码显示
            self.assertIn("数据文件(更新保留)", titles)

    def test_reset_clears_config(self):
        cmd_env = {"yd_to": "zh-CHS", "yd_cn_to": "en", "yd_voice": "en", "yd_sign": "auto"}
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(cmd_env, YD_DATA_DIR=tmp)
            run_yd(["setkey", "K"], env=env)
            result, _ = run_yd(["reset"], env=env)
            self.assertIn("已清除", result["items"][0]["title"])
            self.assertFalse(os.path.exists(os.path.join(tmp, "config.json")))

    def test_version_command(self):
        result, _ = run_yd(["version"], env=ENV)
        self.assertIn("yd-translator v", result["items"][0]["title"])

    def test_long_text_precheck_avoids_api_call(self):
        # 超过有道单次 5000 字符上限：提前拦截，零调用（不浪费额度）
        result, calls = run_yd(["word " * 1001], env=ENV)
        self.assertEqual(calls, {})
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("文本太长", result["items"][0]["title"])
        self.assertIn("5000", result["items"][0]["subtitle"])

    def test_escape_dot_preserved_in_normal_sentence(self):
        # 普通句末标点不应被剥掉（只有拼音/链式"输入中"才把 "." 当逃逸口）
        _, calls = run_yd(["Hello world."], env=ENV)
        self.assertEqual(calls["q"], "hello world.")

    def test_escape_dot_still_bypasses_defer(self):
        # 拼音组词态 + 末尾 "." → 仍按逃逸口处理（剥掉句点、立即翻译）
        _, calls = run_yd(["nihao."], env=ENV)
        self.assertEqual(calls["q"], "nihao")

    def test_quicklook_encodes_slash(self):
        # 查询里的 "/" 不能原样留在网页路径中，否则有道 404
        result, calls = run_yd(["A/B"], env=ENV)
        self.assertEqual(calls["q"], "A/B")
        self.assertIn("A%2FB", result["items"][0]["quicklookurl"])

    def test_network_error_has_dedicated_title(self):
        def boom(q, to):
            raise yd.YoudaoError(-1, "网络请求失败: boom")

        result, _ = run_yd(["hello"], env=ENV, translate_side_effect=boom)
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("网络请求失败", result["items"][0]["title"])


class TestGuardChain(unittest.TestCase):
    """防刷量守卫链：输入演进延迟 / 疑似组词 / 缓存 / 限速 / 411 指数冷却。"""

    def test_pinyin_composition_defers(self):
        # 已上屏+组词混合态：零调用，输出"等待输入完成"并带 rerun
        result, calls = run_yd(["你好shijie"], env=ENV)
        self.assertEqual(calls, {})
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("等待输入", result["items"][0]["title"])
        self.assertIn("rerun", result)

    def test_pure_pinyin_suspect_defers(self):
        result, calls = run_yd(["nihao"], env=ENV)
        self.assertEqual(calls, {})
        self.assertIn("rerun", result)

    def test_single_syllable_suspect_defers(self):
        # v1.2.0 会放行单音节（泄漏），v1.3.0 软判定延后，零调用
        result, calls = run_yd(["da"], env=ENV)
        self.assertEqual(calls, {})
        self.assertIn("rerun", result)

    def test_unparseable_prefix_suspect_defers(self):
        result, calls = run_yd(["nih"], env=ENV)   # ni+h…，补全可成拼音
        self.assertEqual(calls, {})
        self.assertIn("rerun", result)

    def test_english_words_not_suspect(self):
        # 非拼音形态的英文查询不受影响（误伤代价仅存在于拼音形词 +1s 延迟）
        for q in ("hello", "apple", "xyz", "abc"):
            _, calls = run_yd([q], env=ENV)
            self.assertEqual(calls.get("n"), 1, q)

    def test_suspect_stable_rerun_translates(self):
        # 疑似组词 → 延后；回访（同查询、已达延迟）→ 正常翻译
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp, yd_defer_delay="0")
            r1, c1 = run_yd(["nihao"], env=env)
            self.assertEqual(c1, {})
            r2, c2 = run_yd(["nihao"], env=env)
            self.assertEqual(c2.get("n"), 1)
            self.assertNotIn("rerun", r2)

    def test_force_dot_bypasses_defer(self):
        # 末尾 "." 强制立即翻译（句点会被剥掉）
        result, calls = run_yd(["nihao."], env=ENV)
        self.assertEqual(calls.get("n"), 1)
        self.assertEqual(calls["q"], "nihao")
        self.assertNotIn("rerun", result)

    def test_chained_phrase_commits_merge(self):
        # 逐词上屏链：你 → 你在（前缀扩展，3.5s 内）→ 第二次零调用
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp)
            r1, c1 = run_yd(["你"], env=env)
            self.assertEqual(c1.get("n"), 1)        # 首查询直接翻译
            r2, c2 = run_yd(["你在"], env=env)
            self.assertEqual(c2, {})                # 演进中间态 → 延后
            self.assertIn("rerun", r2)
            _, c3 = run_yd(["你在干什么"], env=env)  # 继续演进 → 仍零调用
            self.assertEqual(c3, {})

    def test_backspace_edit_chains(self):
        # 退格编辑：...damk a → ...damk（截断）也属于演进中间态
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp)
            run_yd(["what do you think damk a"], env=env)
            _, calls = run_yd(["what do you think damk"], env=env)
            self.assertEqual(calls, {})

    def test_pinyin_guard_can_be_disabled(self):
        result, calls = run_yd(["nihao"], env=dict(ENV, yd_pinyin_guard="0"))
        self.assertEqual(calls.get("n"), 1)   # 关闭后照常翻译
        self.assertNotEqual(result["items"][0].get("valid"), False)

    def test_mixed_english_query_still_translated(self):
        # 非拼音的混合查询不受组词检测影响
        result, calls = run_yd(["苹果iphone"], env=ENV)
        self.assertEqual(calls.get("n"), 1)
        self.assertNotEqual(result["items"][0].get("valid"), False)

    def test_repeat_query_served_from_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp)
            r1, c1 = run_yd(["API"], env=env)
            self.assertEqual(c1.get("n"), 1)
            r2, c2 = run_yd(["API"], env=env)   # 同数据目录二次查询
            self.assertEqual(c2, {})            # 缓存命中，零调用
            self.assertEqual(r2["items"][0]["title"], r1["items"][0]["title"])
            self.assertEqual(r2["items"][0]["arg"], r1["items"][0]["arg"])

    def test_different_target_not_shared(self):
        # 同一查询不同目标语言不能共用缓存（中↔英结果不同）
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp, yd_cn_to="fr")
            run_yd(["你好世界"], env=env)
            _, calls = run_yd(["你好世界"], env=dict(env, yd_cn_to="en"))
            self.assertEqual(calls.get("n"), 1)

    def test_rate_window_blocks_burst(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp,
                       yd_max_per_window="2", yd_min_interval="0")
            run_yd(["API"], env=env)
            run_yd(["hello"], env=env)
            result, calls = run_yd(["world"], env=env)
            self.assertEqual(calls, {})                       # 第 3 次被拒绝
            self.assertFalse(result["items"][0]["valid"])
            self.assertIn("频繁", result["items"][0]["title"])

    def test_411_sets_cooldown_then_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp)

            def boom(q, to):
                raise yd.YoudaoError("411", "访问频率受限")

            r1, c1 = run_yd(["你好世界"], env=env, translate_side_effect=boom)
            self.assertEqual(c1.get("n"), 1)
            self.assertIn("411", r1["items"][0]["title"])

            # 冷却期内：零调用，提示自动恢复
            r2, c2 = run_yd(["你好世界"], env=env)
            self.assertEqual(c2, {})
            self.assertFalse(r2["items"][0]["valid"])
            self.assertIn("恢复", r2["items"][0].get("subtitle", ""))

    def test_single_letter_hint(self):
        result, calls = run_yd(["a"], env=ENV)
        self.assertEqual(calls, {})
        self.assertIn("字符", result["items"][0]["title"])

    def test_sign_fallback_memory_persisted(self):
        # auto 模式 v3 被拒(202)、v1 成功 → config.json 记住 yd_sign=v1，
        # 此后每次查询单请求直达（请求量减半）
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp)

            def impl(client_self, q, to, from_lang="auto"):
                client_self.effective_sign = "v1"
                return dict(FAKE_RESPONSE, query=q)

            run_yd(["API"], env=env, translate_impl=impl)
            with open(os.path.join(tmp, "config.json")) as f:
                saved = json.load(f)
            self.assertEqual(saved.get("yd_sign"), "v1")

    def test_sign_memory_skipped_when_v3_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp)

            def impl(client_self, q, to, from_lang="auto"):
                client_self.effective_sign = "v3"
                return dict(FAKE_RESPONSE, query=q)

            run_yd(["API"], env=env, translate_impl=impl)
            self.assertFalse(os.path.exists(os.path.join(tmp, "config.json")))

    def test_config_shows_guard_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = run_yd(["config"], env=dict(ENV, YD_DATA_DIR=tmp))
            text = " | ".join(
                it["title"] + " " + it.get("subtitle", "") for it in result["items"]
            )
            self.assertIn("组词检测", text)
            self.assertIn("限速", text)


class TestPassthroughFallback(unittest.TestCase):
    """回显兜底：源语言==目标语言（en2en）时自动换目标语言重试，仍回显则提示。"""

    # 真实触发过问题的文本：英文错误日志里嵌了一个中文词
    MIXED_LOG = (
        "CC Switch local proxy failed while handling Codex endpoint /responses. "
        "Provider: 公司; model: ccs-qianwenai/deepseek-v4.1-flash-1017; "
        "upstream_status: HTTP 400; cause: Invalid 'call_id': call_id is required "
        "for function_call_output"
    )

    def _passthrough_response(self, q):
        return {"errorCode": "0", "query": q, "l": "en2en", "translation": [q]}

    def test_mixed_log_text_targets_chinese(self):
        # 快路径：长文本拉丁主导 → 直接翻译成中文（不再发 en→en 的白费请求）
        _, calls = run_yd([self.MIXED_LOG], env=ENV)
        self.assertEqual(calls["to"], "zh-CHS")

    def test_mixed_log_text_masks_embedded_chinese(self):
        # 中文目标下已有中文片段被打码后送翻译，模型保留标记 → 还原为原文
        def impl(client_self, q, to, from_lang="auto"):
            translation = q.replace("Provider: [[C0]]", "提供方：[[C0]]")
            return {"errorCode": "0", "query": q, "l": "en2zh-CHS",
                    "translation": [translation]}

        result, calls = run_yd([self.MIXED_LOG], env=ENV, translate_impl=impl)
        self.assertEqual(calls["n"], 1)                          # 仍只调用一次
        self.assertEqual(calls["to"], "zh-CHS")
        self.assertIn("[[C0]]", calls["q"])                      # 中文片段被保护
        self.assertNotIn("公司", calls["q"])
        title = result["items"][0]["title"]
        self.assertIn("公司", title)                             # 原样保留
        self.assertNotIn("[[C", title)                           # 不泄漏占位符
        self.assertNotIn("五星", title)

    def test_marker_loss_degrades_to_plain_request(self):
        # 模型吞掉占位符（实测未发生）→ 退回未掩码请求，保证内容完整
        result, calls = run_yd([self.MIXED_LOG], env=ENV)
        self.assertEqual(calls["n"], 2)
        self.assertIn("[[C0]]", calls["qs"][0])                  # 首次带保护
        self.assertNotIn("[[C", calls["qs"][1])                  # 降级用未掩码原文
        self.assertEqual(result["items"][0]["title"], "应用程序编程接口")
        self.assertNotIn("[[C", result["items"][0]["title"])

    def test_short_mixed_text_not_masked(self):
        # 短混排（目标 en）不做中文保护：公司 应照常参与翻译
        def impl(client_self, q, to, from_lang="auto"):
            return {"errorCode": "0", "query": q, "l": "zh-CHS2en",
                    "translation": [q.replace("公司", "Company")]}

        result, calls = run_yd(["Provider: 公司; model: x"], env=ENV, translate_impl=impl)
        self.assertNotIn("[[C", calls["q"])
        self.assertIn("Company", result["items"][0]["title"])

    def test_non_chinese_target_not_masked(self):
        # 目标非中文（如 ja）：中文片段照常参与翻译，不掩码
        env = dict(ENV, yd_to="ja")
        _, calls = run_yd([self.MIXED_LOG], env=env)
        self.assertNotIn("[[C", calls["q"])

    def test_passthrough_retries_alternate_target(self):
        # 首次目标语言回显 → 自动换另一目标语言重试并采用其结果
        def impl(client_self, q, to, from_lang="auto"):
            if to == "zh-CHS":
                return self._passthrough_response(q)
            return dict(FAKE_RESPONSE, query=q)

        result, calls = run_yd(["hello there my friend"], env=ENV, translate_impl=impl)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(calls["to"], "en")                      # 末次为备选目标
        self.assertEqual(result["items"][0]["title"], "应用程序编程接口")

    def test_passthrough_retry_result_is_cached(self):
        def impl(client_self, q, to, from_lang="auto"):
            if to == "zh-CHS":
                return self._passthrough_response(q)
            return dict(FAKE_RESPONSE, query=q)

        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp)
            run_yd(["hello there my friend"], env=env, translate_impl=impl)
            result, calls = run_yd(["hello there my friend"], env=env, translate_impl=impl)
            self.assertEqual(calls, {})                          # 二次零调用
            self.assertEqual(result["items"][0]["title"], "应用程序编程接口")

    def test_still_passthrough_shows_actionable_hint(self):
        def impl(client_self, q, to, from_lang="auto"):
            return self._passthrough_response(q)

        result, calls = run_yd(["hello there my friend"], env=ENV, translate_impl=impl)
        self.assertEqual(calls["n"], 2)                          # 只重试一次，不死循环
        item = result["items"][0]
        self.assertFalse(item["valid"])
        self.assertIn("未能翻译", item["title"])
        self.assertIn("en → en", item["subtitle"])

    def test_cached_passthrough_hints_without_api_call(self):
        def impl(client_self, q, to, from_lang="auto"):
            return self._passthrough_response(q)

        with tempfile.TemporaryDirectory() as tmp:
            env = dict(ENV, YD_DATA_DIR=tmp)
            run_yd(["hello there my friend"], env=env, translate_impl=impl)
            result, calls = run_yd(["hello there my friend"], env=env, translate_impl=impl)
            self.assertEqual(calls, {})                          # 命中缓存，零调用
            self.assertFalse(result["items"][0]["valid"])
            self.assertIn("未能翻译", result["items"][0]["title"])

    def test_no_alternate_target_skips_retry(self):
        # yd_to == yd_cn_to → 无备选目标，只调用一次并给提示
        env = dict(ENV, yd_to="en", yd_cn_to="en")

        def impl(client_self, q, to, from_lang="auto"):
            return self._passthrough_response(q)

        result, calls = run_yd(["hello there"], env=env, translate_impl=impl)
        self.assertEqual(calls["n"], 1)
        self.assertFalse(result["items"][0]["valid"])
        self.assertIn("未能翻译", result["items"][0]["title"])

    def test_empty_result_hint(self):
        # 响应既无译文也无释义 → 不再输出空 items 列表
        result, _ = run_yd(["hello world"], env=ENV,
                           response={"errorCode": "0", "query": "hello world"})
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("未获取到翻译结果", result["items"][0]["title"])


if __name__ == "__main__":
    unittest.main()
