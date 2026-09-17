import io
from unittest.mock import MagicMock
import pandas as pd
import pytest

from amr_extraction.extract_excel_codegen import (
    build_transformation_prompt,
    build_metadata_transformation_prompt,
    classify_single_sheet,
    enrich_ast_with_metadata,
    execute_generated_code,
    finalize_extracted_dataframe,
    generate_transformation_code,
    is_biosample_accession,
    is_candidate_metadata_sheet,
    needs_accession_enrichment,
    validate_extracted_records,
    EXPECTED_OUTPUT_COLUMNS,
    SheetSelection,
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


def test_build_transformation_prompt_with_retry_errors():
    """Verify retry prompt embeds previous error details and correction instructions."""
    preview_df = pd.DataFrame({
        "Isolate": ["ISO-01"],
        "Amikacin": ["<=0.5"],
    })
    previous_errors = [
        "Row 1: invalid mic_sign '~'",
        "Row 2: non-numeric mic 'resistant'",
    ]
    prompt = build_transformation_prompt("Sheet1", preview_df, previous_errors=previous_errors)

    assert "ATTEMPT 1 FAILED QC CHECKS" in prompt
    assert "Row 1: invalid mic_sign '~'" in prompt
    assert "Row 2: non-numeric mic 'resistant'" in prompt
    assert "fix" in prompt.lower()


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


# ==============================================================================
# QC Validation Tests
# ==============================================================================

def test_validate_extracted_records_valid_cases():
    """Verify validator accepts valid numeric MICs, ratios, and SIR-only records."""
    df = pd.DataFrame([
        # Standard numeric MIC
        {"isolate_id": "ISO-1", "accession": None, "drug": "Ampicillin", "mic_sign": "=", "mic": "4", "sir_call": None},
        # Combination ratio MIC
        {"isolate_id": "ISO-2", "accession": None, "drug": "Trimethoprim/Sulfamethoxazole", "mic_sign": "<=", "mic": "32/16", "sir_call": None},
        # SIR-only record (blank mic and mic_sign permitted)
        {"isolate_id": "ISO-3", "accession": None, "drug": "Ciprofloxacin", "mic_sign": None, "mic": None, "sir_call": "R"},
        # Accession-only identifier (blank isolate_id permitted)
        {"isolate_id": None, "accession": "SAMN12345678", "drug": "Meropenem", "mic_sign": ">=", "mic": "8", "sir_call": "R"},
    ])

    valid_df, invalid_df, errors = validate_extracted_records(df)
    assert len(valid_df) == 4
    assert len(invalid_df) == 0
    assert len(errors) == 0


def test_validate_extracted_records_invalid_mic_sign():
    """Verify validator rejects invalid mic_sign symbols."""
    df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": None, "drug": "Ampicillin", "mic_sign": "~", "mic": "4", "sir_call": None},
        {"isolate_id": "ISO-2", "accession": None, "drug": "Ampicillin", "mic_sign": "!=", "mic": "4", "sir_call": None},
    ])

    valid_df, invalid_df, errors = validate_extracted_records(df)
    assert len(valid_df) == 0
    assert len(invalid_df) == 2
    assert any("mic_sign" in err for err in errors)


def test_validate_extracted_records_invalid_mic_format():
    """Verify validator rejects non-numeric mic values."""
    df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": None, "drug": "Ampicillin", "mic_sign": "=", "mic": "resistant", "sir_call": None},
        {"isolate_id": "ISO-2", "accession": None, "drug": "Ampicillin", "mic_sign": "=", "mic": "4mg/L", "sir_call": None},
        {"isolate_id": "ISO-3", "accession": None, "drug": "Ampicillin", "mic_sign": "=", "mic": "ND", "sir_call": None},
    ])

    valid_df, invalid_df, errors = validate_extracted_records(df)
    assert len(valid_df) == 0
    assert len(invalid_df) == 3
    assert any("mic" in err for err in errors)


def test_validate_extracted_records_missing_both_mic_and_sir():
    """Verify validator rejects rows where both mic (and mic_sign) and sir_call are missing."""
    df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": None, "drug": "Ampicillin", "mic_sign": None, "mic": None, "sir_call": None},
    ])

    valid_df, invalid_df, errors = validate_extracted_records(df)
    assert len(valid_df) == 0
    assert len(invalid_df) == 1
    assert any("sir_call" in err or "mic" in err for err in errors)


