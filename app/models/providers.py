from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model

    def _candidate_base_urls(self) -> list[str]:
        urls: list[str] = []
        base = self.base_url
        if "host.docker.internal" in base:
            urls.extend(["http://localhost:11434", "http://127.0.0.1:11434", base])
        elif "localhost" in base:
            urls.extend([base, base.replace("localhost", "127.0.0.1"), "http://host.docker.internal:11434"])
        elif "127.0.0.1" in base:
            urls.extend([base, base.replace("127.0.0.1", "localhost"), "http://host.docker.internal:11434"])
        else:
            urls.append(base)
        return list(dict.fromkeys(url.rstrip("/") for url in urls if url))

    def health_check(self) -> dict:
        last_exc: Exception | None = None
        for base_url in self._candidate_base_urls():
            try:
                response = httpx.get(f"{base_url}/api/tags", timeout=httpx.Timeout(5.0, connect=2.0))
                response.raise_for_status()
                payload = response.json()
                models = [item.get("name", "") for item in payload.get("models", [])]
                return {
                    "base_url": base_url,
                    "model": self.model,
                    "models": models,
                    "model_available": self.model in models,
                }
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise RuntimeError(f"Ollama is not reachable: {last_exc}")

    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        last_exc: Exception | None = None
        for base_url in self._candidate_base_urls():
            try:
                response = httpx.post(
                    f"{base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": temperature},
                    },
                    timeout=httpx.Timeout(120.0, connect=5.0),
                )
                response.raise_for_status()
                data = response.json()
                return data.get("response", "").strip()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("Ollama candidate failed (%s): %s", base_url, exc)
        raise RuntimeError(f"Ollama generation failed: {last_exc}")


class TogetherProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.together_model
        self.api_key = api_key if api_key is not None else settings.together_api_key
        self.base_url = base_url or "https://api.together.xyz/v1/chat/completions"

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
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.openai_chat_model
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.base_url = base_url or "https://api.openai.com/v1/chat/completions"

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


class GroqProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.groq_model
        self.api_key = api_key if api_key is not None else settings.groq_api_key
        self.base_url = base_url or "https://api.groq.com/openai/v1/chat/completions"

    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not configured.")
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


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.gemini_model
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.base_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )

    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        response = httpx.post(
            f"{self.base_url}?key={self.api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature},
            },
            timeout=45.0,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["candidates"][0]["content"]["parts"][0]["text"].strip()


class MockProvider(LLMProvider):
    _POS = {"artis", "guclu", "iyilesme", "onay", "pozitif", "uyumlu"}
    _NEG = {"azalis", "zayif", "iptal", "ceza", "risk", "temkinli", "gecikme"}

    @staticmethod
    def _normalize(text: str) -> str:
        lowered = text.lower()
        table = str.maketrans("ıçğöşü", "icgosu")
        return lowered.translate(table)

    def _score_tone(self, text: str) -> tuple[int, int]:
        norm = self._normalize(text)
        pos = sum(1 for token in self._POS if self._normalize(token) in norm)
        neg = sum(1 for token in self._NEG if self._normalize(token) in norm)
        return pos, neg

    def _mock_contradiction_score(self, prompt: str) -> str:
        items = re.findall(
            r"\[\d+\]\s+([a-z_]+)\s+\|\s+\d{4}-\d{2}-\d{2}\s+\|\s+(.+)",
            prompt,
            flags=re.IGNORECASE,
        )
        if not items:
            return json.dumps({"contradiction_score": 0.0})

        by_source: dict[str, str] = {}
        for source, text in items:
            key = source.lower()
            by_source[key] = f"{by_source.get(key, '')} {text}".strip()

        kap_text = by_source.get("kap", "")
        news_text = by_source.get("news", "")
        if kap_text and news_text:
            kap_pos, kap_neg = self._score_tone(kap_text)
            news_pos, news_neg = self._score_tone(news_text)
            kap_signal = kap_pos - kap_neg
            news_signal = news_pos - news_neg
            if kap_signal * news_signal < 0:
                score = 0.78
            elif abs(kap_signal - news_signal) <= 1:
                score = 0.22
            else:
                score = 0.45
        else:
            merged = " ".join(text for _, text in items)
            pos, neg = self._score_tone(merged)
            score = 0.45 if abs(pos - neg) > 1 else 0.28
        return json.dumps({"contradiction_score": score})

    @staticmethod
    def _extract_ticker(prompt: str) -> str:
        match = re.search(r"Ticker:\s*([A-Z0-9\.]+)", prompt)
        return match.group(1) if match else "TICKER"

    @staticmethod
    def _extract_consistency(prompt: str) -> str:
        match = re.search(r"Consistency seed:\s*([a-z_]+)", prompt)
        return match.group(1) if match else "inconclusive"

    @staticmethod
    def _extract_first_evidence_lines(prompt: str) -> dict[str, str]:
        buckets: dict[str, str] = {}
        for source in ("kap", "news", "brokerage"):
            match = re.search(
                rf"source={source}\s+date=[^\n]+\s+institution=[^\n]+\s+title=[^\n]+\n(.+)",
                prompt,
                flags=re.IGNORECASE,
            )
            if match:
                buckets[source] = match.group(1).strip()
        return buckets

    def _mock_composer(self, prompt: str) -> str:
        ticker = self._extract_ticker(prompt)
        consistency = self._extract_consistency(prompt)
        evidence = self._extract_first_evidence_lines(prompt)

        kap_line = evidence.get("kap", "KAP kaynaginda sinirli kanit bulundu.")
        news_line = evidence.get("news", "Haber kaynaginda sinirli kanit bulundu.")
        broker_line = evidence.get("brokerage", "Araci kurum raporlarinda sinirli kanit bulundu.")

        tr_consistency = {
            "aligned": "Kaynaklar genel olarak ayni yone isaret ediyor.",
            "contradiction": "Kaynaklar arasinda belirgin uyumsuzluk sinyali var.",
            "insufficient_evidence": "Saglam bir sonuca ulasmak icin kanit yetersiz.",
        }.get(consistency, "Gorunum karisik; ek dogrulama gerektirebilir.")
        en_consistency = {
            "aligned": "Sources broadly point in the same direction.",
            "contradiction": "There is a visible inconsistency across sources.",
            "insufficient_evidence": "Evidence is too limited for a firm conclusion.",
        }.get(consistency, "The picture is mixed and may require another retrieval pass.")

        answer_tr = (
            f"{ticker} icin genel gorunum: {tr_consistency} "
            f"Resmi durum: {kap_line[:220]} "
            f"Haber anlatisi: {news_line[:220]} "
            f"Araci kurum cercevesi: {broker_line[:180]}"
        )
        answer_en = (
            f"For {ticker}, overall picture: {en_consistency} "
            f"Official disclosure view: {kap_line[:180]} "
            f"News framing: {news_line[:180]} "
            f"Broker framing: {broker_line[:160]}"
        )
        return json.dumps(
            {
                "answer_tr": answer_tr,
                "answer_en": answer_en,
                "consistency_assessment": consistency,
                "confidence": 0.68 if consistency == "aligned" else 0.56,
            },
            ensure_ascii=False,
        )

    def generate(self, prompt: str, temperature: float = 0.1) -> str:
        _ = temperature
        if "contradiction_score" in prompt:
            return self._mock_contradiction_score(prompt)
        if "strict JSON keys: answer_tr, answer_en, consistency_assessment, confidence" in prompt:
            return self._mock_composer(prompt)
        return json.dumps(
            {
                "answer_tr": "Kanit yetersiz.",
                "answer_en": "Insufficient evidence.",
                "consistency_assessment": "insufficient_evidence",
                "confidence": 0.5,
            },
            ensure_ascii=False,
        )


