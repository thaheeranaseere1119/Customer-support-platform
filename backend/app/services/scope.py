"""Scope guard: Support IQ only answers telecom questions.

A message is in scope when the customer picked a support category, or it names a telecom service or device
(SIM, broadband, Wi-Fi, phone, roaming, ...). Words that are only *usually* telecom ("data", "calls") or merely
ambiguous ("bill", "account", "refund", "plan") count only when nothing places the message in another subject
("electricity bill", "bank account", "Amazon refund", "diet plan"); ambiguous words additionally need a matching
keyword rule, an ongoing telecom conversation, or a close resemblance to a known telecom issue. Anything else
gets a polite "sorry" redirect instead of a made-up answer, and creates no case, feedback request or review item.
"""
from __future__ import annotations

import re

from app.services.taxonomy import TaxonomySnapshot
from app.utils.text import clean_text

# Strong signals: a message containing one of these is about a telecom service.
# Whole words (telecom only as complete words: "sim" but not "simple") ...
STRONG_WORDS = {
    "sim", "sims", "esim", "e-sim", "puk", "imei", "cellular", "cellphone", "ont", "iptv", "otp", "5g", "4g", "3g",
    "lte", "volte", "operator", "carrier", "iphone", "android", "sms", "mms", "apn", "telco",
}
# ... and stems long enough to be safe as prefixes ("calls", "roaming", "recharged").
STRONG_PREFIXES = (
    "phone", "mobile", "smartphone", "handset", "internet", "wifi", "wi-fi", "broadband", "fibre", "fiber", "router",
    "modem", "hotspot", "tether", "voicemail", "landline", "recharg", "top-up", "topup", "tariff", "postpaid",
    "prepaid", "roam", "telecom", "smartwatch", "wearable", "self-care", "selfcare", "airtime", "outage",
    "bandwidth", "buffer", "latency", "connectivity",
)
# Usually telecom, but also used elsewhere ("data science", "a function call"): these count unless the
# message is clearly about another subject.
LIKELY_PREFIXES = ("data", "call", "dial", "network", "signal", "coverage", "tower", "deduct", "balance",
                   "contract")
LIKELY_WORDS = {"port", "porting", "ported", "number", "numbers", "kyc"}
# Ambiguous signals: telecom on a telecom help site ("my bill is too high"), but just as common elsewhere
# ("bank balance", "diet plan"). They count only when nothing marks the message as being about something else.
WEAK_WORDS = {
    "tv", "app", "apps", "pin", "log", "line", "lines", "portal", "pay", "paid", "paying", "plan", "plans", "pack",
    "packs", "text", "texts", "texting", "bill", "bills", "billed", "billing", "provider", "lan", "cell",
}
WEAK_PREFIXES = (
    "device", "message", "invoice", "charge", "refund", "payment", "bundle", "subscri", "abroad", "account", "login", "password", "passcode", "connect", "disconnect", "speed", "download",
    "upload", "stream", "activat", "deactivat", "upgrade", "unlock", "blocked", "netflix", "youtube", "whatsapp",
    "online", "offline",
)
# Words that place a message outside telecom when no strong telecom word is present
# ("my electricity bill", "Amazon refund", "Gmail password", "gym contract").
OTHER_TOPICS = {
    "bank", "banks", "banking", "atm", "loan", "loans", "mortgage", "rent", "insurance", "tax", "taxes", "salary",
    "stock", "stocks", "crypto", "bitcoin", "gmail", "google", "facebook", "instagram", "twitter", "tiktok",
    "amazon", "ebay", "flipkart", "uber", "electricity", "electric", "gas", "water", "gym", "recipe", "recipes",
    "cook", "cooking", "bake", "baking", "cake", "pizza", "food", "diet", "restaurant", "movie", "movies", "film",
    "films", "song", "songs", "lyrics", "laptop", "pc", "computer", "windows", "macbook", "python", "java",
    "javascript", "code", "coding", "programming", "science", "homework", "math", "maths", "football", "cricket",
    "weather", "flight", "flights", "hotel", "doctor", "medicine", "dog", "cat", "pet", "exam", "cheetah", "joke",
    "poem",
}  # deliberately not "car", "school" or "game": connected cars, school sites and gaming lag can be telecom issues
# With only ambiguous words, the message must also resemble a known telecom issue at least this closely.
WEAK_MIN_SIMILARITY = 0.5

