"""Wording of resolution steps: instructions for agents, plain second-person steps for customers.

Help articles carry an authored "Customer steps:" section (one customer step per agent step); those are always
preferred. The rules here cover steps that have no authored customer wording (resolved-ticket notes, newly approved
articles, LLM paraphrases): resolved-ticket notes are written in the past tense ("Checked signal, restarted the
device"), so they are turned into instructions first.
"""
from __future__ import annotations

import re

PAST_TO_PRESENT = {
    "checked": "check", "confirmed": "confirm", "corrected": "correct", "recorded": "record", "restarted": "restart",
    "located": "locate", "shared": "share", "escalated": "escalate", "verified": "verify", "reseated": "reseat",
    "updated": "update", "enabled": "enable", "tested": "test", "replaced": "replace", "reinstalled": "reinstall",
    "cleared": "clear", "retried": "retry", "submitted": "submit", "applied": "apply", "collected": "collect",
    "compared": "compare", "identified": "identify", "reviewed": "review", "explained": "explain", "created": "create",
    "activated": "activate", "refreshed": "refresh", "removed": "remove", "routed": "route", "requested": "request",
    "sent": "send", "provided": "provide", "switched": "switch", "toggled": "toggle", "changed": "change",
    "completed": "complete", "observed": "observe", "skipped": "skip", "presented": "present", "asked": "ask",
    "used": "use", "treated": "treat", "disclosed": "disclose", "secured": "secure", "powered": "power",
    "guided": "guide", "advised": "advise", "selected": "select", "re-registered": "re-register",
}
ACTION_VERBS = set(PAST_TO_PRESENT) | set(PAST_TO_PRESENT.values()) | {
    "turn", "make", "try", "find", "note", "raise", "install", "open", "reset", "run", "move", "attach",
}
_CLAUSE_START = re.compile(r"(^|\band |, |; |\bthen )([A-Za-z][\w-]*)")

HAND_OVER = "If it's still not working, let me know and our team will take it from there."

# Customer wording for the information-gathering checklist shown when no verified source supports a fix.
CUSTOMER_INFO_STEPS = {
    "Record the exact symptom in the customer's words and any error message shown.":
        "Tell me exactly what happens, including any error message you see.",
    "Record when the issue started, how often it happens and at what times.":
        "Let me know when it started, how often it happens and at what times.",
    "Record the device model and whether other devices or services are affected.":
        "Tell me your device model and whether other devices or services are affected.",
    "Record every troubleshooting step the customer has already tried.":
        "Let me know anything you've already tried.",
}


def is_action(word: str) -> bool:
    return word.lower() in ACTION_VERBS


def imperative(text: str) -> str:
    """'Checked signal and restarted the device.' -> 'Check signal and restart the device.'

    Only past-tense notes are converted, so 'Verify the current and requested plan' keeps 'requested'.
    """
    words = text.strip().split()
    if not words or words[0].lower() not in PAST_TO_PRESENT:
        return text

    def swap(match: re.Match) -> str:
        lead, word = match.group(1), match.group(2)
        present = PAST_TO_PRESENT.get(word.lower())
        if not present:
            return match.group(0)
        return lead + (present.capitalize() if word[0].isupper() else present)

    return _CLAUSE_START.sub(swap, text)


def split_on_actions(sentence: str) -> list[str]:
    """Split a ticket resolution at clause boundaries that start a new action, never inside a list.

    'Check signal, retry the call, and record whether incoming, outgoing, or both are affected.' gives three steps;
    the last keeps 'incoming, outgoing, or both' intact.
    """
    parts = re.split(r";\s+|,\s+(?:and|then)\s+|,\s+", sentence)
    steps: list[str] = []
    for part in parts:
        part = part.strip(" .")
        if not part:
            continue
        first = part.split()[0].lower()
        conditional = first in ("if", "where", "when", "unless")
        if steps and is_action(first) and _bare_condition(steps[-1]):
            steps[-1] = f"{steps[-1]}, {part}"  # "If the issue remains" + "collect the details"
        elif steps and not is_action(first) and not conditional:
            joiner = ", " if not steps[-1].endswith(",") else " "
            steps[-1] = f"{steps[-1]}{joiner}{part}"  # a list item or a trailing phrase of the previous step
        else:
            steps.append(part)
    # A short leading condition ("if possible") belongs to the step before it.
    merged: list[str] = []
    for part in steps:
        if merged and re.match(r"^(if|where|when|unless)\b", part, re.I) and len(part.split()) < 4:
            merged[-1] = f"{merged[-1]} {part}"
        elif merged and len(part.split()) == 1:  # "restart the device, and retry" -> one step
            merged[-1] = f"{merged[-1]} and {part}"
        else:
            merged.append(part)
    return merged


