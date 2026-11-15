"""Runtime configuration for the DataMate adapter.

The CHESS stack reads its environment once, at import time, so the adapter owns a
single immutable settings object and exports it back into ``os.environ`` through
:func:`apply_env` before any ``runner.*`` module is imported. Every other module
of this package therefore imports the CHESS stack lazily, inside functions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from datamate.constants import DEFAULT_EMBED_GPU_UTIL, DEFAULT_PROD_GPU_UTIL, DEFAULT_PROD_MODEL

DEFAULT_SPLIT_DIR = Path("dataset/train")
DEFAULT_WORK_ROOT = Path("/tmp/datamate-work")
DEFAULT_RESULT_DIR = Path("/result")


@dataclass(frozen=True)
class Settings:
    """Resolved adapter settings; the env contract is ``env.example``."""

    split_dir: Path
    work_root: Path
    result_dir: Path
    db_mode: str
    embedding_provider: str
    embedding_device: str
    embedding_batch: int
    llm_max_tokens: int
    sql_timeout_s: int
    entity_sim_threshold: float
    top_sim_ratio: float
    use_vllm: bool = False
    vllm_model: str = DEFAULT_PROD_MODEL
    gpu_memory_util: float = DEFAULT_PROD_GPU_UTIL
    gpu_embed_memory_util: float = DEFAULT_EMBED_GPU_UTIL


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser() if raw not in (None, "") else default


def load_settings(**overrides) -> Settings:
    """Build :class:`Settings` from the environment, then apply ``overrides``.

    ``.env`` is loaded without overriding: values already exported by
    :func:`apply_env` (or by the shell) must win, otherwise the export would be
    undone by an unrelated ``load_settings()`` call later in the run.
    """
    load_dotenv(override=False)
    split_dir = Path(overrides.get("split_dir") or DEFAULT_SPLIT_DIR)
    base = Settings(
        split_dir=split_dir,
        work_root=_env_path("WORK_ROOT", DEFAULT_WORK_ROOT),
        result_dir=_env_path("RESULT_DIR", DEFAULT_RESULT_DIR),
        db_mode=os.getenv("DB_MODE") or split_dir.name,
        embedding_provider=(os.getenv("EMBEDDING_PROVIDER") or "local").strip().lower(),
        embedding_device=(os.getenv("EMBEDDING_DEVICE") or "cuda:0").strip(),
        embedding_batch=_env_int("EMBEDDING_BATCH", 16),
        llm_max_tokens=_env_int("LLM_MAX_TOKENS", 4096),
        sql_timeout_s=_env_int("SQL_TIMEOUT_S", 20),
        entity_sim_threshold=_env_float("ENTITY_SIM_THRESHOLD", 0.45),
        top_sim_ratio=_env_float("TOP_SIM_RATIO", 0.90),
        use_vllm=_env_bool("USE_VLLM", False),
        vllm_model=(os.getenv("VLLM_MODEL") or DEFAULT_PROD_MODEL).strip(),
        gpu_memory_util=_env_float("VLLM_GPU_MEMORY_UTILIZATION", DEFAULT_PROD_GPU_UTIL),
        gpu_embed_memory_util=_env_float("VLLM_EMBEDDING_GPU_MEMORY_UTILIZATION", DEFAULT_EMBED_GPU_UTIL),
    )
    if not overrides:
        return base
    return replace(base, **overrides)


def apply_env(settings: Settings) -> None:
    """Export ``settings`` into ``os.environ`` for the CHESS stack.

    Must run before ``runner.database_manager`` is imported: that module binds
    ``DB_ROOT_PATH`` and the index-server coordinates at import time. The tunables
    below are exported as well because the modules that consume them
    (``engine_configs``, ``retrieve_entity``) read the environment themselves, so
    leaving them unset would silently desynchronise them from ``settings``.
    """
    os.environ["DB_ROOT_PATH"] = str(settings.work_root)
    os.environ["DB_MODE"] = settings.db_mode
    os.environ["EMBEDDING_PROVIDER"] = settings.embedding_provider
    os.environ["EMBEDDING_DEVICE"] = settings.embedding_device
    os.environ["EMBEDDING_BATCH"] = str(settings.embedding_batch)
    os.environ["ENTITY_SIM_THRESHOLD"] = str(settings.entity_sim_threshold)
    os.environ["TOP_SIM_RATIO"] = str(settings.top_sim_ratio)
    os.environ["LLM_MAX_TOKENS"] = str(settings.llm_max_tokens)
    os.environ["SQL_TIMEOUT_S"] = str(settings.sql_timeout_s)
    os.environ["USE_VLLM"] = "1" if settings.use_vllm else "0"
    os.environ["VLLM_MODEL"] = settings.vllm_model
    os.environ["VLLM_GPU_MEMORY_UTILIZATION"] = str(settings.gpu_memory_util)
    os.environ["VLLM_EMBEDDING_GPU_MEMORY_UTILIZATION"] = str(settings.gpu_embed_memory_util)


def add_vllm_args(parser: Any) -> None:
    """Register shared vLLM CLI flags on an ArgumentParser."""
    parser.add_argument(
        "--vllm",
        action="store_true",
        default=False,
        help="use offline VLLMEngine and SemanticVectorIndexer (bge-m3 pooling) instead of the default pipeline",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=f"vLLM model name or path when --vllm is enabled (default: {DEFAULT_PROD_MODEL})",
    )
    parser.add_argument(
        "--gpu-memory-util",
        "--gpu-memory-utilization",
        dest="gpu_memory_util",
        type=float,
        default=None,
        help=f"GPU memory utilization for VLLMEngine (default: {DEFAULT_PROD_GPU_UTIL})",
    )
    parser.add_argument(
        "--gpu-embed-memory-util",
        "--gpu-embed-memory-utilization",
        dest="gpu_embed_memory_util",
        type=float,
        default=None,
        help=f"GPU memory utilization for bge-m3 embedding via vLLM pooling (default: {DEFAULT_EMBED_GPU_UTIL})",
    )


def vllm_overrides(arguments: Any) -> dict[str, Any]:
    """Extract Settings overrides for vLLM flags from parsed CLI arguments."""
    overrides: dict[str, Any] = {}
    if getattr(arguments, "vllm", False):
        overrides["use_vllm"] = True
    if getattr(arguments, "model", None):
        overrides["vllm_model"] = arguments.model
    if getattr(arguments, "gpu_memory_util", None) is not None:
        overrides["gpu_memory_util"] = arguments.gpu_memory_util
    if getattr(arguments, "gpu_embed_memory_util", None) is not None:
        overrides["gpu_embed_memory_util"] = arguments.gpu_embed_memory_util
    return overrides
