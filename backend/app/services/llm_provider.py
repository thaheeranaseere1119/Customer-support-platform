"""LLM provider abstraction.

LLMProvider
    +-- GeminiProvider   (AI MODE: DEMO_MODE=false and GEMINI_API_KEY set; key stays server-side)
    +-- MockProvider     (DEMO MODE: deterministic, evidence-only template generation)

Both return plain dicts; every output is passed through the same grounding guard
in `rag.py`, so the system never blindly trusts an LLM.
"""
from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod

import httpx

from app.config import get_settings
from app.services import grounded_templates

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAY_SECONDS = 1.0


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    name: str = "base"
    is_llm: bool = False

    @abstractmethod
    def complete_json(self, task: str, system_prompt: str, user_prompt: str, payload: dict) -> dict:
        """Return a JSON object for the task. `payload` carries structured inputs."""

    def status(self) -> dict:
        return {"provider": self.name, "is_llm": self.is_llm}


class MockProvider(LLMProvider):
    """Deterministic provider for demo mode: builds answers strictly from evidence."""

    name = "mock"
    is_llm = False

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, payload: dict) -> dict:
        if task == "rag_answer":
            return grounded_templates.build_answer(payload)
        if task == "classify":
            return {"intent": "unknown", "confidence": 0.0}
        raise LLMError(f"MockProvider does not support task '{task}'")


class GeminiProvider(LLMProvider):
    name = "gemini"
    is_llm = True
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self) -> None:
        self.settings = get_settings()

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, payload: dict) -> dict:
        key = self.settings.gemini_api_key.get_secret_value() if self.settings.gemini_api_key else ""
        if not key:
            raise LLMError("Gemini API key not configured")
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        response = None
        for attempt in range(2):  # one retry for rate limits and transient server errors
            try:
                response = httpx.post(
                    self.endpoint.format(model=self.settings.gemini_model),
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                    json=body, timeout=self.settings.llm_timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise LLMError(f"Gemini request failed: {exc.__class__.__name__}") from None
            if response.status_code not in RETRYABLE_STATUS or attempt == 1:
                break
            time.sleep(RETRY_DELAY_SECONDS)
        if response.status_code != 200:
            raise LLMError(f"Gemini returned HTTP {response.status_code}")
        try:
            data = response.json()
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
            parsed = json.loads(raw)
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Gemini returned an unparseable response ({exc.__class__.__name__})") from None
        if not isinstance(parsed, dict):
            raise LLMError("Gemini response was not a JSON object")
        return parsed


_mock = MockProvider()


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.ai_mode:
        return GeminiProvider()
    return _mock


def get_fallback_provider() -> LLMProvider:
    return _mock
