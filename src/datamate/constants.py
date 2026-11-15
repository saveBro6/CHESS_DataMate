"""Centralized constants for DataMate vLLM and embedding pipelines.

Maintains zero internal project dependencies to eliminate circular import risks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Ingestion and storage defaults
DEFAULT_BASE_OUTPUT_DIR: Path = Path(os.environ.get("ZAIC_OUTPUT_DIR", "/tmp/zaic_db"))

# Profiling: MinHash and LSH indexer defaults
DEFAULT_NUM_PERM: int = 128
DEFAULT_THRESHOLD: float = 0.4
DEFAULT_SHINGLE_K: int = 3
DEFAULT_MAX_SAMPLE_VALUES: int = 10000

# Profiling / Inference: vLLM generation defaults
DEFAULT_PROD_MODEL: str = "Qwen/Qwen3.5-9B"
DEFAULT_PROD_GPU_UTIL: float = 0.85
DEFAULT_LOCAL_GPU_UTIL: float = 0.75
DEFAULT_LLM_MAX_LENGTH: int = 16384
DEFAULT_QUANTIZATION: str | None = None

# Profiling: Semantic vector indexer defaults
DEFAULT_EMBED_MODEL_PATH: str = "/app/models/bge-m3"
DEFAULT_EMBED_MAX_LENGTH: int = 4096
DEFAULT_BATCH_SIZE: int = 32
DEFAULT_TOP_K: int = 10
DEFAULT_EMBEDDING_DIM: int = 1024
DEFAULT_MAX_CHUNK_CHARS: int = 1000
DEFAULT_MIN_CHUNK_CHARS: int = 150
DEFAULT_EMBED_GPU_UTIL: float = 0.05
MIN_TABLE_ROWS_FOR_SPLIT: int = 3

# Submission and SQL generation defaults
DEFAULT_CANDIDATE_SEEDS: tuple[int, ...] = (42, 100, 2026)
DEFAULT_NUM_CANDIDATES: int = 3
DEFAULT_SQL_MAX_RETRIES: int = 2
DEFAULT_EXECUTION_MAX_RETRIES: int = 2
DEFAULT_SQL_TIMEOUT_SECONDS: float = 10.0
DEFAULT_SQL_MAX_TOKENS: int = 2048
DEFAULT_THINKING_TOKEN_BUDGET: int = 1536

# Regex patterns
ISO_DATE_REGEX: re.Pattern[str] = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
ISO_DATETIME_REGEX: re.Pattern[str] = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?$")
SLASH_DATE_REGEX: re.Pattern[str] = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")

__all__ = [
    "DEFAULT_BASE_OUTPUT_DIR",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_CANDIDATE_SEEDS",
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_EMBED_GPU_UTIL",
    "DEFAULT_EMBED_MAX_LENGTH",
    "DEFAULT_EMBED_MODEL_PATH",
    "DEFAULT_EXECUTION_MAX_RETRIES",
    "DEFAULT_LLM_MAX_LENGTH",
    "DEFAULT_LOCAL_GPU_UTIL",
    "DEFAULT_MAX_CHUNK_CHARS",
    "DEFAULT_MAX_SAMPLE_VALUES",
    "DEFAULT_MIN_CHUNK_CHARS",
    "DEFAULT_NUM_CANDIDATES",
    "DEFAULT_NUM_PERM",
    "DEFAULT_PROD_GPU_UTIL",
    "DEFAULT_PROD_MODEL",
    "DEFAULT_QUANTIZATION",
    "DEFAULT_SHINGLE_K",
    "DEFAULT_SQL_MAX_RETRIES",
    "DEFAULT_SQL_MAX_TOKENS",
    "DEFAULT_SQL_TIMEOUT_SECONDS",
    "DEFAULT_THINKING_TOKEN_BUDGET",
    "DEFAULT_THRESHOLD",
    "DEFAULT_TOP_K",
    "ISO_DATETIME_REGEX",
    "ISO_DATE_REGEX",
    "MIN_TABLE_ROWS_FOR_SPLIT",
    "SLASH_DATE_REGEX",
]
