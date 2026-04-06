from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.jobs import JobRegistry
from app.schemas import EvalRequest, IngestRequest, JobRecord, QueryRequest, QueryResponse
from app.service import BISTAgentService
from app.utils.logging import configure_logging

configure_logging()
settings = get_settings()
app = FastAPI(title="BIST Agentic RAG", version=settings.app_version)
service = BISTAgentService()
jobs = JobRegistry()


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
) -> None:
    if not settings.api_auth_enabled:
        return
    configured = (settings.api_auth_token or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="API auth is enabled but API_AUTH_TOKEN is not configured.")

    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    provided = (x_api_token or "").strip() or bearer
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
      <select id="evalProvider"><option>auto</option><option>ollama</option><option>openai</option><option>together</option></select>
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
      <select id="ingType"><option value="kap">KAP</option><option value="news">News</option><option value="report">Report</option></select>
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
      <select id="qProv"><option value="">auto</option><option>ollama</option><option>together</option><option>mock</option></select>
      <div class="row">
        <button class="primary" onclick="runQuery()">Query</button>
        <button onclick="runInsight()">Insight</button>
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
    const payload = {
      ticker: document.getElementById("qTicker").value,
      question: document.getElementById("qText").value,
      provider_pref: document.getElementById("qProv").value || null,
      language: "bilingual"
    };
    out("queryOut", await call("/v1/query",{method:"POST", body: JSON.stringify(payload)}));
  } catch(e){ out("queryOut", String(e)); }
}
async function runInsight(){
  try{
    const payload = {
      ticker: document.getElementById("qTicker").value,
      question: document.getElementById("qText").value,
      provider_pref: document.getElementById("qProv").value || null,
      language: "bilingual"
    };
    out("queryOut", await call("/v1/query/insight",{method:"POST", body: JSON.stringify(payload)}));
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
    if source_type in {"report", "broker_report"}:
        return ingest_report(request)
    raise HTTPException(status_code=400, detail="source_type must be one of: kap, news, report")


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


@app.post("/v1/jobs/ingest/{source_type}", response_model=JobRecord)
def create_ingest_job(
    source_type: str, request: IngestRequest, _auth: None = Depends(_require_api_token)
) -> JobRecord:
    source_type = source_type.lower()
    if source_type not in {"kap", "news", "report"}:
        raise HTTPException(status_code=400, detail="source_type must be one of: kap, news, report")

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
