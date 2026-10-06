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


# Human-agent chat replies -> article steps. An agent writes to one customer ("Hi Asha, sorry about that! I've
# reissued your e-SIM. Please scan the new QR code. Let me know once done."); a help article needs only the fix,
# worded for agents and for customers.
_CHAT_ONLY = re.compile(
    r"^(?:hi|hello|hey|dear|good (?:morning|afternoon|evening)|thanks|thank you|sorry|so sorry|apologies|"
    r"i'?m sorry|i am sorry|i apologi[sz]e|no problem|no worries|you'?re welcome|glad|great|perfect|ok(?:ay)?|sure|"
    r"happy to help|have a (?:great|nice|good)|let me know|is there anything|anything else|please wait|one moment|"
    r"give me a (?:moment|minute|sec)|bear with me|hope (?:this|that) helps|i'?ll check|i will check|let me check|"
    r"i'?m checking|i am checking|i'?m looking|i am looking|let me look|checking now|welcome)\b", re.I)
_POLITE_LEAD = re.compile(r"^(?:(?:please|kindly|just|now|so|then|next|also|first|firstly)[,\s]+|(?:can|could|would) you "
                          r"(?:please )?|you (?:can|could|should|need to|will need to|'ll need to) )+", re.I)
_DONE_BY_US = re.compile(r"^(?:i|we)(?:'ve| have| just| also)*\s+([a-z][\w-]*)\b\s*(.*)$", re.I)
_IRREGULAR_PAST = {"sent": "send", "gave": "give", "made": "make", "set": "set", "reset": "reset", "put": "put",
                   "did": "do", "got": "get", "rebuilt": "rebuild", "unblocked": "unblock", "unbarred": "unbar"}
_OUR_SIDE = re.compile(r"\s*\b(?:from|on) (?:our|my) (?:side|end)\b|\s*\bfor you\b|\s*\bjust\b", re.I)


def _base_verb(word: str) -> str | None:
    """Present form of a past-tense verb ('reissued' -> 'reissue'), or None if the word is not past tense."""
    w = word.lower()
    if w in _IRREGULAR_PAST:
        return _IRREGULAR_PAST[w]
    if w in PAST_TO_PRESENT:
        return PAST_TO_PRESENT[w]
    if not w.endswith("ed") or len(w) < 5:
        return None
    if w.endswith("ied"):
        return w[:-3] + "y"
    if w.endswith("ssed"):
        return w[:-2]
    if len(w) > 5 and w[-3] == w[-4] and w[-3] in "lpgtmnb":  # cancelled, dropped, barred
        return w[:-3]
    if w.endswith(("ued", "ved", "zed", "sed", "ced", "ged", "ated", "ired", "ored", "ured", "ided", "oded", "uded")):
        return w[:-1]
    return w[:-2]