class RoutedLLM:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.ollama = OllamaProvider()
        self.together = TogetherProvider()
        self.openai = OpenAIProvider()
        self.groq = GroqProvider()
        self.gemini = GeminiProvider()
        self.mock = MockProvider()

    @staticmethod
    def _ov(overrides: dict[str, str] | None, key: str) -> str | None:
        if not overrides:
            return None
        value = overrides.get(key)
        if value is None:
            return None
        return value.strip() or None

    def _build_provider(self, name: str, overrides: dict[str, str] | None) -> LLMProvider:
        if not overrides:
            if name == "ollama":
                return self.ollama
            if name == "groq":
                return self.groq
            if name == "gemini":
                return self.gemini
            if name == "openai":
                return self.openai
            if name == "together":
                return self.together
            return self.mock
        if name == "ollama":
            return OllamaProvider(
                base_url=self._ov(overrides, "ollama_base_url"),
                model=self._ov(overrides, "ollama_model"),
            )
        if name == "groq":
            return GroqProvider(
                api_key=self._ov(overrides, "groq_api_key"),
                model=self._ov(overrides, "groq_model"),
                base_url=self._ov(overrides, "groq_base_url"),
            )
        if name == "gemini":
            return GeminiProvider(
                api_key=self._ov(overrides, "gemini_api_key"),
                model=self._ov(overrides, "gemini_model"),
            )
        if name == "openai":
            return OpenAIProvider(
                api_key=self._ov(overrides, "openai_api_key"),
                model=self._ov(overrides, "openai_model"),
                base_url=self._ov(overrides, "openai_base_url"),
            )
        if name == "together":
            return TogetherProvider(
                api_key=self._ov(overrides, "together_api_key"),
                model=self._ov(overrides, "together_model"),
                base_url=self._ov(overrides, "together_base_url"),
            )
        return self.mock

    def generate_with_provider(
        self,
        prompt: str,
        provider_pref: str | None = None,
        provider_overrides: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        preferred = (provider_pref or "groq").lower()
        provider_names: list[str]

        if preferred == "gemini":
            provider_names = ["gemini", "groq", "openai", "mock"]
        elif preferred == "groq":
            provider_names = ["groq", "gemini", "openai", "mock"]
        elif preferred == "openai":
            provider_names = ["openai", "groq", "gemini", "mock"]
        elif preferred == "together":
            provider_names = ["together", "groq", "openai", "mock"]
        elif preferred == "ollama":
            provider_names = ["ollama", "groq", "openai", "mock"]
        elif preferred == "mock":
            provider_names = ["mock"]
        else:
            provider_names = ["groq", "gemini", "openai", "ollama", "together", "mock"]

        last_exc: Exception | None = None
        for name in provider_names:
            provider = self._build_provider(name, provider_overrides)
            try:
                logger.info("LLM provider attempt: %s", name)
                return provider.generate(prompt), name
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM provider failed (%s): %s", name, exc)
                last_exc = exc
        if last_exc:
            raise RuntimeError(f"No model provider available: {last_exc}") from last_exc
        raise RuntimeError("No model provider available.")

    def generate(
        self,
        prompt: str,
        provider_pref: str | None = None,
        provider_overrides: dict[str, str] | None = None,
    ) -> str:
        text, _ = self.generate_with_provider(
            prompt,
            provider_pref=provider_pref,
            provider_overrides=provider_overrides,
        )
        return text
