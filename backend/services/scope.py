"""Scope guard: Support IQ only answers telecom questions.

A message is in scope when it mentions telecom vocabulary (services, devices, billing, accounts),
matches a taxonomy keyword or product, is a follow-up inside an ongoing telecom conversation, or
the customer picked a support category. Anything else (pets, recipes, homework, ...) gets a polite
redirect instead of a made-up answer, and creates no case, feedback request or review item.
"""
from __future__ import annotations

import re

from app.services.taxonomy import TaxonomySnapshot
from app.utils.text import clean_text

# Whole words that are telecom only as complete words ("sim" but not "simple", "plan" but not "plant").
TELECOM_WORDS = {
    "sim", "sims", "esim", "e-sim", "puk", "imei", "cell", "cellular", "cellphone", "ont", "lan", "tv", "iptv",
    "app", "apps", "pin", "log", "line", "lines", "port", "porting", "ported", "portal", "pay", "paid", "paying",
    "plan", "plans", "pack", "packs", "text", "texts", "texting", "otp", "5g", "4g", "3g", "lte", "volte",
    "bill", "bills", "billed", "billing", "kyc", "operator", "carrier", "provider", "number", "numbers",
}
# Stems long enough to be safe as prefixes, so "charged", "recharging", "calls" and "roaming" all match.
TELECOM_PREFIXES = (
    "phone", "mobile", "smartphone", "handset", "device", "network", "signal", "coverage", "tower",
    "data", "internet", "wifi", "wi-fi", "broadband", "fibre", "fiber", "router", "modem", "hotspot", "tether",
    "call", "dial", "voicemail", "voice", "sms", "mms", "message", "landline", "invoice", "charge", "recharg",
    "top-up", "topup", "balance", "refund", "payment", "deduct", "tariff", "bundle", "subscri", "contract",
    "postpaid", "prepaid", "roam", "abroad", "account", "login", "password", "passcode", "connect",
    "disconnect", "outage", "speed", "bandwidth", "download", "upload", "stream", "telecom", "activat",
    "deactivat", "upgrade", "smartwatch", "wearable", "self-care", "selfcare", "unlock", "blocked", "porting",
    "buffer", "latency", "netflix", "youtube", "whatsapp", "online", "offline",
)
SMALL_TALK = {
    "hi", "hello", "hey", "hiya", "thanks", "thank", "thankyou", "thx", "ty", "ok", "okay", "cool", "great",
    "bye", "goodbye", "good", "morning", "afternoon", "evening", "you", "so", "much", "a", "lot", "there",
    "yes", "no", "sure", "fine", "nice", "awesome", "perfect", "cheers",
}
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")

OUT_OF_SCOPE_REPLY = ("I'm Support IQ, the assistant for your telecom services, so I can only answer questions about "
                      "your phone, mobile data, internet, SIM, calls, plans and bills. That question is outside "
                      "what I can help with here. Is there anything about your telecom service I can help with?")
GREETING_REPLY = "Hi! Tell me what's going on with your phone, internet, SIM or bill, and I'll help you sort it out."
THANKS_REPLY = "You're welcome! If anything else comes up with your phone, internet, SIM or bill, just message me here."


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(clean_text(text).lower())


def small_talk_reply(text: str) -> str | None:
    """A friendly reply for greetings and thanks, which are not questions at all."""
    words = _words(text)
    if not words or len(words) > 6 or any(w not in SMALL_TALK for w in words):
        return None
    return THANKS_REPLY if any(w.startswith(("thank", "thx", "ty", "cheers")) for w in words) else GREETING_REPLY


def is_telecom_question(text: str, *, taxonomy: TaxonomySnapshot, classification_method: str,
                        used_memory: bool, guided_category: str | None) -> bool:
    if guided_category or used_memory or classification_method in ("keyword_rules", "llm"):
        return True
    words = _words(text)
    if any(w in TELECOM_WORDS or w.startswith(TELECOM_PREFIXES) for w in words):
        return True
    joined = f" {' '.join(words)} "
    product_phrases = (" ".join(tokens) for _, _, keyword_lists in taxonomy.products for tokens in keyword_lists)
    return any(f" {phrase} " in joined for phrase in product_phrases if phrase)
