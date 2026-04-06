from datetime import UTC, datetime

from app.guardrails_claims import claim_coverage_score, decompose_claims, ground_claims
from app.schemas import Citation, SourceType


def _citation(snippet: str, source_type: SourceType = SourceType.NEWS) -> Citation:
    now = datetime.now(UTC)
    return Citation(
        source_type=source_type,
        title="News",
        institution="AA",
        date=now,
        url="https://example.com",
        snippet=snippet,
    )


def test_decompose_claims_marks_declarative_sentences() -> None:
    claims = decompose_claims("Şirket gelir artışı bildirdi. Bu bir tahmin olabilir mi?")
    assert len(claims) == 2
    assert claims[0].declarative is True
    assert claims[1].declarative is False


def test_ground_claims_detects_matches() -> None:
    claims = decompose_claims("Şirket gelir artışı bildirdi.")
    citations = [_citation("Bugün şirket gelir artışı bildirdi ve onay aldı.")]
    result = ground_claims(claims, citations)
    assert result.total_claims == 1
    assert result.grounded_claims == 1
    assert claim_coverage_score(result) == 1.0


def test_ground_claims_detects_ungrounded_claims() -> None:
    claims = decompose_claims("Şirket ceza aldı.")
    citations = [_citation("Şirket üretim kapasitesini artırdı.")]
    result = ground_claims(claims, citations)
    assert result.total_claims == 1
    assert result.grounded_claims == 0
    assert result.ungrounded_claims
    assert claim_coverage_score(result) == 0.0


def test_disclaimer_is_excluded_from_claim_coverage() -> None:
    claims = decompose_claims("This system does not provide investment advice.")
    result = ground_claims(claims, [])
    assert result.total_claims == 0
    assert claim_coverage_score(result) == 1.0


def test_source_hint_matches_citation_type() -> None:
    claims = decompose_claims("KAP özeti: operasyonel hedeflerde artış var.")
    citations = [_citation("Detaylar KAP metninde yer alıyor.", source_type=SourceType.KAP)]
    result = ground_claims(claims, citations)
    assert result.total_claims == 1
    assert result.grounded_claims == 1

