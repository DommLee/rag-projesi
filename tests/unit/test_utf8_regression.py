from app.utils.analytics import _normalize_token


def test_utf8_characters_preserved_in_normalization() -> None:
    assert _normalize_token("\u0130yile\u015fme") == "iyile\u015fme"
    assert _normalize_token("\u00c7eli\u015fki") == "\u00e7eli\u015fki"
    assert _normalize_token("G\u00fc\u00e7l\u00fc") == "g\u00fc\u00e7l\u00fc"
    assert _normalize_token("\u00d6ng\u00f6r\u00fc") == "\u00f6ng\u00f6r\u00fc"
    assert _normalize_token("\u00dcretim") == "\u00fcretim"

