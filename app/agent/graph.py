from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Callable, Generator

from app.agent.nodes import AgentNodes
from app.agent.state import AgentState
from app.memory.claim_ledger import ClaimLedger
from app.models.providers import RoutedLLM
from app.retrieval.retriever import Retriever
from app.schemas import QueryResponse

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # noqa: BLE001
    END = "__end__"
    START = "__start__"
    StateGraph = None


class AgentGraph:
    def __init__(
        self,
        retriever: Retriever,
        llm: RoutedLLM,
        claim_ledger: ClaimLedger,
        market_context_fn: Callable[..., dict[str, Any]] | None = None,
        web_search_fn: Callable[..., list[dict[str, str]]] | None = None,
        graph_query_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.nodes = AgentNodes(
            retriever=retriever,
            llm=llm,
            claim_ledger=claim_ledger,
            market_context_fn=market_context_fn,
            web_search_fn=web_search_fn,
            graph_query_fn=graph_query_fn,
        )
        self._compiled = self._compile()

    @staticmethod
    def _route_after_intent(state: AgentState) -> str:
        if state.get("risk_blocked"):
            return "composer"
        return "source_planner"

    @staticmethod
    def _route_after_verifier(state: AgentState) -> str:
        if state.get("should_reretrieve"):
            return "reretriever"
        return "composer"

    @staticmethod
    def _safe_probability(value: object, default: float = 0.5) -> float:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        text = str(value).strip().lower()
        mapping = {
            "low": 0.35,
            "medium": 0.6,
            "high": 0.85,
            "very_low": 0.2,
            "very_high": 0.95,
            "dusuk": 0.35,
            "düşük": 0.35,
            "orta": 0.6,
            "yuksek": 0.85,
            "yüksek": 0.85,
        }
        if text in mapping:
            return mapping[text]
        try:
            return max(0.0, min(1.0, float(text.replace(",", "."))))
        except Exception:  # noqa: BLE001
            return default

    def _compile(self):
        if StateGraph is None:
            logger.warning("LangGraph not available. Falling back to sequential flow.")
            return None
        graph = StateGraph(AgentState)
        graph.add_node("intent_router", self.nodes.intent_router)
        graph.add_node("source_planner", self.nodes.source_planner)
        graph.add_node("graph_retriever", self.nodes.graph_retriever)
        graph.add_node("retriever_pass1", self.nodes.retriever_pass1)
        graph.add_node("verifier", self.nodes.verifier)
        graph.add_node("reretriever", self.nodes.reretriever)
        graph.add_node("counterfactual_probe", self.nodes.counterfactual_probe)
        graph.add_node("composer", self.nodes.composer)

        graph.add_edge(START, "intent_router")
        graph.add_conditional_edges(
            "intent_router",
            self._route_after_intent,
            {"composer": "composer", "source_planner": "source_planner"},
        )
        graph.add_edge("source_planner", "graph_retriever")
        graph.add_edge("graph_retriever", "retriever_pass1")
        graph.add_edge("retriever_pass1", "verifier")
        graph.add_conditional_edges(
            "verifier",
            self._route_after_verifier,
            {"composer": "composer", "reretriever": "reretriever"},
        )
        graph.add_edge("reretriever", "counterfactual_probe")
        graph.add_edge("counterfactual_probe", "composer")
        graph.add_node("reflector", self.nodes.reflector)
        graph.add_edge("composer", "reflector")
        graph.add_edge("reflector", END)
        return graph.compile()

    def _run_sequential(self, state: AgentState) -> AgentState:
        state.update(self.nodes.intent_router(state))
        if state.get("risk_blocked"):
            state.update(self.nodes.composer(state))
            return state

        state.update(self.nodes.source_planner(state))
        state.update(self.nodes.graph_retriever(state))
        state.update(self.nodes.retriever_pass1(state))
        state.update(self.nodes.verifier(state))
        if state.get("should_reretrieve"):
            state.update(self.nodes.reretriever(state))
            state.update(self.nodes.counterfactual_probe(state))
        state.update(self.nodes.composer(state))
        state.update(self.nodes.reflector(state))
        return state

    def run_streaming(self, state: AgentState) -> Generator[dict[str, Any], None, QueryResponse]:
        """Execute the agent graph step-by-step, yielding progress events."""
        steps = [
            ("intent_router", self.nodes.intent_router),
            ("source_planner", self.nodes.source_planner),
            ("graph_retriever", self.nodes.graph_retriever),
            ("retriever_pass1", self.nodes.retriever_pass1),
            ("verifier", self.nodes.verifier),
        ]
        for name, fn in steps:
            if name != "intent_router" and state.get("risk_blocked"):
                break
            result = fn(state)
            state.update(result)
            yield {"node": name, "status": "done", **self._stream_snapshot(name, state)}

        if not state.get("risk_blocked") and state.get("should_reretrieve"):
            for name, fn in [
                ("reretriever", self.nodes.reretriever),
                ("counterfactual_probe", self.nodes.counterfactual_probe),
            ]:
                result = fn(state)
                state.update(result)
                yield {"node": name, "status": "done", **self._stream_snapshot(name, state)}

        # Web search (optional, non-blocking)
        ws_result = self.nodes.web_searcher(state)
        state.update(ws_result)
        if state.get("web_search_results"):
            yield {"node": "web_searcher", "status": "done", "web_results_count": len(state["web_search_results"])}

        result = self.nodes.composer(state)
        state.update(result)
        yield {"node": "composer", "status": "done"}

        # Reflection: self-critique pass
        reflect_result = self.nodes.reflector(state)
        state.update(reflect_result)
        if state.get("reflection_applied"):
            yield {"node": "reflector", "status": "done", "rewritten": True}

        return self._build_response(state)

    @staticmethod
    def _stream_snapshot(node: str, state: AgentState) -> dict[str, Any]:
        if node == "retriever_pass1":
            return {"docs_found": len(state.get("pass1_docs") or [])}
        if node == "verifier":
            return {
                "consistency": state.get("consistency_assessment", ""),
                "tension": state.get("contradiction_confidence", 0),
                "coverage": state.get("evidence_coverage", 0),
                "will_reretrieve": state.get("should_reretrieve", False),
            }
        if node == "intent_router":
            return {"question_type": state.get("question_type", ""), "blocked": state.get("risk_blocked", False)}
        return {}

    def _build_response(self, out: AgentState) -> QueryResponse:
        if out.get("consistency_assessment") == "blocked_policy":
            route_path = "blocked"
        elif out.get("should_reretrieve"):
            route_path = "reretrieve"
        else:
            route_path = "direct"
        return QueryResponse(
            answer_tr=out.get("answer_tr", ""),
            answer_en=out.get("answer_en", ""),
            as_of_date=out.get("as_of_date") or datetime.now(UTC),
            citations=out.get("citations", []),
            consistency_assessment=out.get("consistency_assessment", "inconclusive"),
            confidence=self._safe_probability(out.get("confidence", 0.5), default=0.5),
            disclaimer="This system does not provide investment advice.",
            blocked=out.get("consistency_assessment") == "blocked_policy",
            citation_coverage_score=self._safe_probability(out.get("citation_coverage_score", 0.0), default=0.0),
            evidence_gaps=out.get("evidence_gaps", []),
            used_sources=list({c.source_type for c in out.get("citations", [])}),
            provider_used=out.get("provider_used", "unknown"),
            route_path=route_path,
        )

    def run(self, state: AgentState) -> QueryResponse:
        if self._compiled:
            out = self._compiled.invoke(state)
        else:
            out = self._run_sequential(state)
        return self._build_response(out)
