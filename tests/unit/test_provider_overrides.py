from __future__ import annotations

from app.models.providers import RoutedLLM


class _FakeResponse:
    def raise_for_status(self) -> None:
        return

    @staticmethod
    def json() -> dict:
        return {"response": "ok"}


def test_ollama_runtime_override(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, json, timeout):  # noqa: ANN001
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("app.models.providers.httpx.post", fake_post)

    llm = RoutedLLM()
    text, provider = llm.generate_with_provider(
        "test prompt",
        provider_pref="ollama",
        provider_overrides={
            "ollama_base_url": "http://custom-ollama:11434",
            "ollama_model": "llama3.1:8b",
        },
    )

    assert provider == "ollama"
    assert text == "ok"
    assert captured["url"] == "http://custom-ollama:11434/api/generate"
    assert captured["json"]["model"] == "llama3.1:8b"
