from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Callable
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
from app.utils.query_rewriter import generate_hyde_expansion, rewrite_query
from app.utils.text import normalize_visible_text

logger = logging.getLogger(__name__)


class AgentNodes:
    def __init__(
        self,
        retriever: Retriever,
        llm: RoutedLLM,
        claim_ledger: ClaimLedger,
        market_context_fn: Callable[..., dict[str, Any]] | None = None,
        web_search_fn: Callable[..., list[dict[str, str]]] | None = None,
        graph_query_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.claim_ledger = claim_ledger
        self.settings = get_settings()
        self._market_context_fn = market_context_fn
        self._web_search_fn = web_search_fn
        self._graph_query_fn = graph_query_fn

    @staticmethod
    def _normalize_question(text: str) -> str:
        lowered = normalize_visible_text(text).lower()
        normalized = unicodedata.normalize("NFKD", lowered)
        ascii_safe = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return (
            ascii_safe.replace("ı", "i")
            .replace("ğ", "g")
            .replace("ş", "s")
            .replace("ç", "c")
            .replace("ö", "o")
            .replace("ü", "u")
            .replace("â", "a")
            .replace("î", "i")
            .replace("û", "u")
            .replace("Ä±", "i")
            .replace("ÄŸ", "g")
            .replace("ÅŸ", "s")
            .replace("Ã§", "c")
            .replace("Ã¶", "o")
            .replace("Ã¼", "u")
        )

    @staticmethod
    def _question_type(question: str) -> str:
        q = AgentNodes._normalize_question(question)
        if "kap" in q and ("6 ay" in q or "last 6 months" in q):
            return "kap_disclosure_types"
        if "broker" in q or "araci kurum" in q or "report" in q:
            return "brokerage_narrative"
        relationship_tokens = [
            "iliski",
            "istirak",
            "bagli ortaklik",
            "ortaklik yapisi",
            "pay sahibi",
            "holding",
            "sektor baglantisi",
            "yonetim kurulu",
        ]
        if any(token in q for token in relationship_tokens):
            return "relationship_query"
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
        if question_type == "relationship_query":
            return [SourceType.KAP, SourceType.NEWS], {"kap": 0.75, "news": 0.25, "brokerage": 0.0}
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
                    title=normalize_visible_text(chunk.title or f"{chunk.source_type.value} document"),
                    institution=normalize_visible_text(chunk.institution),
                    date=chunk.publication_date or chunk.date,
                    url=chunk.url,
                    snippet=normalize_visible_text(chunk.content)[:220],
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
    def _as_probability(value: Any, default: float = 0.5) -> float:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))

        text = normalize_visible_text(str(value)).strip().lower()
        mapping = {
            "low": 0.35,
            "medium": 0.6,
            "high": 0.85,
            "very_low": 0.2,
            "very_high": 0.95,
            "dusuk": 0.35,
            "orta": 0.6,
            "yuksek": 0.85,
        }
        if text in mapping:
            return mapping[text]
        try:
            return max(0.0, min(1.0, float(text.replace(",", "."))))
        except Exception:  # noqa: BLE001
            return default

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
            snippets.append(
                f"[{idx}] {doc.source_type.value} | {doc.date.date()} | {normalize_visible_text(doc.content)[:180]}"
            )
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
            return self._as_probability(parsed.get("contradiction_score", 0.0), default=0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def intent_router(self, state: AgentState) -> AgentState:
        original_question = state["question"]
        rewritten = rewrite_query(original_question)
        policy = pre_answer_policy(original_question)
        return {
            "risk_blocked": not policy.allowed,
            "policy_reason": policy.reason,
            "question_type": self._question_type(original_question),
            "rewritten_question": rewritten,
            "refusal_tr": policy.refusal_tr,
            "refusal_en": policy.refusal_en,
            "skip_to_composer": not policy.allowed,
        }

    def source_planner(self, state: AgentState) -> AgentState:
        sources, weights = self._sources_for_question_type(state["question_type"])
        return {"source_plan": sources, "source_weights": weights}

    def graph_retriever(self, state: AgentState) -> AgentState:
        if state.get("question_type") != "relationship_query" or not self._graph_query_fn:
            return {"graph_context": {}}
        try:
            return {"graph_context": self._graph_query_fn(state["question"], ticker=state["ticker"])}
        except Exception as exc:  # noqa: BLE001
            logger.debug("GraphRAG query failed: %s", exc)
            return {"graph_context": {"error": str(exc)}}

    def retriever_pass1(self, state: AgentState) -> AgentState:
        q_type = state.get("question_type")
        docs, trace = self.retriever.retrieve_with_trace(
            query=state["question"],
            ticker=state["ticker"],
            source_types=state.get("source_plan"),
            as_of_date=state.get("as_of_date"),
            top_k=self.settings.max_top_k,
            question_type=q_type,
        )
        evidence_gaps = list(state.get("evidence_gaps", []))
        if not docs and state.get("source_plan"):
            fallback_docs, fallback_trace = self.retriever.retrieve_with_trace(
                query=state["question"],
                ticker=state["ticker"],
                source_types=None,
                as_of_date=state.get("as_of_date"),
                top_k=self.settings.max_top_k,
                question_type=q_type,
            )
            trace["fallback_any_source"] = fallback_trace
            if fallback_docs:
                docs = fallback_docs
                evidence_gaps.append("Preferred sources returned no hit; fallback retrieval used all source types.")

        # HyDE supplementary retrieval: if initial retrieval is sparse,
        # generate a hypothetical answer and use it to find more docs.
        if len(docs) < 3:
            hyde_text = generate_hyde_expansion(state["question"], state["ticker"])
            if hyde_text:
                hyde_docs, hyde_trace = self.retriever.retrieve_with_trace(
                    query=hyde_text,
                    ticker=state["ticker"],
                    source_types=state.get("source_plan"),
                    as_of_date=state.get("as_of_date"),
                    top_k=self.settings.max_top_k,
                    question_type=q_type,
                )
                trace["hyde_expansion"] = hyde_trace
                existing_ids = {id(d) for d in docs}
                for hd in hyde_docs:
                    if id(hd) not in existing_ids:
                        docs.append(hd)
                if hyde_docs:
                    evidence_gaps.append(f"HyDE expansion added {len(hyde_docs)} supplementary docs.")

        return {"pass1_docs": docs, "retrieval_trace": trace, "evidence_gaps": evidence_gaps}

    def verifier(self, state: AgentState) -> AgentState:
        docs = state.get("pass1_docs", [])
        coverage = min(1.0, len(docs) / max(1, int(self.settings.max_top_k * 0.7)))
        rule_signal = disclosure_news_tension_index(docs)
        rule_tension = float(rule_signal.get("tension_index", 0.0))
        # If we have evidence from fewer than two source types, no real
        # cross-source verification is possible — we must call this
        # "inconclusive" rather than collapsing to "aligned" by default.
        present_sources = {chunk.source_type for chunk in docs}
        single_source_evidence = len(present_sources) < 2
        provider_pref = (state.get("provider_pref") or "").lower()
        # In heuristic-only mode (mock provider) the LLM judge has no real
        # signal, so we'd otherwise drag the tension below the contradiction
        # threshold. Detect that case and rely on the rule signal alone with
        # tighter, empirically tuned thresholds.
        heuristic_only = provider_pref in {"", "mock", "heuristic", "auto"} and not (
            self.settings.groq_api_key
            or self.settings.openai_api_key
            or self.settings.gemini_api_key
            or self.settings.together_api_key
        )

        if heuristic_only:
            llm_tension = 0.0
            tension = round(rule_tension, 4)
            contradiction_threshold = 0.55
            aligned_threshold = 0.42
        else:
            llm_tension = self._llm_contradiction_score(
                question=state["question"],
                docs=docs,
                provider_pref=state.get("provider_pref"),
                provider_overrides=state.get("provider_overrides"),
            )
            tension = round((rule_tension * 0.65) + (llm_tension * 0.35), 4)
            contradiction_threshold = 0.54
            aligned_threshold = 0.30

        # Source-type diversity: need evidence from at least 3 distinct
        # source types (kap + news + brokerage) to confidently call
        # "aligned", otherwise fall back to inconclusive.
        rich_source_diversity = len(present_sources) >= 3

        if single_source_evidence:
            consistency = "inconclusive"
        elif tension >= contradiction_threshold:
            consistency = "contradiction"
        elif tension <= aligned_threshold and len(docs) > 2 and rich_source_diversity:
            consistency = "aligned"
        else:
            consistency = "inconclusive"

        should_reretrieve = coverage < 0.7 or (
            (contradiction_threshold - 0.15) <= tension <= (contradiction_threshold + 0.05)
        )
        return {
            "evidence_coverage": round(coverage, 4),
            "contradiction_confidence": tension,
            "rule_tension": round(rule_tension, 4),
            "llm_tension": round(llm_tension, 4),
            "consistency_assessment": consistency,
            "should_reretrieve": should_reretrieve,
            "tension_mode": "heuristic_only" if heuristic_only else "hybrid",
        }

    def reretriever(self, state: AgentState) -> AgentState:
        docs = self.retriever.retrieve(
            query=f"{state['question']} resmi aciklama medya karsilastirmasi",
            ticker=state["ticker"],
            source_types=[SourceType.KAP, SourceType.NEWS, SourceType.BROKERAGE],
            as_of_date=state.get("as_of_date"),
            top_k=self.settings.max_top_k + 4,
            question_type=state.get("question_type"),
        )
        return {"pass2_docs": docs}

    def counterfactual_probe(self, state: AgentState) -> AgentState:
        planned = set(state.get("source_plan") or [])
        opposing = [s for s in [SourceType.KAP, SourceType.NEWS, SourceType.BROKERAGE] if s not in planned]
        if not opposing:
            opposing = [SourceType.NEWS, SourceType.KAP]
        docs = self.retriever.retrieve(
            query=f"Bu soruya ters yonden bakan kanitlar: {state['question']}",
            ticker=state["ticker"],
            source_types=opposing,
            as_of_date=state.get("as_of_date"),
            top_k=max(3, self.settings.max_top_k // 2),
            question_type=state.get("question_type"),
        )
        return {"counterfactual_docs": docs}

    def _fetch_market_context_block(self, ticker: str) -> str:
        """Build a short cross-asset context string from live connectors."""
        if not self._market_context_fn:
            return ""
        try:
            ctx = self._market_context_fn(ticker)
            lines: list[str] = []
            for card in ctx.get("context_cards", []):
                lines.append(f"  {card.get('label', '')}: {card.get('value', '')}")
            if lines:
                return "Cross-Asset Market Context (informational only — not investment advice):\n" + "\n".join(lines)
        except Exception:  # noqa: BLE001
            logger.debug("Market context fetch failed for %s", ticker)
        return ""

    def web_searcher(self, state: AgentState) -> AgentState:
        """Optional web search step — enriches evidence with live web results."""
        if not self._web_search_fn:
            return {"web_search_results": []}
        query = f"{state['ticker']} {state['question']}"
        try:
            results = self._web_search_fn(query, max_results=5)
            return {"web_search_results": results or []}
        except Exception:  # noqa: BLE001
            logger.debug("Web search failed for query: %s", query)
            return {"web_search_results": []}

    def composer(self, state: AgentState) -> AgentState:
        if state.get("risk_blocked"):
            answer_tr = append_disclaimer(state.get("refusal_tr") or "Bu istek politika geregi engellendi.")
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
        as_of_text = as_of_date.strftime("%Y-%m-%d")
        graph_context = state.get("graph_context") or {}

        if state.get("question_type") == "relationship_query" and graph_context.get("answer_tr") and not citations:
            return {
                "answer_tr": append_disclaimer(f"{as_of_text} itibariyla, {normalize_visible_text(graph_context['answer_tr'])}"),
                "answer_en": append_disclaimer(f"As of {as_of_text}, {normalize_visible_text(graph_context.get('answer_en', 'Graph relationship context is available.'))}"),
                "citations": [],
                "confidence": self._as_probability(graph_context.get("confidence", 0.45), default=0.45),
                "consistency_assessment": "graph_context_only",
                "evidence_gaps": ["GraphRAG context used without document-level citation; verify against KAP/public filings before relying on it."],
                "citation_coverage_score": 0.0,
                "provider_used": "graph_rag",
            }

        if not final_docs or not citations:
            answer_tr = append_disclaimer(
                f"{as_of_text} itibariyla, {state['ticker']} icin yeterli dogrulanmis kanit bulunamadi. "
                "Bu nedenle resmi durum, haber anlatisi ve araci kurum cercevesi hakkinda guvenilir bir sonuc uretilmedi. "
                "Lutfen daha spesifik bir soru sormay veya farkli bir zaman araligi belirtmeyi deneyin."
            )
            answer_en = append_disclaimer(
                f"As of {as_of_text}, there is not enough verified evidence for {state['ticker']}. "
                "A reliable conclusion could not be produced for the official disclosure view, news framing, or brokerage framing. "
                "Please try a more specific question or a different time range."
            )
            evidence_gaps = list(dict.fromkeys(list(state.get("evidence_gaps", [])) + ["No verified citations were available for final synthesis."]))
            return {
                "answer_tr": answer_tr,
                "answer_en": answer_en,
                "citations": [],
                "confidence": 0.35,
                "consistency_assessment": "insufficient_evidence",
                "evidence_gaps": evidence_gaps,
                "citation_coverage_score": 0.0,
                "provider_used": "rule_guarded",
            }

        # Low-relevance calibration: if we have very few docs, flag it
        low_evidence = len(final_docs) < 3
        evidence = []
        for idx, doc in enumerate(final_docs[:10], start=1):
            evidence.append(
                f"[{idx}] source={doc.source_type.value} date={doc.date.date()} institution={normalize_visible_text(doc.institution)}\n"
                f"title={normalize_visible_text(doc.title)}\n{normalize_visible_text(doc.content)[:450]}"
            )
        market_ctx = self._fetch_market_context_block(state["ticker"])
        web_results = state.get("web_search_results") or []
        web_block = ""
        if web_results:
            web_lines = []
            for idx, wr in enumerate(web_results[:5], start=1):
                web_lines.append(f"  [{idx}] {wr.get('title', '')} — {wr.get('snippet', '')[:200]}")
            web_block = "Web Search Results (supplementary context):\n" + "\n".join(web_lines)
        graph_block = ""
        if graph_context:
            graph_block = (
                "GraphRAG Relationship Context (supplementary, not a substitute for citations):\n"
                + normalize_visible_text(graph_context.get("answer_en") or graph_context.get("answer_tr") or "")
            )

        prompt = f"""
You are a BIST market intelligence assistant.
User question: {state['question']}
Ticker: {state['ticker']}
As of date: {as_of_date.date()}
Consistency seed: {state.get("consistency_assessment", "inconclusive")}
Evidence:
{chr(10).join(evidence)}
{market_ctx}
{web_block}
{graph_block}
Rules:
- Never provide investment advice or buy/sell signals.
- Return strict JSON keys: answer_tr, answer_en, consistency_assessment, confidence.
- Answers must be time-aware and evidence-based.
- Cross-asset context is supplementary only — do not base conclusions on it alone.
"""
        llm_raw, provider_used = self.llm.generate_with_provider(
            prompt,
            provider_pref=state.get("provider_pref"),
            provider_overrides=state.get("provider_overrides"),
        )
        parsed = self._parse_model_json(llm_raw)

        answer_tr = parsed.get("answer_tr") or (
            f"{state['ticker']} icin kanitlar {state.get('consistency_assessment', 'inconclusive')} "
            "gorunmektedir. Detaylar asagidaki atiflarda listelenmistir."
        )
        answer_en = parsed.get("answer_en") or (
            f"For {state['ticker']}, evidence appears {state.get('consistency_assessment', 'inconclusive')}. "
            "Details are listed in citations."
        )
        answer_tr = normalize_visible_text(answer_tr)
        answer_en = normalize_visible_text(answer_en)
        verifier_consistency = state.get("consistency_assessment", "inconclusive")
        parsed_consistency = parsed.get("consistency_assessment", verifier_consistency)
        valid_consistency = {"aligned", "contradiction", "inconclusive", "insufficient_evidence"}
        if provider_used == "mock" or parsed_consistency not in valid_consistency:
            consistency = verifier_consistency
        else:
            consistency = parsed_consistency
        confidence = self._as_probability(parsed.get("confidence", 0.65), default=0.65)

        # "I don't know" calibration: cap confidence when evidence is thin
        evidence_gaps = list(state.get("evidence_gaps", []))
        if low_evidence:
            confidence = min(confidence, 0.50)
            evidence_gaps.append(
                f"Low evidence: only {len(final_docs)} docs found. Confidence capped."
            )

        if "itibariyla" not in normalize_visible_text(answer_tr).lower():
            answer_tr = f"{as_of_text} itibariyla, {answer_tr}"
        if "as of" not in answer_en.lower():
            answer_en = f"As of {as_of_text}, {answer_en}"

        answer_tr = append_disclaimer(answer_tr)
        answer_en = append_disclaimer(answer_en)

        ok_tr, gaps_tr, score_tr = post_answer_policy(answer_tr, citations)
        ok_en, gaps_en, score_en = post_answer_policy(answer_en, citations)
        score = round((score_tr + score_en) / 2, 4)
        gaps = list(dict.fromkeys(normalize_visible_text(item) for item in gaps_tr + gaps_en if item))

        tr_claims = decompose_claims(answer_tr)
        tr_grounding = ground_claims(tr_claims, citations)
        if tr_grounding.ungrounded_claims:
            gaps.extend(
                [normalize_visible_text(f"Ungrounded claim (TR): {claim}") for claim in tr_grounding.ungrounded_claims[:3]]
            )

        en_claims = decompose_claims(answer_en)
        en_grounding = ground_claims(en_claims, citations)
        if en_grounding.ungrounded_claims:
            gaps.extend(
                [normalize_visible_text(f"Ungrounded claim (EN): {claim}") for claim in en_grounding.ungrounded_claims[:3]]
            )

        if not ok_tr or not ok_en or tr_grounding.ungrounded_claims or en_grounding.ungrounded_claims:
            if provider_used == "mock":
                confidence = min(confidence, 0.55)
            else:
                consistency = "insufficient_evidence"
                confidence = min(confidence, 0.45)
                score = 0.0
                gaps.append("Model output failed claim-level grounding and was replaced with a safe insufficient-evidence summary.")
                answer_tr = append_disclaimer(
                    f"{as_of_text} itibariyla, {state['ticker']} icin mevcut kanitlar kesin bir sonuc vermemektedir. "
                    "Model uretimi claim-level grounding testini gecemedigi icin yanit guvenli yetersiz kanit moduna alinmistir."
                )
                answer_en = append_disclaimer(
                    f"As of {as_of_text}, the available evidence does not support a firm conclusion for {state['ticker']}. "
                    "The model output did not pass claim-level grounding, so the response was downgraded to an insufficient-evidence summary."
                )

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

    # ── Reflection / self-critique ─────────────────────────────────

    def reflector(self, state: AgentState) -> AgentState:
        """Post-generation faithfulness check.

        Compares the generated answer against citations.  If the coverage
        score is low and ungrounded claims exist, rewrites the answer to
        only include evidence-backed statements.
        """
        score = state.get("citation_coverage_score", 1.0)
        gaps = state.get("evidence_gaps") or []
        citations = state.get("citations") or []

        # If already at high quality, skip reflection
        ungrounded = [g for g in gaps if "Ungrounded claim" in g]
        if score >= 0.8 and not ungrounded:
            return {"reflection_applied": False}

        # Build a tighter, evidence-only answer
        as_of = (state.get("as_of_date") or datetime.now(UTC)).strftime("%Y-%m-%d")
        ticker = state["ticker"]
        cite_summary = "; ".join(
            f"[{c.source_type}] {normalize_visible_text(c.snippet)[:120]}"
            for c in citations[:6]
        )

        if not cite_summary:
            return {"reflection_applied": False}

        answer_tr = append_disclaimer(
            f"{as_of} itibariyla, {ticker} icin dogrulanmis kanitlar sunlardir: {cite_summary}. "
            "Desteklenmeyen iddialar cikartilmistir."
        )
        answer_en = append_disclaimer(
            f"As of {as_of}, the verified evidence for {ticker} includes: {cite_summary}. "
            "Unsupported claims have been removed."
        )

        # Adjust confidence down since we had to reflect
        new_confidence = min(state.get("confidence", 0.5), 0.6)

        logger.info(
            "Reflection applied for %s: score %.2f -> rewritten (had %d ungrounded claims)",
            ticker, score, len(ungrounded),
        )

        return {
            "answer_tr": answer_tr,
            "answer_en": answer_en,
            "confidence": new_confidence,
            "evidence_gaps": gaps + ["Reflection node rewrote answer to remove ungrounded claims."],
            "reflection_applied": True,
        }
