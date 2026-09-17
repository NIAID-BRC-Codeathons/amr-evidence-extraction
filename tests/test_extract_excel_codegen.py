import io
from unittest.mock import MagicMock
import pandas as pd
import pytest

from amr_extraction.extract_excel_codegen import (
    build_transformation_prompt,
    build_metadata_transformation_prompt,
    build_cli_parser,
    classify_single_sheet,
    enrich_ast_with_metadata,
    execute_generated_code,
    extract_pmid_from_paths,
    finalize_extracted_dataframe,
    generate_transformation_code,
    is_biosample_accession,
    is_candidate_metadata_sheet,
    load_antibiotics_list,
    needs_accession_enrichment,
    process_excel_with_code_gen,
    validate_extracted_records,
    DEFAULT_ANTIBIOTICS_PATH,
    EXPECTED_OUTPUT_COLUMNS,
    SheetSelection,
)


def test_expected_output_columns_definition():
    """Verify standard schema column list and ordering."""
    assert EXPECTED_OUTPUT_COLUMNS == [
        "pmid",
        "file_name",
        "sheet_name",
        "isolate_id",
        "bioproject_accession",
        "biosample_accession",
        "assembly_accession",
        "genbank_accessions",
        "refseq_accessions",
        "sra_accession",
        "other_accessions",
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

    # Accession rule: no fallback to isolate_id, comma-delimited if multiple
    assert "accession" in prompt
    assert "SAMN" in prompt or "BioSample" in prompt
    assert "fallback" in prompt.lower() or "leave blank" in prompt.lower()
    assert "comma" in prompt.lower()

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


def test_split_accession_tokens_classification():
    """Verify classification of accessions into the 7 typed categories."""
    from amr_extraction.extract_excel_codegen import split_accession_tokens

    raw = "PRJNA12345,SAMN001,SAMEA002,GCA_001.1,NZ_CP012345.1,SRR100,ERR200,CP099999,XYZ123"
    result = split_accession_tokens(raw)

    assert result["bioproject_accession"] == "PRJNA12345"
    assert result["biosample_accession"] == "SAMEA002,SAMN001"
    assert result["assembly_accession"] == "GCA_001.1"
    assert result["genbank_accessions"] == "CP099999"
    assert result["refseq_accessions"] == "NZ_CP012345.1"
    assert result["sra_accession"] == "ERR200,SRR100"
    assert result["other_accessions"] == "XYZ123"


def test_split_accession_tokens_empty_fields():
    """Verify missing accession categories return None / blank."""
    from amr_extraction.extract_excel_codegen import split_accession_tokens

    raw = "SAMN12345"
    result = split_accession_tokens(raw)
    assert result["biosample_accession"] == "SAMN12345"
    assert result["bioproject_accession"] is None
    assert result["assembly_accession"] is None
    assert result["genbank_accessions"] is None
    assert result["refseq_accessions"] is None
    assert result["sra_accession"] is None
    assert result["other_accessions"] is None


def test_finalize_extracted_dataframe_splits_accessions():
    """Verify finalize_extracted_dataframe splits accession and formats columns."""
    inner_df = pd.DataFrame([{
        "isolate_id": "ISO-100",
        "accession": "SAMN001,ERR100",
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
    assert "accession" not in final_df.columns
    assert final_df.loc[0, "file_name"] == "test_paper_s1.xlsx"
    assert final_df.loc[0, "sheet_name"] == "Table S1"
    assert final_df.loc[0, "isolate_id"] == "ISO-100"
    assert final_df.loc[0, "biosample_accession"] == "SAMN001"
    assert final_df.loc[0, "sra_accession"] == "ERR100"
    assert pd.isna(final_df.loc[0, "assembly_accession"]) or final_df.loc[0, "assembly_accession"] is None


def test_export_tsv_clean_blanks():
    """Verify writing final DataFrame to TSV produces clean empty fields without 'nan' or 'None'."""
    df = pd.DataFrame([{
        "pmid": "31266463",
        "file_name": "paper.xlsx",
        "sheet_name": "Sheet1",
        "isolate_id": "ISO-1",
        "bioproject_accession": None,
        "biosample_accession": "SAMN001",
        "assembly_accession": None,
        "genbank_accessions": None,
        "refseq_accessions": None,
        "sra_accession": None,
        "other_accessions": None,
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
    biosample_idx = header.index("biosample_accession")
    sra_idx = header.index("sra_accession")
    sir_call_idx = header.index("sir_call")

    assert row[biosample_idx] == "SAMN001"
    assert row[sra_idx] == ""
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
    assert enriched_df.loc[1, "accession"] == "SAMN002,ERR002"
    assert enriched_df.loc[1, "notes"] == "mic_sign '=' inferred"


def test_enrich_ast_with_metadata_upgrade_to_biosample_records_notes():
    """Verify upgrading a non-BioSample accession records the original in notes and retains both accessions."""
    ast_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "ERR100", "drug": "Amp", "notes": None},
        {"isolate_id": "ISO-2", "accession": "GCA_200", "drug": "Cip", "notes": "mic_sign '=' inferred"},
    ])
    meta_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "SAMN001", "secondary_accession": None},
        {"isolate_id": "ISO-2", "accession": "SAMN002", "secondary_accession": None},
    ])

    enriched_df = enrich_ast_with_metadata(ast_df, meta_df)
    assert enriched_df.loc[0, "accession"] == "SAMN001,ERR100"
    assert enriched_df.loc[0, "notes"] == "original accession: ERR100"

    assert enriched_df.loc[1, "accession"] == "SAMN002,GCA_200"
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
    assert enriched_df.loc[0, "accession"] == "SAMN999,ERR555"
    assert enriched_df.loc[0, "notes"] == "original accession: ERR555"


def test_enrich_ast_with_metadata_collision_resolution():
    """Verify multiple metadata accessions are aggregated comma-delimited."""
    ast_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": None, "drug": "Amp", "notes": None},
    ])
    meta_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "SAMN001", "secondary_accession": None},
        {"isolate_id": "ISO-1", "accession": "SAMN999", "secondary_accession": None},
    ])

    enriched_df = enrich_ast_with_metadata(ast_df, meta_df)
    assert len(enriched_df) == 1
    assert enriched_df.loc[0, "accession"] == "SAMN001,SAMN999"


