"""Offline vLLM engine wrapper and LangChain Runnable adapter for DataMate."""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig

# Disable FlashInfer top-p/top-k sampler by default to prevent JIT compilation failures on NVCC < 12.2
os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")

from datamate.constants import (
    DEFAULT_LLM_MAX_LENGTH,
    DEFAULT_PROD_GPU_UTIL,
    DEFAULT_PROD_MODEL,
    DEFAULT_QUANTIZATION,
)

_THINK_BLOCK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)
_ENGINE_CACHE_LOCK = threading.Lock()
_VLLM_ENGINE_CACHE: dict[tuple[str, float, int, str | None], "VLLMEngine"] = {}


def clear_vllm_engine_cache() -> None:
    """Clear all cached VLLMEngine instances (useful for test isolation)."""
    with _ENGINE_CACHE_LOCK:
        _VLLM_ENGINE_CACHE.clear()


@runtime_checkable
class LLMEngineProtocol(Protocol):
    """Protocol for offline inference engines supporting batched generation."""

    def generate(
        self,
        prompts: list[str] | str,
        max_tokens: int = 512,
        temperature: float = 0.0,
        stop: list[str] | None = None,
        seed: int | None = None,
        thinking_token_budget: int | None = None,
        **kwargs: Any,
    ) -> list[str] | str:
        """Generate text completions for a single prompt or batch of prompts."""
        ...


