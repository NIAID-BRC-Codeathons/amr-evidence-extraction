"""Tests for Excel AST extraction."""

import pytest
import pandas as pd

from amr_extraction.schemas import (
    ASTExtractionRecord,
    ColumnRole,
    SheetClassification,
    SheetColumnMap,
)
from amr_extraction.excel_extractor import (
    parse_mic_string,
    extract_ast_records,
    classify_sheets,
    map_columns,
    extract_from_excel,
)


# ==============================================================================
# Unit Tests: parse_mic_string
# ==============================================================================

@pytest.mark.parametrize(
    "raw_value, expected_operator, expected_value",
    [
        (">64", ">", "64"),
        ("<=0.5", "<=", "0.5"),
        (">=128", ">=", "128"),
        ("<1", "<", "1"),
        ("4", "=", "4"),
        ("0.25", "=", "0.25"),
        ("32/16", "=", "32/16"),
        ("<0.25/4.75", "<", "0.25/4.75"),
        (">8/152", ">", "8/152"),
        ("=16", "=", "16"),
    ],
)
def test_parse_mic_string_valid(raw_value, expected_operator, expected_value):
    """Test parsing valid MIC strings into operator and value."""
    op, val = parse_mic_string(raw_value)
    assert op == expected_operator
    assert val == expected_value


@pytest.mark.parametrize(
    "raw_value",
    [
        "S",
        "R",
        "I",
        "Susceptible",
        "Resistant",
        "Intermediate",
        "",
        "   ",
        None,
        "-",
        "ND",
    ],
)
def test_parse_mic_string_non_mic_or_empty(raw_value):
    """Test that non-MIC strings (e.g. SIR calls, empty values) return (None, None)."""
    op, val = parse_mic_string(raw_value)
    assert op is None
    assert val is None


# ==============================================================================
# Unit Tests: extract_ast_records (using mock column map, no LLM)
# ==============================================================================

def test_extract_ast_records_row_count(pmid_35651495_excel, mock_column_map_35651495):
    """Test that 260 isolates x 14 drugs produces exactly 3,640 records."""
    records = extract_ast_records(
        excel_path=pmid_35651495_excel,
        sheet_name="Sheet1",
        column_map=mock_column_map_35651495,
        pubmed_id="35651495",
    )
    assert len(records) == 260 * 14
    assert isinstance(records[0], ASTExtractionRecord)


def test_extract_ast_records_all_isolates_present(pmid_35651495_excel, mock_column_map_35651495):
    """Test that all 260 unique accessions are present in the extracted records."""
    records = extract_ast_records(
        excel_path=pmid_35651495_excel,
        sheet_name="Sheet1",
        column_map=mock_column_map_35651495,
        pubmed_id="35651495",
    )
    extracted_accessions = {r.accession for r in records if r.accession}
    df = pd.read_excel(pmid_35651495_excel)
    expected_accessions = set(df["Accession number"].dropna())
    assert extracted_accessions == expected_accessions
    assert len(extracted_accessions) == 260


def test_extract_ast_records_all_drugs_present(pmid_35651495_excel, mock_column_map_35651495):
    """Test that all 14 drugs from the column map appear in extracted records."""
    records = extract_ast_records(
        excel_path=pmid_35651495_excel,
        sheet_name="Sheet1",
        column_map=mock_column_map_35651495,
        pubmed_id="35651495",
    )
    extracted_drugs = {r.drug_raw for r in records}
    expected_drugs = {
        "AMP", "CAZ", "AMS", "CFX", "CTX", "CFZ", "IMP",
        "TET", "NAL", "CIP", "AZM", "CHL", "GEN", "SXT",
    }
    assert extracted_drugs == expected_drugs