def test_enrich_ast_with_metadata_aggregates_all_public_accessions():
    """Verify all unique public accessions are merged comma-delimited with BioSample first."""
    ast_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "ERR100", "drug": "Amp", "notes": None},
    ])
    meta_df = pd.DataFrame([
        {
            "isolate_id": "ISO-1",
            "accession": "SAMN001,SRR200",
            "secondary_accession": "CP012345",
        },
    ])

    enriched_df = enrich_ast_with_metadata(ast_df, meta_df)
    assert enriched_df.loc[0, "accession"] == "SAMN001,CP012345,ERR100,SRR200"
    assert enriched_df.loc[0, "notes"] == "original accession: ERR100"


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
    """Verify metadata transformation prompt requires extracting all accession columns comma-delimited."""
    preview_df = pd.DataFrame({
        "Strain": ["S1"],
        "BioSample": ["SAMN001"],
        "GenBank": ["GCA_001"],
    })
    prompt = build_metadata_transformation_prompt("MetadataSheet", preview_df)
    assert "isolate_id" in prompt
    assert "accession" in prompt
    assert "secondary_accession" in prompt
    assert "comma" in prompt.lower()
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

    assert enriched.loc[0, "accession"] == "SAMN11111111,GCA_001"
    assert pd.isna(enriched.loc[0, "notes"]) or enriched.loc[0, "notes"] is None

    assert enriched.loc[1, "accession"] == "SAMN22222222,GCA_002"
    assert enriched.loc[1, "notes"] == "mic_sign '=' inferred; original accession: GCA_002"


