"""Shared text normalisation used by classification, BM25 and hashing embeddings."""
from __future__ import annotations

import hashlib
import re

STOPWORDS = frozenset(
    """a an the is are was were be been being am i me my mine we our you your it its this that these those to of on in
    at for and or with as by from have has had do did please very really so just also there their them they he she his
    her im ive id can could would should will shall may might about into than then too some any all every""".split()
)
# Words kept for meaning even though they are common: not, no, but, cannot, keep(s), again, still
_CONTRACTIONS = {
    "can't": "cannot", "cant": "cannot", "won't": "will not", "don't": "do not", "doesn't": "does not",
    "isn't": "is not", "aren't": "are not", "didn't": "did not", "i'm": "i am", "it's": "it is", "wasn't": "was not",
    "haven't": "have not", "hasn't": "has not", "couldn't": "could not",
}
_SYNONYMS = {"wi-fi": "wifi", "wi fi": "wifi", "e-sim": "esim", "log-in": "log in", "sign-in": "sign in",
             "re-start": "restart", "rebooted": "restarted", "reboot": "restart", "recognise": "recognize",
             "recognised": "recognized", "unauthorised": "unauthorized", "top-up": "top up"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
SYNTHETIC_TAG_RE = re.compile(r"\s*\[synthetic case \d+\]", re.IGNORECASE)


def clean_text(text: str) -> str:
    text = (text or "").lower().replace("’", "'")
    for src, dst in _SYNONYMS.items():
        text = text.replace(src, dst)
    for src, dst in _CONTRACTIONS.items():
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
    return text


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    tokens = _TOKEN_RE.findall(clean_text(text))
    if keep_stopwords:
        return tokens
    return [t for t in tokens if t not in STOPWORDS]


def stem(token: str) -> str:
    """Very light suffix stripping so 'drops'/'dropping'/'dropped' align."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def stem_tokens(text: str) -> list[str]:
    return [stem(t) for t in tokenize(text)]


def contains_phrase(tokens: list[str], phrase_tokens: list[str]) -> bool:
    n = len(phrase_tokens)
    if n == 0 or n > len(tokens):
        return False
    return any(tokens[i : i + n] == phrase_tokens for i in range(len(tokens) - n + 1))


def strip_synthetic_tag(text: str) -> str:
    return SYNTHETIC_TAG_RE.sub("", text or "").strip()


def text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip(" -•\t") for p in parts if p and p.strip(" -•\t")]


def token_overlap(a: str, b: str) -> float:
    """Share of a's content tokens that appear in b (stemmed)."""
    ta = set(stem_tokens(a))
    if not ta:
        return 0.0
    tb = set(stem_tokens(b))
    return len(ta & tb) / len(ta)


def jaccard(a: str, b: str) -> float:
    ta, tb = set(stem_tokens(a)), set(stem_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
