"""Rule-based entity extraction (time, frequency, duration, devices, money, context...)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

TIME_OF_DAY = r"(?:morning|afternoon|evening|night|midnight|noon|after work|weekends?|weekdays?|peak hours?)"
# Destinations customers travel to (a phone problem "in France" is usually roaming).
COUNTRIES = (
    "france", "germany", "spain", "italy", "portugal", "greece", "turkey", "the netherlands", "netherlands", "belgium",
    "switzerland", "austria", "ireland", "the uk", "uk", "england", "scotland", "london", "paris", "the us", "usa",
    "america", "the united states", "canada", "mexico", "brazil", "japan", "china", "india", "thailand", "vietnam",
    "malaysia", "singapore", "indonesia", "bali", "the philippines", "australia", "new zealand", "dubai", "the uae",
    "uae", "qatar", "saudi arabia", "egypt", "south africa", "kenya", "nigeria", "sri lanka", "nepal", "maldives",
    "europe", "asia", "africa",
)
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("time", re.compile(r"\b(?:at|around|about|by|after|before|from)?\s*(\d{1,2}(?::\d{2})?\s?(?:am|pm))\b", re.I)),
    ("time", re.compile(r"\b(\d{1,2}:\d{2})\b")),
    ("time_of_day", re.compile(rf"\b((?:every|each|in the|at|during the|most|mostly at)\s+{TIME_OF_DAY}|{TIME_OF_DAY})\b", re.I)),
    ("frequency", re.compile(r"\b(twice|thrice|once|(?:\d+|two|three|four|five|several|many)\s+times(?:\s+a\s+(?:day|week))?|"
                             r"every\s+(?:day|week|hour|few minutes)|daily|hourly|repeatedly|constantly|intermittent(?:ly)?)\b", re.I)),
    ("duration", re.compile(r"\b((?:for|since|over)\s+(?:the\s+)?(?:past|last)?\s*(?:\d+|a|an|one|two|three|four|five|several|few)?\s*"
                            r"(?:minutes?|hours?|days?|weeks?|months?|yesterday|this morning|last night))\b", re.I)),
    ("device", re.compile(r"\b(router|modem|ont|phone|smartphone|iphone|android|laptop|tablet|smart ?watch|tv|"
                          r"sim(?: card)?|e-?sim|hotspot|extender)\b", re.I)),
    ("money", re.compile(r"((?:₹|\$|£|€|rs\.?\s?|inr\s?)\s?\d[\d,]*(?:\.\d{1,2})?)", re.I)),
    ("billing_event", re.compile(r"\b(charged twice|double charged|overcharged|charged \w+ times|deducted twice)\b", re.I)),
    ("troubleshooting", re.compile(r"\b((?:already\s+)?(?:restarted|rebooted|reset|reseated|reinstalled|turned off|switched off|"
                                   r"power cycled|unplugged|checked|tried|replaced)\s+(?:the\s+|my\s+)?[a-z\- ]{2,25}?)"
                                   r"(?=[,.;]|\s+(?:and|but|twice|again|already|still|yet)\b|$)", re.I)),
    ("customer_context", re.compile(r"\b(work(?:ing)? from home|wfh|business|small business|online classes|elderly|"
                                    r"medical condition|costing me(?: money)?|losing money|exams?)\b", re.I)),
    ("location", re.compile(r"\b(abroad|overseas|upstairs|downstairs|basement|office|at home|in the city|rural area|"
                            r"(?:in|to) (?:" + "|".join(COUNTRIES) + r"))\b", re.I)),
    ("network_type", re.compile(r"\b(5g|4g|lte|3g|volte|wi-?fi calling|fibre|fiber|dsl)\b", re.I)),
    ("error_code", re.compile(r"\b(error\s*(?:code\s*)?[a-z]?\d{2,5})\b", re.I)),
]
# Everyday ways of saying a fix was already tried, recorded as the step they correspond to.
_TRIED_PHRASES = [
    (re.compile(r"\b(?:took|taken|take) (?:it|the sim|my sim|the sim card)? ?out and (?:put|placed) it back\b|"
                r"\bre-?inserted (?:the |my )?sim\b|\bremoved and reinserted\b", re.I), "reseated the SIM"),
    (re.compile(r"\b(?:turned|switched|powered) (?:it|the router|my router|the phone|my phone)? ?off and (?:on|back on)"
                r"(?: again)?\b", re.I), "restarted it"),
]
# Asking how to do something is not having done it ("how do I reset my password").
_REQUEST_BEFORE = re.compile(r"\b(?:how (?:do|can|should|would) (?:i|we)|how to|want to|need to|trying to|help me|"
                             r"can (?:i|you)|should i|will i|do i|to)\s*$", re.I)

# Account / phone numbers are detected but masked so they are never stored in clear text.
_SENSITIVE = re.compile(r"\b(\d{9,16})\b")


@dataclass
class Entity:
    type: str
    value: str

    def to_dict(self) -> dict:
        return asdict(self)


def extract_entities(text: str) -> list[Entity]:
    found: list[Entity] = []
    seen: set[tuple[str, str]] = set()
    for etype, pattern in _PATTERNS:
        for match in pattern.finditer(text or ""):
            if etype == "troubleshooting" and _REQUEST_BEFORE.search(text[:match.start()]):
                continue
            value = (match.group(1) if match.groups() else match.group(0)).strip(" ,.")
            value = re.sub(r"\s+", " ", value)
            if not value:
                continue
            key = (etype, value.lower())
            if key in seen:
                continue
            seen.add(key)
            found.append(Entity(etype, value))
    for pattern, value in _TRIED_PHRASES:
        if pattern.search(text or "") and ("troubleshooting", value.lower()) not in seen:
            seen.add(("troubleshooting", value.lower()))
            found.append(Entity("troubleshooting", value))
    for match in _SENSITIVE.finditer(text or ""):
        masked = "•" * (len(match.group(1)) - 4) + match.group(1)[-4:]
        found.append(Entity("account_reference", masked))
    # Drop time_of_day entries already covered by a more specific match ("every evening" vs "evening").
    tod = [e for e in found if e.type == "time_of_day"]
    redundant = {id(a) for a in tod for b in tod if a is not b and a.value.lower() in b.value.lower() and len(a.value) < len(b.value)}
    return [e for e in found if id(e) not in redundant]


def mask_sensitive(text: str) -> str:
    return _SENSITIVE.sub(lambda m: "•" * (len(m.group(1)) - 4) + m.group(1)[-4:], text or "")