def test_discover_and_apply_metadata_scans_all_sheets_without_early_stop(tmp_path, monkeypatch):
    """Verify discover_and_apply_metadata continues scanning all candidate sheets even if BioSamples exist."""
    from amr_extraction.extract_excel_codegen import discover_and_apply_metadata

    # Primary excel has AST data and a metadata sheet
    primary_file = tmp_path / "primary.xlsx"
    with pd.ExcelWriter(primary_file) as writer:
        pd.DataFrame({
            "Sample": ["ISO-1"],
            "Amp": ["4"],
        }).to_excel(writer, sheet_name="AST_Data", index=False)
        pd.DataFrame({
            "Isolate": ["ISO-1"],
            "RunAccession": ["ERR101"],
        }).to_excel(writer, sheet_name="Meta_Sheet_1", index=False)

    # Supp dir has a second metadata excel
    supp_dir = tmp_path / "supp"
    supp_dir.mkdir()
    meta_file2 = supp_dir / "meta2.xlsx"
    with pd.ExcelWriter(meta_file2) as writer:
        pd.DataFrame({
            "Isolate": ["ISO-1"],
            "Assembly": ["GCA_101"],
        }).to_excel(writer, sheet_name="Meta_Sheet_2", index=False)

    # ast_df already has BioSample accession
    ast_df = pd.DataFrame([
        {"isolate_id": "ISO-1", "accession": "SAMN101", "drug": "Ampicillin", "mic_sign": "=", "mic": "4", "notes": None},
    ])

    def mock_gen_code(sheet_name, preview_df, client, tracker):
        if sheet_name == "Meta_Sheet_1":
            return """
import pandas as pd
def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "isolate_id": df["Isolate"],
        "accession": df["RunAccession"],
        "secondary_accession": None,
    })
"""
        else:
            return """
import pandas as pd
def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "isolate_id": df["Isolate"],
        "accession": df["Assembly"],
        "secondary_accession": None,
    })
"""

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.generate_metadata_code",
        mock_gen_code,
    )

    enriched = discover_and_apply_metadata(
        current_df=ast_df,
        primary_excel_path=str(primary_file),
        processed_sheets=["AST_Data"],
        supp_dir=str(supp_dir),
        client=MagicMock(),
        token_tracker={"calls": 0, "input_tokens": 0, "output_tokens": 0},
    )

    # Both ERR101 and GCA_101 must be accumulated alongside SAMN101
    assert enriched.loc[0, "accession"] == "SAMN101,ERR101,GCA_101"



