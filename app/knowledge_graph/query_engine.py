from __future__ import annotations

import re
from typing import Any

from app.knowledge_graph.graph_builder import BISTKnowledgeGraphBuilder
from app.market.entity_aliases import DEFAULT_TICKER_ENTITY_ALIASES, detect_ticker_from_text
from app.utils.text import normalize_visible_text


class BISTGraphQueryEngine:
    def __init__(self, builder: BISTKnowledgeGraphBuilder | None = None) -> None:
        self.builder = builder or BISTKnowledgeGraphBuilder()

    @staticmethod
    def is_relationship_query(question: str) -> bool:
        q = normalize_visible_text(question).lower()
        return any(
            token in q
            for token in [
                "ilişki", "iliski", "iştirak", "istirak", "bağlı", "bagli", "ortak",
                "holding", "sektör", "sektor", "benzer şirket", "benzer sirket",
            ]
        )

    def _resolve_ticker(self, question: str, ticker: str | None = None) -> str:
        cleaned = (ticker or "").strip().upper()
        if cleaned:
            if cleaned == "KOCHO":
                return "KCHOL"
            return cleaned
        direct = re.findall(r"\b[A-Z]{4,5}\b", question.upper())
        for item in direct:
            if item == "KOCHO":
                return "KCHOL"
            if item in DEFAULT_TICKER_ENTITY_ALIASES or item in self.builder.SECTORS:
                return item
        return detect_ticker_from_text(question) or "KCHOL"

    def query(self, question: str, ticker: str | None = None) -> dict[str, Any]:
        resolved = self._resolve_ticker(question, ticker)
        relation = None
        q = normalize_visible_text(question).lower()
        if "sektor" in q or "sektör" in q:
            relation = "same_sector"
        if any(token in q for token in ["istirak", "iştirak", "holding", "bagli", "bağlı"]):
            relation = "portfolio_association"

        edges = self.builder.neighbors(resolved, relation=relation)
        peers = self.builder.sector_peers(resolved)
        lines = []
        if edges:
            for edge in edges[:12]:
                direction = f"{edge['source']} -> {edge['target']}"
                lines.append(f"{direction}: {edge['relation']} (confidence={float(edge['confidence']):.2f})")
        elif peers:
            lines.append(f"{resolved} için aynı sektör eşleşmeleri: {', '.join(peers)}")
        else:
            lines.append(f"{resolved} için local bilgi grafında yeterli ilişki bulunamadı.")

        answer_tr = (
            f"{resolved} için GraphRAG ilişki katmanı sonucu: "
            + " ; ".join(lines)
            + ". Bu çıktı resmi yatırım tavsiyesi değil, ilişki keşfi bağlamıdır."
        )
        answer_en = (
            f"GraphRAG relationship layer for {resolved}: "
            + " ; ".join(lines)
            + ". This is relationship discovery context, not investment advice."
        )
        return {
            "ticker": resolved,
            "question": question,
            "relation_filter": relation or "all",
            "nodes": sorted({resolved, *peers, *[edge["source"] for edge in edges], *[edge["target"] for edge in edges]}),
            "edges": edges,
            "sector_peers": peers,
            "answer_tr": answer_tr,
            "answer_en": answer_en,
            "confidence": 0.75 if edges else 0.45,
            "source_note": "Local NetworkX/pure-Python GraphRAG seed from public issuer context and alias registry.",
            "disclaimer": "This system does not provide investment advice.",
        }
