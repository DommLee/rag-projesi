from __future__ import annotations

import re


MOJIBAKE_MARKERS = ("\u00c3", "\u00c4", "\u00c5", "\u00d0", "\u00de", "\u00e2")


def repair_mojibake(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text
    for codec in ("latin1", "cp1252"):
        try:
            repaired = text.encode(codec, errors="ignore").decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        if repaired and repaired != text:
            return repaired
    return text


def normalize_visible_text(value: str | None) -> str:
    text = repair_mojibake(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()
