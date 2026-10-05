"""Deterministic, evidence-only answer construction (used by MockProvider in demo mode
and as the fallback when an LLM call fails).

Every resolution step is copied from a supplied source and cited with that
source's ID. Nothing here invents policies, prices, causes or procedures; when no
source supports a fix the answer says the evidence is insufficient and only lists
information to collect.
"""
from __future__ import annotations

import re

from app.utils.text import jaccard, sentences, stem_tokens

INFO_GATHERING_STEPS = [
    "Record the exact symptom in the customer's words and any error message shown.",
    "Record when the issue started, how often it happens and at what times.",
    "Record the device model and whether other devices or services are affected.",
    "Record every troubleshooting step the customer has already tried.",
]
_ACTION_STEMS = {"restart", "reseat", "reinstal", "reset", "unplug", "replac", "check"}
_SECTION = re.compile(r"^(Symptoms|Resolution steps|Escalate when|Caution|Source note):\s*(.*)$", re.I)


def parse_kb(content: str) -> dict:
    parsed = {"symptoms": "", "steps": [], "escalate": "", "caution": ""}
    for raw in (content or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _SECTION.match(line)
        if match:
            key = match.group(1).lower()
            value = match.group(2).strip()
            if key == "symptoms":
                parsed["symptoms"] = value
            elif key == "escalate when":
                parsed["escalate"] = value
            elif key == "caution":
                parsed["caution"] = value
            continue
        numbered = re.match(r"^\d+[.)]\s+(.*)$", line)
        if numbered:
            parsed["steps"].append(numbered.group(1).strip())
    if not parsed["steps"]:
        parsed["steps"] = split_resolution(content)
    return parsed


def split_resolution(text: str) -> list[str]:
    """Split a one-sentence resolution ("Check X, restart Y, and record Z.") into steps."""
    body = re.sub(r"^.*?Resolution:\s*", "", text or "", flags=re.S | re.I).strip()
    pieces: list[str] = []
    for sentence in sentences(body):
        parts = re.split(r";\s+|,\s+and\s+|,\s+then\s+|,\s+(?=[a-z])", sentence)
        buffer = ""
        for part in parts:
            part = part.strip(" .")
            if not part:
                continue
            if buffer:
                part = f"{buffer}, {part}"
                buffer = ""
            if re.match(r"^(if|where|when|unless)\b", part, re.I) and "," not in part and len(part.split()) < 8:
                buffer = part
                continue
            pieces.append(part[0].upper() + part[1:] + ".")
        if buffer:
            pieces.append(buffer[0].upper() + buffer[1:] + ".")
    return pieces


def parse_ticket(content: str) -> dict:
    complaint = re.search(r"Complaint:\s*(.*?)(?:\n|$)", content or "", re.I)
    resolution = re.search(r"Resolution:\s*(.*?)(?:\n|$)", content or "", re.I)
    body = resolution.group(1) if resolution else content
    return {"complaint": complaint.group(1).strip() if complaint else "", "steps": split_resolution(body)}


def already_attempted(step: str, troubleshooting: list[str]) -> bool:
    if not troubleshooting:
        return False
    step_actions = set(stem_tokens(step)) & _ACTION_STEMS
    tried = set()
    for item in troubleshooting:
        tried |= set(stem_tokens(item))
    return bool(step_actions & tried & {"restart", "reseat", "reinstal", "reset", "unplug", "replac"})


def _cite(text: str, source_id: str) -> str:
    return f"{text.rstrip()} [{source_id}]"


def build_answer(payload: dict) -> dict:
    mode = payload["mode"]
    analysis = payload["analysis"]
    evidence = payload["evidence"]
    sources = payload["sources"]
    troubleshooting = payload.get("troubleshooting") or []
    previous_steps = payload.get("previous_steps") or []
    attempt = payload.get("attempt", 1)
    known_threshold = payload["thresholds"]["known"]
    score = evidence["score"]

    steps: list[dict] = []
    warnings: list[str] = []
    escalate_rules: list[tuple[str, str]] = []
    kb_count = ticket_count = 0

    # Knowledge articles are the authoritative procedure; resolved tickets corroborate them
    # and only contribute their own steps when the articles leave fewer than three.
    ordered = sorted(sources, key=lambda x: 0 if x["type"] == "knowledge_base" else 1)
    primary = ordered[0] if ordered else None
    for src in ordered:
        is_kb = src["type"] == "knowledge_base"
        if is_kb:
            parsed = parse_kb(src["content"])
            kb_count += 1
            if parsed["caution"]:
                warnings.append(_cite(parsed["caution"], src["id"]))
            if parsed["escalate"]:
                escalate_rules.append((parsed["escalate"], src["id"]))
        else:
            parsed = parse_ticket(src["content"])
            ticket_count += 1
        for text in parsed["steps"]:
            if any(jaccard(text, prev) >= 0.6 for prev in previous_steps):
                continue  # adaptive retry: do not repeat steps from earlier attempts
            similar = max(steps, key=lambda st: jaccard(text, st["text"]), default=None)
            overlap = jaccard(text, similar["text"]) if similar else 0.0
            if similar and overlap >= (0.5 if is_kb else 0.3):
                if src["id"] not in similar["citations"]:
                    similar["citations"].append(src["id"])
                continue
            if len(steps) >= 6 or (not is_kb and kb_count and len(steps) >= 3):
                continue
            steps.append({"text": text, "citations": [src["id"]], "kind": "resolution",
                          "already_attempted": already_attempted(text, troubleshooting)})

    intent_display = analysis.get("intent_display") or analysis.get("intent")
    if analysis.get("intent") in (None, "unknown") and primary:
        intent_display = primary["title"]
    insufficient = False
    only_general = bool(sources) and all(src.get("general") for src in sources)
    if only_general and steps:
        summary = (f"BEST-SUITABLE GUIDANCE - no issue-specific verified evidence was found (score {score:.2f}). "
                   f"The steps below come from the closest general checklist '{primary['title']}' and are a "
                   f"candidate, not a confirmed fix. Please confirm whether they solved the problem.")
    elif mode == "known" and steps:
        summary = (f"Verified evidence matches '{intent_display}'. The steps below come from {kb_count} knowledge "
                   f"article(s) and {ticket_count} resolved historical ticket(s); each step cites its source.")
    elif mode == "uncertain" and steps:
        summary = (f"CANDIDATE RESOLUTION - not verified. The evidence score {score:.2f} is below the KNOWN threshold "
                   f"({known_threshold:.2f}). These steps come from the closest verified sources and must be confirmed "
                   f"with the customer before closing.")
    elif steps:
        summary = (f"NEW ISSUE - insufficient verified evidence (score {score:.2f}). The candidate below uses only "
                   f"loosely related verified sources and is not a confirmed fix.")
    else:
        insufficient = True
        if previous_steps and sources:
            summary = ("The evidence is insufficient: no alternative verified steps remain beyond those already "
                       "suggested. Collect the details below for escalation.")
        else:
            summary = ("The evidence is insufficient: no verified source in the knowledge base supports a resolution "
                       "for this issue. Collect the details below so the case can be reviewed and escalated.")
        steps = [{"text": t, "citations": [], "kind": "information_gathering", "already_attempted": False}
                 for t in INFO_GATHERING_STEPS]

    if primary and not insufficient and only_general:
        diagnosis = (f"The evidence is insufficient to confirm a cause. The closest guidance is the general "
                     f"checklist '{primary['title']}' [{primary['id']}].")
    elif primary and not insufficient:
        if primary["type"] == "knowledge_base":
            symptoms = parse_kb(primary["content"])["symptoms"]
            if mode == "known":
                diagnosis = f"The complaint matches the documented pattern '{primary['title']}': {symptoms} [{primary['id']}]"
                ticket = next((x for x in ordered if x["type"] != "knowledge_base"), None)
                if ticket:
                    similar_case = parse_ticket(ticket["content"])["complaint"]
                    diagnosis += f" A similar resolved ticket reported: \"{similar_case}\" [{ticket['id']}]"
            else:
                diagnosis = (f"The evidence is insufficient to confirm a cause. Closest documented pattern: "
                             f"'{primary['title']}' [{primary['id']}].")
        else:
            similar = parse_ticket(primary["content"])["complaint"]
            prefix = "A similar resolved ticket reported" if mode == "known" else "The cause is not confirmed; the closest resolved ticket reported"
            diagnosis = f"{prefix}: \"{similar}\" [{primary['id']}]"
    else:
        diagnosis = "The evidence is insufficient to determine a cause."

    attempted = [s["text"] for s in steps if s.get("already_attempted")]
    if attempted:
        warnings.insert(0, "The customer already tried: " + "; ".join(troubleshooting[:3])
                        + ". Steps marked 'already tried' should not be repeated.")
    if mode != "known":
        warnings.insert(0, f"Evidence score {score:.2f} is below the KNOWN threshold ({known_threshold:.2f}); "
                           f"treat this as a candidate, not a verified answer.")
    if attempt > 1:
        warnings.append(f"Attempt {attempt}: steps suggested in earlier attempts were excluded and alternative evidence was used.")

    escalation, reason = False, None
    severity = analysis.get("severity")
    context = payload.get("customer_context") or []
    if severity == "critical":
        escalation = True
        rule = escalate_rules[0] if escalate_rules else None
        reason = "Critical severity (security or fraud risk)." + (f" {rule[0]} [{rule[1]}]" if rule else "")
    elif escalate_rules and mode == "known" and (troubleshooting or context or severity == "high"):
        rule_text, rule_id = escalate_rules[0]
        signals = []
        if troubleshooting:
            signals.append("customer already tried: " + "; ".join(troubleshooting[:2]))
        if context:
            signals.append("customer context: " + ", ".join(context[:2]))
        if severity == "high":
            signals.append("high severity")
        escalation = True
        reason = f"Escalate when: {rule_text} [{rule_id}] Signals: {'; '.join(signals)}."
    elif insufficient and attempt >= payload.get("max_attempts", 3):
        escalation = True
        reason = "Maximum resolution attempts reached without sufficient evidence."

    return {"summary": summary, "diagnosis": diagnosis, "steps": steps, "warnings": warnings,
            "escalation": escalation, "escalation_reason": reason, "insufficient_evidence": insufficient}
