"""Unit tests for Argo support in extract_excel_codegen.py."""

from unittest.mock import MagicMock, patch
import httpx
import pandas as pd
import pytest

from amr_extraction.extract_excel_codegen import (
    build_cli_parser,
    classify_single_sheet,
    generate_transformation_code,
    get_llm_description,
    _generate_content_with_retry,
    ArgoClient,
    SheetSelection,
)


def test_cli_parser_argo_options():
    parser = build_cli_parser()
    args = parser.parse_args(["myfile.xlsx", "--llm-provider", "argo", "--model", "custom-argo", "--argo-user", "my_user"])
    assert args.llm_provider == "argo"
    assert args.model == "custom-argo"
    assert args.argo_user == "my_user"


def test_argo_client_init(monkeypatch):
    monkeypatch.delenv("ARGO_USER", raising=False)
    with pytest.raises(ValueError, match="ARGO_USER"):
        ArgoClient()

    monkeypatch.setenv("ARGO_USER", "ac.abprasad")
    monkeypatch.delenv("ARGO_MODEL", raising=False)
    client = ArgoClient()
    assert client.user == "ac.abprasad"
    assert client.model == "gpt56sol"

    # Changing ARGO_MODEL dynamically updates client.model when no explicit model was passed
    monkeypatch.setenv("ARGO_MODEL", "custom-model")
    assert client.model == "custom-model"

    # Explicit model argument overrides ARGO_MODEL
    client2 = ArgoClient(model="explicit-model")
    assert client2.model == "explicit-model"


def test_classify_single_sheet_with_argo(monkeypatch):
    monkeypatch.setenv("ARGO_USER", "ac.abprasad")
    monkeypatch.delenv("ARGO_MODEL", raising=False)
    client = ArgoClient()

    df = pd.DataFrame({
        "Isolate": ["ISO1", "ISO2"],
        "Amikacin": ["<=0.5", ">64"],
    })
    token_tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        '```json\n'
                        '{\n'
                        '  "sheet_name": "Table_1",\n'
                        '  "contains_ast_data": true,\n'
                        '  "has_mic_values": true,\n'
                        '  "has_sir_calls": false,\n'
                        '  "reasoning": "Contains isolate rows with Amikacin MIC concentrations."\n'
                        '}\n'
                        '```'
                    )
                }
            }
        ],
        "usage": {
            "prompt_tokens": 150,
            "completion_tokens": 35,
        },
    }

    with patch("httpx.Client.post", return_value=fake_response) as mock_post:
        result = classify_single_sheet(
            sheet_name="Table_1",
            preview_df=df,
            client=client,
            token_tracker=token_tracker,
        )

        assert isinstance(result, SheetSelection)
        assert result.sheet_name == "Table_1"
        assert result.contains_ast_data is True
        assert result.has_mic_values is True
        assert result.has_sir_calls is False
        assert token_tracker["calls"] == 1
        assert token_tracker["input_tokens"] == 150
        assert token_tracker["output_tokens"] == 35

        assert mock_post.called
        kwargs = mock_post.call_args[1]
        assert kwargs["headers"]["Authorization"] == "Bearer ac.abprasad"
        assert kwargs["json"]["model"] == "gpt56sol"
        assert "temperature" not in kwargs["json"]


def test_generate_transformation_code_with_argo(monkeypatch):
    monkeypatch.setenv("ARGO_USER", "ac.abprasad")
    monkeypatch.delenv("ARGO_MODEL", raising=False)
    client = ArgoClient()

    df = pd.DataFrame({
        "Isolate": ["ISO1"],
        "Amikacin": ["<=0.5"],
    })
    token_tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    generated_py = (
        "import pandas as pd\n"
        "def transform_sheet(df):\n"
        "    return pd.DataFrame()\n"
    )

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": f"```python\n{generated_py}```"
                }
            }
        ],
        "usage": {
            "prompt_tokens": 200,
            "completion_tokens": 40,
        },
    }

    with patch("httpx.Client.post", return_value=fake_response):
        code = generate_transformation_code(
            sheet_name="Table_1",
            preview_df=df,
            client=client,
            token_tracker=token_tracker,
        )

        assert "def transform_sheet(df):" in code
        assert token_tracker["calls"] == 1
        assert token_tracker["input_tokens"] == 200
        assert token_tracker["output_tokens"] == 40