def test_validate_extracted_records_missing_identifiers():
    """Verify validator rejects rows where both isolate_id and accession are blank."""
    df = pd.DataFrame([
        {"isolate_id": None, "accession": None, "drug": "Ampicillin", "mic_sign": "=", "mic": "4", "sir_call": None},
        {"isolate_id": "", "accession": "", "drug": "Ampicillin", "mic_sign": "=", "mic": "4", "sir_call": None},
    ])

    valid_df, invalid_df, errors = validate_extracted_records(df)
    assert len(valid_df) == 0
    assert len(invalid_df) == 2
    assert any("identifier" in err.lower() for err in errors)


def test_validate_extracted_records_missing_drug():
    """Verify validator rejects rows where drug is blank."""
    df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": None, "drug": None, "mic_sign": "=", "mic": "4", "sir_call": None},
        {"isolate_id": "ISO-2", "accession": None, "drug": "   ", "mic_sign": "=", "mic": "4", "sir_call": None},
    ])

    valid_df, invalid_df, errors = validate_extracted_records(df)
    assert len(valid_df) == 0
    assert len(invalid_df) == 2
    assert any("drug" in err.lower() for err in errors)


def test_validate_extracted_records_invalid_sir_call():
    """Verify validator rejects unnormalized or invalid sir_call values."""
    df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": None, "drug": "Ampicillin", "mic_sign": None, "mic": None, "sir_call": "Susceptible"},
        {"isolate_id": "ISO-2", "accession": None, "drug": "Ampicillin", "mic_sign": None, "mic": None, "sir_call": "INVALID"},
    ])

    valid_df, invalid_df, errors = validate_extracted_records(df)
    assert len(valid_df) == 0
    assert len(invalid_df) == 2
    assert any("sir_call" in err for err in errors)


