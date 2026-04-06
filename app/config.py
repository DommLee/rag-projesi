from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "BIST Agentic RAG"
    app_version: str = "2.0.0"
    app_env: str = "dev"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    vector_dim: int = 1024
    vector_backend: str = "weaviate"
    weaviate_url: str = "http://localhost:8080"
    weaviate_class_name: str = "BISTChunk"
    weaviate_strict_mode: bool = False

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "bist_chunks"
    milvus_dim: int = 384
    milvus_strict_mode: bool = False

    redis_url: str = "redis://localhost:6379/0"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_embedding_model: str = "nomic-embed-text"

    together_api_key: str = ""
    together_model: str = "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
    groq_api_key: str = ""
    groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-pro"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    voyage_api_key: str = ""
    voyage_embedding_model: str = "voyage-finance-2"
    nomic_api_key: str = ""
    nomic_embedding_model: str = "nomic-embed-text-v1.5"
    embedding_provider: str = "voyage"

    default_language: str = "bilingual"
    max_top_k: int = 8
    session_ttl_hours: int = 24
    disclaimer: str = "This system does not provide investment advice."

    retrieval_time_decay_lambda: float = 0.03
    trace_store_size: int = 300
    crawler_user_agent: str = "BIST-Agentic-RAG/2.0 (+Academic Research; contact: fintech-course@example.local)"
    crawler_robots_timeout_seconds: int = 6
    crawler_default_rate_limit_seconds: float = 4.0
    crawler_fail_open: bool = False
    crawler_safe_domains_csv: str = "kap.org.tr,aa.com.tr,news.google.com"
    jobs_db_path: str = "data/jobs.db"
    api_auth_enabled: bool = False
    api_auth_token: str = ""
    auto_ingest_enabled: bool = False
    auto_ingest_interval_minutes: int = 30
    auto_ingest_config_path: str = "data/auto_ingest_sources.json"
    live_news_interval_seconds: int = 60
    live_kap_interval_seconds: int = 300
    live_report_interval_seconds: int = 1800
    live_price_interval_seconds: int = 60
    live_dynamic_universe_enabled: bool = True
    live_universe_path: str = "data/bist_universe.json"
    live_universe_batch_size: int = 20
    web_ui_port: int = 3000
    web_ui_url: str = "http://127.0.0.1:3000"
    kap_api_key: str = ""
    kap_api_disclosure_url_template: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
