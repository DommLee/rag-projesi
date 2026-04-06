from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    KAP = "kap"
    NEWS = "news"
    BROKER_REPORT = "broker_report"


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
    date: datetime
    institution: str
    doc_id: str
    url: str
    published_at: datetime
    retrieved_at: datetime
    language: str = "tr"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    title: str = ""
    chunk_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def ticker_upper(cls, value: str) -> str:
        return value.upper()


class QueryRequest(BaseModel):
    ticker: str = Field(min_length=1)
    question: str = Field(min_length=3)
    as_of_date: datetime | None = None
    language: str = "bilingual"
    provider_pref: str | None = None
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


class IngestRequest(BaseModel):
    ticker: str
    institution: str
    source_urls: list[str] = Field(default_factory=list)
    date_from: datetime | None = None
    date_to: datetime | None = None
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