def test_afc_disabled_in_codegen_calls():
    """Verify automatic function calling is explicitly disabled on Gemini calls to prevent AFC warnings."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.usage_metadata = None
    mock_response.parsed = SheetSelection(
        sheet_name="Test",
        contains_ast_data=True,
        has_mic_values=True,
        has_sir_calls=False,
        reasoning="test",
    )
    mock_response.text = "```python\ndef transform_sheet(df):\n    return df\n```"
    mock_client.models.generate_content.return_value = mock_response

    token_tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    df = pd.DataFrame({"col": [1]})

    # 1. classify_single_sheet
    classify_single_sheet("Test", df, mock_client, token_tracker)
    _, kwargs = mock_client.models.generate_content.call_args
    config = kwargs.get("config")
    assert config is not None
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True

    # 2. generate_transformation_code
    generate_transformation_code("Test", df, mock_client, token_tracker)
    _, kwargs = mock_client.models.generate_content.call_args
    config = kwargs.get("config")
    assert config is not None
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True


def test_discover_relevant_sheets_detects_header_row(monkeypatch):
    """Verify discover_relevant_sheets detects banner/title rows and sets proper header."""
    from amr_extraction.extract_excel_codegen import discover_relevant_sheets

    excel_path = "data/starter/27381390/supplements/AAC.01030-16_zac009165488sd2.xlsx"
    mock_client = MagicMock()
    captured_dfs = []

    def mock_classify(name, sample_df, client, tracker):
        captured_dfs.append(sample_df)
        return SheetSelection(
            sheet_name=name,
            contains_ast_data=True,
            has_mic_values=True,
            has_sir_calls=False,
            reasoning="test",
        )

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.classify_single_sheet",
        mock_classify,
    )

    tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    sheets = discover_relevant_sheets(excel_path, mock_client, tracker)

    assert len(captured_dfs) == 1
    sample_df = captured_dfs[0]
    # Header row should be 1 (CVM_NUMBER, Nucleotide accession, etc.), not row 0 title banner
    assert "CVM_NUMBER" in sample_df.columns
    assert "Unnamed: 1" not in sample_df.columns
    assert "Table S2" in sheets


# ==============================================================================
# Metadata Discovery and Accession Enrichment Tests
# ==============================================================================

def test_is_biosample_accession():
    """Verify regex identification of BioSample accessions across NCBI, EBI, and DDBJ."""
    assert is_biosample_accession("SAMN12345678") is True
    assert is_biosample_accession("SAMEA104523") is True
    assert is_biosample_accession("SAME12345") is True
    assert is_biosample_accession("SAMD000123") is True
    assert is_biosample_accession("SAMN12345.1") is True

    # Non-BioSample accessions
    assert is_biosample_accession("GCA_000001405.1") is False
    assert is_biosample_accession("GCF_000001405.1") is False
    assert is_biosample_accession("ERR123456") is False
    assert is_biosample_accession("SRR987654") is False
    assert is_biosample_accession("JYTM00000000") is False
    assert is_biosample_accession(None) is False
    assert is_biosample_accession("") is False


def test_needs_accession_enrichment():
    """Verify triggers when accessions are missing or non-BioSample."""
    # Has empty accession
    df_missing = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": None},
        {"isolate_id": "ISO-2", "accession": "SAMN001"},
    ])
    assert needs_accession_enrichment(df_missing) is True

    # Has only non-BioSample accession (e.g. ERR, GCA)
    df_non_biosample = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "ERR12345"},
        {"isolate_id": "ISO-2", "accession": "GCA_001"},
    ])
    assert needs_accession_enrichment(df_non_biosample) is True

    # All already have BioSample accessions
    df_complete = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "SAMN001"},
        {"isolate_id": "ISO-2", "accession": "SAMEA002"},
    ])
    assert needs_accession_enrichment(df_complete) is False


def test_enrich_ast_with_metadata_join_by_isolate_id():
    """Verify joining metadata on isolate_id fills missing accession."""
    ast_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": None, "drug": "Amp", "notes": None},
        {"isolate_id": "ISO-2", "accession": None, "drug": "Cip", "notes": "mic_sign '=' inferred"},
    ])
    meta_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "SAMN001", "secondary_accession": None},
        {"isolate_id": "ISO-2", "accession": "SAMN002", "secondary_accession": "ERR002"},
    ])

    enriched_df = enrich_ast_with_metadata(ast_df, meta_df)
    assert enriched_df.loc[0, "accession"] == "SAMN001"
    assert pd.isna(enriched_df.loc[0, "notes"]) or enriched_df.loc[0, "notes"] is None
    assert enriched_df.loc[1, "accession"] == "SAMN002"
    assert enriched_df.loc[1, "notes"] == "mic_sign '=' inferred"


def test_enrich_ast_with_metadata_upgrade_to_biosample_records_notes():
    """Verify upgrading a non-BioSample accession records the original in notes."""
    ast_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "ERR100", "drug": "Amp", "notes": None},
        {"isolate_id": "ISO-2", "accession": "GCA_200", "drug": "Cip", "notes": "mic_sign '=' inferred"},
    ])
    meta_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "SAMN001", "secondary_accession": None},
        {"isolate_id": "ISO-2", "accession": "SAMN002", "secondary_accession": None},
    ])

    enriched_df = enrich_ast_with_metadata(ast_df, meta_df)
    assert enriched_df.loc[0, "accession"] == "SAMN001"
    assert enriched_df.loc[0, "notes"] == "original accession: ERR100"

    assert enriched_df.loc[1, "accession"] == "SAMN002"
    assert enriched_df.loc[1, "notes"] == "mic_sign '=' inferred; original accession: GCA_200"


def test_enrich_ast_with_metadata_fallback_join_by_secondary_accession():
    """Verify fallback join when isolate_id doesn't match but non-BioSample accession matches."""
    ast_df = pd.DataFrame([
        {"isolate_id": "DifferentName", "accession": "ERR555", "drug": "Amp", "notes": None},
    ])
    meta_df = pd.DataFrame([
        {"isolate_id": "OriginalLabID", "accession": "SAMN999", "secondary_accession": "ERR555"},
    ])

    enriched_df = enrich_ast_with_metadata(ast_df, meta_df)
    assert enriched_df.loc[0, "accession"] == "SAMN999"
    assert enriched_df.loc[0, "notes"] == "original accession: ERR555"


def test_enrich_ast_with_metadata_collision_resolution():
    """Verify collision resolves by taking the first non-empty accession."""
    ast_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": None, "drug": "Amp", "notes": None},
    ])
    meta_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "SAMN001", "secondary_accession": None},
        {"isolate_id": "ISO-1", "accession": "SAMN999", "secondary_accession": None},
    ])

    enriched_df = enrich_ast_with_metadata(ast_df, meta_df)
    assert len(enriched_df) == 1
    assert enriched_df.loc[0, "accession"] == "SAMN001"


