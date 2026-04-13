from app.market.entity_aliases import alias_keywords, detect_ticker_from_text, entity_match_details, entity_match_score


def test_entity_match_score_positive_for_alias() -> None:
    score = entity_match_score(
        "Aselsan yeni savunma sözleşmesi açıkladı.",
        "ASELS",
        title="Aselsan savunma sözleşmesi",
        source_label="Bloomberg HT",
    )
    assert score >= 0.34


def test_detect_ticker_from_text_returns_best_match() -> None:
    ticker = detect_ticker_from_text("Türk Hava Yolları ve THY operasyonel sonuçları gündemde.")
    assert ticker == "THYAO"


def test_alias_keywords_loads_clean_aliases() -> None:
    aliases = alias_keywords("KCHOL")
    assert "koc holding" in aliases
    assert "koc" in aliases


def test_entity_match_details_penalizes_macro_only_context() -> None:
    macro = entity_match_details(
        "TCMB enflasyon ve kur görünümüyle ilgili makro rapor yayımlandı.",
        "ASELS",
        title="Makro görünüm raporu",
        source_label="Google News Discovery",
    )
    assert macro["score"] < 0.34
    assert macro["reason"] in {"low_confidence_macro_context", "no_match"}


def test_entity_match_details_uses_title_prior() -> None:
    details = entity_match_details(
        "Savunma sanayii gündeminde yeni sözleşmeler konuşuluyor.",
        "ASELS",
        title="Aselsan yeni sözleşme açıkladı",
        source_label="Bloomberg HT",
    )
    assert details["score"] >= 0.34
    assert details["reason"] in {"title_match", "matched"}