def test_extract_ast_records_hand_verified(pmid_35651495_excel, mock_column_map_35651495):
    """Verify specific values for the first isolate SAMN26764332 / JLS98."""
    records = extract_ast_records(
        excel_path=pmid_35651495_excel,
        sheet_name="Sheet1",
        column_map=mock_column_map_35651495,
        pubmed_id="35651495",
    )
    isolate_records = {
        r.drug_raw: r for r in records if r.accession == "SAMN26764332"
    }

    # AMP: >64, R
    assert "AMP" in isolate_records
    assert isolate_records["AMP"].mic_operator == ">"
    assert isolate_records["AMP"].mic_value == "64"
    assert isolate_records["AMP"].sir_call == "R"

    # CAZ: <1, S
    assert "CAZ" in isolate_records
    assert isolate_records["CAZ"].mic_operator == "<"
    assert isolate_records["CAZ"].mic_value == "1"
    assert isolate_records["CAZ"].sir_call == "S"

    # AMS: 32/16, R
    assert "AMS" in isolate_records
    assert isolate_records["AMS"].mic_operator == "="
    assert isolate_records["AMS"].mic_value == "32/16"
    assert isolate_records["AMS"].sir_call == "R"

    # CIP: 0.25, I
    assert "CIP" in isolate_records
    assert isolate_records["CIP"].mic_operator == "="
    assert isolate_records["CIP"].mic_value == "0.25"
    assert isolate_records["CIP"].sir_call == "I"

    # SXT: <0.25/4.75, S
    assert "SXT" in isolate_records
    assert isolate_records["SXT"].mic_operator == "<"
    assert isolate_records["SXT"].mic_value == "0.25/4.75"
    assert isolate_records["SXT"].sir_call == "S"


def test_extract_ast_records_schema_valid(pmid_35651495_excel, mock_column_map_35651495):
    """Test that every extracted record conforms to ASTExtractionRecord."""
    records = extract_ast_records(
        excel_path=pmid_35651495_excel,
        sheet_name="Sheet1",
        column_map=mock_column_map_35651495,
        pubmed_id="35651495",
    )
    for r in records:
        assert isinstance(r, ASTExtractionRecord)
        assert r.pubmed_id == "35651495"
        assert r.source_sheet == "Sheet1"
        assert r.isolate_name  # non-empty
        assert r.accession.startswith("SAMN")
        assert r.accession_type == "BioSample"
        assert r.drug_raw  # non-empty


def test_extract_ast_records_ground_truth_overlap(
    pmid_35651495_excel, mock_column_map_35651495, pmid_35651495_ground_truth
):
    """Test alignment between extracted records and BV-BRC ground truth for common drugs."""
    records = extract_ast_records(
        excel_path=pmid_35651495_excel,
        sheet_name="Sheet1",
        column_map=mock_column_map_35651495,
        pubmed_id="35651495",
    )

    # Check isolate JLS98 (SAMN26764332) against ground truth
    gt_jls98 = pmid_35651495_ground_truth[
        pmid_35651495_ground_truth["isolate_name"] == "JLS98"
    ]
    assert len(gt_jls98) > 0

    extracted_jls98 = {
        r.drug_raw: r for r in records if r.isolate_name == "JLS98"
    }

    # AMP in ground truth: mic_operator='>', mic_value='64.0'
    gt_amp = gt_jls98[gt_jls98["drug_raw"] == "ampicillin"].iloc[0]
    rec_amp = extracted_jls98["AMP"]
    assert rec_amp.mic_operator == gt_amp["mic_operator"]
    assert float(rec_amp.mic_value) == float(gt_amp["mic_value"])

    # AMS in ground truth: mic_operator='=', mic_value='32/16'
    gt_ams = gt_jls98[gt_jls98["drug_raw"] == "ampicillin/sulbactam"].iloc[0]
    rec_ams = extracted_jls98["AMS"]
    assert rec_ams.mic_operator == gt_ams["mic_operator"]
    assert rec_ams.mic_value == gt_ams["mic_value"]

    # CIP in ground truth: mic_operator='=', mic_value='0.25'
    gt_cip = gt_jls98[gt_jls98["drug_raw"] == "ciprofloxacin"].iloc[0]
    rec_cip = extracted_jls98["CIP"]
    assert rec_cip.mic_operator == gt_cip["mic_operator"]
    assert float(rec_cip.mic_value) == float(gt_cip["mic_value"])


# ==============================================================================
# Unit Tests: Header Detection & Header Guard
# ==============================================================================

def test_detect_header_row():
    """Test detect_header_row across varied table layouts."""
    from amr_extraction.excel_extractor import detect_header_row

    # Standard layout with headers at row 0
    p_35651495 = "data/starter/35651495/supplements/Table_3.XLSX"
    assert detect_header_row(p_35651495, "Sheet1") == 0

    # Layout with title row at 0 and headers at row 1
    p_27381390 = "data/starter/27381390/supplements/AAC.01030-16_zac009165488sd1.xlsx"
    assert detect_header_row(p_27381390, "Table S1") == 1

    # Layout with title and notes at rows 0-4 and headers at row 5
    p_34907895 = "data/starter/34907895/supplements/Supplementary Tables.xlsx"
    assert detect_header_row(p_34907895, "Supplementary Table S1") == 5