def test_is_candidate_metadata_sheet():
    """Verify detection of candidate metadata sheets based on accession patterns and ID overlap."""
    sample_df = pd.DataFrame({
        "Isolate_Name": ["ISO-1", "ISO-2"],
        "BioSample_ID": ["SAMN001", "SAMN002"],
        "SRA_Run": ["ERR001", "ERR002"],
    })
    target_ids = {"ISO-1", "ISO-2", "ISO-3"}
    target_accs = {"ERR001"}

    assert is_candidate_metadata_sheet(sample_df, target_ids, target_accs) is True

    # No overlapping IDs or accessions
    unrelated_df = pd.DataFrame({
        "Patient": ["P1", "P2"],
        "Age": [45, 52],
    })
    assert is_candidate_metadata_sheet(unrelated_df, target_ids, target_accs) is False


def test_build_metadata_transformation_prompt():
    """Verify metadata transformation prompt requires isolate_id, accession, and secondary_accession."""
    preview_df = pd.DataFrame({
        "Strain": ["S1"],
        "BioSample": ["SAMN001"],
        "GenBank": ["GCA_001"],
    })
    prompt = build_metadata_transformation_prompt("MetadataSheet", preview_df)
    assert "isolate_id" in prompt
    assert "accession" in prompt
    assert "secondary_accession" in prompt
    assert "extract_metadata" in prompt


def test_discover_and_apply_metadata_from_supp_dir(tmp_path, monkeypatch):
    """Verify discover_and_apply_metadata locates candidate sheet in supp_dir and enriches AST data."""
    from amr_extraction.extract_excel_codegen import discover_and_apply_metadata

    # Create primary AST excel
    primary_file = tmp_path / "table_s1_ast.xlsx"
    with pd.ExcelWriter(primary_file) as writer:
        pd.DataFrame({
            "Sample": ["ISO-101", "ISO-102"],
            "Cip": ["<=0.5", "4"],
        }).to_excel(writer, sheet_name="AST_Data", index=False)

    # Create secondary metadata excel in supp_dir
    supp_dir = tmp_path / "supplements"
    supp_dir.mkdir()
    meta_file = supp_dir / "table_s2_meta.xlsx"
    with pd.ExcelWriter(meta_file) as writer:
        pd.DataFrame({
            "Isolate ID": ["ISO-101", "ISO-102"],
            "BioSample ID": ["SAMN11111111", "SAMN22222222"],
            "GenBank Acc": ["GCA_001", "GCA_002"],
        }).to_excel(writer, sheet_name="Isolate_Metadata", index=False)

    ast_df = pd.DataFrame([
        {"isolate_id": "ISO-101", "accession": None, "drug": "Ciprofloxacin", "mic_sign": "<=", "mic": "0.5", "notes": None},
        {"isolate_id": "ISO-102", "accession": "GCA_002", "drug": "Ciprofloxacin", "mic_sign": "=", "mic": "4", "notes": "mic_sign '=' inferred"},
    ])

    # Mock metadata code generator
    def mock_generate_metadata_code(sheet_name, preview_df, client, tracker):
        return """
import pandas as pd
def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "isolate_id": df["Isolate ID"],
        "accession": df["BioSample ID"],
        "secondary_accession": df["GenBank Acc"],
    })
"""

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.generate_metadata_code",
        mock_generate_metadata_code,
    )

    mock_client = MagicMock()
    token_tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    scripts = {}

    enriched = discover_and_apply_metadata(
        current_df=ast_df,
        primary_excel_path=str(primary_file),
        processed_sheets=["AST_Data"],
        supp_dir=str(supp_dir),
        client=mock_client,
        token_tracker=token_tracker,
        generated_scripts=scripts,
    )

    assert enriched.loc[0, "accession"] == "SAMN11111111"
    assert pd.isna(enriched.loc[0, "notes"]) or enriched.loc[0, "notes"] is None

    assert enriched.loc[1, "accession"] == "SAMN22222222"
    assert enriched.loc[1, "notes"] == "mic_sign '=' inferred; original accession: GCA_002"


