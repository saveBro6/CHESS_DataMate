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

from dotenv import load_dotenv

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
