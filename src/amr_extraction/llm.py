"""LLM client interface for AMR extraction.

Provides a thin, swappable wrapper around Gemini Flash structured outputs.
This is the only module in the package that imports google.genai.
"""

import logging
import os
import time
from typing import TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-3.6-flash"  # gemini-2.5-flash was retired for new API keys as of
# Sept 2026 (Google's API returns a 404 naming gemini-3.6-flash as the replacement) — override
# with the GEMINI_MODEL env var if this needs to change again without editing code.

# HTTP status codes worth retrying: 429 (rate limit/quota — usually the free tier's per-minute
# request cap, not a hard quota exhaustion, so it clears after a short wait) and 503 (transient
# "model overloaded" on Google's end). Anything else (400, 404, etc.) is a real problem that a
# retry won't fix, so it's raised immediately.
_RETRYABLE_CODES = {429, 503}
_RETRY_DELAYS = [10, 20, 45, 90]  # seconds; exhausted after len(_RETRY_DELAYS) retries


def query_structured(
    prompt: str,
    response_schema: type[T],
    temperature: float = 0.0,
    model: str | None = None,
) -> T:
    """Send a prompt to Gemini Flash and return a parsed Pydantic object.

    Args:
        prompt: Text prompt with table preview and instructions.
        response_schema: Pydantic model class to constrain the output.
        temperature: Sampling temperature (default 0.0 for deterministic output).
        model: Model name override (defaults to GEMINI_MODEL env var or DEFAULT_MODEL above).

    Returns:
        Instance of response_schema parsed from Gemini structured JSON output.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY environment variable is not set. "
            "Please set GOOGLE_API_KEY before calling LLM functions."
        )

    target_model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    client = genai.Client(api_key=api_key)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        temperature=temperature,
    )

    start_time = time.perf_counter()
    attempt = 0
    while True:
        try:
            response = client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config,
            )
            break
        except genai_errors.APIError as e:
            code = getattr(e, "code", None)
            if code not in _RETRYABLE_CODES or attempt >= len(_RETRY_DELAYS):
                raise
            delay = _RETRY_DELAYS[attempt]
            attempt += 1
            logger.warning(
                "Gemini request hit %s (attempt %d/%d) — retrying in %ds: %s",
                code, attempt, len(_RETRY_DELAYS), delay, e,
            )
            time.sleep(delay)
    elapsed = time.perf_counter() - start_time

    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = getattr(usage, "prompt_token_count", "N/A") if usage else "N/A"
    output_tokens = getattr(usage, "candidates_token_count", "N/A") if usage else "N/A"

    logger.info(
        "LLM query completed in %.2fs. Model: %s, Schema: %s, Input tokens: %s, Output tokens: %s",
        elapsed,
        target_model,
        response_schema.__name__,
        prompt_tokens,
        output_tokens,
    )

    if response.parsed is None:
        raise ValueError(f"Failed to parse LLM response as {response_schema.__name__}: {response.text}")

    return response.parsed
