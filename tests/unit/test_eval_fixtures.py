from app.evaluation.fixtures import build_eval_fixture_chunks
from app.schemas import SourceType


def test_build_eval_fixture_chunks_generates_multisource_docs() -> None:
    questions = [
        {"ticker": "AKBNK", "expected_consistency": "contradiction"},
        {"ticker": "THYAO", "expected_consistency": "aligned"},
    ]
    chunks = build_eval_fixture_chunks(questions)
    assert len(chunks) >= 10

    akbnk = [chunk for chunk in chunks if chunk.ticker == "AKBNK"]
    assert len(akbnk) >= 5
    assert any(chunk.source_type == SourceType.KAP for chunk in akbnk)
    assert any(chunk.source_type == SourceType.NEWS for chunk in akbnk)
    assert any(chunk.source_type == SourceType.BROKERAGE for chunk in akbnk)
