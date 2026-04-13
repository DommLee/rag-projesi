from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.utils.text import normalize_visible_text

DEFAULT_TICKER_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "AEFES": ("anadolu efes", "efes", "efes bira"),
    "AKBNK": ("akbank",),
    "AKSEN": ("aksa enerji",),
    "ALARK": ("alarko", "alarko holding"),
    "ARCLK": ("arcelik", "arçelik"),
    "ASELS": ("aselsan",),
    "ASTOR": ("astor enerji",),
    "BIMAS": ("bim", "bim magazalar", "bim mağazalar", "birlesik magazalar", "birleşik mağazalar"),
    "CCOLA": ("coca cola icecek", "coca cola içecek", "cci", "coca-cola icecek", "coca-cola içecek"),
    "DOAS": ("dogus otomotiv", "doğuş otomotiv"),
    "DOHOL": ("dogan holding", "doğan holding"),
    "ENKAI": ("enka insaat", "enka inşaat", "enka"),
    "EREGL": ("eregli demir", "ereğli demir", "erdemir"),
    "FROTO": ("ford otosan",),
    "GARAN": ("garanti", "garanti bbva"),
    "ISCTR": ("is bankasi", "iş bankası", "isbank", "işbank"),
    "KCHOL": ("koc holding", "koç holding", "koc", "koç"),
    "MGROS": ("migros",),
    "PGSUS": ("pegasus", "pegasus hava tasimaciligi", "pegasus hava taşımacılığı"),
    "SAHOL": ("sabanci", "sabancı", "sabanci holding", "sabancı holding"),
    "SISE": ("sisecam", "şişecam"),
    "TCELL": ("turkcell", "türkcell"),
    "THYAO": ("thy", "turk hava yollari", "türk hava yolları", "turkish airlines", "thyao"),
    "TOASO": ("tofas", "tofaş"),
    "TUPRS": ("tupras", "tüpraş"),
    "ULKER": ("ulker", "ülker"),
    "YKBNK": ("yapi kredi", "yapı kredi", "yapi ve kredi", "yapı ve kredi"),
}

NEGATIVE_CONTEXT_TERMS = {
    "endeks",
    "sepet",
    "fon",
    "makro",
    "tcmb",
    "enflasyon",
    "tufe",
    "tüfe",
    "ufe",
    "üfe",
    "tefas",
    "kur",
    "doviz",
    "döviz",
    "usdtry",
    "eurtry",
    "faiz",
    "tahvil",
    "eurobond",
    "veri takvimi",
}

SOURCE_TITLE_PRIOR = {
    "aa": 0.06,
    "bloomberg ht": 0.06,
    "paraanaliz": 0.04,
    "ekonomim": 0.05,
    "google news discovery": 0.0,
    "reuters": 0.06,
}


def _normalize_match_text(value: str | None) -> str:
    text = normalize_visible_text(value).lower()
    replacements = str.maketrans(
        {
            "ı": "i",
            "ğ": "g",
            "ş": "s",
            "ç": "c",
            "ö": "o",
            "ü": "u",
            "â": "a",
            "î": "i",
            "û": "u",
        }
    )
    return text.translate(replacements)


@lru_cache(maxsize=1)
def _external_alias_map() -> dict[str, tuple[str, ...]]:
    path = Path(__file__).resolve().parents[2] / "config" / "ticker_aliases.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, tuple[str, ...]] = {}
    if isinstance(payload, dict):
        for ticker, aliases in payload.items():
            if not isinstance(aliases, list):
                continue
            cleaned = tuple(
                dict.fromkeys(
                    alias
                    for alias in (_normalize_match_text(item) for item in aliases)
                    if alias
                )
            )
            if cleaned:
                out[str(ticker).upper()] = cleaned
    return out


def alias_keywords(ticker: str) -> tuple[str, ...]:
    normalized = ticker.strip().upper()
    aliases = list(DEFAULT_TICKER_ENTITY_ALIASES.get(normalized, ()))
    aliases.extend(_external_alias_map().get(normalized, ()))
    aliases.append(normalized.lower())
    return tuple(
        dict.fromkeys(
            alias
            for alias in (_normalize_match_text(item) for item in aliases)
            if alias
        )
    )


def entity_match_details(text: str, ticker: str, *, title: str = "", source_label: str = "") -> dict[str, object]:
    haystack = _normalize_match_text(text)
    title_text = _normalize_match_text(title)
    if not haystack and not title_text:
        return {"score": 0.0, "matched_aliases": [], "negative_terms": [], "reason": "empty_text"}

    aliases = alias_keywords(ticker)
    if not aliases:
        return {"score": 0.0, "matched_aliases": [], "negative_terms": [], "reason": "no_alias"}

    matched_body = [alias for alias in aliases if alias in haystack]
    matched_title = [alias for alias in aliases if alias in title_text]
    negative_terms = [term for term in NEGATIVE_CONTEXT_TERMS if term in haystack]
    direct_ticker_hit = ticker.strip().lower() in haystack or ticker.strip().lower() in title_text

    body_ratio = min(1.0, len(matched_body) / max(1, min(3, len(aliases))))
    title_ratio = min(1.0, len(matched_title) / max(1, min(2, len(aliases))))

    prior = 0.0
    source_norm = _normalize_match_text(source_label)
    for key, value in SOURCE_TITLE_PRIOR.items():
        if key in source_norm:
            prior = value
            break

    score = 0.06 + (body_ratio * 0.48) + (title_ratio * 0.28) + prior
    if direct_ticker_hit:
        score += 0.12
    if matched_title:
        score += 0.08

    macro_penalty = 0.0
    if negative_terms and not matched_title and len(matched_body) <= 1 and not direct_ticker_hit:
        macro_penalty += 0.26
    if source_norm == "google news discovery" and title_ratio == 0 and body_ratio < 0.34:
        macro_penalty += 0.08
    score = max(0.0, min(1.0, score - macro_penalty))

    reason = "matched"
    if score == 0.0:
        reason = "no_match"
    elif macro_penalty > 0:
        reason = "low_confidence_macro_context"
    elif matched_title:
        reason = "title_match"
    elif matched_body:
        reason = "body_match"

    return {
        "score": round(score, 4),
        "matched_aliases": matched_title[:2] + [alias for alias in matched_body if alias not in matched_title][:2],
        "negative_terms": negative_terms[:4],
        "reason": reason,
    }


def entity_match_score(text: str, ticker: str, *, title: str = "", source_label: str = "") -> float:
    return float(entity_match_details(text, ticker, title=title, source_label=source_label)["score"])


def detect_ticker_from_text(text: str, allowed: list[str] | None = None) -> str:
    candidates = [ticker.upper() for ticker in (allowed or DEFAULT_TICKER_ENTITY_ALIASES.keys())]
    ranked = sorted(
        ((ticker, entity_match_score(text, ticker, title=text)) for ticker in candidates),
        key=lambda item: item[1],
        reverse=True,
    )
    best_ticker, best_score = ranked[0] if ranked else ("", 0.0)
    return best_ticker if best_score >= 0.34 else ""
