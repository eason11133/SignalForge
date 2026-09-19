"""Shared OpenAI async client with retry logic and token tracking."""

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import structlog
from dotenv import load_dotenv
from openai import AsyncOpenAI, APITimeoutError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from spending_tracker import PRICING, is_over_budget, record_spend

load_dotenv()

logger = structlog.get_logger()

_client: AsyncOpenAI | None = None


@dataclass
class TokenUsage:
    """Accumulates token usage across multiple LLM calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.calls += 1

    @property
    def estimated_cost_usd(self) -> float:
        """Rough estimate based on gpt-4o-mini pricing."""
        input_cost = (self.prompt_tokens / 1_000_000) * 0.15
        output_cost = (self.completion_tokens / 1_000_000) * 0.60
        return input_cost + output_cost


def get_client() -> AsyncOpenAI:
    """Lazy singleton for the standard OpenAI async client."""
    global _client

    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set in .env")

        _client = AsyncOpenAI(api_key=api_key)

    return _client


def _get_model(model: str) -> str:
    """Map the repo's model aliases to standard OpenAI model names."""
    if model == "mini":
        return os.getenv("OPENAI_MODEL_MINI", "gpt-4o-mini")

    return os.getenv("OPENAI_MODEL", "gpt-4o")


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers from LLM output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type((RateLimitError, APITimeoutError)),
)
async def call_llm(
    prompt: str,
    system_message: str = "You are a helpful assistant.",
    model: str = "default",
    temperature: float = 0.3,
    max_tokens: int = 2000,
    parse_json: bool = False,
    usage_tracker: TokenUsage | None = None,
) -> str | dict[str, Any]:
    """
    Call standard OpenAI with retry logic.

    model="default" -> OPENAI_MODEL, default gpt-4o
    model="mini"    -> OPENAI_MODEL_MINI, default gpt-4o-mini
    parse_json=True -> strips markdown fences, parses JSON, returns dict
    """
    if is_over_budget():
        raise RuntimeError("LLM spending cap reached — refusing new LLM calls")

    client = get_client()
    model_name = _get_model(model)

    response = await client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if response.usage and usage_tracker is not None:
        usage_tracker.add(
            prompt=response.usage.prompt_tokens,
            completion=response.usage.completion_tokens,
        )

    if response.usage:
        pricing_key = "gpt-4o-mini" if model == "mini" else "gpt-4o"
        prices = PRICING.get(pricing_key, PRICING["gpt-4o-mini"])
        cost = (
            (response.usage.prompt_tokens / 1_000_000) * prices["input"]
            + (response.usage.completion_tokens / 1_000_000) * prices["output"]
        )
        record_spend(
            phase=f"llm:{model_name}",
            cost_usd=cost,
            details=(
                f"{response.usage.prompt_tokens}in+"
                f"{response.usage.completion_tokens}out"
            ),
        )

    content = response.choices[0].message.content or ""

    if parse_json:
        cleaned = _strip_json_fences(content)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(
                "json_parse_failed",
                error=str(exc),
                raw_content=content[:500],
            )
            raise

    return content