def _coerce_prompt_text(prompt_input: Any) -> str:
    """Convert LangChain prompt values or message lists into a single prompt string."""
    if isinstance(prompt_input, str):
        return prompt_input
    if hasattr(prompt_input, "to_string"):
        return str(prompt_input.to_string())
    if hasattr(prompt_input, "to_messages"):
        messages = prompt_input.to_messages()
        return "\n".join(
            str(getattr(msg, "content", msg)) for msg in messages
        )
    if isinstance(prompt_input, BaseMessage):
        return str(prompt_input.content)
    if isinstance(prompt_input, list):
        parts: list[str] = []
        for item in prompt_input:
            if isinstance(item, BaseMessage):
                parts.append(str(item.content))
            elif isinstance(item, dict) and "content" in item:
                parts.append(str(item["content"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(prompt_input)


def _strip_leading_think_block(text: str) -> str:
    """Drop a leading `<think>...</think>` block when followed by final output."""
    if "</think>" not in text:
        return text
    stripped = _THINK_BLOCK_RE.sub("", text, count=1).strip()
    return stripped if stripped else text


class VLLMEngine(Runnable[Any, AIMessage]):
    """Wrapper around vLLM offline engine implementing both .generate() and LangChain Runnable."""

    def __init__(
        self,
        model: str = DEFAULT_PROD_MODEL,
        gpu_memory_utilization: float = DEFAULT_PROD_GPU_UTIL,
        max_model_len: int = DEFAULT_LLM_MAX_LENGTH,
        tensor_parallel_size: int = 1,
        trust_remote_code: bool = True,
        dtype: str = "auto",
        quantization: str | None = DEFAULT_QUANTIZATION,
        reasoning_config: Any | None = None,
        default_temperature: float = 0.0,
        default_max_tokens: int = 4096,
        **kwargs: Any,
    ) -> None:
        """Initialize vLLM engine instance."""
        from vllm import LLM

        self.model_name = model
        self.gpu_memory_utilization = gpu_memory_utilization
        self.max_model_len = max_model_len
        self.tensor_parallel_size = tensor_parallel_size
        self.quantization = quantization
        self.reasoning_config = reasoning_config
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self._generate_lock = threading.Lock()

        llm_kwargs: dict[str, Any] = {
            "model": model,
            "gpu_memory_utilization": gpu_memory_utilization,
            "max_model_len": max_model_len,
            "tensor_parallel_size": tensor_parallel_size,
            "trust_remote_code": trust_remote_code,
            "dtype": dtype,
            "quantization": quantization,
            **kwargs,
        }
        if reasoning_config is not None:
            llm_kwargs["reasoning_config"] = reasoning_config

        self.llm = LLM(**llm_kwargs)

    def generate(
        self,
        prompts: list[str] | str,
        max_tokens: int = 512,
        temperature: float = 0.0,
        stop: list[str] | None = None,
        seed: int | None = None,
        thinking_token_budget: int | None = None,
        **kwargs: Any,
    ) -> list[str] | str:
        """Generate completions using vLLM continuous batching."""
        from vllm import SamplingParams

        is_single = isinstance(prompts, str)
        if is_single and not prompts:
            return ""
        prompt_list = [prompts] if is_single else prompts

        if not prompt_list:
            return []

        default_stop = ["<|im_end|>", "<|endoftext|>", "</output>", "\n</output>"]
        stop_tokens = list(set(default_stop + (stop or [])))

        sampling_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stop": stop_tokens,
            **kwargs,
        }
        if seed is not None:
            sampling_kwargs["seed"] = seed
        if thinking_token_budget is not None:
            sampling_kwargs["thinking_token_budget"] = thinking_token_budget

        sampling_params = SamplingParams(**sampling_kwargs)

        with self._generate_lock:
            outputs = self.llm.generate(prompt_list, sampling_params)
        results = [output.outputs[0].text.strip() for output in outputs]

        return results[0] if is_single else results

    def invoke(
        self,
        input: Any,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        """LangChain Runnable interface for CHESS chains and direct calls."""
        prompt_text = _coerce_prompt_text(input)
        max_tokens = int(
            kwargs.pop("max_tokens", None)
            or os.getenv("LLM_MAX_TOKENS")
            or self.default_max_tokens
        )
        temperature = float(kwargs.pop("temperature", self.default_temperature))
        raw = self.generate(
            prompt_text,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )
        text = raw if isinstance(raw, str) else (raw[0] if raw else "")
        return AIMessage(content=_strip_leading_think_block(text))


class MockLLMEngine:
    """Offline mock engine for tests without GPU or network access."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def generate(
        self,
        prompts: list[str] | str,
        max_tokens: int = 512,
        temperature: float = 0.0,
        stop: list[str] | None = None,
        seed: int | None = None,
        thinking_token_budget: int | None = None,
        **kwargs: Any,
    ) -> list[str] | str:
        is_single = isinstance(prompts, str)
        if is_single:
            return "SELECT 1" if prompts else ""
        return ["SELECT 1" if p else "" for p in prompts]

    def invoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> AIMessage:
        prompt_text = _coerce_prompt_text(input)
        return AIMessage(content=str(self.generate(prompt_text)))


def create_engine(
    model: str | None = None,
    gpu_memory_utilization: float | None = None,
    mock: bool = False,
    quantize: str | None = None,
    quantization: str | None = None,
    max_model_len: int = DEFAULT_LLM_MAX_LENGTH,
    **kwargs: Any,
) -> LLMEngineProtocol:
    """Factory creating the vLLM (or Mock) engine using centralized constants."""
    if mock:
        return MockLLMEngine(**kwargs)

    resolved_model = model or os.getenv("VLLM_MODEL") or DEFAULT_PROD_MODEL
    resolved_gpu_util = (
        gpu_memory_utilization
        if gpu_memory_utilization is not None
        else float(os.getenv("VLLM_GPU_MEMORY_UTILIZATION") or DEFAULT_PROD_GPU_UTIL)
    )
    resolved_quantization = quantize if quantize is not None else (quantization or DEFAULT_QUANTIZATION)

    return VLLMEngine(
        model=resolved_model,
        gpu_memory_utilization=resolved_gpu_util,
        max_model_len=max_model_len,
        quantization=resolved_quantization,
        **kwargs,
    )


def get_vllm_chain(temperature: float = 0.0) -> VLLMEngine:
    """Return a process-wide cached VLLMEngine Runnable configured from the environment."""
    model = os.getenv("VLLM_MODEL") or DEFAULT_PROD_MODEL
    gpu_util = float(os.getenv("VLLM_GPU_MEMORY_UTILIZATION") or DEFAULT_PROD_GPU_UTIL)
    max_len = int(os.getenv("VLLM_MAX_MODEL_LEN") or DEFAULT_LLM_MAX_LENGTH)
    quantization = os.getenv("VLLM_QUANTIZATION") or DEFAULT_QUANTIZATION
    cache_key = (model, gpu_util, max_len, quantization)

    with _ENGINE_CACHE_LOCK:
        engine = _VLLM_ENGINE_CACHE.get(cache_key)
        if engine is None:
            engine = VLLMEngine(
                model=model,
                gpu_memory_utilization=gpu_util,
                max_model_len=max_len,
                quantization=quantization,
                default_temperature=temperature,
                default_max_tokens=int(os.getenv("LLM_MAX_TOKENS") or 4096),
            )
            _VLLM_ENGINE_CACHE[cache_key] = engine
        return engine
