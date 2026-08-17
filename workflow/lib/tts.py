"""发音 URL：优先使用 API 返回的 speakUrl（美音）/ tSpeakUrl（英音），
缺省时用有道词典 dictvoice 兜底。"""
import urllib.parse

DICTVOICE_URL = "https://dict.youdao.com/dictvoice"


def fallback_speak_url(word, voice="en"):
    """dictvoice 兜底 URL。voice: en(美音 type=2) / uk(英音 type=1)。"""
    audio_type = 2 if voice == "en" else 1
    return "{}?audio={}&type={}".format(
        DICTVOICE_URL, urllib.parse.quote(word), audio_type
    )


def pick_speak_url(data, voice="en"):
    """从 API 响应中选择发音 URL；返回 (url, 说明)。"""
    if voice == "uk":
        url = (data or {}).get("tSpeakUrl")
        label = "英音"
    else:
        url = (data or {}).get("speakUrl")
        label = "美音"
    if url:
        return url, label
    word = (data or {}).get("query", "")
    return fallback_speak_url(word, voice), label
