from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "BIST Agentic RAG"
    app_version: str = "1.3.0"
    app_env: str = "dev"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

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
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    voyage_api_key: str = ""
    voyage_embedding_model: str = "voyage-3-lite"
    nomic_api_key: str = ""
    nomic_embedding_model: str = "nomic-embed-text-v1.5"
    embedding_provider: str = "local"

    default_language: str = "bilingual"
    max_top_k: int = 8
    session_ttl_hours: int = 24
    disclaimer: str = "This system does not provide investment advice."

    retrieval_time_decay_lambda: float = 0.03
    trace_store_size: int = 300
    crawler_user_agent: str = "bist-agentic-rag/1.0"
    crawler_robots_timeout_seconds: int = 6
    crawler_default_rate_limit_seconds: float = 1.0
    jobs_db_path: str = "data/jobs.db"
    api_auth_enabled: bool = False
    api_auth_token: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
