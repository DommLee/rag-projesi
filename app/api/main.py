from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.rate_limiter import rate_limit_middleware
from app.config import get_settings
from app.jobs import JobRegistry
from app.schemas import (
    AutoIngestConfig,
    ChatQueryRequest,
    EvalRequest,
    IngestRequest,
    JobRecord,
    ProviderValidateRequest,
    ProviderValidateResponse,
    QueryRequest,
    QueryResponse,
    UploadRequest,
)
from app.service import BISTAgentService
from app.utils.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Run warmup automatically in the background on startup
    import threading
    def auto_warmup():
        try:
            logger.info("Auto-warming up all sources...")
            service.warm_up_all_sources()
            logger.info("Auto-warmup complete.")
        except Exception as e:
            logger.error(f"Auto-warmup failed: {e}")
    threading.Thread(target=auto_warmup, daemon=True).start()
    yield
    # Shutdown logic if needed

app = FastAPI(title="BIST Agentic RAG", version=settings.app_version, lifespan=lifespan)
service = BISTAgentService()
jobs = JobRegistry()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3311",
        "http://127.0.0.1:3311",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        settings.web_ui_url if hasattr(settings, "web_ui_url") and settings.web_ui_url else "",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.middleware("http")(rate_limit_middleware)


class IngestResponse(BaseModel):
    inserted_chunks: int
    ingested_at: datetime
    dedup_rate: float = 0.0
    selected_docs: int = 0
    skipped_docs: int = 0
    doc_level_stats: dict = Field(default_factory=dict)
    chunk_level_stats: dict = Field(default_factory=dict)
    policy_summary: dict = Field(default_factory=dict)


class GraphQueryRequest(BaseModel):
    question: str = Field(min_length=3)
    ticker: str | None = None


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
    ui_url = f"http://127.0.0.1:{settings.web_ui_port or 3311}"
    return f"""
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>BIST Agentic RAG API</title>
  <style>
    body {{
      margin: 0;
      font-family: \"Segoe UI\", sans-serif;
      background: radial-gradient(circle at top left, rgba(6,182,212,.12), transparent 30%), linear-gradient(180deg, #07111f 0%, #0b1220 55%, #08101d 100%);
      color: #e5e7eb;
    }}
    .wrap {{
      max-width: 1040px;
      margin: 48px auto;
      padding: 0 20px;
    }}
    .card {{
      border: 1px solid #243044;
      background: rgba(15, 23, 42, 0.82);
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 20px 50px rgba(0,0,0,.28);
    }}
    .eyebrow {{ color: #86efac; text-transform: uppercase; letter-spacing: .24em; font-size: 12px; }}
    h1 {{ margin: 12px 0 0; font-size: 40px; }}
    p {{ color: #94a3b8; line-height: 1.8; }}
    .row {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 14px 18px;
      border-radius: 16px;
      text-decoration: none;
      font-weight: 600;
      border: 1px solid #334155;
      color: #e5e7eb;
      background: #0f172a;
    }}
    .btn.primary {{ background: #059669; border-color: #059669; color: white; }}
    .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); margin-top: 28px; }}
    .metric {{
      border: 1px solid #243044;
      border-radius: 18px;
      padding: 18px;
      background: rgba(2,6,23,.55);
    }}
    .metric .label {{ font-size: 12px; text-transform: uppercase; letter-spacing: .18em; color: #64748b; }}
    .metric .value {{ margin-top: 8px; font-size: 28px; font-weight: 700; color: white; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="eyebrow">BIST Agentic RAG v2.3</div>
      <h1>Bu adres API servisidir, ana uygulama değildir.</h1>
      <p>
        Modern analyst workspace arayüzü ayrı Next.js uygulaması olarak çalışır.
        Canlı dashboard, research chat, upload workspace ve evaluation panellerini görmek için web UI'ı açın.
      </p>
      <div class="row">
        <a class="btn primary" href="{ui_url}" target="_blank" rel="noreferrer">Modern Uygulamayı Aç</a>
        <a class="btn" href="/v1/health" target="_blank" rel="noreferrer">Health JSON</a>
        <a class="btn" href="/docs" target="_blank" rel="noreferrer">FastAPI Docs</a>
      </div>
      <div class="grid">
        <div class="metric"><div class="label">API Port</div><div class="value">{settings.port}</div></div>
        <div class="metric"><div class="label">Suggested UI</div><div class="value">{settings.web_ui_port or 3311}</div></div>
        <div class="metric"><div class="label">Mode</div><div class="value">{settings.app_env}</div></div>
      </div>
    </div>
  </div>
</body>
</html>
"""


@app.get("/v1/health")
def health() -> dict:
    return {**service.health(), "version": settings.app_version}


