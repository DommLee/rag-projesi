"""Semantic query rewriter for Turkish financial queries.

Normalizes TR↔EN mixed queries, expands common abbreviations, and fixes
common typos in BIST ticker/finance context.
"""

from __future__ import annotations

import re

# Only expand abbreviations that are unlikely to appear in tickers or
# established financial shorthand.  Well-known terms like KAP, BIST,
# TCMB are left as-is because the retriever already understands them
# and expanding them can change question_type classification.
_ABBR_MAP = {
    "spk": "SPK (Sermaye Piyasasi Kurulu)",
    "bddk": "BDDK (Bankacilik Duzenleme ve Denetleme Kurumu)",
    "f/k": "fiyat/kazanc orani",
    "pd/dd": "piyasa degeri/defter degeri",
    "gyo": "GYO (gayrimenkul yatirim ortakligi)",
}

# Common typos in Turkish financial context
_TYPO_MAP = {
    "hise": "hisse",
    "bors": "borsa",
    "borsa istanbul": "Borsa Istanbul",
    "aciklma": "aciklama",
    "bildiirm": "bildirim",
    "faaliyt": "faaliyet",
    "finasal": "finansal",
    "finanasal": "finansal",
    "rapro": "rapor",
    "yatirimci": "yatirimci",
    "temettü": "temettu",
    "bilanc": "bilanco",
    "gelir tablosuu": "gelir tablosu",
    "contradiciton": "contradiction",
    "consitency": "consistency",
}

# Turkish question patterns → enhanced retrieval queries
_QUERY_TEMPLATES = {
    r"son\s+(\d+)\s+(gun|ay|hafta)": "son {0} {1} icindeki gelismeler",
    r"ne\s+oldu": "son gelismeler ve onemli olaylar",
    r"neden\s+(dustu|yukseldi|degisti)": "fiyat degisiminin nedenleri",
    r"temettu.*(ne\s+zaman|dagit|odeme)": "temettu dagitim tarihi ve orani",
}


def rewrite_query(question: str) -> str:
    """Normalize and enhance a Turkish financial query for better retrieval."""
    q = question.strip()
    if not q:
        return q

    lowered = q.lower()

    # Fix common typos
    for typo, fix in _TYPO_MAP.items():
        if typo in lowered:
            q = re.sub(re.escape(typo), fix, q, flags=re.IGNORECASE)
            lowered = q.lower()

    # Expand abbreviations (only in isolation, not inside words)
    for abbr, expansion in _ABBR_MAP.items():
        pattern = rf"\b{re.escape(abbr)}\b"
        if re.search(pattern, lowered):
            q = re.sub(pattern, expansion, q, flags=re.IGNORECASE, count=1)
            lowered = q.lower()

    # If the query is too short, try to expand it with template patterns
    if len(q.split()) <= 3:
        for pattern, template in _QUERY_TEMPLATES.items():
            match = re.search(pattern, lowered)
            if match:
                expanded = template.format(*match.groups()) if match.groups() else template
                q = f"{q} — {expanded}"
                break

    return q.strip()


def generate_hyde_expansion(question: str, ticker: str) -> str:
    """Generate a Hypothetical Document Embedding (HyDE) expansion.

    For short or vague queries, we create a hypothetical ideal answer
    that would contain the information the user is looking for. This
    hypothetical text is used alongside the original query for retrieval,
    improving recall for sparse queries.

    This is a template-based HyDE (no LLM call needed).
    """
    q_lower = question.lower()
    ticker_up = ticker.upper()

    # Don't expand already-detailed queries
    if len(question.split()) > 12:
        return ""

    # Template hypothetical answers for common query patterns
    if any(k in q_lower for k in ["kap", "bildirim", "aciklama", "disclosure"]):
        return (
            f"{ticker_up} sirketinin son donemde Kamuyu Aydinlatma Platformu (KAP) "
            f"uzerinden yaptigi onemli bildirimlerde ozel durum aciklamasi, "
            f"finansal rapor ve yonetim kurulu kararlari yer almaktadir. "
            f"{ticker_up} material event disclosure financial report board decision."
        )
    elif any(k in q_lower for k in ["haber", "news", "media", "basin"]):
        return (
            f"{ticker_up} hakkinda son donem haber akisinda sektorel gelismeler, "
            f"finansal sonuclar ve piyasa beklentileri one cikmaktadir. "
            f"{ticker_up} recent news financial results market expectations sector developments."
        )
    elif any(k in q_lower for k in ["analiz", "rapor", "broker", "araci"]):
        return (
            f"{ticker_up} icin araci kurum raporlarinda hedef fiyat, "
            f"finansal analiz ve sektor karsilastirmasi degerlendirmeleri bulunmaktadir. "
            f"{ticker_up} brokerage report target price financial analysis sector comparison."
        )
    elif any(k in q_lower for k in ["celisk", "contradic", "tutarsiz", "mismatch"]):
        return (
            f"{ticker_up} icin resmi KAP aciklamalari ile haber akisi arasinda "
            f"olasi tutarsizliklar ve farkli cerceveleme yaklisimlari tespit edilmistir. "
            f"{ticker_up} contradiction mismatch between official KAP filings and news media framing."
        )
    elif any(k in q_lower for k in ["fiyat", "price", "degisim", "change"]):
        return (
            f"{ticker_up} hisse fiyatinda son donemde yasanan degisimler "
            f"sektorel ve makroekonomik faktorlerle iliskilendirilmektedir. "
            f"{ticker_up} stock price change recent period sector macroeconomic factors."
        )
    else:
        # Generic expansion
        return (
            f"{ticker_up} hakkinda resmi bildirimler, haber anlatisi ve "
            f"araci kurum raporlari cercevesinde guncel gelismeler. "
            f"{ticker_up} official disclosures news narrative brokerage reports recent developments."
        )