def test_process_excel_with_code_gen_directory_mode(tmp_path, monkeypatch):
    """Verify process_excel_with_code_gen processes all files in supp_dir when excel_path is None."""
    from amr_extraction.extract_excel_codegen import process_excel_with_code_gen

    supp_dir = tmp_path / "supplements"
    supp_dir.mkdir()

    file_a = supp_dir / "paper_supp_a.xlsx"
    with pd.ExcelWriter(file_a) as writer:
        pd.DataFrame({
            "Isolate": ["ISO-1"],
            "Ciprofloxacin": ["<=0.5"],
        }).to_excel(writer, sheet_name="AST_A", index=False)

    file_b = supp_dir / "paper_supp_b.xlsx"
    with pd.ExcelWriter(file_b) as writer:
        pd.DataFrame({
            "Isolate": ["ISO-2"],
            "Gentamicin": ["4"],
        }).to_excel(writer, sheet_name="AST_B", index=False)
        pd.DataFrame({
            "Isolate ID": ["ISO-1", "ISO-2"],
            "BioSample": ["SAMN99900001", "SAMN99900002"],
        }).to_excel(writer, sheet_name="Accession_Map", index=False)

    # Mock genai.Client
    mock_client = MagicMock()
    monkeypatch.setattr("amr_extraction.extract_excel_codegen.genai.Client", lambda: mock_client)

    # Mock sheet discovery
    def mock_discover_relevant_sheets(excel_path, client, token_tracker):
        if "paper_supp_a" in excel_path:
            return ["AST_A"]
        elif "paper_supp_b" in excel_path:
            return ["AST_B"]
        return []

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.discover_relevant_sheets",
        mock_discover_relevant_sheets,
    )

    # Mock AST transformation code generation
    def mock_generate_transformation_code(sheet_name, preview_df, client, token_tracker, previous_errors=None, antibiotics_list=None):
        if sheet_name == "AST_A":
            return """
import pandas as pd
def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "Ciprofloxacin",
        "mic_sign": "<=",
        "mic": "0.5",
        "sir_call": None,
        "notes": None,
    }])
"""
        elif sheet_name == "AST_B":
            return """
import pandas as pd
def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "isolate_id": "ISO-2",
        "accession": None,
        "drug": "Gentamicin",
        "mic_sign": "=",
        "mic": "4",
        "sir_call": None,
        "notes": "mic_sign '=' inferred",
    }])
"""
        return ""

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.generate_transformation_code",
        mock_generate_transformation_code,
    )

    # Mock metadata transformation code generation
    def mock_generate_metadata_code(sheet_name, preview_df, client, token_tracker):
        return """
import pandas as pd
def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "isolate_id": df["Isolate ID"],
        "accession": df["BioSample"],
        "secondary_accession": None,
    })
"""

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.generate_metadata_code",
        mock_generate_metadata_code,
    )

    out_tsv = tmp_path / "output.tsv"
    save_code = tmp_path / "code.py"

    process_excel_with_code_gen(
        excel_path=None,
        output_tsv=str(out_tsv),
        save_code_path=str(save_code),
        supp_dir=str(supp_dir),
    )

    assert out_tsv.exists()
    result_df = pd.read_csv(out_tsv, sep="\t")
    assert len(result_df) == 2
    assert set(result_df["file_name"]) == {"paper_supp_a.xlsx", "paper_supp_b.xlsx"}
    assert set(result_df["isolate_id"]) == {"ISO-1", "ISO-2"}
    assert list(result_df["biosample_accession"]) == ["SAMN99900001", "SAMN99900002"]


def test_cli_parser_supp_dir_only():
    """Verify build_cli_parser allows omitting excel_file when --supp-dir is passed."""
    from amr_extraction.extract_excel_codegen import build_cli_parser

    parser = build_cli_parser()
    args = parser.parse_args(["--supp-dir", "/path/to/supplements"])
    assert args.excel_file is None
    assert args.supp_dir == "/path/to/supplements"


def test_cli_parser_pmid_argument():
    """Verify build_cli_parser parses --pmid flag."""
    from amr_extraction.extract_excel_codegen import build_cli_parser

    parser = build_cli_parser()
    args = parser.parse_args(["data/file.xlsx", "--pmid", "31266463"])
    assert args.pmid == "31266463"


def test_extract_pmid_from_paths():
    """Verify extraction of 7-8 digit PMIDs from paths with precedence."""
    # From excel_file path with 8 digits
    pmid = extract_pmid_from_paths(
        excel_path="data/starter/31266463/supplements/12866_2019_1520_MOESM1_ESM.xlsx"
    )
    assert pmid == "31266463"

    # From supp_dir path with 8 digits
    pmid = extract_pmid_from_paths(
        supp_dir="scripts/query_pmids_to_find_ast/output/supplements/33658988/"
    )
    assert pmid == "33658988"

    # Precedence: excel_path checked first
    pmid = extract_pmid_from_paths(
        excel_path="/data/27381390/table.xlsx",
        supp_dir="/data/31266463/supps",
    )
    assert pmid == "27381390"

    # Fallback to supp_dir if excel_path has no PMID
    pmid = extract_pmid_from_paths(
        excel_path="/tmp/table.xlsx",
        supp_dir="data/starter/35651495/supplements",
    )
    assert pmid == "35651495"

    # No PMID found in paths
    pmid = extract_pmid_from_paths(
        excel_path="/tmp/unrelated_table_2020.xlsx",
        supp_dir="/tmp/other_dir",
    )
    assert pmid is None


