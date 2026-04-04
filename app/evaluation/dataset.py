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

