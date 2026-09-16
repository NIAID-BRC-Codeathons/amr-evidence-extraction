"""Tests for extract_excel_codegen.py."""

import io
import pandas as pd
import pytest

from amr_extraction.extract_excel_codegen import (
    build_transformation_prompt,
    execute_generated_code,
    finalize_extracted_dataframe,
    EXPECTED_OUTPUT_COLUMNS,
)


def test_expected_output_columns_definition():
    """Verify standard schema column list and ordering."""
    assert EXPECTED_OUTPUT_COLUMNS == [
        "file_name",
        "sheet_name",
        "isolate_id",
        "accession",
        "drug",
        "mic_sign",
        "mic",
        "sir_call",
        "notes",
    ]


def test_build_transformation_prompt_requirements():
    """Verify prompt instructs LLM on column schema and extraction rules."""
    preview_df = pd.DataFrame({
        "Isolate": ["ISO-01"],
        "BioSample": ["SAMN12345678"],
        "Amikacin": ["<=0.5"],
    })
    prompt = build_transformation_prompt("Sheet1", preview_df)

    # Required column names in transform_sheet output
    for col in ["isolate_id", "accession", "drug", "mic_sign", "mic", "sir_call", "notes"]:
        assert col in prompt

    # Accession rule: no fallback to isolate_id
    assert "accession" in prompt
    assert "SAMN" in prompt or "BioSample" in prompt
    assert "fallback" in prompt.lower() or "leave blank" in prompt.lower()

    # Normalization of SIR
    assert "SDD" in prompt
    assert "NS" in prompt

    # Notes for inferred mic_sign '='
    assert "mic_sign '=' inferred" in prompt


def test_execute_generated_code_with_new_schema():
    """Test executing a valid transform function matching the new column schema."""
    code = """
import pandas as pd

def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in df.iterrows():
        raw_val = str(row["CIP"])
        if raw_val == "4":
            mic_sign = "="
            mic = "4"
            sir_call = None
            notes = "mic_sign '=' inferred"
        elif raw_val == "<=0.5":
            mic_sign = "<="
            mic = "0.5"
            sir_call = None
            notes = None
        else:
            mic_sign = None
            mic = None
            sir_call = "R"
            notes = None
        records.append({
            "isolate_id": row["Sample"],
            "accession": row.get("Accession", None),
            "drug": "Ciprofloxacin",
            "mic_sign": mic_sign,
            "mic": mic,
            "sir_call": sir_call,
            "notes": notes,
        })
    return pd.DataFrame(records)
"""
    input_df = pd.DataFrame({
        "Sample": ["S1", "S2", "S3"],
        "Accession": ["SAMN001", None, "SAMN003"],
        "CIP": ["4", "<=0.5", "Resistant"],
    })

    result_df = execute_generated_code(code, input_df)
    expected_inner_cols = ["isolate_id", "accession", "drug", "mic_sign", "mic", "sir_call", "notes"]
    assert list(result_df.columns) == expected_inner_cols
    assert result_df.loc[0, "notes"] == "mic_sign '=' inferred"
    assert result_df.loc[0, "mic_sign"] == "="
    assert result_df.loc[0, "mic"] == "4"


def test_finalize_extracted_dataframe_prepends_file_and_sheet():
    """Verify finalize_extracted_dataframe adds file_name and sheet_name in correct order."""
    inner_df = pd.DataFrame([{
        "isolate_id": "ISO-100",
        "accession": None,
        "drug": "Gentamicin",
        "mic_sign": "<=",
        "mic": "1",
        "sir_call": "S",
        "notes": None,
    }])

    final_df = finalize_extracted_dataframe(
        inner_df,
        file_path="/path/to/supplements/test_paper_s1.xlsx",
        sheet_name="Table S1",
    )

    assert list(final_df.columns) == EXPECTED_OUTPUT_COLUMNS
    assert final_df.loc[0, "file_name"] == "test_paper_s1.xlsx"
    assert final_df.loc[0, "sheet_name"] == "Table S1"
    assert final_df.loc[0, "isolate_id"] == "ISO-100"
    assert pd.isna(final_df.loc[0, "accession"]) or final_df.loc[0, "accession"] is None


def test_export_tsv_clean_blanks():
    """Verify writing final DataFrame to TSV produces clean empty fields without 'nan' or 'None'."""
    df = pd.DataFrame([{
        "file_name": "paper.xlsx",
        "sheet_name": "Sheet1",
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "Ampicillin",
        "mic_sign": "=",
        "mic": "8",
        "sir_call": None,
        "notes": "mic_sign '=' inferred",
    }])

    buf = io.StringIO()
    df.to_csv(buf, sep="\t", index=False, na_rep="")
    tsv_content = buf.getvalue()

    lines = tsv_content.strip().split("\n")
    header = lines[0].split("\t")
    row = lines[1].split("\t")

    assert header == EXPECTED_OUTPUT_COLUMNS
    accession_idx = header.index("accession")
    sir_call_idx = header.index("sir_call")

    assert row[accession_idx] == ""
    assert row[sir_call_idx] == ""
    assert "None" not in row
    assert "nan" not in row
    assert "NaN" not in row