def test_finalize_extracted_dataframe_with_pmid():
    """Verify finalize_extracted_dataframe populates pmid as the first column."""
    inner_df = pd.DataFrame([{
        "isolate_id": "ISO-100",
        "accession": "SAMN001",
        "drug": "Gentamicin",
        "mic_sign": "<=",
        "mic": "1",
        "sir_call": "S",
        "notes": None,
    }])

    final_df = finalize_extracted_dataframe(
        inner_df,
        file_path="test_paper.xlsx",
        sheet_name="Table S1",
        pmid="31266463",
    )

    assert list(final_df.columns) == EXPECTED_OUTPUT_COLUMNS
    assert final_df.columns[0] == "pmid"
    assert final_df.loc[0, "pmid"] == "31266463"
    assert final_df.loc[0, "file_name"] == "test_paper.xlsx"


def test_finalize_extracted_dataframe_without_pmid():
    """Verify finalize_extracted_dataframe leaves pmid None if omitted."""
    inner_df = pd.DataFrame([{
        "isolate_id": "ISO-100",
        "accession": "SAMN001",
        "drug": "Gentamicin",
        "mic_sign": "<=",
        "mic": "1",
        "sir_call": "S",
        "notes": None,
    }])

    final_df = finalize_extracted_dataframe(
        inner_df,
        file_path="test_paper.xlsx",
        sheet_name="Table S1",
    )

    assert list(final_df.columns) == EXPECTED_OUTPUT_COLUMNS
    assert final_df.columns[0] == "pmid"
    assert pd.isna(final_df.loc[0, "pmid"]) or final_df.loc[0, "pmid"] is None


def test_process_excel_with_inferred_pmid(tmp_path, monkeypatch):
    """Verify process_excel_with_code_gen extracts PMID from directory path."""
    from amr_extraction.extract_excel_codegen import process_excel_with_code_gen

    pmid_dir = tmp_path / "31266463" / "supplements"
    pmid_dir.mkdir(parents=True)
    excel_file = pmid_dir / "supplement.xlsx"
    with pd.ExcelWriter(excel_file) as writer:
        pd.DataFrame({
            "Isolate": ["ISO-1"],
            "Ciprofloxacin": ["<=0.5"],
        }).to_excel(writer, sheet_name="AST_Data", index=False)

    monkeypatch.setattr("amr_extraction.extract_excel_codegen.genai.Client", lambda: MagicMock())
    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.discover_relevant_sheets",
        lambda excel_path, client, token_tracker: ["AST_Data"],
    )
    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.generate_transformation_code",
        lambda sheet_name, preview_df, client, token_tracker, previous_errors=None, antibiotics_list=None: """
import pandas as pd
def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "Ciprofloxacin",
        "mic_sign": "<=",
        "mic": "0.5",
        "sir_call": None,
        "notes": None,
    }])
""",
    )

    out_tsv = tmp_path / "output.tsv"
    process_excel_with_code_gen(
        excel_path=str(excel_file),
        output_tsv=str(out_tsv),
    )

    assert out_tsv.exists()
    df = pd.read_csv(out_tsv, sep="\t", dtype=str)
    assert list(df.columns) == EXPECTED_OUTPUT_COLUMNS
    assert df.loc[0, "pmid"] == "31266463"


def test_process_excel_with_explicit_pmid(tmp_path, monkeypatch):
    """Verify process_excel_with_code_gen uses explicit --pmid over path."""
    from amr_extraction.extract_excel_codegen import process_excel_with_code_gen

    pmid_dir = tmp_path / "31266463" / "supplements"
    pmid_dir.mkdir(parents=True)
    excel_file = pmid_dir / "supplement.xlsx"
    with pd.ExcelWriter(excel_file) as writer:
        pd.DataFrame({
            "Isolate": ["ISO-1"],
            "Ciprofloxacin": ["<=0.5"],
        }).to_excel(writer, sheet_name="AST_Data", index=False)

    monkeypatch.setattr("amr_extraction.extract_excel_codegen.genai.Client", lambda: MagicMock())
    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.discover_relevant_sheets",
        lambda excel_path, client, token_tracker: ["AST_Data"],
    )
    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.generate_transformation_code",
        lambda sheet_name, preview_df, client, token_tracker, previous_errors=None, antibiotics_list=None: """
import pandas as pd
def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "Ciprofloxacin",
        "mic_sign": "<=",
        "mic": "0.5",
        "sir_call": None,
        "notes": None,
    }])
""",
    )

    out_tsv = tmp_path / "output.tsv"
    process_excel_with_code_gen(
        excel_path=str(excel_file),
        output_tsv=str(out_tsv),
        pmid="99999999",
    )

    assert out_tsv.exists()
    df = pd.read_csv(out_tsv, sep="\t", dtype=str)
    assert list(df.columns) == EXPECTED_OUTPUT_COLUMNS
    assert df.loc[0, "pmid"] == "99999999"