@app.get("/v1/health/detailed")
def health_detailed(_auth: None = Depends(_require_api_token)) -> dict:
    return service.health_detailed()


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


@app.post("/v1/query/debate")
def query_debate(request: QueryRequest, _auth: None = Depends(_require_api_token)) -> dict:
    try:
        return service.query_debate(request)
    except Exception as exc:  # noqa: BLE001
        service._track_error(str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/graph/query")
def graph_query(request: GraphQueryRequest, _auth: None = Depends(_require_api_token)) -> dict:
    try:
        return service.graph_query(question=request.question, ticker=request.ticker)
    except Exception as exc:  # noqa: BLE001
        service._track_error(str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/chat/query")
def chat_query(request: ChatQueryRequest, _auth: None = Depends(_require_api_token)) -> dict:
    try:
        return service.chat_query(request).model_dump(mode="json")
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


async def _coerce_upload_request(request: Request) -> UploadRequest:
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if file is None:
            raise HTTPException(status_code=400, detail="Multipart upload requires 'file'.")
        raw = await file.read()
        return UploadRequest(
            session_id=str(form.get("session_id") or "default"),
            ticker=str(form.get("ticker") or ""),
            filename=str(getattr(file, "filename", "") or ""),
            content_type=str(getattr(file, "content_type", "") or "application/octet-stream"),
            content_base64=base64.b64encode(raw).decode("utf-8"),
        )
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid upload payload: {exc}") from exc
    return UploadRequest.model_validate(payload)


@app.post("/v1/uploads")
async def upload_document(request: Request, _auth: None = Depends(_require_api_token)) -> dict:
    try:
        upload_request = await _coerce_upload_request(request)
        return service.upload_document(upload_request).model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        service._track_error(str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/uploads/{session_id}")
def list_uploads(session_id: str, _auth: None = Depends(_require_api_token)) -> dict:
    return {
        "session_id": session_id,
        "count": len(service.list_uploads(session_id)),
        "items": [row.model_dump(mode="json") for row in service.list_uploads(session_id)],
    }


@app.delete("/v1/uploads/{upload_id}")
def delete_upload(upload_id: str, _auth: None = Depends(_require_api_token)) -> dict:
    return service.delete_upload(upload_id)


@app.post("/v1/eval/run")
def run_eval(request: EvalRequest, _auth: None = Depends(_require_api_token)) -> dict:
    result = service.eval_run(request)
    return result.model_dump()


@app.get("/v1/eval/report/latest")
def latest_eval_report(_auth: None = Depends(_require_api_token)) -> dict:
    return service.get_latest_eval_report()


@app.get("/v1/eval/history")
def eval_history(
    limit: int = Query(default=10, ge=1, le=100),
    _auth: None = Depends(_require_api_token),
) -> dict:
    return service.get_eval_history(limit=limit)


@app.get("/v1/diagnostics/{ticker}")
def diagnostics(ticker: str, _auth: None = Depends(_require_api_token)) -> dict:
    return service.diagnostics(ticker=ticker.upper())


@app.get("/v1/metrics")
def metrics(_auth: None = Depends(_require_api_token)) -> dict:
    return service.get_metrics()


@app.get("/v1/providers")
def providers(_auth: None = Depends(_require_api_token)) -> dict:
    return service.get_provider_registry()


@app.get("/v1/source-catalog")
def source_catalog(_auth: None = Depends(_require_api_token)) -> dict:
    items = service.get_source_catalog()
    return {"count": len(items), "items": items}


@app.get("/v1/source-health")
def source_health(_auth: None = Depends(_require_api_token)) -> dict:
    return service.get_source_health_report()


@app.post("/v1/sources/warm-up")
def warm_up_sources(_auth: None = Depends(_require_api_token)) -> dict:
    return service.warm_up_all_sources()


@app.get("/v1/crypto/context")
def crypto_context(
    symbols: str = Query(default="BTC,ETH", description="Comma separated crypto symbols"),
    _auth: None = Depends(_require_api_token),
) -> dict:
    requested = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    return service.get_crypto_context(requested)


@app.get("/v1/audit/ledger")
def audit_ledger(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _auth: None = Depends(_require_api_token),
) -> dict:
    return service.get_audit_ledger(ticker=ticker.upper() if ticker else None, limit=limit)


@app.get("/v1/audit/verify")
def audit_verify(
    ticker: str | None = Query(default=None),
    _auth: None = Depends(_require_api_token),
) -> dict:
    return service.verify_audit_ledger(ticker=ticker.upper() if ticker else None)


@app.get("/v1/storage/raw-lake")
def raw_lake_summary(_auth: None = Depends(_require_api_token)) -> dict:
    return service.get_raw_lake_summary()


@app.get("/v1/market/universe")
def market_universe(
    limit: int = Query(default=50, ge=1, le=500),
    mode: str = Query(default="priority", pattern="^(all|priority)$"),
    queue: str | None = Query(default=None, pattern="^(hot|active|background)$"),
    _auth: None = Depends(_require_api_token),
) -> dict:
    return service.get_ticker_universe(limit=limit, mode=mode, queue=queue)


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


@app.get("/v1/research/ticker/{ticker}")
def research_ticker(
    ticker: str,
    session_id: str = Query(default="default"),
    _auth: None = Depends(_require_api_token),
) -> dict:
    return service.get_research_ticker_bundle(ticker=ticker.upper(), session_id=session_id)


@app.get("/v1/cross-asset/context")
def cross_asset_context(
    ticker: str = Query(...),
    _auth: None = Depends(_require_api_token),
) -> dict:
    return service.get_cross_asset_context(ticker=ticker.upper())


@app.get("/v1/ticker/dossier/{ticker}")
def ticker_dossier(
    ticker: str,
    _auth: None = Depends(_require_api_token),
) -> dict:
    return service.get_ticker_dossier(ticker.upper())


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
            metrics_payload = service.get_metrics()
            payload = {
                "auto_ingest": service.get_auto_ingest_status(),
                "last_ingest_stats": service.last_ingest_stats,
                "market_prices": service.get_market_prices(limit=8),
                "sources": metrics_payload.get("source_health", {}),
                "live_ingest_health": metrics_payload.get("live_ingest_health", {}),
                "fresh_doc_ratio": metrics_payload.get("fresh_doc_ratio", 0.0),
                "ticker_coverage_ratio": metrics_payload.get("ticker_coverage_ratio", 0.0),
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


class CompareRequest(BaseModel):
    tickers: list[str] = Field(min_length=2)
    question: str = Field(min_length=3)
    provider_pref: str | None = None


class PDFExportRequest(BaseModel):
    ticker: str = Field(min_length=1)
    question: str = Field(min_length=3)
    provider_pref: str | None = None


# Streaming query (SSE)

@app.post("/v1/query/stream")
async def query_stream(request: QueryRequest, _auth: None = Depends(_require_api_token)) -> StreamingResponse:
    async def event_gen():
        try:
            for event in service.query_streaming(request):
                yield _sse("agent_step", event)
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Cross-ticker comparison

@app.post("/v1/query/compare")
def query_compare(request: CompareRequest, _auth: None = Depends(_require_api_token)) -> dict:
    try:
        return service.compare_query(
            tickers=request.tickers,
            question=request.question,
            provider_pref=request.provider_pref,
        )
    except Exception as exc:  # noqa: BLE001
        service._track_error(str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# Audit trail JSON export

@app.get("/v1/audit/export")
def audit_export(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    _auth: None = Depends(_require_api_token),
) -> StreamingResponse:
    data = service.export_audit_trail(ticker=ticker.upper() if ticker else None, limit=limit)
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    filename = f"audit_trail_{(ticker or 'all').upper()}_{data['exported_at'][:10]}.json"
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# PDF report export

@app.post("/v1/query/export/pdf")
def query_export_pdf(request: PDFExportRequest, _auth: None = Depends(_require_api_token)) -> StreamingResponse:
    from app.utils.pdf_export import generate_query_pdf

    try:
        query_req = QueryRequest(ticker=request.ticker, question=request.question, provider_pref=request.provider_pref)
        result = service.query(query_req)
        pdf_bytes = generate_query_pdf(result, ticker=request.ticker, question=request.question)
        filename = f"report_{request.ticker}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.pdf"
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:  # noqa: BLE001
        service._track_error(str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# Batch query

class BatchQueryRequest(BaseModel):
    questions: list[dict] = Field(min_length=1, description="List of {ticker, question} dicts")
    provider_pref: str | None = None


@app.post("/v1/query/batch")
def query_batch(request: BatchQueryRequest, _auth: None = Depends(_require_api_token)) -> dict:
    try:
        results = service.batch_query(request.questions, provider_pref=request.provider_pref)
        return {
            "count": len(results),
            "results": results,
            "disclaimer": "This system does not provide investment advice.",
        }
    except Exception as exc:  # noqa: BLE001
        service._track_error(str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# Ticker autocomplete

@app.get("/v1/ticker/suggest")
def ticker_suggest(
    q: str = Query(..., min_length=1, description="Prefix or keyword to search"),
    limit: int = Query(default=10, ge=1, le=50),
    _auth: None = Depends(_require_api_token),
) -> dict:
    results = service.suggest_tickers(q, limit=limit)
    return {"query": q, "count": len(results), "suggestions": results}


# Chat history

@app.get("/v1/chat/history")
def chat_history(
    session_id: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _auth: None = Depends(_require_api_token),
) -> dict:
    items = service.get_chat_history(session_id=session_id, ticker=ticker, limit=limit)
    return {"count": len(items), "items": items}


# Cache management

@app.post("/v1/cache/clear")
def cache_clear(_auth: None = Depends(_require_api_token)) -> dict:
    cleared = service.clear_query_cache()
    return {"cleared": cleared, "status": "ok"}


# Alerts

@app.get("/v1/alerts")
def list_alerts(
    ticker: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    unacknowledged: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    _auth: None = Depends(_require_api_token),
) -> dict:
    items = service.alert_manager.list_alerts(
        ticker=ticker, severity=severity,
        unacknowledged_only=unacknowledged, limit=limit,
    )
    return {"count": len(items), "stats": service.alert_manager.stats(), "alerts": items}


@app.post("/v1/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, _auth: None = Depends(_require_api_token)) -> dict:
    ok = service.alert_manager.acknowledge(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="alert not found")
    return {"status": "acknowledged", "alert_id": alert_id}


@app.post("/v1/alerts/acknowledge-all")
def acknowledge_all_alerts(
    ticker: str | None = Query(default=None),
    _auth: None = Depends(_require_api_token),
) -> dict:
    count = service.alert_manager.acknowledge_all(ticker=ticker)
    return {"acknowledged": count}


@app.get("/v1/alerts/rules")
def alert_rules(_auth: None = Depends(_require_api_token)) -> dict:
    return {"rules": service.alert_manager.get_rules()}


@app.post("/v1/alerts/test")
def alert_test(_auth: None = Depends(_require_api_token)) -> dict:
    from app.alerts import AlertSeverity, AlertType

    alert = service.alert_manager.emit(
        AlertType.INGEST_FAILURE,
        ticker="SYSTEM",
        message="Test critical alert dispatch from BIST Agentic RAG.",
        severity=AlertSeverity.CRITICAL,
        details={"source": "manual_test"},
    )
    return {"status": "sent" if alert else "disabled", "alert": alert.to_dict() if alert else None}


# Query analytics

@app.get("/v1/analytics/queries")
def query_analytics(_auth: None = Depends(_require_api_token)) -> dict:
    latencies = list(service.query_latencies_ms)
    sorted_lat = sorted(latencies) if latencies else []
    buckets = {"<50ms": 0, "50-200ms": 0, "200-500ms": 0, "500ms-1s": 0, ">1s": 0}
    for ms in latencies:
        if ms < 50:
            buckets["<50ms"] += 1
        elif ms < 200:
            buckets["50-200ms"] += 1
        elif ms < 500:
            buckets["200-500ms"] += 1
        elif ms < 1000:
            buckets["500ms-1s"] += 1
        else:
            buckets[">1s"] += 1
    top_tickers = [
        {"ticker": t, "count": c}
        for t, c in service._ticker_activity.most_common(15)
    ]
    return {
        "total_queries": service.metrics["total_queries"],
        "blocked_queries": service.metrics["blocked_queries"],
        "latency_histogram": buckets,
        "latency_percentiles": {
            "p50": round(sorted_lat[len(sorted_lat) // 2], 1) if sorted_lat else 0,
            "p90": round(sorted_lat[int(len(sorted_lat) * 0.9)], 1) if len(sorted_lat) >= 2 else 0,
            "p95": round(sorted_lat[int(len(sorted_lat) * 0.95)], 1) if len(sorted_lat) >= 2 else 0,
            "p99": round(sorted_lat[int(len(sorted_lat) * 0.99)], 1) if len(sorted_lat) >= 2 else 0,
        },
        "route_distribution": {
            "direct": service.metrics["route_direct_count"],
            "reretrieve": service.metrics["route_reretrieve_count"],
            "blocked": service.metrics["route_blocked_count"],
        },
        "cache_stats": {
            "hits": service._query_cache_hits,
            "misses": service._query_cache_misses,
            "size": service.query_cache_size(),
            "backend": "redis" if service._query_cache_backend.enabled else "memory",
            "hit_rate": round(service._query_cache_hits / max(1, service._query_cache_hits + service._query_cache_misses), 3),
        },
        "top_tickers": top_tickers,
    }


@app.get("/v1/jobs/{job_id}", response_model=JobRecord)
def get_job(job_id: str, _auth: None = Depends(_require_api_token)) -> JobRecord:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/v1/jobs", response_model=list[JobRecord])
def list_jobs(_auth: None = Depends(_require_api_token)) -> list[JobRecord]:
    return jobs.list_jobs()
