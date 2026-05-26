import hashlib
import time
import urllib.parse
import urllib.request
import json as json_mod

from fastapi import APIRouter

from backend.schemas import TranslationRequest, TranslationOut

router = APIRouter(prefix="/api/translate", tags=["translation"])

# Simple built-in dictionary fallback — swap with Baidu/Google API in production
_ZH_EN_MAP = {
    "欢迎参加会议": "Welcome to the meeting",
    "欢迎": "Welcome",
    "谢谢": "Thank you",
    "你好": "Hello",
    "再见": "Goodbye",
    "请投票": "Please vote",
    "我同意": "I agree",
    "我反对": "I disagree",
    "弃权": "Abstain",
    "会议开始": "Meeting starts",
    "会议结束": "Meeting ends",
    "请发言": "Please speak",
    "提案一": "Proposal One",
    "提案二": "Proposal Two",
    "服务": "Service",
    "咖啡": "Coffee",
    "茶水": "Tea",
    "签到": "Check in",
}


@router.post("", response_model=TranslationOut)
def translate(data: TranslationRequest):
    text = data.text.strip()
    source = data.source_lang
    target = data.target_lang

    if source == "zh" and target == "en":
        translated = _ZH_EN_MAP.get(text)
        if translated is None:
            # fallback: try Baidu translate API if credentials configured,
            # otherwise return pinyin-like indication
            translated = f"[EN] {text}"
    elif source == "en" and target == "zh":
        reverse = {v: k for k, v in _ZH_EN_MAP.items()}
        translated = reverse.get(text, f"[ZH] {text}")
    else:
        translated = text

    return TranslationOut(
        original=text,
        translated=translated,
        source_lang=source,
        target_lang=target,
    )
