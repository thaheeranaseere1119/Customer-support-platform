from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SESSION_PATTERN = r"^[A-Za-z0-9_\-:.]{1,80}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def clean_user_text(value: str) -> str:
    """Strip control characters; user text is always rendered as plain text."""
    return _CONTROL.sub("", value or "").strip()


class Page(BaseModel):
    total: int
    page: int
    page_size: int
