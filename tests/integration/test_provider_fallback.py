from app.models.providers import RoutedLLM


def test_provider_fallback_ollama_to_together(monkeypatch) -> None:
    llm = RoutedLLM()

    def fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("ollama down")

    def succeed(*args, **kwargs):  # noqa: ANN002, ANN003
        return '{"answer_tr":"ok","answer_en":"ok","consistency_assessment":"inconclusive","confidence":0.5}'

    monkeypatch.setattr(llm.ollama, "generate", fail)
    monkeypatch.setattr(llm.together, "generate", succeed)
    out = llm.generate("test prompt")
    assert "answer_tr" in out