SMALL_TALK = {
    "hi", "hello", "hey", "hiya", "thanks", "thank", "thankyou", "thx", "ty", "ok", "okay", "cool", "great",
    "bye", "goodbye", "good", "morning", "afternoon", "evening", "you", "so", "much", "a", "lot", "there",
    "yes", "no", "sure", "fine", "nice", "awesome", "perfect", "cheers",
}
# Short, vague problem reports ("it's not working", "help") get a clarifying question, not the off-topic reply.
_VAGUE_PROBLEM = re.compile(r"\b(help|not working|isn'?t working|doesn'?t work|stopped working|broken|problem|issue|"
                            r"nothing (loads|works)|won'?t (load|work)|can'?t connect|not loading)\b", re.I)
# "talk to a human", "I want an agent", "connect me to a person"
_HUMAN_REQUEST = re.compile(r"\b(talk|speak|chat|connect|transfer|want|need|get)\b.*\b(human|person|agent|"
                            r"representative|someone|somebody|staff)\b|^\s*(human|agent|representative)\s*[.!?]*\s*$",
                            re.I)
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")

OUT_OF_SCOPE_REPLY = ("Sorry, I can't help with that. I'm Support IQ, the assistant for your telecom services, so I can "
                      "only answer questions about your phone, mobile data, internet, SIM, calls, texts, plans and "
                      "bills. Is there anything about your telecom service I can help with?")
CLARIFY_REPLY = ("Sorry you're having trouble. Which service is affected: your phone, mobile data, home internet "
                 "or Wi-Fi, SIM, calls and texts, or your bill? A few words about what happens will help me find "
                 "the right fix.")
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


def is_vague_problem(text: str) -> bool:
    """A short problem report without any subject ("it's not working", "help", "nothing loads")."""
    words = _words(text)
    return 0 < len(words) <= 8 and bool(_VAGUE_PROBLEM.search(text)) and not any(w in OTHER_TOPICS for w in words)


def wants_human(text: str) -> bool:
    """The customer asks for a person in their own words ("talk to a human", "agent please")."""
    return len(_words(text)) <= 12 and bool(_HUMAN_REQUEST.search(text))


def is_telecom_question(text: str, *, taxonomy: TaxonomySnapshot, classification_method: str,
                        used_memory: bool, guided_category: str | None, top_similarity: float = 0.0) -> bool:
    """True when the message is about a telecom service; decides whether the assistant answers it at all."""
    if guided_category:
        return True
    words = _words(text)
    if any(w in STRONG_WORDS or w.startswith(STRONG_PREFIXES) for w in words):
        return True
    joined = f" {' '.join(words)} "
    product_phrases = (" ".join(tokens) for _, _, keyword_lists in taxonomy.products for tokens in keyword_lists)
    named_product = any(f" {phrase} " in joined for phrase in product_phrases if phrase)
    if any(w in OTHER_TOPICS for w in words):
        return False  # "my electricity bill", "data science": even if a keyword rule matched
    if any(w in LIKELY_WORDS or w.startswith(LIKELY_PREFIXES) for w in words):
        return True
    weak = any(w in WEAK_WORDS or w.startswith(WEAK_PREFIXES) for w in words)
    if used_memory or classification_method == "llm":
        return True
    if classification_method == "keyword_rules" and (weak or named_product):
        return True
    return (weak or named_product) and top_similarity >= WEAK_MIN_SIMILARITY
