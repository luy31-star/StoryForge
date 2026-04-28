from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Any, Protocol, runtime_checkable

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbeddingProvider:
    """本地确定性伪向量，无外部依赖；与词袋 + 稳定哈希近似的稠密嵌入。"""

    name = "hash"

    def __init__(self, *, dimension: int | None = None) -> None:
        self.dimension = max(8, int(dimension or settings.novel_embedding_dimension))

    def embed(self, text: str) -> list[float]:
        return _hash_embed_text(text, dimension=self.dimension)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class OpenAICompatibleEmbeddingProvider:
    """
    调用 OpenAI 兼容的 /v1/embeddings（如 302.AI 转发）。
    若请求失败且允许 fall back，应在外部回退，不在此静默吞掉维度错误。
    """

    name = "http"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimension: int,
        timeout: float,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip() or "text-embedding-3-small"
        self.dimension = max(8, int(dimension))
        self.timeout = float(timeout)

    def _url(self) -> str:
        return f"{self.base_url}/embeddings"

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @staticmethod
    def _fit_dimension(vec: list[float], dim: int) -> list[float]:
        if len(vec) == dim:
            return vec
        if len(vec) > dim:
            return vec[:dim]
        return vec + [0.0] * (dim - len(vec))

    def embed(self, text: str) -> list[float]:
        out = self.embed_batch([text])
        return out[0] if out else [0.0] * self.dimension

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key or not self.base_url:
            raise RuntimeError("http embedding: missing base_url or api_key")
        # OpenAI 支持 input 为 string 或 string[]，分批以控制体量和超时
        batch_size = max(1, int(getattr(settings, "novel_embedding_http_batch_size", 32)))
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            body: dict[str, Any] = {"model": self.model, "input": chunk}
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    self._url(), headers=self._headers(), json=body
                )
                resp.raise_for_status()
                data = resp.json()
            items = data.get("data")
            if not isinstance(items, list):
                raise RuntimeError("http embedding: invalid response (no data[])")
            # 按 index 排序
            try:
                items = sorted(
                    items,
                    key=lambda x: int(x.get("index", 0))
                    if isinstance(x, dict)
                    else 0,
                )
            except Exception:
                pass
            for it in items:
                if not isinstance(it, dict):
                    continue
                emb = it.get("embedding")
                if not isinstance(emb, list):
                    continue
                vec = [float(x) for x in emb]
                all_vecs.append(self._fit_dimension(vec, self.dimension))
        if len(all_vecs) != len(texts):
            raise RuntimeError(
                f"http embedding: length mismatch {len(all_vecs)} != {len(texts)}"
            )
        return all_vecs


def get_embedding_provider() -> EmbeddingProvider:
    mode = (getattr(settings, "novel_embedding_provider", None) or "hash").strip().lower()
    if mode in ("http", "openai", "remote", "api"):
        return OpenAICompatibleEmbeddingProvider(
            base_url=settings.ai302_base_url,
            api_key=settings.ai302_api_key,
            model=settings.novel_embedding_http_model,
            dimension=settings.novel_embedding_dimension,
            timeout=float(
                getattr(settings, "novel_embedding_http_timeout", 30.0) or 30.0
            ),
        )
    return HashEmbeddingProvider(dimension=settings.novel_embedding_dimension)


def _hash_embed_text(text: str, *, dimension: int) -> list[float]:
    dim = max(8, int(dimension))
    vec = [0.0] * dim
    for token in _tokenize_text(text):
        bucket = _stable_bucket(token, dim)
        sign = -1.0 if _stable_bucket(f"{token}:sign", 2) == 0 else 1.0
        weight = 1.0 + min(len(token), 8) * 0.08
        vec[bucket] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 1e-9:
        return vec
    return [v / norm for v in vec]


def embed_text(text: str, *, dimension: int | None = None) -> list[float]:
    """对外统一入口；HTTP 模式失败时可选回退到 hash（见 settings）。"""
    prov = get_embedding_provider()
    try:
        if dimension is not None and prov.name == "hash":
            return HashEmbeddingProvider(dimension=dimension).embed(text)
        if dimension is not None and int(dimension) != int(
            settings.novel_embedding_dimension
        ):
            return HashEmbeddingProvider(dimension=dimension).embed(text)
        vec = prov.embed(text)
        if prov.name == "http" and (
            not vec or all(abs(x) < 1e-12 for x in vec)
        ):
            raise RuntimeError("empty http embedding")
        return vec
    except Exception:
        if prov.name == "http" and settings.novel_embedding_http_fallback:
            logger.warning(
                "embed_text http failed, using hash fallback", exc_info=True
            )
            return _hash_embed_text(
                text, dimension=dimension or settings.novel_embedding_dimension
            )
        raise


def embed_texts(texts: list[str], *, dimension: int | None = None) -> list[list[float]]:
    if not texts:
        return []
    prov = get_embedding_provider()
    try:
        if dimension is not None and (
            prov.name != "hash"
            and int(dimension) != int(settings.novel_embedding_dimension)
        ):
            h = HashEmbeddingProvider(dimension=dimension)
            return h.embed_batch(texts)
        return prov.embed_batch(texts)
    except Exception:
        if prov.name == "http" and settings.novel_embedding_http_fallback:
            logger.warning("embed_texts http failed, hash fallback for batch", exc_info=True)
            h = HashEmbeddingProvider(
                dimension=dimension or settings.novel_embedding_dimension
            )
            return h.embed_batch(texts)
        raise


def _tokenize_text(text: str) -> list[str]:
    raw = str(text or "").strip().lower()
    if not raw:
        return []
    tokens: list[str] = []
    tokens.extend(_WORD_RE.findall(raw))
    cjk_chars = [ch for ch in raw if _CJK_RE.match(ch)]
    tokens.extend(cjk_chars)
    if len(cjk_chars) >= 2:
        tokens.extend("".join(cjk_chars[i : i + 2]) for i in range(len(cjk_chars) - 1))
    return tokens[:400]


def _stable_bucket(token: str, mod: int) -> int:
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, mod)
