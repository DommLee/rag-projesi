from __future__ import annotations

import hashlib
import logging

import httpx
import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)


def _seed_from_text(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return int(digest, 16)


def _normalize_dim(vector: list[float], dim: int) -> list[float]:
    if len(vector) == dim:
        arr = np.array(vector, dtype=np.float32)
        norm = np.linalg.norm(arr) or 1.0
        return (arr / norm).tolist()
    if len(vector) > dim:
        arr = np.array(vector[:dim], dtype=np.float32)
        norm = np.linalg.norm(arr) or 1.0
        return (arr / norm).tolist()
    padded = vector + ([0.0] * (dim - len(vector)))
    arr = np.array(padded, dtype=np.float32)
    norm = np.linalg.norm(arr) or 1.0
    return (arr / norm).tolist()


def _local_fallback_embedding(text: str, dim: int) -> list[float]:
    rng = np.random.default_rng(_seed_from_text(text))
    vector = rng.normal(0, 1, dim)
    norm = np.linalg.norm(vector) or 1.0
    return (vector / norm).tolist()


def _embed_ollama(text: str) -> list[float]:
    settings = get_settings()
    response = httpx.post(
        f"{settings.ollama_base_url.rstrip('/')}/api/embeddings",
        json={"model": settings.ollama_embedding_model, "prompt": text},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    emb = data.get("embedding")
    if not emb:
        raise RuntimeError("Ollama embedding response missing 'embedding'")
    return emb


def _embed_openai(text: str) -> list[float]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY missing")
    response = httpx.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={"model": settings.openai_embedding_model, "input": text},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["data"][0]["embedding"]


def _embed_voyage(text: str) -> list[float]:
    settings = get_settings()
    if not settings.voyage_api_key:
        raise RuntimeError("VOYAGE_API_KEY missing")
    response = httpx.post(
        "https://api.voyageai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {settings.voyage_api_key}",
            "Content-Type": "application/json",
        },
        json={"model": settings.voyage_embedding_model, "input": [text]},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["data"][0]["embedding"]


def _embed_nomic(text: str) -> list[float]:
    settings = get_settings()
    if not settings.nomic_api_key:
        raise RuntimeError("NOMIC_API_KEY missing")
    response = httpx.post(
        "https://api-atlas.nomic.ai/v1/embedding/text",
        headers={
            "Authorization": f"Bearer {settings.nomic_api_key}",
            "Content-Type": "application/json",
        },
        json={"model": settings.nomic_embedding_model, "texts": [text]},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    if "embeddings" in payload and payload["embeddings"]:
        return payload["embeddings"][0]
    if "data" in payload and payload["data"]:
        return payload["data"][0]["embedding"]
    raise RuntimeError("Nomic embedding response did not include embeddings")


def embed_text_with_provider(text: str, provider_override: str | None = None) -> tuple[list[float], str]:
    settings = get_settings()
    dim = settings.milvus_dim
    provider = (provider_override or settings.embedding_provider).lower()

    order: list[str]
    if provider in {"openai", "voyage", "ollama", "nomic", "local"}:
        order = [provider]
    else:
        order = ["ollama", "openai", "voyage", "nomic", "local"]

    for candidate in order + ["local"]:
        try:
            if candidate == "openai":
                vector = _embed_openai(text)
            elif candidate == "voyage":
                vector = _embed_voyage(text)
            elif candidate == "ollama":
                vector = _embed_ollama(text)
            elif candidate == "nomic":
                vector = _embed_nomic(text)
            else:
                vector = _local_fallback_embedding(text, dim)
            return _normalize_dim(vector, dim), candidate
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding provider failed (%s): %s", candidate, exc)
            continue

    return _local_fallback_embedding(text, dim), "local"


def embed_text(text: str, provider_override: str | None = None) -> list[float]:
    vector, _ = embed_text_with_provider(text, provider_override=provider_override)
    return vector