def test_default_antibiotics_list_file_exists_and_loads():
    """Verify default antibiotics list file exists and contains expected standard drugs."""
    drugs = load_antibiotics_list()
    assert isinstance(drugs, list)
    assert len(drugs) == 52
    assert "ampicillin" in drugs
    assert "ciprofloxacin" in drugs
    assert "vancomycin" in drugs


def test_load_antibiotics_list_custom_and_missing(tmp_path):
    """Verify load_antibiotics_list loads custom files and raises FileNotFoundError when missing."""
    custom_file = tmp_path / "custom_drugs.txt"
    custom_file.write_text("DrugA\nDrugB\n\n  DrugC  \n")

    loaded = load_antibiotics_list(str(custom_file))
    assert loaded == ["DrugA", "DrugB", "DrugC"]

    non_existent = tmp_path / "does_not_exist.txt"
    with pytest.raises(FileNotFoundError):
        load_antibiotics_list(str(non_existent))


def test_cli_parser_defaults_antibiotics_list():
    """Verify CLI parser sets default --antibiotics-list to DEFAULT_ANTIBIOTICS_PATH."""
    parser = build_cli_parser()
    args = parser.parse_args(["some_file.xlsx"])
    assert args.antibiotics_list == DEFAULT_ANTIBIOTICS_PATH


def test_process_excel_uses_default_antibiotics_list(monkeypatch, tmp_path):
    """Verify process_excel_with_code_gen passes default antibiotics list to code generation."""
    excel_file = tmp_path / "test.xlsx"
    with pd.ExcelWriter(excel_file) as writer:
        pd.DataFrame({"Isolate": ["ISO-1"], "CIP": ["4"]}).to_excel(writer, sheet_name="AST", index=False)

    captured_antibiotics = {}

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.classify_single_sheet",
        lambda sheet_name, preview_df, client, token_tracker: SheetSelection(
            sheet_name=sheet_name,
            contains_ast_data=True,
            has_mic_values=True,
            has_sir_calls=False,
            reasoning="AST sheet"
        )
    )

    def mock_gen_code(sheet_name, preview_df, client, token_tracker, previous_errors=None, antibiotics_list=None):
        captured_antibiotics["list"] = antibiotics_list
        return """
import pandas as pd
def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "Ciprofloxacin",
        "mic_sign": "=",
        "mic": "4",
        "sir_call": None,
        "notes": None,
    }])
"""

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.generate_transformation_code",
        mock_gen_code
    )

    out_tsv = tmp_path / "output.tsv"
    process_excel_with_code_gen(
        excel_path=str(excel_file),
        output_tsv=str(out_tsv),
    )

    assert "list" in captured_antibiotics
    assert captured_antibiotics["list"] is not None
    assert "ciprofloxacin" in captured_antibiotics["list"]


def test_cli_parser_num_passes():
    """Verify CLI parser sets default --num-passes to 1 and parses integer."""
    from amr_extraction.extract_excel_codegen import build_cli_parser
    parser = build_cli_parser()
    args = parser.parse_args(["some_file.xlsx"])
    assert args.num_passes == 1

    args_multi = parser.parse_args(["some_file.xlsx", "--num-passes", "3"])
    assert args_multi.num_passes == 3