def _bare_condition(text: str) -> bool:
    """'If the issue remains' (a condition still waiting for its action)."""
    words = text.split()
    return bool(words) and words[0].lower() in ("if", "where", "when", "unless") and "," not in text


# Agent-only actions: what the customer sees instead ("" hides the step for customers).
AGENT_ONLY = [
    (r"^(?:treat|present|provide only|identify the issue was|confirm the (?:balance|activation step|restart)|skip)\b", ""),
    (r"^(?:do not disclose|disclose no)\b.*", "For your safety, please don't share passwords, PINs or codes in this chat."),
    (r"^secure the account\b.*", "We'll secure your account."),
    (r"^create the replacement request\b.*", "We'll create the replacement request for you if you're eligible."),
    (r"^(?:record|note) that\b.*", ""),
    (r"^(?:escalate|route)\b.*", HAND_OVER),
]


def customer_version(text: str) -> str:
    """Plain second-person wording for a step that has no authored customer version."""
    step = imperative(text.strip()).rstrip(".")
    step = step[:1].upper() + step[1:]
    for pattern, replacement in AGENT_ONLY:
        if re.match(pattern, step, re.I):
            return replacement
    step = re.sub(r"\s+for escalation\b", "", step, flags=re.I)
    escalates = bool(re.search(r"\bescalat(?:e|ed|es|ing)\b", step, re.I))
    step = re.sub(r"[,;]?\s*(?:and\s+|then\s+)?escalat(?:e|ed|es|ing)\b[^.;]*", "", step, flags=re.I)
    replacements = [
        (r"\bthe customer's\b", "your"), (r"\bthe customer\b", "you"),
        (r"\brouter/ONT\b", "router"), (r"\bONT\b", "fibre box"),
        (r"\s*through the approved [\w\s-]*?(?:process|flow|view|source)\b", ""),
        (r"\bthe approved\s+", "the "), (r"^Verify\b", "Check"), (r"^Record whether\b", "Let me know whether"),
        (r"^(?:Record|Collect)\b", "Note"), (r"\bthe device\b", "your device"),
        (r"^Check signal availability\b", "Check your signal"), (r"^Retry the call\b", "Try the call again"),
        (r"^Retry from (.+?) if possible\b", r"If possible, try again from \1"),
        (r"^Retry login\b", "Try signing in again"), (r"^Retry the (connection|service)\b", r"Try the \1 again"),
        (r"^Retry$", "Try again"),
    ]
    for pattern, replacement in replacements:
        step = re.sub(pattern, replacement, step, flags=re.I if pattern[0] != "^" else 0)
    step = re.sub(r"\s{2,}", " ", step).strip(" ,;")
    if not step:
        return HAND_OVER
    step = step[0].upper() + step[1:]
    if not step.endswith((".", "!", "?")):
        step += "."
    return f"{step} {HAND_OVER}" if escalates else step


# Internal wording customers must never see, and signs of a broken step.
CUSTOMER_JARGON = re.compile(r"\b(the customer|approved|escalat\w*|route the|routed|ONT|agent follow-up)\b", re.I)


def customer_wording_issues(text: str) -> list[str]:
    """Problems with a customer-facing step: agent jargon, past-tense ticket notes or fragments."""
    issues = []
    if CUSTOMER_JARGON.search(text):
        issues.append("agent jargon")
    first = text.split()[0].lower().strip(",.") if text.split() else ""
    if first in PAST_TO_PRESENT:
        issues.append("past-tense note")
    if len(text.split()) < 3 or re.search(r"\b(for|and|the|of)\.$", text) or _bare_condition(text.rstrip(".")):
        issues.append("fragment")
    return issues
