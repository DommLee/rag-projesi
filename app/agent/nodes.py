from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from app.agent.state import AgentState
from app.config import get_settings
from app.guardrails import append_disclaimer, post_answer_policy, pre_answer_policy
from app.guardrails_claims import decompose_claims, ground_claims
from app.memory.claim_ledger import ClaimLedger
from app.models.providers import RoutedLLM
from app.retrieval.retriever import Retriever
from app.schemas import Citation, DocumentChunk, SourceType
from app.utils.analytics import disclosure_news_tension_index

logger = logging.getLogger(__name__)


class AgentNodes:
    def __init__(self, retriever: Retriever, llm: RoutedLLM, claim_ledger: ClaimLedger) -> None:
        self.retriever = retriever
        self.llm = llm
        self.claim_ledger = claim_ledger
        self.settings = get_settings()

    @staticmethod
    def _normalize_question(text: str) -> str:
        lowered = text.lower()
        normalized = unicodedata.normalize("NFKD", lowered)
        ascii_safe = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return (
            ascii_safe.replace("ı", "i")
            .replace("ğ", "g")
            .replace("ş", "s")
            .replace("ç", "c")
            .replace("ö", "o")
            .replace("ü", "u")
        )

    @staticmethod
    def _question_type(question: str) -> str:
        q = AgentNodes._normalize_question(question)
        if "kap" in q and ("6 ay" in q or "last 6 months" in q):
            return "kap_disclosure_types"
        if "broker" in q or "araci kurum" in q or "report" in q:
            return "brokerage_narrative"
        if "celis" in q or "contradict" in q or "align" in q or "tutarli" in q:
            return "consistency_check"
        if "zaman" in q or "evolution" in q or "degis" in q:
            return "narrative_evolution"
        return "general_market_intel"

    @staticmethod
    def _sources_for_question_type(question_type: str) -> tuple[list[SourceType], dict[str, float]]:
        if question_type == "kap_disclosure_types":
            return [SourceType.KAP], {"kap": 0.9, "news": 0.05, "brokerage": 0.05}
        if question_type == "brokerage_narrative":
            return [SourceType.BROKERAGE, SourceType.NEWS], {"kap": 0.1, "news": 0.35, "brokerage": 0.55}
        if question_type == "consistency_check":
            return [SourceType.KAP, SourceType.NEWS, SourceType.BROKERAGE], {
                "kap": 0.5,
                "news": 0.35,
                "brokerage": 0.15,
            }
        if question_type == "narrative_evolution":
            return [SourceType.KAP, SourceType.NEWS, SourceType.BROKERAGE], {
                "kap": 0.45,
                "news": 0.4,
                "brokerage": 0.15,
            }
        return [SourceType.KAP, SourceType.NEWS], {"kap": 0.55, "news": 0.45, "brokerage": 0.0}

    @staticmethod
    def _build_citations(chunks: list[DocumentChunk], limit: int = 8) -> list[Citation]:
        citations: list[Citation] = []
        seen = set()
        for chunk in chunks:
            key = (chunk.doc_id, chunk.url)
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                Citation(
                    source_type=chunk.source_type,
                    title=chunk.title or f"{chunk.source_type.value} document",
                    institution=chunk.institution,
                    date=chunk.publication_date or chunk.date,
                    url=chunk.url,
                    snippet=chunk.content[:220],
                )
            )
            if len(citations) >= limit:
                break
        return citations

    @staticmethod
    def _parse_model_json(raw: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _dedupe_docs(groups: list[list[DocumentChunk]]) -> list[DocumentChunk]:
        deduped: list[DocumentChunk] = []
        seen = set()
        for group in groups:
            for chunk in group:
                if chunk.chunk_id in seen:
                    continue
                deduped.append(chunk)
                seen.add(chunk.chunk_id)
        return deduped

    def _llm_contradiction_score(
        self,
        question: str,
        docs: list[DocumentChunk],
        provider_pref: str | None,
        provider_overrides: dict[str, str] | None = None,
    ) -> float:
        if not docs:
            return 0.0
        snippets = []
        for idx, doc in enumerate(docs[:6], start=1):
            snippets.append(f"[{idx}] {doc.source_type.value} | {doc.date.date()} | {doc.content[:180]}")
        prompt = f"""
Return only JSON: {{"contradiction_score": float between 0 and 1}}.
Question: {question}
Evidence snippets:
{chr(10).join(snippets)}
"""
        try:
            raw, _ = self.llm.generate_with_provider(
                prompt,
                provider_pref=provider_pref,
                provider_overrides=provider_overrides,
            )
            parsed = self._parse_model_json(raw)
            return max(0.0, min(1.0, float(parsed.get("contradiction_score", 0.0))))
        except Exception:  # noqa: BLE001
            return 0.0

    def intent_router(self, state: AgentState) -> AgentState:
        policy = pre_answer_policy(state["question"])
        return {
            "risk_blocked": not policy.allowed,
            "policy_reason": policy.reason,
            "question_type": self._question_type(state["question"]),
            "refusal_tr": policy.refusal_tr,
            "refusal_en": policy.refusal_en,
            "skip_to_composer": not policy.allowed,
        }

    def source_planner(self, state: AgentState) -> AgentState:
        sources, weights = self._sources_for_question_type(state["question_type"])
        return {"source_plan": sources, "source_weights": weights}

    def retriever_pass1(self, state: AgentState) -> AgentState:
        docs, trace = self.retriever.retrieve_with_trace(
            query=state["question"],
            ticker=state["ticker"],
            source_types=state.get("source_plan"),
            as_of_date=state.get("as_of_date"),
            top_k=self.settings.max_top_k,
        )
        evidence_gaps = list(state.get("evidence_gaps", []))
        if not docs and state.get("source_plan"):
            fallback_docs, fallback_trace = self.retriever.retrieve_with_trace(
                query=state["question"],
                ticker=state["ticker"],
                source_types=None,
                as_of_date=state.get("as_of_date"),
                top_k=self.settings.max_top_k,
            )
            trace["fallback_any_source"] = fallback_trace
            if fallback_docs:
                docs = fallback_docs
                evidence_gaps.append("Preferred sources returned no hit; fallback retrieval used all source types.")
        return {"pass1_docs": docs, "retrieval_trace": trace, "evidence_gaps": evidence_gaps}

    def verifier(self, state: AgentState) -> AgentState:
        docs = state.get("pass1_docs", [])
        coverage = min(1.0, len(docs) / max(1, int(self.settings.max_top_k * 0.7)))
        rule_tension = float(disclosure_news_tension_index(docs).get("tension_index", 0.0))
        llm_tension = self._llm_contradiction_score(
            question=state["question"],
            docs=docs,
            provider_pref=state.get("provider_pref"),
            provider_overrides=state.get("provider_overrides"),
        )
        tension = round((rule_tension * 0.65) + (llm_tension * 0.35), 4)
        if tension >= 0.54:
            consistency = "contradiction"
        elif tension <= 0.30 and len(docs) > 2:
            consistency = "aligned"
        else:
            consistency = "inconclusive"

        should_reretrieve = coverage < 0.7 or (0.4 <= tension <= 0.6)
        return {
            "evidence_coverage": round(coverage, 4),
            "contradiction_confidence": tension,
            "consistency_assessment": consistency,
            "should_reretrieve": should_reretrieve,
        }

    def reretriever(self, state: AgentState) -> AgentState:
        docs = self.retriever.retrieve(
            query=f"{state['question']} resmi açıklama medya karşılaştırması",
            ticker=state["ticker"],
            source_types=[SourceType.KAP, SourceType.NEWS, SourceType.BROKERAGE],
            as_of_date=state.get("as_of_date"),
            top_k=self.settings.max_top_k + 4,
        )
        return {"pass2_docs": docs}

    def counterfactual_probe(self, state: AgentState) -> AgentState:
        planned = set(state.get("source_plan") or [])
        opposing = [s for s in [SourceType.KAP, SourceType.NEWS, SourceType.BROKERAGE] if s not in planned]
        if not opposing:
            opposing = [SourceType.NEWS, SourceType.KAP]
        docs = self.retriever.retrieve(
            query=f"Bu soruya ters yönden bakan kanıtlar: {state['question']}",
            ticker=state["ticker"],
            source_types=opposing,
            as_of_date=state.get("as_of_date"),
            top_k=max(3, self.settings.max_top_k // 2),
        )
        return {"counterfactual_docs": docs}

    def composer(self, state: AgentState) -> AgentState:
        if state.get("risk_blocked"):
            answer_tr = append_disclaimer(state.get("refusal_tr") or "Bu istek politika gereği engellendi.")
            answer_en = append_disclaimer(state.get("refusal_en") or "This request is blocked by policy.")
            return {
                "answer_tr": answer_tr,
                "answer_en": answer_en,
                "citations": [],
                "confidence": 1.0,
                "consistency_assessment": "blocked_policy",
                "evidence_gaps": ["Policy blocked investment advice request."],
                "citation_coverage_score": 0.0,
                "provider_used": "policy",
            }

        primary_docs = state.get("pass2_docs") or state.get("pass1_docs") or []
        counter_docs = state.get("counterfactual_docs") or []
        final_docs = self._dedupe_docs([primary_docs, counter_docs])
        citations = self._build_citations(final_docs)
        as_of_date = state.get("as_of_date") or datetime.now(UTC)

        evidence = []
        for idx, doc in enumerate(final_docs[:10], start=1):
            evidence.append(
                f"[{idx}] source={doc.source_type.value} date={doc.date.date()} institution={doc.institution}\n"
                f"title={doc.title}\n{doc.content[:450]}"
            )
        prompt = f"""
You are a BIST market intelligence assistant.
User question: {state['question']}
Ticker: {state['ticker']}
As of date: {as_of_date.date()}
Consistency seed: {state.get("consistency_assessment", "inconclusive")}
Evidence:
{chr(10).join(evidence)}

Rules:
- Never provide investment advice or buy/sell signals.
- Return strict JSON keys: answer_tr, answer_en, consistency_assessment, confidence.
- Answers must be time-aware and evidence-based.
"""
        llm_raw, provider_used = self.llm.generate_with_provider(
            prompt,
            provider_pref=state.get("provider_pref"),
            provider_overrides=state.get("provider_overrides"),
        )
        parsed = self._parse_model_json(llm_raw)

        answer_tr = parsed.get("answer_tr") or (
            f"{state['ticker']} için kanıtlar {state.get('consistency_assessment', 'inconclusive')} görünmektedir. "
            "Detaylar aşağıdaki atıflarda listelenmiştir."
        )
        answer_en = parsed.get("answer_en") or (
            f"For {state['ticker']}, evidence appears {state.get('consistency_assessment', 'inconclusive')}. "
            "Details are listed in citations."
        )
        verifier_consistency = state.get("consistency_assessment", "inconclusive")
        parsed_consistency = parsed.get("consistency_assessment", verifier_consistency)
        valid_consistency = {"aligned", "contradiction", "inconclusive", "insufficient_evidence"}
        if provider_used == "mock" or parsed_consistency not in valid_consistency:
            consistency = verifier_consistency
        else:
            consistency = parsed_consistency
        confidence = float(parsed.get("confidence", 0.65))

        as_of_text = as_of_date.strftime("%Y-%m-%d")
        if "itibarıyla" not in answer_tr.lower():
            answer_tr = f"{as_of_text} itibarıyla, {answer_tr}"
        if "as of" not in answer_en.lower():
            answer_en = f"As of {as_of_text}, {answer_en}"

        answer_tr = append_disclaimer(answer_tr)
        answer_en = append_disclaimer(answer_en)

        ok_tr, gaps_tr, score_tr = post_answer_policy(answer_tr, citations)
        ok_en, gaps_en, score_en = post_answer_policy(answer_en, citations)
        score = round((score_tr + score_en) / 2, 4)
        gaps = list(dict.fromkeys(gaps_tr + gaps_en))

        tr_claims = decompose_claims(answer_tr)
        tr_grounding = ground_claims(tr_claims, citations)
        if tr_grounding.ungrounded_claims:
            gaps.extend([f"Ungrounded claim (TR): {claim}" for claim in tr_grounding.ungrounded_claims[:3]])

        en_claims = decompose_claims(answer_en)
        en_grounding = ground_claims(en_claims, citations)
        if en_grounding.ungrounded_claims:
            gaps.extend([f"Ungrounded claim (EN): {claim}" for claim in en_grounding.ungrounded_claims[:3]])

        if not ok_tr or not ok_en or tr_grounding.ungrounded_claims or en_grounding.ungrounded_claims:
            if provider_used == "mock":
                confidence = min(confidence, 0.55)
            else:
                consistency = "insufficient_evidence"
                confidence = min(confidence, 0.45)

        for claim in tr_claims:
            if not claim.declarative:
                continue
            supported = claim.sentence_index in tr_grounding.matched_claim_to_citation_idx
            self.claim_ledger.register(claim.text, supported=supported)

        return {
            "answer_tr": answer_tr,
            "answer_en": answer_en,
            "citations": citations,
            "confidence": max(0.0, min(1.0, confidence)),
            "consistency_assessment": consistency,
            "evidence_gaps": list(dict.fromkeys(gaps)),
            "citation_coverage_score": score,
            "provider_used": provider_used,
        }
