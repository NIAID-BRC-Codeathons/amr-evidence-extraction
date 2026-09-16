# Testing Guide

This document explains the testing architecture and instructions for running the test suite for the AMR evidence extraction module.

## Architecture and Test Strategy

The test suite follows a layered testing strategy:

1. **Unit Tests (Fast, Deterministic, No API Key Required)**:
   - Tests MIC string parsing (`parse_mic_string`) for all boundary patterns (operators, ratios, decimals, non-MIC strings).
   - Tests deterministic unpivoting and record construction (`extract_ast_records`) using pre-defined mock column mappings.
   - Compares extracted records against BV-BRC ground truth data for PMID 35651495.
   - Runs in less than 1 second without external network or LLM dependencies.

2. **Integration Tests (Live LLM via Gemini Flash)**:
   - Marked with `@pytest.mark.llm`.
   - Tests live worksheet classification (`classify_sheets`).
   - Tests live column mapping (`map_columns`).
   - Tests end-to-end extraction from raw Excel files (`extract_from_excel`).
   - Requires the `GOOGLE_API_KEY` environment variable.

---

## Environment Setup

Install the project in editable mode with development dependencies:

```bash
# Using uv (recommended)
uv venv
uv pip install -e ".[dev]"

# Or using standard pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Running Unit Tests (No LLM / No API Key)

To run all unit tests without calling the LLM:

```bash
pytest -m "not llm" -v
```

This runs all 27 unit tests and deselects the 3 LLM integration tests.

---

## Running Full Test Suite (Including Live LLM)

To run the complete suite, including live LLM integration tests:

1. Obtain a Gemini API key from [Google AI Studio](https://aistudio.google.com/).
2. Export your key in your shell:

```bash
export GOOGLE_API_KEY="your-gemini-api-key"
```

3. Run pytest:

```bash
pytest -v
```

You can also run only the LLM integration tests:

```bash
pytest -m "llm" -v
```

---

## Conspicuous Warning Banner for Skipped Tests

If you run `pytest` without setting `GOOGLE_API_KEY`, the 3 live LLM integration tests will automatically be skipped rather than failing, and pytest will output a conspicuous warning banner at the end of the test run:

```
+==============================================================================+
| WARNING: LIVE LLM INTEGRATION TESTS WERE SKIPPED                             |
|                                                                              |
| Live LLM integration tests require a Gemini API key.                         |
| Set the GOOGLE_API_KEY environment variable to run them:                     |
|                                                                              |
|     export GOOGLE_API_KEY="your-gemini-api-key"                              |
|     pytest -v                                                                |
|                                                                              |
| For detailed setup instructions, see:                                        |
| docs/amr_excel_extraction_testing.md                                         |
+==============================================================================+
```

This ensures you are immediately aware that live model behavior was not verified and can provide an API key to run the full verification.

---

## Test Files Reference

- [tests/conftest.py](file:///Users/aprasad/dev/amr-evidence-extraction/tests/conftest.py): Fixtures for starter data paths, mock column maps, and skip banner hooks.
- [tests/test_excel_extractor.py](file:///Users/aprasad/dev/amr-evidence-extraction/tests/test_excel_extractor.py): Test implementations for MIC parsing, record unpivoting, and LLM calls.
