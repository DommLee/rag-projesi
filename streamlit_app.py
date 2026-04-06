from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import requests
import streamlit as st


st.set_page_config(page_title="BIST Agentic RAG v2.0", layout="wide")


def _discover_api_base() -> str:
    env_base = os.environ.get("BIST_API_BASE", "").strip()
    if env_base:
        return env_base.rstrip("/")

    runtime_port_file = Path("logs/.runtime_api_port")
    if runtime_port_file.exists():
        port = runtime_port_file.read_text(encoding="utf-8", errors="ignore").strip()
        if port:
            return f"http://localhost:{port}"

    for port in (18000, 18001, 18002, 8088):
        try:
            response = requests.get(f"http://localhost:{port}/v1/health", timeout=1.2)
            if response.status_code == 200:
                return f"http://localhost:{port}"
        except Exception:  # noqa: BLE001
            continue

    return "http://localhost:18000"


def _default_overrides(provider_pref: str) -> str:
    if provider_pref == "ollama":
        return json.dumps(
            {
                "ollama_base_url": "http://host.docker.internal:11434",
                "ollama_model": "llama3.1:8b",
            },
            ensure_ascii=False,
            indent=2,
        )
    return ""


def _headers(token: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = token.strip()
    if token:
        headers["X-API-Token"] = token
    return headers


def _request(base_url: str, token: str, method: str, path: str, payload: dict | None = None, timeout: int = 90) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    response = requests.request(
        method=method,
        url=url,
        headers=_headers(token),
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"{response.status_code}: {response.text}")
    if not response.text.strip():
        return {}
    return response.json()


def _badge(consistency: str) -> str:
    color_map = {
        "aligned": "#16a34a",
        "contradiction": "#dc2626",
        "inconclusive": "#f59e0b",
        "blocked_policy": "#6b7280",
        "insufficient_evidence": "#ef4444",
    }
    color = color_map.get((consistency or "").lower(), "#2563eb")
    return f"<span style='display:inline-block;padding:6px 12px;border-radius:999px;background:{color};color:white;font-weight:700;'>{consistency}</span>"


def _citations_df(citations: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for c in citations:
        rows.append(
            {
                "source_type": c.get("source_type", ""),
                "title": c.get("title", ""),
                "institution": c.get("institution", ""),
                "date": c.get("date", ""),
                "url": c.get("url", ""),
            }
        )
    return pd.DataFrame(rows)


def _timeline_chart(citations: list[dict[str, Any]]) -> None:
    if not citations:
        st.info("Timeline için citation bulunamadı.")
        return

    rows = []
    for c in citations:
        dt_raw = c.get("date")
        try:
            dt = pd.to_datetime(dt_raw)
        except Exception:  # noqa: BLE001
            continue
        rows.append({"date": dt.date().isoformat(), "source_type": c.get("source_type", "unknown")})

    if not rows:
        st.info("Timeline verisi parse edilemedi.")
        return

    df = pd.DataFrame(rows)
    grouped = df.groupby(["date", "source_type"], as_index=False).size()
    chart = (
        alt.Chart(grouped)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("size:Q", title="Citation Count"),
            color=alt.Color("source_type:N", title="Source"),
            tooltip=["date:T", "source_type:N", "size:Q"],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, use_container_width=True)


def _rubric_chart(rubric_scores: dict[str, float]) -> None:
    if not rubric_scores:
        st.info("Rubric skorları henüz yok.")
        return

    rows = []
    for key, value in rubric_scores.items():
        if key == "total_100":
            continue
        rows.append({"criterion": key.replace("_", " "), "score": float(value)})

    if not rows:
        return

    df = pd.DataFrame(rows)
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("score:Q", title="Score"),
            y=alt.Y("criterion:N", sort="-x", title="Criterion"),
            color=alt.value("#0ea5e9"),
            tooltip=["criterion:N", "score:Q"],
        )
        .properties(height=330)
    )
    st.altair_chart(chart, use_container_width=True)


def _section(title: str, subtitle: str = "") -> None:
    st.markdown(f"### {title}")
    if subtitle:
        st.caption(subtitle)


st.markdown(
    """
<style>
    .stApp {
        background: radial-gradient(circle at 20% 10%, #0b1f3a 0%, #071225 35%, #030712 100%);
        color: #e2e8f0;
    }
    .block-container {
        padding-top: 1.2rem;
        max-width: 1300px;
    }
    .card {
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid rgba(100, 116, 139, 0.35);
        border-radius: 14px;
        padding: 14px;
    }
    .hero {
        background: linear-gradient(120deg, rgba(14,165,233,0.25), rgba(59,130,246,0.10));
        border: 1px solid rgba(125, 211, 252, 0.35);
        border-radius: 16px;
        padding: 18px;
        margin-bottom: 10px;
    }
</style>
""",
    unsafe_allow_html=True,
)