def test_ensemble_extracted_records_merges_disjoint_drugs():
    """Verify ensembling combines non-overlapping drug records from different passes."""
    from amr_extraction.extract_excel_codegen import ensemble_extracted_records

    df1 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "linezolid",
        "mic_sign": "=",
        "mic": "2",
        "sir_call": "S",
        "notes": None,
    }])
    df2 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "cefoxitin",
        "mic_sign": "<=",
        "mic": "0.5",
        "sir_call": "S",
        "notes": None,
    }])

    ensembled_df, dropped = ensemble_extracted_records([df1, df2])
    assert len(ensembled_df) == 2
    assert len(dropped) == 0
    drugs = set(ensembled_df["drug"])
    assert drugs == {"linezolid", "cefoxitin"}


def test_ensemble_extracted_records_merges_partial_attributes():
    """Verify ensembling fills in missing attributes across passes without conflict."""
    from amr_extraction.extract_excel_codegen import ensemble_extracted_records

    df1 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "ciprofloxacin",
        "mic_sign": "=",
        "mic": "4",
        "sir_call": None,
        "notes": None,
    }])
    df2 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": "SAMN001",
        "drug": "ciprofloxacin",
        "mic_sign": None,
        "mic": None,
        "sir_call": "R",
        "notes": None,
    }])

    ensembled_df, dropped = ensemble_extracted_records([df1, df2])
    assert len(ensembled_df) == 1
    assert len(dropped) == 0
    row = ensembled_df.iloc[0]
    assert row["isolate_id"] == "ISO-1"
    assert row["accession"] == "SAMN001"
    assert row["drug"] == "ciprofloxacin"
    assert row["mic"] == "4"
    assert row["mic_sign"] == "="
    assert row["sir_call"] == "R"


def test_ensemble_extracted_records_merges_accessions():
    """Verify ensembling merges accessions from both passes when keys match."""
    from amr_extraction.extract_excel_codegen import ensemble_extracted_records

    df1 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": "SAMN100",
        "drug": "daptomycin",
        "mic_sign": "=",
        "mic": "1",
        "sir_call": "S",
        "notes": None,
    }])
    df2 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": "ERR200",
        "drug": "daptomycin",
        "mic_sign": "=",
        "mic": "1",
        "sir_call": "S",
        "notes": None,
    }])

    ensembled_df, dropped = ensemble_extracted_records([df1, df2])
    assert len(ensembled_df) == 1
    assert len(dropped) == 0
    assert ensembled_df.iloc[0]["accession"] == "SAMN100,ERR200"


def test_ensemble_extracted_records_normalizes_numeric_mic():
    """Verify numeric strings like '4.0' and '4' are recognized as identical and not dropped."""
    from amr_extraction.extract_excel_codegen import ensemble_extracted_records

    df1 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "daptomycin",
        "mic_sign": "=",
        "mic": "4.0",
        "sir_call": "R",
        "notes": None,
    }])
    df2 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "daptomycin",
        "mic_sign": "=",
        "mic": "4",
        "sir_call": "R",
        "notes": None,
    }])

    ensembled_df, dropped = ensemble_extracted_records([df1, df2])
    assert len(ensembled_df) == 1
    assert len(dropped) == 0
    assert ensembled_df.iloc[0]["mic"] == "4"


def test_ensemble_extracted_records_drops_conflicting_mic():
    """Verify conflicting numeric mic values for same isolate and drug are dropped entirely."""
    from amr_extraction.extract_excel_codegen import ensemble_extracted_records

    df1 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "gentamicin",
        "mic_sign": "=",
        "mic": "4",
        "sir_call": None,
        "notes": None,
    }])
    df2 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "gentamicin",
        "mic_sign": "=",
        "mic": "8",
        "sir_call": None,
        "notes": None,
    }])

    ensembled_df, dropped = ensemble_extracted_records([df1, df2])
    assert len(ensembled_df) == 0
    assert len(dropped) == 1
    assert dropped[0]["key"] == ("ISO-1", "gentamicin")
    assert "mic" in dropped[0]["reason"]


