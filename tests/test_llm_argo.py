"""Unit tests for the Argo provider in amr_extraction.llm."""

import json
from unittest.mock import MagicMock, patch
import httpx
from pydantic import BaseModel
import pytest

from amr_extraction.llm import query_structured, _VALID_PROVIDERS


class SampleSchema(BaseModel):
    name: str
    count: int


def test_argo_in_valid_providers():
    assert "argo" in _VALID_PROVIDERS


def test_query_structured_argo_missing_user(monkeypatch):
    monkeypatch.delenv("ARGO_USER", raising=False)
    with pytest.raises(ValueError, match="ARGO_USER"):
        query_structured("test prompt", SampleSchema, provider="argo")


def test_query_structured_argo_success_raw_json(monkeypatch):
    monkeypatch.setenv("ARGO_USER", "test_user")
    monkeypatch.delenv("ARGO_MODEL", raising=False)

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [
            {"message": {"content": '{"name": "test_item", "count": 42}'}}
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        },
    }

    with patch("httpx.Client.post", return_value=fake_response) as mock_post:
        result = query_structured("Identify items", SampleSchema, provider="argo")

        assert isinstance(result, SampleSchema)
        assert result.name == "test_item"
        assert result.count == 42

        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer test_user"
        json_payload = kwargs["json"]
        assert json_payload["model"] == "gpt56sol"
        # temperature should be omitted for gpt56sol
        assert "temperature" not in json_payload
        # Schema instructions should be in prompt
        assert "SampleSchema" in json_payload["messages"][0]["content"] or "count" in json_payload["messages"][0]["content"]


def test_query_structured_argo_success_markdown_wrapped_json(monkeypatch):
    monkeypatch.setenv("ARGO_USER", "test_user")
    monkeypatch.delenv("ARGO_MODEL", raising=False)

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [
            {"message": {"content": '```json\n{"name": "wrapped", "count": 7}\n```'}}
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 15},
    }

    with patch("httpx.Client.post", return_value=fake_response):
        result = query_structured("Identify items", SampleSchema, provider="argo")
        assert result.name == "wrapped"
        assert result.count == 7


def test_query_structured_argo_model_override(monkeypatch):
    monkeypatch.setenv("ARGO_USER", "test_user")
    monkeypatch.setenv("ARGO_MODEL", "custom-argo-model")

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"name": "custom", "count": 1}'}}],
    }

    with patch("httpx.Client.post", return_value=fake_response) as mock_post:
        # ARGO_MODEL env var
        query_structured("test", SampleSchema, provider="argo")
        assert mock_post.call_args[1]["json"]["model"] == "custom-argo-model"
        # Since custom-argo-model doesn't start with gpt56sol/o1/o3/claude, temperature should be included
        assert "temperature" in mock_post.call_args[1]["json"]

        # Explicit model parameter overrides ARGO_MODEL
        query_structured("test", SampleSchema, provider="argo", model="param-model")
        assert mock_post.call_args[1]["json"]["model"] == "param-model"


def test_query_structured_argo_retry_on_429(monkeypatch):
    monkeypatch.setenv("ARGO_USER", "test_user")
    monkeypatch.delenv("ARGO_MODEL", raising=False)

    error_response = MagicMock(spec=httpx.Response)
    error_response.status_code = 429
    error_response.text = "Rate limit exceeded"

    success_response = MagicMock(spec=httpx.Response)
    success_response.status_code = 200
    success_response.json.return_value = {
        "choices": [{"message": {"content": '{"name": "after_retry", "count": 99}'}}],
    }

    with patch("httpx.Client.post", side_effect=[error_response, success_response]), \
         patch("time.sleep", return_value=None):
        result = query_structured("retry test", SampleSchema, provider="argo")
        assert result.name == "after_retry"
        assert result.count == 99


def test_query_structured_argo_claude_streaming(monkeypatch):
    monkeypatch.setenv("ARGO_USER", "test_user")
    monkeypatch.setenv("ARGO_MODEL", "claudesonnet5")

    sse_lines = [
        'data: {"choices": [{"delta": {"content": "```json\\n{\\"name\\": \\"claude_item\\", \\"count\\": 88}\\n```"}}]}',
        'data: {"usage": {"prompt_tokens": 100, "completion_tokens": 25}}',
        'data: [DONE]',
    ]

    mock_stream_ctx = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = sse_lines
    mock_stream_ctx.__enter__.return_value = mock_resp
    mock_stream_ctx.__exit__.return_value = None

    with patch("httpx.Client.stream", return_value=mock_stream_ctx) as mock_stream:
        result = query_structured("Test prompt", SampleSchema, provider="argo")
        assert result.name == "claude_item"
        assert result.count == 88
        assert mock_stream.called
        kwargs = mock_stream.call_args[1]
        assert kwargs["json"]["stream"] is True
        assert "temperature" not in kwargs["json"]

