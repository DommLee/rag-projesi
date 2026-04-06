from __future__ import annotations

import logging
from datetime import UTC, datetime

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
    def __init__(self, retriever: Retriever, llm: RoutedLLM, claim_ledger: ClaimLedger) -> None:
        self.nodes = AgentNodes(retriever=retriever, llm=llm, claim_ledger=claim_ledger)
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

    def _compile(self):
        if StateGraph is None:
            logger.warning("LangGraph not available. Falling back to sequential flow.")
            return None
        graph = StateGraph(AgentState)
        graph.add_node("intent_router", self.nodes.intent_router)
        graph.add_node("source_planner", self.nodes.source_planner)
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
        graph.add_edge("source_planner", "retriever_pass1")
        graph.add_edge("retriever_pass1", "verifier")
        graph.add_conditional_edges(
            "verifier",
            self._route_after_verifier,
            {"composer": "composer", "reretriever": "reretriever"},
        )
        graph.add_edge("reretriever", "counterfactual_probe")
        graph.add_edge("counterfactual_probe", "composer")
        graph.add_edge("composer", END)
        return graph.compile()

    def _run_sequential(self, state: AgentState) -> AgentState:
        state.update(self.nodes.intent_router(state))
        if state.get("risk_blocked"):
            state.update(self.nodes.composer(state))
            return state

        state.update(self.nodes.source_planner(state))
        state.update(self.nodes.retriever_pass1(state))
        state.update(self.nodes.verifier(state))
        if state.get("should_reretrieve"):
            state.update(self.nodes.reretriever(state))
            state.update(self.nodes.counterfactual_probe(state))
        state.update(self.nodes.composer(state))
        return state

    def run(self, state: AgentState) -> QueryResponse:
        if self._compiled:
            out = self._compiled.invoke(state)
        else:
            out = self._run_sequential(state)

        return QueryResponse(
            answer_tr=out.get("answer_tr", ""),
            answer_en=out.get("answer_en", ""),
            as_of_date=state.get("as_of_date") or datetime.now(UTC),
            citations=out.get("citations", []),
            consistency_assessment=out.get("consistency_assessment", "inconclusive"),
            confidence=float(out.get("confidence", 0.5)),
            disclaimer="This system does not provide investment advice.",
            blocked=out.get("consistency_assessment") == "blocked_policy",
            citation_coverage_score=float(out.get("citation_coverage_score", 0.0)),
            evidence_gaps=out.get("evidence_gaps", []),
            used_sources=list({c.source_type for c in out.get("citations", [])}),
            provider_used=out.get("provider_used", "unknown"),
        )

