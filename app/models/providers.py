from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model

    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        response = httpx.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=45.0,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()


class TogetherProvider(LLMProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.together_model
        self.api_key = settings.together_api_key
        self.base_url = "https://api.together.xyz/v1/chat/completions"

    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        if not self.api_key:
            raise RuntimeError("TOGETHER_API_KEY is not configured.")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = httpx.post(
            self.base_url,
            headers=headers,
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
            timeout=45.0,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"].strip()


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.openai_chat_model
        self.api_key = settings.openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"

    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = httpx.post(
            self.base_url,
            headers=headers,
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
            timeout=45.0,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"].strip()


class MockProvider(LLMProvider):
    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        _ = temperature
        return json.dumps(
            {
                "answer_tr": "Bu bir test cevabidir.",
                "answer_en": "This is a test response.",
                "consistency_assessment": "insufficient_evidence",
                "confidence": 0.55,
            }
        )


class RoutedLLM:
    def __init__(self) -> None:
        self.ollama = OllamaProvider()
        self.together = TogetherProvider()
        self.openai = OpenAIProvider()
        self.mock = MockProvider()

    def generate_with_provider(self, prompt: str, provider_pref: str | None = None) -> tuple[str, str]:
        preferred = (provider_pref or "ollama").lower()
        providers: list[tuple[str, LLMProvider]]

        if preferred == "together":
            providers = [("together", self.together), ("ollama", self.ollama), ("openai", self.openai), ("mock", self.mock)]
        elif preferred == "openai":
            providers = [("openai", self.openai), ("ollama", self.ollama), ("together", self.together), ("mock", self.mock)]
        elif preferred == "mock":
            providers = [("mock", self.mock)]
        else:
            providers = [("ollama", self.ollama), ("openai", self.openai), ("together", self.together), ("mock", self.mock)]

        last_exc: Exception | None = None
        for name, provider in providers:
            try:
                logger.info("LLM provider attempt: %s", name)
                return provider.generate(prompt), name
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM provider failed (%s): %s", name, exc)
                last_exc = exc
        if last_exc:
            raise RuntimeError(f"No model provider available: {last_exc}") from last_exc
        raise RuntimeError("No model provider available.")

    def generate(self, prompt: str, provider_pref: str | None = None) -> str:
        text, _ = self.generate_with_provider(prompt, provider_pref=provider_pref)
        return text
