from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SentimentResult:
    score: float
    label: str
    method: str = "tr_finance_lexicon"


class TurkishSentimentScorer:
    """Small Turkish financial sentiment scorer with optional HF fallback.

    The default path is dependency-free and safe for local demos. If a
    HuggingFace pipeline is already installed, callers can enable it later
    without making the core application fail at import time.
    """

    POSITIVE = {
        "artış", "artis", "güçlü", "guclu", "iyileşme", "iyilesme", "büyüme", "buyume",
        "karlılık", "karlilik", "pozitif", "rekor", "yüksek", "yuksek", "talep",
        "onay", "sipariş", "siparis", "yatırım", "yatirim", "ihracat", "marj",
    }
    NEGATIVE = {
        "azalış", "azalis", "zayıf", "zayif", "düşüş", "dusus", "negatif", "risk",
        "ceza", "iptal", "zarar", "daralma", "gerileme", "borç", "borc", "karşılık",
        "karsilik", "tedbir", "temkinli", "soruşturma", "sorusturma", "yaptırım", "yaptirim",
    }

    def __init__(self, use_hf: bool = False, model_name: str = "savasy/bert-base-turkish-sentiment-cased") -> None:
        self.use_hf = use_hf
        self.model_name = model_name
        self._pipeline = None

    @staticmethod
    def _normalize(text: str) -> str:
        lowered = unicodedata.normalize("NFKC", text or "").lower()
        asciiish = (
            lowered.replace("ı", "i")
            .replace("ğ", "g")
            .replace("ş", "s")
            .replace("ç", "c")
            .replace("ö", "o")
            .replace("ü", "u")
        )
        return asciiish

    def _score_lexicon(self, text: str) -> SentimentResult:
        norm = self._normalize(text)
        tokens = set(re.findall(r"[a-zA-ZğüşöçıİĞÜŞÖÇ]+", text.lower()))
        norm_tokens = set(re.findall(r"[a-z]+", norm))
        positive = len({self._normalize(token) for token in self.POSITIVE} & norm_tokens) + len(self.POSITIVE & tokens)
        negative = len({self._normalize(token) for token in self.NEGATIVE} & norm_tokens) + len(self.NEGATIVE & tokens)
        total = max(positive + negative, 1)
        score = max(-1.0, min(1.0, (positive - negative) / total))
        if score >= 0.2:
            label = "positive"
        elif score <= -0.2:
            label = "negative"
        else:
            label = "neutral"
        return SentimentResult(score=round(score, 4), label=label)

    def score(self, text: str) -> SentimentResult:
        if self.use_hf:
            try:
                if self._pipeline is None:
                    from transformers import pipeline  # type: ignore

                    self._pipeline = pipeline("sentiment-analysis", model=self.model_name)
                result = self._pipeline(text[:512])[0]
                label = str(result.get("label", "neutral")).lower()
                raw_score = float(result.get("score", 0.0))
                signed = raw_score if "pos" in label else -raw_score if "neg" in label else 0.0
                return SentimentResult(score=round(signed, 4), label="positive" if signed > 0 else "negative" if signed < 0 else "neutral", method="huggingface")
            except Exception as exc:  # noqa: BLE001
                logger.debug("HF Turkish sentiment unavailable; using lexicon scorer: %s", exc)
        return self._score_lexicon(text)


_DEFAULT_SCORER = TurkishSentimentScorer()


def score_turkish_financial_sentiment(text: str) -> SentimentResult:
    return _DEFAULT_SCORER.score(text)
