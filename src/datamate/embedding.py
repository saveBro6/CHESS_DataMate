"""Local bge-m3 embedding provider for the DataMate adapter.

FlagEmbedding 1.4.2 facts this module encodes (measured in this checkout):

* the importable package is ``FlagEmbedding`` (capital F);
* ``BGEM3FlagModel`` takes ``devices=``; omitting it silently runs on CPU;
* ``encode(..., normalize_embeddings=True)`` raises ``TypeError`` because the
  kwarg is forwarded to the tokenizer, and it is unnecessary: bge-m3 already
  returns L2-normalised dense vectors (measured norm 1.0000, dim 1024, float16).

Nothing here loads a model at import time: the singleton is built from the
environment on first request and the weights are loaded on first use, so the
CHESS modules that call :func:`get_embedding_function` stay cheap to import.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from langchain_core.embeddings import Embeddings

from datamate.config import load_settings
from datamate.constants import DEFAULT_EMBED_GPU_UTIL, DEFAULT_EMBED_MODEL_PATH

LOGGER = logging.getLogger(__name__)

EMBEDDING_DIM = 1024
DEFAULT_LOCAL_MODEL = "BAAI/bge-m3"
MAX_LENGTH = 8192

_lock = threading.Lock()
_embeddings: "DatamateEmbeddings | None" = None


class EmbeddingUnavailable(RuntimeError):
    """No embedding backend could be built; callers must degrade."""


def _resolve_device(requested: str) -> tuple[str, bool]:
    """Return ``(device, use_fp16)`` actually usable by the local provider."""
    device = (requested or "").strip() or "cuda:0"
    if not device.startswith("cuda"):
        return "cpu", False
    try:
        import torch
    except Exception:  # torch is a pinned dependency; degrade instead of crashing
        LOGGER.warning("torch is unavailable, embedding on CPU")
        return "cpu", False
    if not torch.cuda.is_available():
        LOGGER.warning("EMBEDDING_DEVICE=%s but CUDA is unavailable, embedding on CPU", device)
        return "cpu", False
    return device, True


class DatamateEmbeddings(Embeddings):
    """Chroma/LangChain embedding function backed by bge-m3.

    Chroma calls ``embed_documents`` and ``embed_query``; both return plain
    Python floats so the vectors are JSON-serialisable.
    """

    def __init__(
        self,
        *,
        provider: str,
        device: str,
        model: str,
        batch_size: int,
        use_vllm: bool = False,
        gpu_memory_utilization: float | None = None,
    ) -> None:
        self.provider = provider
        self.model_name = model
        self.batch_size = batch_size
        self.requested_device = device
        self.use_vllm = use_vllm
        self.gpu_memory_utilization = gpu_memory_utilization
        self._device = device
        self._model: Any = None
        self._logged = False

    def _is_vllm_enabled(self) -> bool:
        return (
            self.use_vllm
            or self.provider == "vllm"
            or os.environ.get("USE_VLLM", "").strip().lower() in {"1", "true", "yes", "on"}
        )

    def describe(self) -> str:
        """One-line description; reports the resolved device once loaded."""
        if self._is_vllm_enabled():
            return f"provider=vllm dim={EMBEDDING_DIM} model={self.model_name or DEFAULT_EMBED_MODEL_PATH}"
        if self.provider == "local":
            return f"provider=local dim={EMBEDDING_DIM} device={self._device}"
        return f"provider={self.provider} dim=unknown device=remote"

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        with _lock:
            if self._model is None:
                self._model = self._build_model()
        return self._model

    def _build_model(self) -> Any:
        if self._is_vllm_enabled():
            from datamate.vector_indexer import SemanticVectorIndexer

            model_path = (
                os.environ.get("EMBEDDING_MODEL_PATH")
                or os.environ.get("EMBEDDING_MODEL")
                or self.model_name
                or DEFAULT_EMBED_MODEL_PATH
            )
            gpu_util = (
                self.gpu_memory_utilization
                if self.gpu_memory_utilization is not None
                else float(os.environ.get("VLLM_EMBEDDING_GPU_MEMORY_UTILIZATION") or DEFAULT_EMBED_GPU_UTIL)
            )
            indexer = SemanticVectorIndexer(
                model_path=model_path,
                batch_size=self.batch_size,
                gpu_memory_utilization=gpu_util,
            )
            _ = indexer.embedder
            self._log_once(
                f"embedding_provider=vllm dim={EMBEDDING_DIM} model={model_path} gpu_util={gpu_util}"
            )
            return indexer
        if self.provider == "openai":
            remote_model = os.environ.get("EMBEDDING_MODEL")
            if not remote_model:
                raise EmbeddingUnavailable(
                    "EMBEDDING_PROVIDER=openai requires EMBEDDING_MODEL to be set"
                )
            from langchain_openai import OpenAIEmbeddings

            self._log_once("embedding_provider=openai dim=unknown device=remote")
            return OpenAIEmbeddings(model=remote_model)
        if self.provider != "local":
            raise EmbeddingUnavailable(f"unsupported EMBEDDING_PROVIDER={self.provider!r}")
        device, use_fp16 = _resolve_device(self.requested_device)
        try:
            from FlagEmbedding import BGEM3FlagModel

            model = BGEM3FlagModel(self.model_name, use_fp16=use_fp16, devices=device)
        except Exception as exc:
            raise EmbeddingUnavailable(
                f"cannot load {self.model_name} on {device}: {exc}"
            ) from exc
        self._device = device
        self._log_once(f"embedding_provider=local dim={EMBEDDING_DIM} device={device}")
        return model

    def _log_once(self, message: str) -> None:
        """Log the provider banner exactly once, at ``logging.warning``."""
        if not self._logged:
            self._logged = True
            LOGGER.warning("%s", message)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed texts into L2-normalised 1024-d vectors."""
        batch = [text if isinstance(text, str) else str(text) for text in texts]
        if not batch:
            return []
        model = self._ensure_model()
        if hasattr(model, "_encode_texts"):
            return model._encode_texts(batch).tolist()
        if self.provider == "openai":
            return [[float(value) for value in vector] for vector in model.embed_documents(batch)]
        # `normalize_embeddings=` is deliberately not passed: in FlagEmbedding 1.4.2
        # it reaches the tokenizer and raises TypeError, and bge-m3 already
        # returns L2-normalised dense vectors.
        encoded = model.encode(batch, batch_size=self.batch_size, max_length=MAX_LENGTH)
        return encoded["dense_vecs"].tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed one query string with the same space used for documents."""
        vectors = self.embed_documents([text])
        if not vectors:
            raise EmbeddingUnavailable("no embedding was produced")
        return vectors[0]


def get_embedding_function() -> DatamateEmbeddings:
    """Return the process-wide embedding function; no model load happens here."""
    global _embeddings
    if _embeddings is None:
        with _lock:
            if _embeddings is None:
                settings = load_settings()
                configured = os.environ.get("EMBEDDING_MODEL")
                model = configured or (
                    DEFAULT_LOCAL_MODEL if settings.embedding_provider == "local" else ""
                )
                _embeddings = DatamateEmbeddings(
                    provider=settings.embedding_provider,
                    device=settings.embedding_device,
                    model=model,
                    batch_size=settings.embedding_batch,
                    use_vllm=settings.use_vllm,
                    gpu_memory_utilization=settings.gpu_embed_memory_util,
                )
    return _embeddings
