from __future__ import annotations

import json
import random
from pathlib import Path


DEFAULT_QUESTIONS = [
    {
        "ticker": "ASELS",
        "question": "What types of KAP disclosures has ASELS published in the last 6 months?",
        "expected_consistency": "inconclusive",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "THYAO",
        "question": "Summarize recent KAP material event disclosures for THYAO.",
        "expected_consistency": "aligned",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "SISE",
        "question": "What themes are repeated in recent brokerage reports for SISE?",
        "expected_consistency": "inconclusive",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "BIMAS",
        "question": "Do recent news items align with official KAP disclosures for BIMAS?",
        "expected_consistency": "aligned",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "EREGL",
        "question": "How did the narrative around EREGL change over the last quarter?",
        "expected_consistency": "inconclusive",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "AKBNK",
        "question": "Compare KAP vs media framing for AKBNK in the last 30 days.",
        "expected_consistency": "contradiction",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "GARAN",
        "question": "What are the dominant sector-level signals affecting GARAN narrative?",
        "expected_consistency": "inconclusive",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "KCHOL",
        "question": "Which disclosures are most cited by media for KCHOL recently?",
        "expected_consistency": "aligned",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "YKBNK",
        "question": "Identify possible contradictions between news and KAP for YKBNK.",
        "expected_consistency": "contradiction",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "PETKM",
        "question": "How do brokerage institutions differ in PETKM report language?",
        "expected_consistency": "inconclusive",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "TUPRS",
        "question": "What changed in TUPRS narrative before and after latest KAP filing?",
        "expected_consistency": "inconclusive",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "FROTO",
        "question": "List recent evidence-backed themes for FROTO across sources.",
        "expected_consistency": "aligned",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "ISCTR",
        "question": "Find consistency or mismatch between official and media statements for ISCTR.",
        "expected_consistency": "contradiction",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "SASA",
        "question": "What is the timeline-aware summary for SASA from KAP and news?",
        "expected_consistency": "inconclusive",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "TCELL",
        "question": "Which recurring topics appear in TCELL brokerage reports this month?",
        "expected_consistency": "inconclusive",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "PGSUS",
        "question": "Do recent PGSUS news headlines align with official disclosures?",
        "expected_consistency": "aligned",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "SAHOL",
        "question": "Summarize the latest SAHOL KAP-driven narrative and media framing.",
        "expected_consistency": "inconclusive",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "TCELL",
        "question": "Are there any contradiction signals between TCELL disclosures and market news?",
        "expected_consistency": "contradiction",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "DOAS",
        "question": "What changed in DOAS narrative after the latest official filing?",
        "expected_consistency": "inconclusive",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "AEFES",
        "question": "Which themes are repeated across AEFES news and brokerage commentary?",
        "expected_consistency": "aligned",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "KOZAL",
        "question": "Identify potential mismatch between KOZAL KAP statements and media narrative.",
        "expected_consistency": "contradiction",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "VAKBN",
        "question": "Provide a time-aware summary of recent VAKBN disclosures and news coverage.",
        "expected_consistency": "inconclusive",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "ULKER",
        "question": "What evidence-backed storyline appears for ULKER across sources?",
        "expected_consistency": "aligned",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "ENKAI",
        "question": "Do ENKAI media summaries overstate or align with official disclosure content?",
        "expected_consistency": "contradiction",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "ARCLK",
        "question": "Summarize ARCLK narrative drift over recent weeks.",
        "expected_consistency": "inconclusive",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "MGROS",
        "question": "Which official MGROS developments are echoed by financial news sources?",
        "expected_consistency": "aligned",
        "min_citations": 2,
        "must_include_time": True,
    },
    {
        "ticker": "HEKTS",
        "question": "Check whether HEKTS news flow contradicts recent KAP disclosures.",
        "expected_consistency": "contradiction",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "ASTOR",
        "question": "What are the dominant recent ASTOR themes across KAP, news and brokerage?",
        "expected_consistency": "inconclusive",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "ENJSA",
        "question": "Produce an evidence-backed ENJSA narrative summary with source agreement status.",
        "expected_consistency": "aligned",
        "min_citations": 3,
        "must_include_time": True,
    },
    {
        "ticker": "TKFEN",
        "question": "Are recent TKFEN headlines consistent with official disclosure tone?",
        "expected_consistency": "contradiction",
        "min_citations": 3,
        "must_include_time": True,
    },
]


def load_eval_questions(path: str) -> list[dict]:
    file_path = Path(path)
    if not file_path.exists():
        return DEFAULT_QUESTIONS
    with file_path.open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    if not isinstance(data, list):
        return DEFAULT_QUESTIONS
    return data


def sample_eval_questions(items: list[dict], sample_size: int) -> list[dict]:
    if sample_size <= 0 or sample_size >= len(items):
        return items
    return random.sample(items, sample_size)
