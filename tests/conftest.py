"""Shared pytest fixtures and hooks for AMR evidence extraction tests."""

import os
from pathlib import Path
import re
import pandas as pd
import pytest

# Automatically load environment variables from .env if present
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        _line = re.sub(r"^export\s+", "", _line)
        if "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ[_k.strip()] = _v.strip("\"'")

from amr_extraction.schemas import (
    ColumnMapping,
    ColumnRole,
    SheetColumnMap,
)

BASE_DIR = Path(__file__).resolve().parent.parent
STARTER_DATA_DIR = BASE_DIR / "data" / "starter"


@pytest.fixture
def starter_data_dir() -> Path:
    """Path to the starter data directory."""
    return STARTER_DATA_DIR


@pytest.fixture
def pmid_35651495_excel() -> Path:
    """Path to Table_3.XLSX for PMID 35651495."""
    path = STARTER_DATA_DIR / "35651495" / "supplements" / "Table_3.XLSX"
    if not path.exists():
        pytest.fail(f"Test data file not found: {path}")
    return path


@pytest.fixture
def pmid_35651495_ground_truth() -> pd.DataFrame:
    """Ground truth DataFrame for PMID 35651495 from BV-BRC."""
    path = STARTER_DATA_DIR / "35651495" / "ground_truth_bvbrc.tsv"
    if not path.exists():
        pytest.fail(f"Ground truth file not found: {path}")
    return pd.read_csv(path, sep="\t")


@pytest.fixture
def mock_column_map_35651495() -> SheetColumnMap:
    """Mock SheetColumnMap for Table_3.XLSX of PMID 35651495."""
    drug_pairs = [
        ("AMP", "Unnamed: 14", "ampicillin"),
        ("CAZ", "Unnamed: 16", "ceftazidime"),
        ("AMS", "Unnamed: 18", "ampicillin-sulbactam"),
        ("CFX", "Unnamed: 20", "cefuroxime"),
        ("CTX", "Unnamed: 22", "cefotaxime"),
        ("CFZ", "Unnamed: 24", "cefazolin"),
        ("IMP", "Unnamed: 26", "imipenem"),
        ("TET", "Unnamed: 28", "tetracycline"),
        ("NAL", "Unnamed: 30", "nalidixic acid"),
        ("CIP", "Unnamed: 32", "ciprofloxacin"),
        ("AZM", "Unnamed: 34", "azithromycin"),
        ("CHL", "Unnamed: 36", "chloramphenicol"),
        ("GEN", "Unnamed: 38", "gentamicin"),
        ("SXT", "Unnamed: 40", "trimethoprim-sulfamethoxazole"),
    ]

    columns = [
        ColumnMapping(column_name="Specimen number", role=ColumnRole.METADATA),
        ColumnMapping(column_name="Accession number", role=ColumnRole.PUBLIC_ACCESSION),
        ColumnMapping(column_name="Sequencing number", role=ColumnRole.LOCAL_ID),
        ColumnMapping(column_name="Gender", role=ColumnRole.METADATA),
        ColumnMapping(column_name="Age(moonths)", role=ColumnRole.METADATA),
        ColumnMapping(column_name="Whether in the hospital", role=ColumnRole.METADATA),
        ColumnMapping(column_name="Symptom", role=ColumnRole.METADATA),
        ColumnMapping(column_name="Specimen type", role=ColumnRole.METADATA),
        ColumnMapping(column_name="Suspected exposed food", role=ColumnRole.METADATA),
        ColumnMapping(column_name="Unnamed: 9", role=ColumnRole.METADATA),
        ColumnMapping(column_name="Unnamed: 10", role=ColumnRole.METADATA),
        ColumnMapping(
            column_name="Predicted serotype after confirmation by serum agglutination",
            role=ColumnRole.METADATA,
        ),
        ColumnMapping(column_name="Year", role=ColumnRole.METADATA),
    ]

    for mic_col, sir_col, drug_name in drug_pairs:
        columns.append(
            ColumnMapping(
                column_name=mic_col,
                role=ColumnRole.DRUG_MIC,
                drug_name=drug_name,
                paired_with=sir_col,
            )
        )
        columns.append(
            ColumnMapping(
                column_name=sir_col,
                role=ColumnRole.DRUG_SIR,
                drug_name=drug_name,
                paired_with=mic_col,
            )
        )

    columns.append(ColumnMapping(column_name="MDR", role=ColumnRole.METADATA))

    return SheetColumnMap(
        sheet_name="Sheet1",
        columns=columns,
        header_row_index=0,
        reasoning="Sheet1 has 14 paired drug columns (MIC and SIR) with BioSample accession in column 1 and sequencing number in column 2.",
    )


def pytest_collection_modifyitems(config, items):
    """Automatically skip tests marked with 'llm' if GOOGLE_API_KEY is not set."""
    has_api_key = bool(os.environ.get("GOOGLE_API_KEY"))
    if not has_api_key:
        skip_llm = pytest.mark.skip(
            reason="GOOGLE_API_KEY is not set. Set GOOGLE_API_KEY to run live LLM integration tests."
        )
        for item in items:
            if "llm" in item.keywords:
                item.add_marker(skip_llm)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Display a conspicuous banner if live LLM integration tests were skipped."""
    skipped_tests = terminalreporter.stats.get("skipped", [])
    llm_skipped = any(
        "GOOGLE_API_KEY" in getattr(rep, "longreprtext", "")
        or "llm" in getattr(rep, "keywords", {})
        for rep in skipped_tests
    )

    # Also check if markexpr excluded llm
    markexpr = config.option.markexpr or ""
    excluded_llm = "not llm" in markexpr or "llm" not in markexpr and not os.environ.get("GOOGLE_API_KEY")

    if llm_skipped or (not os.environ.get("GOOGLE_API_KEY") and len(skipped_tests) > 0):
        banner = [
            "",
            "+==============================================================================+",
            "| WARNING: LIVE LLM INTEGRATION TESTS WERE SKIPPED                             |",
            "|                                                                              |",
            "| Live LLM integration tests require a Gemini API key.                         |",
            "| Set the GOOGLE_API_KEY environment variable to run them:                     |",
            "|                                                                              |",
            "|     export GOOGLE_API_KEY=\"your-gemini-api-key\"                              |",
            "|     pytest -v                                                                |",
            "|                                                                              |",
            "| For detailed setup instructions, see:                                        |",
            "| docs/amr_excel_extraction_testing.md                                         |",
            "+==============================================================================+",
            "",
        ]
        terminalreporter.write_line("\n".join(banner))
