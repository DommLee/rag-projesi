from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.jobs import JobRegistry
from app.schemas import (
    AutoIngestConfig,
    EvalRequest,
    IngestRequest,
    JobRecord,
    ProviderValidateRequest,
    ProviderValidateResponse,
    QueryRequest,
    QueryResponse,
)
from app.service import BISTAgentService
from app.utils.logging import configure_logging

configure_logging()
settings = get_settings()
app = FastAPI(title="BIST Agentic RAG", version=settings.app_version)
service = BISTAgentService()
jobs = JobRegistry()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IngestResponse(BaseModel):
    inserted_chunks: int
    ingested_at: datetime
    dedup_rate: float = 0.0
    selected_docs: int = 0
    skipped_docs: int = 0
    doc_level_stats: dict = Field(default_factory=dict)
    chunk_level_stats: dict = Field(default_factory=dict)
    policy_summary: dict = Field(default_factory=dict)


def _require_api_token(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    if not settings.api_auth_enabled:
        return
    configured = (settings.api_auth_token or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="API auth is enabled but API_AUTH_TOKEN is not configured.")

    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    provided = (x_api_token or "").strip() or bearer or (token or "").strip()
    if not provided or provided != configured:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>BIST Agentic RAG Console</title>
  <style>
    :root { --bg:#0f172a; --panel:#111827; --line:#263248; --text:#e5e7eb; --muted:#9ca3af; --ok:#22c55e; --warn:#f59e0b; }
    body { margin:0; font-family:"Segoe UI",sans-serif; background:linear-gradient(140deg,#0f172a,#0b1324 55%,#111827); color:var(--text); }
    .wrap { max-width:1280px; margin:30px auto; padding:0 16px; display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); }
    .card { background:rgba(17,24,39,.94); border:1px solid var(--line); border-radius:14px; padding:14px; box-shadow:0 8px 30px rgba(0,0,0,.25); }
    h1 { margin:0 0 8px; font-size:22px; } h2 { margin:0 0 8px; font-size:16px; color:#d1d5db; }
    label { display:block; margin-top:8px; font-size:13px; color:var(--muted); }
    input, textarea, select, button { width:100%; box-sizing:border-box; margin-top:6px; border-radius:10px; border:1px solid #324055; background:#0b1220; color:var(--text); padding:10px 11px; }
    textarea { min-height:88px; resize:vertical; }
    button { cursor:pointer; background:#1f2937; border-color:#374151; font-weight:600; }
    button.primary { background:#16a34a; border-color:#16a34a; color:white; }
    .row { display:flex; gap:8px; } .row > * { flex:1; }
    pre { white-space:pre-wrap; word-break:break-word; background:#020817; border:1px solid #283548; border-radius:10px; padding:11px; min-height:120px; max-height:420px; overflow:auto; }
    .chip { display:inline-block; margin-right:6px; padding:4px 8px; font-size:12px; border-radius:99px; border:1px solid #334155; color:#cbd5e1; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card" style="grid-column:1/-1">
      <h1>BIST Agentic RAG Console</h1>
      <span class="chip">Agentic Verify Loop</span>
      <span class="chip">Delta Ingestion</span>
      <span class="chip">Hybrid Evaluation</span>
      <span class="chip">No Investment Advice</span>
    </div>

    <div class="card">
      <h2>System & Ops</h2>
      <label>API Token (optional)</label>
      <input id="apiToken" placeholder="Enter token when auth is enabled" />
      <div class="row">
        <button onclick="checkHealth()">Health</button>
        <button onclick="checkReady()">Ready</button>
        <button onclick="loadMetrics()">Metrics</button>
      </div>
      <pre id="sysOut"></pre>
    </div>

    <div class="card">
      <h2>Evaluation</h2>
      <label>Mode</label>
      <select id="evalMode"><option>heuristic</option><option>hybrid</option><option>mock</option><option>real</option></select>
      <label>Provider</label>
      <select id="evalProvider"><option>auto</option><option>groq</option><option>gemini</option><option>ollama</option><option>openai</option><option>together</option></select>
      <label>Sample Size</label><input id="evalSample" value="15" />
      <div class="row">
        <button class="primary" onclick="runEval()">Run Eval</button>
        <button onclick="latestEval()">Latest Eval</button>
      </div>
      <pre id="evalOut"></pre>
    </div>

    <div class="card">
      <h2>Ingestion Job</h2>
      <label>Ticker</label><input id="ingTicker" value="ASELS" />
      <label>Institution</label><input id="ingInst" value="BIST-Collector" />
      <label>Type</label>
      <select id="ingType"><option value="kap">KAP</option><option value="news">News</option><option value="report">Report</option><option value="brokerage">Brokerage</option></select>
      <label>Source URLs (comma)</label>
      <textarea id="ingUrls">https://www.aa.com.tr/tr/rss/default?cat=ekonomi</textarea>
      <label>Delta Mode</label><select id="ingDelta"><option value="true">true</option><option value="false">false</option></select>
      <div class="row">
        <button class="primary" onclick="submitIngest()">Submit Job</button>
        <button onclick="listJobs()">List Jobs</button>
      </div>
      <pre id="jobOut"></pre>
    </div>

    <div class="card">
      <h2>Query</h2>
      <label>Ticker</label><input id="qTicker" value="ASELS" />
      <label>Question</label><textarea id="qText">Do recent news articles align with official KAP disclosures?</textarea>
      <label>Provider</label>
      <select id="qProv"><option value="">auto</option><option>groq</option><option>gemini</option><option>ollama</option><option>together</option><option>mock</option></select>
      <label>Provider Overrides (JSON, optional)</label>
      <textarea id="qProvOverrides" placeholder='{"ollama_base_url":"http://localhost:11434","ollama_model":"llama3.1:8b"}'></textarea>
      <div class="row">
        <button class="primary" onclick="runQuery()">Query</button>
        <button onclick="runInsight()">Insight</button>
        <button onclick="validateProvider()">Validate Provider</button>
      </div>
      <pre id="queryOut"></pre>
    </div>
  </div>
<script>
async function call(url, options={}) {
  const token = document.getElementById("apiToken")?.value?.trim();
  const headers = {"Content-Type":"application/json"};
  if (token) { headers["X-API-Token"] = token; }
  const res = await fetch(url, {headers: headers, ...options});
  const text = await res.text();
  let data = text; try { data = JSON.parse(text); } catch {}
  if (!res.ok) throw new Error(JSON.stringify(data));
  return data;
}
function out(id, data) { document.getElementById(id).textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2); }
async function checkHealth(){ try { out("sysOut", await call("/v1/health")); } catch(e){ out("sysOut", String(e)); } }
async function checkReady(){ try { out("sysOut", await call("/v1/ready")); } catch(e){ out("sysOut", String(e)); } }
async function loadMetrics(){ try { out("sysOut", await call("/v1/metrics")); } catch(e){ out("sysOut", String(e)); } }
async function runEval(){
  try{
    const payload = {
      mode: document.getElementById("evalMode").value,
      provider: document.getElementById("evalProvider").value,
      sample_size: Number(document.getElementById("evalSample").value || 15),
      dataset_path: "datasets/eval_questions.json",
      store_artifacts: true,
      run_ragas: true,
      run_deepeval: true
    };
    out("evalOut", await call("/v1/eval/run",{method:"POST", body: JSON.stringify(payload)}));
  }catch(e){ out("evalOut", String(e)); }
}
async function latestEval(){ try { out("evalOut", await call("/v1/eval/report/latest")); } catch(e){ out("evalOut", String(e)); } }
async function submitIngest(){
  try{
    const t = document.getElementById("ingType").value;
    const payload = {
      ticker: document.getElementById("ingTicker").value,
      institution: document.getElementById("ingInst").value,
      source_urls: document.getElementById("ingUrls").value.split(",").map(x=>x.trim()).filter(Boolean),
      delta_mode: document.getElementById("ingDelta").value === "true",
      max_docs: 100,
      force_reingest: false
    };
    out("jobOut", await call("/v1/jobs/ingest/" + t, {method:"POST", body: JSON.stringify(payload)}));
  } catch(e){ out("jobOut", String(e)); }
}
async function listJobs(){ try { out("jobOut", await call("/v1/jobs")); } catch(e){ out("jobOut", String(e)); } }
async function runQuery(){
  try{
    let providerOverrides = null;
    const rawOverrides = document.getElementById("qProvOverrides").value.trim();
    if (rawOverrides) {
      providerOverrides = JSON.parse(rawOverrides);
    }
    const payload = {
      ticker: document.getElementById("qTicker").value,
      question: document.getElementById("qText").value,
      provider_pref: document.getElementById("qProv").value || null,
      language: "bilingual",
      provider_overrides: providerOverrides
    };
    out("queryOut", await call("/v1/query",{method:"POST", body: JSON.stringify(payload)}));
  } catch(e){ out("queryOut", String(e)); }
}
async function runInsight(){
  try{
    let providerOverrides = null;
    const rawOverrides = document.getElementById("qProvOverrides").value.trim();
    if (rawOverrides) {
      providerOverrides = JSON.parse(rawOverrides);
    }
    const payload = {
      ticker: document.getElementById("qTicker").value,
      question: document.getElementById("qText").value,
      provider_pref: document.getElementById("qProv").value || null,
      language: "bilingual",
      provider_overrides: providerOverrides
    };
    out("queryOut", await call("/v1/query/insight",{method:"POST", body: JSON.stringify(payload)}));
  } catch(e){ out("queryOut", String(e)); }
}
async function validateProvider(){
  try{
    let providerOverrides = null;
    const rawOverrides = document.getElementById("qProvOverrides").value.trim();
    if (rawOverrides) {
      providerOverrides = JSON.parse(rawOverrides);
    }
    const payload = {
      provider_pref: document.getElementById("qProv").value || null,
      provider_overrides: providerOverrides
    };
    out("queryOut", await call("/v1/provider/validate",{method:"POST", body: JSON.stringify(payload)}));
  } catch(e){ out("queryOut", String(e)); }
}
checkHealth();
</script>
</body>
</html>
"""


@app.get("/v1/health")
def health() -> dict:
    return {**service.health(), "version": settings.app_version}


@app.get("/v1/ready")
def ready() -> dict:
    return service.ready()


@app.post("/v1/query", response_model=QueryResponse)
def query(request: QueryRequest, _auth: None = Depends(_require_api_token)) -> QueryResponse:
    try:
        return service.query(request)
    except Exception as exc:  # noqa: BLE001
        service._track_error(str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/query/insight")
def query_insight(request: QueryRequest, _auth: None = Depends(_require_api_token)) -> dict:
    try:
        return service.query_with_insight(request)
    except Exception as exc:  # noqa: BLE001
        service._track_error(str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/provider/validate", response_model=ProviderValidateResponse)
def provider_validate(request: ProviderValidateRequest, _auth: None = Depends(_require_api_token)) -> ProviderValidateResponse:
    result = service.validate_provider(
        provider_pref=request.provider_pref,
        provider_overrides=request.provider_overrides,
        prompt=request.prompt,
    )
    return ProviderValidateResponse(**result)


def _ingest_response(inserted: int) -> IngestResponse:
    stats = service.last_ingest_stats or {}
    return IngestResponse(
        inserted_chunks=inserted,
        ingested_at=datetime.now(UTC),
        dedup_rate=float(stats.get("dedup_rate", 0.0)),
        selected_docs=int(stats.get("selected_docs", 0)),
        skipped_docs=int(stats.get("skipped", 0)),
        doc_level_stats=stats.get("doc_level_stats", {}),
        chunk_level_stats=stats.get("chunk_level_stats", {}),
        policy_summary=stats.get("policy_summary", {}),
    )


@app.post("/v1/ingest/kap", response_model=IngestResponse)
def ingest_kap(request: IngestRequest, _auth: None = Depends(_require_api_token)) -> IngestResponse:
    inserted = service.ingest_kap(request)
    return _ingest_response(inserted)


@app.post("/v1/ingest/news", response_model=IngestResponse)
def ingest_news(request: IngestRequest, _auth: None = Depends(_require_api_token)) -> IngestResponse:
    inserted = service.ingest_news(request)
    return _ingest_response(inserted)


@app.post("/v1/ingest/report", response_model=IngestResponse)
def ingest_report(request: IngestRequest, _auth: None = Depends(_require_api_token)) -> IngestResponse:
    inserted = service.ingest_report(request)
    return _ingest_response(inserted)


@app.post("/v1/ingest/{source_type}", response_model=IngestResponse)
def ingest_generic(source_type: str, request: IngestRequest, _auth: None = Depends(_require_api_token)) -> IngestResponse:
    source_type = source_type.lower()
    if source_type == "kap":
        return ingest_kap(request)
    if source_type == "news":
        return ingest_news(request)
    if source_type in {"report", "broker_report", "brokerage"}:
        return ingest_report(request)
    raise HTTPException(status_code=400, detail="source_type must be one of: kap, news, report, brokerage")


@app.post("/v1/eval/run")
def run_eval(request: EvalRequest, _auth: None = Depends(_require_api_token)) -> dict:
    result = service.eval_run(request)
    return result.model_dump()


@app.get("/v1/eval/report/latest")
def latest_eval_report(_auth: None = Depends(_require_api_token)) -> dict:
    return service.get_latest_eval_report()


@app.get("/v1/diagnostics/{ticker}")
def diagnostics(ticker: str, _auth: None = Depends(_require_api_token)) -> dict:
    return service.diagnostics(ticker=ticker.upper())


@app.get("/v1/metrics")
def metrics(_auth: None = Depends(_require_api_token)) -> dict:
    return service.get_metrics()


@app.get("/v1/providers")
def providers(_auth: None = Depends(_require_api_token)) -> dict:
    return service.get_provider_registry()


@app.get("/v1/market/universe")
def market_universe(limit: int = Query(default=50, ge=1, le=500), _auth: None = Depends(_require_api_token)) -> dict:
    return service.get_ticker_universe(limit=limit)


@app.get("/v1/market/prices")
def market_prices(
    ticker: str | None = Query(default=None, description="Comma separated tickers, e.g. ASELS,THYAO"),
    limit: int = Query(default=12, ge=1, le=100),
    force_refresh: bool = Query(default=False),
    _auth: None = Depends(_require_api_token),
) -> dict:
    tickers = [item.strip().upper() for item in ticker.split(",")] if ticker else []
    tickers = [item for item in tickers if item]
    return service.get_market_prices(tickers=tickers or None, limit=limit, force_refresh=force_refresh)


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/v1/stream/metrics")
async def stream_metrics(
    request: Request,
    interval: float = Query(default=1.5, ge=0.5, le=20.0),
    _auth: None = Depends(_require_api_token),
) -> StreamingResponse:
    async def event_gen():
        while True:
            if await request.is_disconnected():
                break
            payload = service.get_metrics()
            yield _sse("metrics", payload)
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/v1/stream/ingest")
async def stream_ingest(
    request: Request,
    interval: float = Query(default=2.0, ge=0.5, le=20.0),
    _auth: None = Depends(_require_api_token),
) -> StreamingResponse:
    async def event_gen():
        while True:
            if await request.is_disconnected():
                break
            payload = {
                "auto_ingest": service.get_auto_ingest_status(),
                "last_ingest_stats": service.last_ingest_stats,
                "market_prices": service.get_market_prices(limit=8),
            }
            yield _sse("ingest", payload)
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/v1/auto-ingest/status")
def auto_ingest_status(_auth: None = Depends(_require_api_token)) -> dict:
    return service.get_auto_ingest_status()


@app.get("/v1/auto-ingest/config")
def auto_ingest_config(_auth: None = Depends(_require_api_token)) -> dict:
    return service.auto_ingest_config.model_dump(mode="json")


@app.put("/v1/auto-ingest/config")
@app.post("/v1/auto-ingest/config")
def auto_ingest_update_config(request: AutoIngestConfig, _auth: None = Depends(_require_api_token)) -> dict:
    return service.update_auto_ingest_config(request)


@app.post("/v1/auto-ingest/start")
def auto_ingest_start(_auth: None = Depends(_require_api_token)) -> dict:
    if not service.auto_ingest_config.enabled:
        cfg = service.auto_ingest_config.model_copy(update={"enabled": True})
        service.update_auto_ingest_config(cfg)
    return service.start_auto_ingest()


@app.post("/v1/auto-ingest/stop")
def auto_ingest_stop(_auth: None = Depends(_require_api_token)) -> dict:
    return service.stop_auto_ingest()


@app.post("/v1/auto-ingest/run-once")
def auto_ingest_run_once(_auth: None = Depends(_require_api_token)) -> dict:
    return service.run_auto_ingest_once()


@app.post("/v1/jobs/ingest/{source_type}", response_model=JobRecord)
def create_ingest_job(
    source_type: str, request: IngestRequest, _auth: None = Depends(_require_api_token)
) -> JobRecord:
    source_type = source_type.lower()
    if source_type == "brokerage":
        source_type = "report"
    if source_type not in {"kap", "news", "report"}:
        raise HTTPException(status_code=400, detail="source_type must be one of: kap, news, report, brokerage")

    job = jobs.create_job(
        job_type=f"ingest_{source_type}",
        payload={
            "ticker": request.ticker,
            "institution": request.institution,
            "source_urls": request.source_urls,
            "delta_mode": request.delta_mode,
            "max_docs": request.max_docs,
            "force_reingest": request.force_reingest,
        },
    )

    def _run() -> dict:
        if source_type == "kap":
            inserted = service.ingest_kap(request)
        elif source_type == "news":
            inserted = service.ingest_news(request)
        else:
            inserted = service.ingest_report(request)
        return {
            "inserted_chunks": inserted,
            "ingested_at": datetime.now(UTC).isoformat(),
            "ingest_stats": service.last_ingest_stats,
        }

    jobs.run_async(job.job_id, _run)
    return job


@app.get("/v1/jobs/{job_id}", response_model=JobRecord)
def get_job(job_id: str, _auth: None = Depends(_require_api_token)) -> JobRecord:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/v1/jobs", response_model=list[JobRecord])
def list_jobs(_auth: None = Depends(_require_api_token)) -> list[JobRecord]:
    return jobs.list_jobs()
