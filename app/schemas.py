from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceType(str, Enum):
    KAP = "kap"
    NEWS = "news"
    BROKERAGE = "brokerage"
    BROKER_REPORT = "brokerage"  # backward-compatible alias


class Citation(BaseModel):
    source_type: SourceType
    title: str
    institution: str
    date: datetime
    url: str
    snippet: str


class DocumentChunk(BaseModel):
    content: str
    ticker: str
    source_type: SourceType
    publication_date: datetime | None = None
    date: datetime | None = None
    institution: str
    notification_type: str = "General Assembly"
    doc_id: str
    url: str
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ingest_date: date = Field(default_factory=lambda: datetime.now(UTC).date())
    language: str = "tr"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    title: str = ""
    chunk_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def ticker_upper(cls, value: str) -> str:
        return value.upper()

    @field_validator("notification_type")
    @classmethod
    def normalize_notification_type(cls, value: str) -> str:
        mapping = {
            "material event": "Material Event",
            "financial report": "Financial Report",
            "board decision": "Board Decision",
            "general assembly": "General Assembly",
        }
        lowered = value.strip().lower()
        return mapping.get(lowered, value.strip() or "General Assembly")

    @model_validator(mode="after")
    def align_dates(self) -> "DocumentChunk":
        base_dt = self.publication_date or self.date or self.published_at or datetime.now(UTC)
        if base_dt.tzinfo is None:
            base_dt = base_dt.replace(tzinfo=UTC)
        else:
            base_dt = base_dt.astimezone(UTC)

        self.publication_date = base_dt
        if self.date:
            self.date = self.date.astimezone(UTC) if self.date.tzinfo else self.date.replace(tzinfo=UTC)
        else:
            self.date = base_dt
        if self.published_at:
            self.published_at = (
                self.published_at.astimezone(UTC)
                if self.published_at.tzinfo
                else self.published_at.replace(tzinfo=UTC)
            )
        else:
            self.published_at = base_dt
        if self.retrieved_at.tzinfo is None:
            self.retrieved_at = self.retrieved_at.replace(tzinfo=UTC)
        else:
            self.retrieved_at = self.retrieved_at.astimezone(UTC)
        return self


class QueryRequest(BaseModel):
    ticker: str = Field(min_length=1)
    question: str = Field(min_length=3)
    as_of_date: datetime | None = None
    language: str = "bilingual"
    provider_pref: str | None = None
    provider_overrides: dict[str, str] | None = None
    session_id: str = "default"

    @field_validator("ticker")
    @classmethod
    def clean_ticker(cls, value: str) -> str:
        return value.strip().upper()


class QueryResponse(BaseModel):
    answer_tr: str
    answer_en: str
    as_of_date: datetime
    citations: list[Citation]
    consistency_assessment: str
    confidence: float = Field(ge=0.0, le=1.0)
    disclaimer: str
    blocked: bool = False
    citation_coverage_score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_gaps: list[str] = Field(default_factory=list)
    used_sources: list[SourceType] = Field(default_factory=list)
    provider_used: str = "unknown"
    route_path: str = "direct"


class IngestRequest(BaseModel):
    ticker: str
    institution: str
    source_urls: list[str] = Field(default_factory=list)
    date_from: datetime | None = None
    date_to: datetime | None = None
    notification_types: list[str] = Field(default_factory=list)
    language: str = "tr"
    delta_mode: bool = True
    max_docs: int = 100
    force_reingest: bool = False

    @field_validator("ticker")
    @classmethod
    def clean_ingest_ticker(cls, value: str) -> str:
        return value.strip().upper()


class EvalRequest(BaseModel):
    mode: str = "hybrid"
    provider: str = "auto"
    sample_size: int = 15
    dataset_path: str = "datasets/eval_questions.json"
    store_artifacts: bool = True
    run_ragas: bool = True
    run_deepeval: bool = True


class EvalResult(BaseModel):
    mode: str = "hybrid"
    provider: str = "auto"
    evaluation_mode_effective: str = "heuristic"
    real_provider_available: bool = False
    total_questions: int
    citation_coverage: float
    disclaimer_presence: float
    contradiction_detection_accuracy: float
    avg_confidence: float
    heuristic_metrics: dict[str, float] = Field(default_factory=dict)
    model_based_metrics: dict[str, Any] = Field(default_factory=dict)
    gate_results: dict[str, bool] = Field(default_factory=dict)
    rubric_scores: dict[str, float] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    details: list[dict[str, Any]]


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRecord(BaseModel):
    job_id: str
    job_type: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AutoIngestSource(BaseModel):
    ticker: str
    institution: str = "BIST-Collector"
    kap_urls: list[str] = Field(default_factory=list)
    news_urls: list[str] = Field(default_factory=list)
    report_urls: list[str] = Field(default_factory=list)
    notification_types: list[str] = Field(default_factory=list)
    date_from: datetime | None = None
    date_to: datetime | None = None
    delta_mode: bool = True
    max_docs: int = 100
    force_reingest: bool = False

    @field_validator("ticker")
    @classmethod
    def clean_auto_ticker(cls, value: str) -> str:
        return value.strip().upper()


class AutoIngestConfig(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=30, ge=1, le=1440)
    sources: list[AutoIngestSource] = Field(default_factory=list)


class ProviderValidateRequest(BaseModel):
    provider_pref: str | None = None
    provider_overrides: dict[str, str] | None = None
    prompt: str = "Reply with a short health confirmation."


class ProviderValidateResponse(BaseModel):
    ok: bool
    provider_used: str
    latency_ms: float
    preview: str = ""
    error: str | None = None