def _sentence(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;-")
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def agent_reply_steps(messages: list[str], customer_name: str | None = None) -> list[tuple[str, str]]:
    """(agent step, customer step) pairs from what a human agent told a customer in chat.

    Greetings, apologies, sign-offs and questions asking for details are dropped, the customer's name is removed,
    "please ..." becomes an instruction, and work the agent did ("I've reissued your e-SIM") becomes an agent action
    ("Reissue the customer's e-SIM.") that customers see as "We'll reissue your e-SIM.".
    """
    name = re.escape(customer_name.strip()) if customer_name and customer_name.strip() else None
    pairs: list[tuple[str, str]] = []
    for message in messages:
        for raw in re.split(r"(?<=[.!?])\s+|\n+", message or ""):
            text = raw.strip()
            if name:
                text = re.sub(rf"^(?:(?:hi|hello|hey|dear)\s+)?{name}\b[,!.]?\s*|,?\s*\b{name}\b(?=[,.!?]|$)", "", text,
                              flags=re.I).strip()
            if not text or _CHAT_ONLY.match(text):
                continue
            question = text.endswith("?")
            asked = re.match(r"^(?:can|could|would) you (?:please )?", text, re.I)
            if question and (not asked or re.match(r"^(?:can|could|would) you (?:please )?(?:tell|share|send|confirm|let|"
                                                    r"check (?:if|whether)|give)\b", text, re.I)):
                continue  # the agent asking for details is not part of the fix
            text = _POLITE_LEAD.sub("", text.rstrip("?!. ")).strip()
            done = _DONE_BY_US.match(text)
            base = _base_verb(done.group(1)) if done else None
            if done and base:
                rest = re.sub(r"\b(and|then) ([a-z]+ed)\b", lambda m: f"{m.group(1)} {_base_verb(m.group(2)) or m.group(2)}",
                              _OUR_SIDE.sub("", done.group(2)).strip(), flags=re.I)
                agent_rest = re.sub(r"\byour\b", "the customer's", re.sub(r"\byou\b", "the customer", rest, flags=re.I),
                                    flags=re.I)
                agent, customer = _sentence(f"{base} {agent_rest}"), _sentence(f"We'll {base} {rest}")
            else:
                text = re.sub(r"\bjust\s+", "", text, flags=re.I)
                customer = _sentence(text)
                agent = _sentence(re.sub(r"\byour\b", "the customer's", text, flags=re.I))
            if len(customer.split()) < 3 or any(customer.lower() == c.lower() for _, c in pairs):
                continue
            pairs.append((agent, customer))
    return pairs


def numbered(lines: list[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


# Opening line for customers: what the problem is (for "Sorry ...") and what we'll do about it (for "Let's ...").
CUSTOMER_TOPICS = {
    "broadband_disconnects": ("your broadband keeps dropping", "get your connection stable again"),
    "broadband_no_internet": ("you have no internet", "get you back online"),
    "broadband_slow": ("your internet is running slow", "get your speed back up"),
    "wifi_not_working": ("your Wi-Fi isn't working properly", "get your Wi-Fi working again"),
    "router_restart_issue": ("restarting your router didn't fix it", "get your connection working"),
    "mobile_data_not_working": ("your mobile data isn't working", "get your mobile data working"),
    "mobile_data_slow": ("your mobile data is slow", "speed up your mobile data"),
    "no_signal": ("your phone has no signal", "get your signal back"),
    "5g_not_available": ("you're not getting 5G", "get 5G showing on your phone"),
    "call_drops": ("your calls keep dropping", "stop your calls dropping"),
    "call_quality": ("your call quality is poor", "improve your call quality"),
    "sms_not_received": ("your messages aren't coming through", "get your texts and codes arriving"),
    "sim_not_detected": ("your phone isn't detecting the SIM", "get your SIM detected"),
    "sim_activation": ("your SIM isn't active yet", "activate your SIM"),
    "sim_replacement": ("you need a new SIM", "get you a replacement SIM"),
    "roaming_not_working": ("your phone isn't working abroad", "get your phone working abroad"),
    "billing_dispute": ("something on your bill looks wrong", "sort out your bill"),
    "unexpected_charge": ("there's a charge you don't recognise", "look into that charge"),
    "payment_failed": ("your payment didn't go through", "get your payment through"),
    "refund_status": ("you're still waiting for your refund", "track down your refund"),
    "recharge_issue": ("your recharge hasn't come through", "get your recharge applied"),
    "plan_change": ("you'd like to change your plan", "change your plan"),
    "plan_information": ("you're looking for plan details", "find the right plan for you"),
    "account_login": ("you can't sign in", "get you signed in"),
    "account_security": ("you're worried about your account's security", "secure your account"),
    "password_reset": ("you need to reset your password", "reset your password"),
    "profile_update": ("you need to update your details", "update your details"),
    "service_activation": ("your service isn't active yet", "get your service activated"),
    "new_connection_status": ("you're waiting on your new connection", "check on your new connection"),
    "service_outage": ("you might be affected by an outage", "check for an outage in your area"),
}
# Requests rather than faults: no "Sorry" for these.
REQUEST_INTENTS = {"plan_change", "plan_information", "password_reset", "profile_update", "sim_replacement"}
_ASKING = re.compile(r"^\s*(?:how|what|which|where|when|why|is|are|do|does|did|can|could|will|would|should|has|have|"
                     r"please|i(?:'d| would) like|i (?:want|need) to)\b", re.I)


def customer_intro(complaint: str, intent: str | None, entities: list[dict], steps: list[dict], attempt: int) -> str | None:
    """A first line that answers what the customer actually said, built only from their words and the issue type.

    None when there is nothing specific to say (unrecognised issue, or only questions back to the customer); the chat
    then shows its general headline.
    """
    topic = CUSTOMER_TOPICS.get(intent or "")
    if topic is None or not any(st.get("kind") == "resolution" for st in steps):
        return None
    problem, task = topic
    if attempt > 1:
        return f"Let's try another way to {task}:"
    tried = next((e["value"] for e in entities if e.get("type") == "troubleshooting"), None)
    skip = ""
    if tried and any(st.get("already_attempted") for st in steps):
        done = re.sub(r"^already\s+", "", tried.strip(), flags=re.I)
        done = re.sub(r"\bmy\b", "your", done[0].lower() + done[1:])
        skip = f"Since you've already {done}, you can skip that step. "
    asking = bool(_ASKING.search(complaint)) or complaint.strip().endswith("?")
    if asking or intent in REQUEST_INTENTS:
        return f"{skip}Let's {task}:"
    when = next((e["value"] for e in entities if e.get("type") == "time_of_day"), "")
    if when and not re.match(r"^(every|each|in the|at|during|mostly|most)\b", when, re.I):
        when = f"in the {when}" if when.lower() in ("morning", "afternoon", "evening") else f"at {when}"
    detail = f" {when.lower()}" if when else ""
    return f"Sorry {problem}{detail}. {skip}Let's {task}:"
