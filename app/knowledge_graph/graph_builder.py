from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.market.entity_aliases import alias_keywords


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    confidence: float
    evidence: str


class BISTKnowledgeGraphBuilder:
    """Small local knowledge graph for BIST relationship questions.

    NetworkX is used when installed; otherwise a plain adjacency map is used.
    This keeps the local demo reliable without requiring a Neo4j service.
    """

    SECTORS: dict[str, str] = {
        "AKBNK": "bankacilik",
        "GARAN": "bankacilik",
        "ISCTR": "bankacilik",
        "YKBNK": "bankacilik",
        "ASELS": "savunma-teknoloji",
        "THYAO": "havacilik",
        "PGSUS": "havacilik",
        "KCHOL": "holding",
        "SAHOL": "holding",
        "FROTO": "otomotiv",
        "TOASO": "otomotiv",
        "TUPRS": "enerji",
        "ARCLK": "dayanikli-tuketim",
        "SISE": "cam-kimya",
        "BIMAS": "perakende",
        "TCELL": "telekom",
    }

    STATIC_EDGES: tuple[GraphEdge, ...] = (
        GraphEdge("KCHOL", "ARCLK", "portfolio_association", 0.82, "Koc Holding group context / public issuer profile"),
        GraphEdge("KCHOL", "FROTO", "portfolio_association", 0.82, "Koc Holding group context / public issuer profile"),
        GraphEdge("KCHOL", "TOASO", "portfolio_association", 0.82, "Koc Holding group context / public issuer profile"),
        GraphEdge("KCHOL", "TUPRS", "portfolio_association", 0.82, "Koc Holding group context / public issuer profile"),
        GraphEdge("KCHOL", "YKBNK", "portfolio_association", 0.78, "Koc Holding group context / public issuer profile"),
        GraphEdge("SAHOL", "AKBNK", "portfolio_association", 0.78, "Sabanci Holding group context / public issuer profile"),
    )

    def __init__(self) -> None:
        try:
            import networkx as nx  # type: ignore

            self._nx = nx
            self.graph = nx.MultiDiGraph()
        except Exception:  # noqa: BLE001
            self._nx = None
            self.graph = {"nodes": {}, "edges": []}
        self.build_default_graph()

    def build_default_graph(self) -> None:
        for ticker, sector in self.SECTORS.items():
            self.add_node(ticker, {"sector": sector, "aliases": list(alias_keywords(ticker))})
        for edge in self.STATIC_EDGES:
            self.add_edge(edge)
        for left, left_sector in self.SECTORS.items():
            for right, right_sector in self.SECTORS.items():
                if left >= right or left_sector != right_sector:
                    continue
                self.add_edge(GraphEdge(left, right, "same_sector", 0.65, f"Shared sector: {left_sector}"))
                self.add_edge(GraphEdge(right, left, "same_sector", 0.65, f"Shared sector: {left_sector}"))

    def add_node(self, ticker: str, attrs: dict[str, Any]) -> None:
        ticker = ticker.upper()
        if self._nx:
            self.graph.add_node(ticker, **attrs)
        else:
            self.graph["nodes"][ticker] = attrs

    def add_edge(self, edge: GraphEdge) -> None:
        if self._nx:
            self.graph.add_edge(
                edge.source,
                edge.target,
                relation=edge.relation,
                confidence=edge.confidence,
                evidence=edge.evidence,
            )
        else:
            self.graph["edges"].append(edge)

    def neighbors(self, ticker: str, relation: str | None = None) -> list[dict[str, Any]]:
        ticker = ticker.upper()
        out: list[dict[str, Any]] = []
        if self._nx:
            for _, target, data in self.graph.out_edges(ticker, data=True):
                if relation and data.get("relation") != relation:
                    continue
                out.append({"source": ticker, "target": target, **data})
            for source, _, data in self.graph.in_edges(ticker, data=True):
                if relation and data.get("relation") != relation:
                    continue
                out.append({"source": source, "target": ticker, **data})
            return out
        for edge in self.graph["edges"]:
            if edge.source != ticker and edge.target != ticker:
                continue
            if relation and edge.relation != relation:
                continue
            out.append(edge.__dict__)
        return out

    def sector_peers(self, ticker: str) -> list[str]:
        ticker = ticker.upper()
        sector = self.SECTORS.get(ticker, "")
        return sorted([item for item, value in self.SECTORS.items() if value == sector and item != ticker])
