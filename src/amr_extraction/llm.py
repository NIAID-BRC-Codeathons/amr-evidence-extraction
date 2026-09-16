"""LLM client interface for AMR extraction.

Provides a thin, swappable wrapper around Gemini Flash structured outputs.
This is the only module in the package that imports google.genai.
"""

import logging
import os
from pathlib import Path
import re
import time
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

# Automatically load .env if present and GOOGLE_API_KEY is not yet in os.environ
if not os.environ.get("GOOGLE_API_KEY"):
    for env_candidate in [Path(".env"), Path(__file__).resolve().parent.parent.parent / ".env"]:
        if env_candidate.exists():
            for _line in env_candidate.read_text().splitlines():
                _line = _line.strip()
                if not _line or _line.startswith("#"):
                    continue
                _line = re.sub(r"^export\s+", "", _line)
                if "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip("\"'"))
            break

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-3.6-flash"


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
        model: Model name override (defaults to GEMINI_MODEL env var or gemini-2.5-flash).

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
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    start_time = time.perf_counter()
    response = client.models.generate_content(
        model=target_model,
        contents=prompt,
        config=config,
    )
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
