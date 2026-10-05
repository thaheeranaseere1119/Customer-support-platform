"""Deterministic sentiment and severity estimation."""
from __future__ import annotations

import re
from dataclasses import dataclass

_URGENT = re.compile(r"\b(urgent|urgently|asap|immediately|right now|emergency|critical|cannot work|can't work|"
                     r"need it now|as soon as possible)\b", re.I)
_FRUSTRATED = re.compile(r"\b(already|again|still|keeps?|twice|thrice|fed up|ridiculous|unacceptable|frustrat\w*|"
                         r"annoy\w*|tired of|costing me|every (?:day|evening|night)|third time|no one|nobody|useless|"
                         r"terrible|awful|worst)\b", re.I)
_NEGATIVE = re.compile(r"\b(not working|doesn't|does not|cannot|can't|unable|fail\w*|problem|issue|broken|drops?|"
                       r"dropping|disconnect\w*|slow|wrong|error|no (?:signal|service|internet)|lost|stopped|"
                       r"charged|concerned|worried|declined)\b", re.I)
_POSITIVE = re.compile(r"\b(thanks|thank you|great|resolved|working now|happy|appreciate|perfect|solved)\b", re.I)

_CRITICAL = re.compile(r"\b(hacked|unauthori[sz]ed|fraud\w*|stolen|sim swap|someone (?:accessed|changed|logged)|"
                       r"identity theft|emergency (?:call|services)|cannot call emergency|phishing)\b", re.I)
_HIGH = re.compile(r"\b(no (?:service|signal|internet)(?: at all)?|completely down|outage|not working at all|"
                   r"work(?:ing)? from home|business|costing me|losing money|every (?:day|evening|night)|"
                   r"for (?:days|weeks|a week)|past week|several days|keeps? (?:dropping|disconnecting|failing)|"
                   r"drops? every|several times a day)\b", re.I)
_LOW = re.compile(r"\b(information|info|want to know|would like to know|how do i|status of|which plan|available plans|"
                  r"update my (?:profile|email|address)|question)\b", re.I)


@dataclass
class SentimentResult:
    label: str  # positive | neutral | negative | frustrated | urgent
    score: float
    cues: list[str]


@dataclass
class SeverityResult:
    label: str  # low | medium | high | critical
    reasons: list[str]


def analyze_sentiment(text: str) -> SentimentResult:
    text = text or ""
    urgent = _URGENT.findall(text)
    frustrated = _FRUSTRATED.findall(text)
    negative = _NEGATIVE.findall(text)
    positive = _POSITIVE.findall(text)
    if urgent:
        return SentimentResult("urgent", -0.8, sorted(set(m.lower() for m in urgent)))
    if len(frustrated) >= 2 or (frustrated and negative):
        return SentimentResult("frustrated", -0.7, sorted(set(m.lower() for m in frustrated)))
    if negative and len(positive) < len(negative):
        return SentimentResult("negative", -0.4, sorted(set(m.lower() for m in negative)))
    if positive:
        return SentimentResult("positive", 0.6, sorted(set(m.lower() for m in positive)))
    return SentimentResult("neutral", 0.0, [])


def estimate_severity(text: str, sentiment: SentimentResult, intent: str | None = None,
                      domain_category: str | None = None) -> SeverityResult:
    text = text or ""
    reasons: list[str] = []
    critical = _CRITICAL.findall(text)
    if critical or domain_category == "SECURITY" or intent == "account_security":
        reasons.append("security or fraud risk" + (f" ({critical[0].lower()})" if critical else ""))
        return SeverityResult("critical", reasons)
    high = sorted(set(m.lower() for m in _HIGH.findall(text)))
    if high:
        reasons.append("impact signals: " + ", ".join(high[:4]))
    if sentiment.label == "urgent":
        reasons.append("urgent customer sentiment")
    if len(high) >= 2 or (high and sentiment.label == "urgent"):
        return SeverityResult("high", reasons)
    if _LOW.search(text) and not high:
        return SeverityResult("low", ["information or administrative request"])
    if not reasons:
        reasons.append("standard service issue")
    return SeverityResult("medium", reasons)