def test_ensemble_extracted_records_drops_conflicting_sir():
    """Verify conflicting SIR calls for same isolate and drug are dropped entirely."""
    from amr_extraction.extract_excel_codegen import ensemble_extracted_records

    df1 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "ampicillin",
        "mic_sign": None,
        "mic": None,
        "sir_call": "S",
        "notes": None,
    }])
    df2 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "ampicillin",
        "mic_sign": None,
        "mic": None,
        "sir_call": "R",
        "notes": None,
    }])

    ensembled_df, dropped = ensemble_extracted_records([df1, df2])
    assert len(ensembled_df) == 0
    assert len(dropped) == 1
    assert "sir_call" in dropped[0]["reason"]


def test_ensemble_extracted_records_drops_conflicting_mic_sign():
    """Verify conflicting mic signs ('=' vs '<=') are dropped entirely."""
    from amr_extraction.extract_excel_codegen import ensemble_extracted_records

    df1 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "vancomycin",
        "mic_sign": "=",
        "mic": "1",
        "sir_call": None,
        "notes": None,
    }])
    df2 = pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "vancomycin",
        "mic_sign": "<=",
        "mic": "1",
        "sir_call": None,
        "notes": None,
    }])

    ensembled_df, dropped = ensemble_extracted_records([df1, df2])
    assert len(ensembled_df) == 0
    assert len(dropped) == 1
    assert "mic_sign" in dropped[0]["reason"]


def test_ensemble_extracted_records_fallback_to_accession_key():
    """Verify fallback to accession key when isolate_id is None."""
    from amr_extraction.extract_excel_codegen import ensemble_extracted_records

    df1 = pd.DataFrame([{
        "isolate_id": None,
        "accession": "SAMN999",
        "drug": "penicillin",
        "mic_sign": ">=",
        "mic": "16",
        "sir_call": "R",
        "notes": None,
    }])
    df2 = pd.DataFrame([{
        "isolate_id": None,
        "accession": "SAMN999",
        "drug": "penicillin",
        "mic_sign": ">=",
        "mic": "16",
        "sir_call": "R",
        "notes": None,
    }])

    ensembled_df, dropped = ensemble_extracted_records([df1, df2])
    assert len(ensembled_df) == 1
    assert len(dropped) == 0


def test_process_excel_writes_companion_log_file(monkeypatch, tmp_path):
    """Verify process_excel_with_code_gen writes companion .log file alongside output."""
    excel_file = tmp_path / "test.xlsx"
    with pd.ExcelWriter(excel_file) as writer:
        pd.DataFrame({"Isolate": ["ISO-1"], "CIP": ["4"]}).to_excel(writer, sheet_name="AST", index=False)

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.classify_single_sheet",
        lambda sheet_name, preview_df, client, token_tracker: SheetSelection(
            sheet_name=sheet_name,
            contains_ast_data=True,
            has_mic_values=True,
            has_sir_calls=False,
            reasoning="AST sheet",
        ),
    )

    def mock_gen_code(sheet_name, preview_df, client, token_tracker, previous_errors=None, antibiotics_list=None, temperature=0.0):
        return """
import pandas as pd
def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "isolate_id": "ISO-1",
        "accession": None,
        "drug": "Ciprofloxacin",
        "mic_sign": "=",
        "mic": "4",
        "sir_call": None,
        "notes": None,
    }])
"""

    monkeypatch.setattr(
        "amr_extraction.extract_excel_codegen.generate_transformation_code",
        mock_gen_code,
    )

    out_tsv = tmp_path / "29729180.mic.tsv"
    process_excel_with_code_gen(
        excel_path=str(excel_file),
        output_tsv=str(out_tsv),
        num_passes=2,
    )

    log_file = tmp_path / "29729180.mic.log"
    assert out_tsv.exists()
    assert log_file.exists()
    log_content = log_file.read_text()
    assert "Passes configured: 2" in log_content
    assert "Ensemble Summary" in log_content








