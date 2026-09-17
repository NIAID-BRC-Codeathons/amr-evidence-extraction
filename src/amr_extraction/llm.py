"""LLM client interface for AMR extraction.

Provides a thin, swappable wrapper around structured-output LLM calls. Two backends are
supported, selected via LLM_PROVIDER (or --llm-provider on find_ast_evidence.py):

  gemini (default) - Google's Gemini API. Requires GOOGLE_API_KEY. This is the only provider
                      google.genai is imported for.
  ollama            - a locally-running Ollama daemon (https://ollama.com). No API key or network
                      egress needed, but you must have `ollama serve` running and the target model
                      pulled first (`ollama pull <model>`, or `ollama pull hf.co/<user>/<repo>` for
                      a Hugging Face GGUF model). Requires the `ollama` pip package.

Both backends expose the same query_structured(prompt, response_schema, ...) -> BaseModel
signature, so callers (e.g. excel_extractor.py) don't need to know which one is active.
"""

import json
import logging
import os
from pathlib import Path
import re
import time
from typing import TypeVar

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

_RETRYABLE_CODES = {429, 503}
_RETRY_DELAYS = [10, 20, 45, 90]  # seconds; exhausted after len(_RETRY_DELAYS) retries
DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
_VALID_PROVIDERS = {"gemini", "ollama"}


class DailyQuotaExhausted(RuntimeError):
    """Raised instead of retrying when a 429 is Gemini's free-tier *daily* request quota
    (e.g. GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit 20/day) rather than the
    ordinary per-minute rate limit. No amount of backoff fixes this until the quota resets, so
    retrying it is pure wasted time — callers should stop making further Gemini calls for the
    rest of the run instead of hitting this on every remaining file. Gemini-specific: the Ollama
    backend runs locally and has no daily quota, so it never raises this."""


def _is_daily_quota_error(e) -> bool:
    """Google's 429 response distinguishes a burst-rate 429 from a hard daily-quota 429 via the
    `quotaId` in its structured error details (e.g. "...PerDayPerProjectPerModel-FreeTier" vs.
    "...PerMinutePerProjectPerModel..."). The top-level message text and its suggested
    `retryDelay` look the same either way (both can say "retry in 23s"), so `quotaId` is the only
    reliable signal — check it rather than trusting retryDelay."""
    try:
        return "PerDay" in json.dumps(e.details)
    except Exception:
        return "PerDay" in str(e)


def query_structured(
    prompt: str,
    response_schema: type[T],
    temperature: float = 0.0,
    model: str | None = None,
    provider: str | None = None,
) -> T:
    """Send a prompt to the configured LLM backend and return a parsed Pydantic object.

    Args:
        prompt: Text prompt with table preview and instructions.
        response_schema: Pydantic model class to constrain the output.
        temperature: Sampling temperature (default 0.0 for deterministic output).
        model: Model name override. Defaults to GEMINI_MODEL/OLLAMA_MODEL env var (whichever
            matches the active provider), or that provider's own default.
        provider: "gemini" or "ollama". Defaults to the LLM_PROVIDER env var, or "gemini" if unset.

    Returns:
        Instance of response_schema parsed from the LLM's structured JSON output.
    """
    target_provider = (provider or os.environ.get("LLM_PROVIDER", "gemini")).strip().lower()
    if target_provider not in _VALID_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider {target_provider!r} (from --llm-provider / LLM_PROVIDER). "
            f"Expected one of: {sorted(_VALID_PROVIDERS)}"
        )

    if target_provider == "ollama":
        return _query_structured_ollama(prompt, response_schema, temperature, model)
    return _query_structured_gemini(prompt, response_schema, temperature, model)


def _query_structured_gemini(
    prompt: str,
    response_schema: type[T],
    temperature: float = 0.0,
    model: str | None = None,
) -> T:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY environment variable is not set. "
            "Please set GOOGLE_API_KEY before calling LLM functions, or switch to the Ollama "
            "backend with --llm-provider ollama / LLM_PROVIDER=ollama."
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
            if code == 429 and _is_daily_quota_error(e):
                raise DailyQuotaExhausted(
                    f"Gemini's free-tier DAILY request quota for model {target_model!r} is "
                    f"exhausted (not a per-minute limit — retrying won't help until it resets, "
                    f"usually ~24h from when the quota window started): {e}"
                ) from e
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
        "LLM query completed in %.2fs. Provider: gemini, Model: %s, Schema: %s, Input tokens: %s, Output tokens: %s",
        elapsed,
        target_model,
        response_schema.__name__,
        prompt_tokens,
        output_tokens,
    )

    if response.parsed is None:
        raise ValueError(f"Failed to parse LLM response as {response_schema.__name__}: {response.text}")

    return response.parsed


def _query_structured_ollama(
    prompt: str,
    response_schema: type[T],
    temperature: float = 0.0,
    model: str | None = None,
) -> T:
    try:
        import ollama
    except ImportError as e:
        raise ImportError(
            "LLM_PROVIDER=ollama (or --llm-provider ollama) was selected, but the 'ollama' pip "
            "package isn't installed. Install it with: pip install ollama\n"
            "Also make sure the Ollama app/daemon is actually running (`ollama serve`, or just "
            "open the Ollama app) and the model is pulled, e.g.: ollama pull llama3.1:8b "
            "(or ollama pull hf.co/<user>/<repo> for a Hugging Face GGUF model)."
        ) from e

    target_model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    host = os.environ.get("OLLAMA_HOST")  # falls back to ollama's own default (http://localhost:11434)
    client = ollama.Client(host=host) if host else ollama.Client()

    start_time = time.perf_counter()
    try:
        response = client.chat(
            model=target_model,
            messages=[{"role": "user", "content": prompt}],
            format=response_schema.model_json_schema(),
            options={"temperature": temperature},
        )
    except Exception as e:  # noqa: BLE001 - ollama raises its own ResponseError/ConnectionError types
        raise RuntimeError(
            f"Ollama request failed (model={target_model!r}). Make sure `ollama serve` is running "
            f"locally and the model has been pulled (`ollama pull {target_model}`): {e}"
        ) from e
    elapsed = time.perf_counter() - start_time

    content = response["message"]["content"]
    try:
        parsed = response_schema.model_validate_json(content)
    except Exception as e:
        raise ValueError(f"Failed to parse Ollama response as {response_schema.__name__}: {content}") from e

    logger.info(
        "LLM query completed in %.2fs. Provider: ollama, Model: %s, Schema: %s",
        elapsed,
        target_model,
        response_schema.__name__,
    )

    return parsed