def test_classify_single_sheet_with_argo_claude_streaming(monkeypatch):
    monkeypatch.setenv("ARGO_USER", "ac.abprasad")
    monkeypatch.setenv("ARGO_MODEL", "claudesonnet5")
    client = ArgoClient()

    df = pd.DataFrame({"Isolate": ["ISO1"], "Amikacin": ["<=0.5"]})
    token_tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    sse_lines = [
        'data: {"choices": [{"delta": {"content": "```json\\n{\\"sheet_name\\": \\"Table_1\\", \\"contains_ast_data\\": true, \\"has_mic_values\\": true, \\"has_sir_calls\\": false, \\"reasoning\\": \\"ok\\"}\\n```"}}]}',
        'data: {"usage": {"prompt_tokens": 120, "completion_tokens": 30}}',
        'data: [DONE]',
    ]

    mock_stream_ctx = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = sse_lines
    mock_stream_ctx.__enter__.return_value = mock_resp
    mock_stream_ctx.__exit__.return_value = None

    with patch("httpx.Client.stream", return_value=mock_stream_ctx) as mock_stream:
        result = classify_single_sheet("Table_1", df, client, token_tracker)
        assert result.contains_ast_data is True
        assert token_tracker["input_tokens"] == 120
        assert mock_stream.called
        kwargs = mock_stream.call_args[1]
        assert kwargs["json"]["stream"] is True
        assert "temperature" not in kwargs["json"]


def test_get_llm_description(monkeypatch):
    monkeypatch.setenv("ARGO_USER", "ac.abprasad")
    monkeypatch.delenv("ARGO_MODEL", raising=False)

    # Argo default model
    argo_client = ArgoClient()
    assert get_llm_description(argo_client) == "Argo (gpt56sol)"

    # Argo custom model
    argo_custom = ArgoClient(model="claudesonnet5")
    assert get_llm_description(argo_custom) == "Argo (claudesonnet5)"

    # Gemini default client without GEMINI_MODEL
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    gemini_client = MagicMock()
    gemini_client.provider = None
    del gemini_client.model
    assert get_llm_description(gemini_client) == "Gemini (gemini-3.8-flash)"

    # Gemini with GEMINI_MODEL env var
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    assert get_llm_description(gemini_client) == "Gemini (gemini-2.5-pro)"

    # Gemini with custom model on client overrides GEMINI_MODEL env var
    gemini_custom = MagicMock()
    gemini_custom.provider = None
    gemini_custom.model = "models/custom-model"
    assert get_llm_description(gemini_custom) == "Gemini (custom-model)"


def test_generate_content_with_retry_gemini_model_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "custom-env-model")
    gemini_client = MagicMock()
    gemini_client.provider = None
    del gemini_client.model
    gemini_client.models.generate_content.return_value = MagicMock(text="ok")

    _generate_content_with_retry(gemini_client, model="", contents="hello", config=None)
    assert gemini_client.models.generate_content.called
    kwargs = gemini_client.models.generate_content.call_args[1]
    assert kwargs["model"] == "custom-env-model"


def test_status_message_dynamic_provider(monkeypatch, capsys):
    monkeypatch.setenv("ARGO_USER", "ac.abprasad")
    client = ArgoClient(model="claudesonnet5")

    df = pd.DataFrame({"Isolate": ["ISO1"], "Amikacin": ["<=0.5"]})
    token_tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = [
        'data: {"choices": [{"delta": {"content": "```python\\ndef transform_sheet(df):\\n    return df\\n```"}}]}',
        'data: [DONE]',
    ]
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__.return_value = mock_resp
    mock_stream_ctx.__exit__.return_value = None

    with patch("httpx.Client.stream", return_value=mock_stream_ctx):
        generate_transformation_code("Table_1", df, client, token_tracker)

    captured = capsys.readouterr()
    assert "Requesting transformation code for sheet 'Table_1' from Argo (claudesonnet5)" in captured.out