if "api_base" not in st.session_state:
    st.session_state.api_base = _discover_api_base()
if "api_token" not in st.session_state:
    st.session_state.api_token = os.environ.get("API_AUTH_TOKEN", "")
if "last_query" not in st.session_state:
    st.session_state.last_query = {}
if "last_eval" not in st.session_state:
    st.session_state.last_eval = {}

st.markdown(
    """
<div class="hero">
  <h2 style="margin:0;">BIST Agentic RAG v2.0</h2>
  <p style="margin:6px 0 0 0;opacity:.9;">Planner -> Source Router -> Parallel Retrievers -> Verifier -> Re-Retrieve -> Synthesizer -> Guardrail</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Connection")
    st.session_state.api_base = st.text_input("API Base", value=st.session_state.api_base).rstrip("/")
    st.session_state.api_token = st.text_input("API Token", value=st.session_state.api_token, type="password")

    if st.button("Ping API"):
        try:
            h = _request(st.session_state.api_base, st.session_state.api_token, "GET", "/v1/health", timeout=15)
            r = _request(st.session_state.api_base, st.session_state.api_token, "GET", "/v1/ready", timeout=15)
            st.success(f"API OK: {h.get('app')} | ready={r.get('status')}")
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    st.divider()
    st.caption("Rule: This system does not provide investment advice.")


tab_query, tab_ingest, tab_eval, tab_narrative, tab_provider = st.tabs(
    [
        "Query Studio",
        "Ingestion & Auto",
        "Evaluation Scorecard",
        "Narrative Explorer",
        "Provider Lab",
    ]
)

with tab_query:
    _section("Query Studio", "Zaman-duyarlı, kaynaklı, TR/EN üretim")

    c1, c2, c3 = st.columns([1, 3, 1])
    ticker = c1.text_input("Ticker", value="ASELS").strip().upper()
    question = c2.text_area(
        "Question",
        value="Son 3 ayda KAP bildirimleri ile haberler arasında çelişki var mı?",
        height=110,
    )
    provider_pref = c3.selectbox("Provider", ["auto", "groq", "gemini", "openai", "ollama", "together", "mock"])

    overrides_default = _default_overrides(provider_pref)
    provider_overrides_raw = st.text_area("Provider Overrides (JSON)", value=overrides_default, height=110)

    q1, q2 = st.columns([1, 1])

    if q1.button("Run Agent Query", type="primary", use_container_width=True):
        try:
            provider_overrides = None
            if provider_overrides_raw.strip():
                parsed = json.loads(provider_overrides_raw)
                if not isinstance(parsed, dict):
                    raise ValueError("Provider overrides JSON object olmalı")
                provider_overrides = {str(k): str(v) for k, v in parsed.items() if v is not None}

            payload = {
                "ticker": ticker,
                "question": question,
                "language": "bilingual",
                "provider_pref": None if provider_pref == "auto" else provider_pref,
                "provider_overrides": provider_overrides,
            }
            result = _request(st.session_state.api_base, st.session_state.api_token, "POST", "/v1/query", payload, timeout=180)
            st.session_state.last_query = result
            st.success("Query tamamlandı")
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    if q2.button("Run Rubric Demo Flow (1-7)", use_container_width=True):
        try:
            with st.status("Demo akışı çalışıyor", expanded=True) as status:
                status.write("1) Ticker seçildi")

                ingest_payload = {
                    "ticker": ticker,
                    "institution": "BIST-Collector",
                    "source_urls": [f"https://www.kap.org.tr/tr/sirket-bilgileri/genel/{ticker}", f"https://www.kap.org.tr/tr/sirket-bilgileri/ozet/{ticker}"],
                    "delta_mode": True,
                    "max_docs": 100,
                    "force_reingest": False,
                }
                _request(st.session_state.api_base, st.session_state.api_token, "POST", "/v1/ingest/kap", ingest_payload, timeout=180)
                status.write("2) KAP retrieval/ingest tamamlandı")

                ingest_payload_news = {
                    "ticker": ticker,
                    "institution": "BIST-Collector",
                    "source_urls": [
                        f"https://news.google.com/rss/search?q={ticker}%20BIST&hl=tr&gl=TR&ceid=TR:tr",
                        "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
                    ],
                    "delta_mode": True,
                    "max_docs": 100,
                    "force_reingest": False,
                }
                _request(st.session_state.api_base, st.session_state.api_token, "POST", "/v1/ingest/news", ingest_payload_news, timeout=180)
                status.write("3) News retrieval/ingest tamamlandı")

                status.write("4) Brokerage parser hazır (manual/pdf feed ile)")

                query_payload = {
                    "ticker": ticker,
                    "question": question,
                    "language": "bilingual",
                    "provider_pref": None if provider_pref == "auto" else provider_pref,
                }
                result = _request(st.session_state.api_base, st.session_state.api_token, "POST", "/v1/query", query_payload, timeout=180)
                st.session_state.last_query = result
                status.write("5-6) Agent karşılaştırma + cited answer tamamlandı")
                status.write("7) Disclaimer doğrulandı")
                status.update(label="Demo flow tamamlandı", state="complete")
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    result = st.session_state.last_query
    if result:
        st.markdown("---")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Confidence", f"{float(result.get('confidence', 0.0)):.2f}")
        m2.metric("Citation Coverage", f"{float(result.get('citation_coverage_score', 0.0)):.2f}")
        m3.metric("Citation Count", str(len(result.get("citations", []))))
        m4.metric("Provider Used", str(result.get("provider_used", "unknown")))

        st.markdown(_badge(str(result.get("consistency_assessment", "inconclusive"))), unsafe_allow_html=True)

        a1, a2 = st.columns(2)
        with a1:
            st.markdown("#### Answer TR")
            st.write(result.get("answer_tr", ""))
        with a2:
            st.markdown("#### Answer EN")
            st.write(result.get("answer_en", ""))

        st.markdown("#### Evidence Timeline")
        _timeline_chart(result.get("citations", []))

        st.markdown("#### Citations")
        citations_df = _citations_df(result.get("citations", []))
        if citations_df.empty:
            st.info("Citation bulunamadı")
        else:
            st.dataframe(citations_df, use_container_width=True)

        gaps = result.get("evidence_gaps", [])
        if gaps:
            st.markdown("#### Evidence Gaps")
            st.write(gaps)

        st.warning(result.get("disclaimer", "This system does not provide investment advice."))

with tab_ingest:
    _section("Ingestion & Auto", "Manual source ingest + auto scheduler")

    col_l, col_r = st.columns([2, 2])
    with col_l:
        st.markdown("#### Manual Ingest")
        ing_ticker = st.text_input("Ticker ", value="ASELS").strip().upper()
        ing_source = st.selectbox("Source", ["kap", "news", "report"])
        ing_inst = st.text_input("Institution", value="BIST-Collector")
        ing_urls = st.text_area(
            "Source URLs (line by line)",
            value=f"https://www.kap.org.tr/tr/sirket-bilgileri/genel/{ing_ticker}" if ing_source == "kap" else "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
            height=120,
        )
        ing_delta = st.checkbox("Delta Mode", value=True)
        ing_max_docs = st.number_input("Max Docs", min_value=1, max_value=500, value=100, step=1)

        if st.button("Run Manual Ingest", type="primary"):
            try:
                payload = {
                    "ticker": ing_ticker,
                    "institution": ing_inst,
                    "source_urls": [u.strip() for u in ing_urls.splitlines() if u.strip()],
                    "delta_mode": ing_delta,
                    "max_docs": int(ing_max_docs),
                    "force_reingest": False,
                }
                response = _request(
                    st.session_state.api_base,
                    st.session_state.api_token,
                    "POST",
                    f"/v1/ingest/{ing_source}",
                    payload,
                    timeout=240,
                )
                st.json(response)
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

    with col_r:
        st.markdown("#### Auto Ingest Controls")
        c1, c2, c3, c4 = st.columns(4)
        if c1.button("Status"):
            try:
                st.json(_request(st.session_state.api_base, st.session_state.api_token, "GET", "/v1/auto-ingest/status"))
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        if c2.button("Start"):
            try:
                st.json(_request(st.session_state.api_base, st.session_state.api_token, "POST", "/v1/auto-ingest/start", {}))
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        if c3.button("Stop"):
            try:
                st.json(_request(st.session_state.api_base, st.session_state.api_token, "POST", "/v1/auto-ingest/stop", {}))
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        if c4.button("Run Once"):
            try:
                st.json(_request(st.session_state.api_base, st.session_state.api_token, "POST", "/v1/auto-ingest/run-once", {}, timeout=300))
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

        try:
            cfg = _request(st.session_state.api_base, st.session_state.api_token, "GET", "/v1/auto-ingest/config")
            cfg_text = st.text_area("Auto Config JSON", value=json.dumps(cfg, ensure_ascii=False, indent=2), height=260)
            if st.button("Save Auto Config"):
                parsed = json.loads(cfg_text)
                save_resp = _request(
                    st.session_state.api_base,
                    st.session_state.api_token,
                    "POST",
                    "/v1/auto-ingest/config",
                    parsed,
                    timeout=90,
                )
                st.success("Auto config kaydedildi")
                st.json(save_resp)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    st.markdown("#### Metrics")
    if st.button("Refresh Metrics"):
        try:
            st.json(_request(st.session_state.api_base, st.session_state.api_token, "GET", "/v1/metrics"))
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

with tab_eval:
    _section("Evaluation Scorecard", "Rubric mapped eval + gates")

    e1, e2, e3 = st.columns(3)
    mode = e1.selectbox("Mode", ["heuristic", "hybrid", "real", "mock"], index=0)
    provider = e2.selectbox("Provider", ["auto", "groq", "gemini", "openai", "ollama", "together", "mock"], index=0)
    sample_size = int(e3.slider("Sample Size", min_value=5, max_value=30, value=15))

    if st.button("Run Evaluation", type="primary"):
        try:
            payload = {
                "mode": mode,
                "provider": provider,
                "sample_size": sample_size,
                "dataset_path": "datasets/eval_questions.json",
                "store_artifacts": True,
                "run_ragas": True,
                "run_deepeval": True,
            }
            st.session_state.last_eval = _request(
                st.session_state.api_base,
                st.session_state.api_token,
                "POST",
                "/v1/eval/run",
                payload,
                timeout=600,
            )
            st.success("Evaluation tamamlandı")
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    if st.button("Load Latest Eval"):
        try:
            latest = _request(st.session_state.api_base, st.session_state.api_token, "GET", "/v1/eval/report/latest")
            st.session_state.last_eval = latest.get("report", {}) if isinstance(latest, dict) and "report" in latest else latest
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    eval_report = st.session_state.last_eval
    if eval_report:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Citation Coverage", f"{float(eval_report.get('citation_coverage', 0.0)):.2f}")
        m2.metric("Disclaimer Presence", f"{float(eval_report.get('disclaimer_presence', 0.0)):.2f}")
        m3.metric("Contradiction Accuracy", f"{float(eval_report.get('contradiction_detection_accuracy', 0.0)):.2f}")
        total_score = float(eval_report.get("rubric_scores", {}).get("total_100", 0.0))
        m4.metric("Rubric Total", f"{total_score:.1f}/100")

        st.markdown("#### Gate Results")
        st.json(eval_report.get("gate_results", {}))

        st.markdown("#### Rubric Breakdown")
        _rubric_chart(eval_report.get("rubric_scores", {}))

        st.markdown("#### Notes")
        st.write(eval_report.get("notes", []))

with tab_narrative:
    _section("Narrative Explorer", "Drift + tension + broker lens")

    nticker = st.text_input("Ticker  ", value="ASELS").strip().upper()
    if st.button("Analyze Narrative", type="primary"):
        try:
            diag = _request(st.session_state.api_base, st.session_state.api_token, "GET", f"/v1/diagnostics/{nticker}")
            left, right = st.columns(2)
            with left:
                st.markdown("#### Disclosure-News Tension")
                tension = float(diag.get("disclosure_news_tension_index", {}).get("tension_index", 0.0))
                st.metric("Tension Index", f"{tension:.3f}")
                st.progress(min(max(tension, 0.0), 1.0))
                st.caption(str(diag.get("disclosure_news_tension_index", {}).get("reason", "")))

                st.markdown("#### Claim Ledger")
                st.json(diag.get("claim_ledger", {}))

            with right:
                st.markdown("#### Narrative Drift Radar")
                st.json(diag.get("narrative_drift_radar", {}))

                st.markdown("#### Broker Bias Lens")
                st.json(diag.get("broker_bias_lens", {}))

            st.markdown("#### Retrieval Trace")
            st.json(diag.get("retrieval_trace", {}))
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

with tab_provider:
    _section("Provider Lab", "Kendi Ollama/API key bağlantını test et")

    p1, p2 = st.columns([1, 2])
    prov = p1.selectbox("Provider", ["ollama", "groq", "gemini", "openai", "together", "mock"])
    p_overrides = p2.text_area("Overrides JSON", value=_default_overrides(prov), height=140)
    prompt = st.text_input("Validation Prompt", value="Reply with a short health confirmation.")

    if st.button("Validate Provider", type="primary"):
        try:
            overrides = None
            if p_overrides.strip():
                parsed = json.loads(p_overrides)
                if not isinstance(parsed, dict):
                    raise ValueError("Overrides JSON object olmalı")
                overrides = {str(k): str(v) for k, v in parsed.items() if v is not None}

            payload = {
                "provider_pref": prov,
                "provider_overrides": overrides,
                "prompt": prompt,
            }
            result = _request(
                st.session_state.api_base,
                st.session_state.api_token,
                "POST",
                "/v1/provider/validate",
                payload,
                timeout=180,
            )
            if result.get("ok"):
                st.success("Provider bağlantısı başarılı")
            else:
                st.error("Provider bağlantısı başarısız")
            st.json(result)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

st.caption(f"Last refresh: {datetime.now().isoformat(timespec='seconds')} | API: {st.session_state.api_base}")