def test_extract_ast_records_filters_header_pollution(tmp_path):
    """Test that extract_ast_records skips rows matching header or subheader patterns."""
    from amr_extraction.excel_extractor import extract_ast_records
    from amr_extraction.schemas import ColumnMapping, SheetColumnMap

    test_file = tmp_path / "test_table.xlsx"
    data = [
        ["CVM_NUMBER", "Nucleotide accession", "GENUS", "AMP"],
        ["CVM_NUMBER", "Nucleotide accession", "GENUS", "AMP"],  # Repeated header row
        ["N29307", "JYTM00000000", "Salmonella", "<= 1"],       # Valid isolate row
        ["Range measured", None, None, "4 - 64"],               # Subheader row
        ["Cutoff (>= X)", None, None, "32"],                     # Subheader row
    ]
    df = pd.DataFrame(data[1:], columns=data[0])
    df.to_excel(test_file, index=False)

    col_map = SheetColumnMap(
        sheet_name="Sheet1",
        header_row_index=0,
        reasoning="Test layout",
        columns=[
            ColumnMapping(column_name="CVM_NUMBER", role=ColumnRole.LOCAL_ID),
            ColumnMapping(column_name="Nucleotide accession", role=ColumnRole.PUBLIC_ACCESSION),
            ColumnMapping(column_name="GENUS", role=ColumnRole.ORGANISM),
            ColumnMapping(column_name="AMP", role=ColumnRole.DRUG_MIC, drug_name="ampicillin"),
        ],
    )

    records = extract_ast_records(
        excel_path=test_file,
        sheet_name="Sheet1",
        column_map=col_map,
        pubmed_id="27381390",
    )

    assert len(records) == 1
    rec = records[0]
    assert rec.isolate_name == "N29307"
    assert rec.accession == "JYTM00000000"
    assert rec.organism == "Salmonella"
    assert rec.mic_operator == "<="
    assert rec.mic_value == "1"


# ==============================================================================
# Integration Tests: Live LLM (@pytest.mark.llm)
# ==============================================================================

@pytest.mark.llm
def test_classify_sheets_35651495(pmid_35651495_excel):
    """Test live LLM sheet classification on PMID 35651495 Table_3.XLSX."""
    from amr_extraction.llm import query_structured

    classifications = classify_sheets(
        excel_path=pmid_35651495_excel,
        query_fn=query_structured,
    )
    assert len(classifications) >= 1
    sheet1 = next((c for c in classifications if c.sheet_name == "Sheet1"), None)
    assert sheet1 is not None
    assert sheet1.contains_ast_data is True
    assert sheet1.has_mic_values is True
    assert sheet1.has_sir_calls is True


@pytest.mark.llm
def test_map_columns_35651495(pmid_35651495_excel):
    """Test live LLM column mapping on PMID 35651495 Table_3.XLSX."""
    from amr_extraction.llm import query_structured

    col_map = map_columns(
        excel_path=pmid_35651495_excel,
        sheet_name="Sheet1",
        query_fn=query_structured,
    )
    assert isinstance(col_map, SheetColumnMap)
    assert col_map.sheet_name == "Sheet1"

    roles = {c.column_name: c.role for c in col_map.columns}
    # Check that accession was identified
    assert roles.get("Accession number") == ColumnRole.PUBLIC_ACCESSION
    # Check that at least one local ID was identified
    has_local_id = any(c.role == ColumnRole.LOCAL_ID for c in col_map.columns)
    assert has_local_id

    # Check that drug columns were identified
    drug_cols = [c for c in col_map.columns if c.role == ColumnRole.DRUG_MIC]
    assert len(drug_cols) >= 10  # Should identify at least 10 of the 14 drugs


@pytest.mark.llm
def test_end_to_end_35651495(pmid_35651495_excel):
    """Test end-to-end extraction from Excel using live LLM."""
    from amr_extraction.llm import query_structured

    records = extract_from_excel(
        excel_path=pmid_35651495_excel,
        pubmed_id="35651495",
        query_fn=query_structured,
    )
    assert len(records) > 2000  # Expect ~3,640 records
    assert all(isinstance(r, ASTExtractionRecord) for r in records)
    assert all(r.pubmed_id == "35651495" for r in records)
