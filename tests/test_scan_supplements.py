"""Tests for scan_supplements.py CLI script."""

import io
from pathlib import Path
import pytest

from amr_extraction.schemas import ASTExtractionRecord, SheetClassification
from amr_extraction.scan_supplements import (
    discover_files,
    format_mic_data_tsv,
    format_sheet_summary_text,
    format_sheet_summary_tsv,
    infer_pmid_from_path,
    main,
    parse_args,
)


def test_infer_pmid_from_path():
    """Test extracting PMID digits from directory path or fallback."""
    assert infer_pmid_from_path(Path("data/starter/35651495/supplements")) == "35651495"
    assert infer_pmid_from_path(Path("/tmp/papers/pmid_27381390")) == "27381390"
    assert infer_pmid_from_path(Path("supplements/no_id_here")) == "UNKNOWN"


def test_discover_files(tmp_path):
    """Test discovering Excel files while tracking skipped non-Excel files."""
    # Create sample files
    (tmp_path / "table1.xlsx").write_text("dummy")
    (tmp_path / "table2.XLS").write_text("dummy")
    (tmp_path / "supp1.pdf").write_text("dummy")
    (tmp_path / "supp2.docx").write_text("dummy")
    (tmp_path / "supp3.csv").write_text("dummy")

    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "table3.xlsx").write_text("dummy")
    (sub / "supp4.pdf").write_text("dummy")

    # Non-recursive
    excel_files, skipped = discover_files(tmp_path, recursive=False)
    excel_names = {f.name for f in excel_files}
    skipped_names = {f.name for f in skipped}

    assert excel_names == {"table1.xlsx", "table2.XLS"}
    assert "supp1.pdf" in skipped_names
    assert "supp2.docx" in skipped_names
    assert "supp3.csv" in skipped_names
    assert len(skipped) == 3

    # Recursive
    excel_files_r, skipped_r = discover_files(tmp_path, recursive=True)
    excel_names_r = {f.name for f in excel_files_r}
    skipped_names_r = {f.name for f in skipped_r}

    assert excel_names_r == {"table1.xlsx", "table2.XLS", "table3.xlsx"}
    assert "supp4.pdf" in skipped_names_r
    assert len(skipped_r) == 4


def test_format_sheet_summary_tsv():
    """Test TSV formatting for sheet classifications."""
    results = [
        (
            Path("Table_3.XLSX"),
            SheetClassification(
                sheet_name="Sheet1",
                contains_ast_data=True,
                has_mic_values=True,
                has_sir_calls=True,
                reasoning="Contains MIC table",
            ),
        ),
        (
            Path("Table_2.XLS"),
            SheetClassification(
                sheet_name="Metadata",
                contains_ast_data=False,
                has_mic_values=False,
                has_sir_calls=False,
                reasoning="Genomic metadata only",
            ),
        ),
    ]
    tsv = format_sheet_summary_tsv(results)
    lines = tsv.strip().split("\n")
    assert lines[0] == "file_name\tsheet_name\tcontains_ast_data\thas_mic_values\thas_sir_calls\treasoning"
    assert lines[1] == "Table_3.XLSX\tSheet1\tTrue\tTrue\tTrue\tContains MIC table"
    assert lines[2] == "Table_2.XLS\tMetadata\tFalse\tFalse\tFalse\tGenomic metadata only"


def test_format_sheet_summary_text():
    """Test human-readable summary formatting."""
    results = [
        (
            Path("Table_3.XLSX"),
            SheetClassification(
                sheet_name="Sheet1",
                contains_ast_data=True,
                has_mic_values=True,
                has_sir_calls=True,
                reasoning="Contains MIC table",
            ),
        )
    ]
    text = format_sheet_summary_text(results, total_excel_files=1, skipped_files_count=2)
    assert "Scanned 1 Excel file(s)" in text
    assert "Table_3.XLSX" in text
    assert "Sheet1" in text
    assert "MIC: YES" in text


def test_format_mic_data_tsv():
    """Test TSV formatting for extracted AST records."""
    records = [
        (
            Path("Table_3.XLSX"),
            "Sheet1",
            ASTExtractionRecord(
                pubmed_id="35651495",
                source_sheet="Sheet1",
                isolate_name="JLS98",
                accession="SAMN12345",
                accession_type="BioSample",
                organism="Salmonella",
                drug_raw="AMP",
                mic_operator=">",
                mic_value="64",
                sir_call="R",
            ),
        )
    ]
    tsv = format_mic_data_tsv(records)
    lines = tsv.strip().split("\n")
    assert "file_name\tsheet_name\tpubmed_id\tisolate_name\taccession" in lines[0]
    assert "Table_3.XLSX\tSheet1\t35651495\tJLS98\tSAMN12345" in lines[1]
    assert ">" in lines[1]
    assert "64" in lines[1]


def test_parse_args():
    """Test CLI argument parsing."""
    # Test default mic_data and log
    default_args = parse_args(["my_dir"])
    assert default_args.directory == Path("my_dir")
    assert default_args.mic_data == Path("scan_supplements.mic.tsv")
    assert default_args.log == Path("scan_supplements.log")

    # Test explicit override
    args = parse_args([
        "my_dir",
        "--tsv",
        "--pmid",
        "12345",
        "-r",
        "-o",
        "out.tsv",
        "--mic_data",
        "ast_out.tsv",
        "--log",
        "custom.log",
    ])
    assert args.directory == Path("my_dir")
    assert args.tsv is True
    assert args.pmid == "12345"
    assert args.recursive is True
    assert args.output == Path("out.tsv")
    assert args.mic_data == Path("ast_out.tsv")
    assert args.log == Path("custom.log")

    # Test --no_mic_data and --no_log
    no_mic_args = parse_args(["my_dir", "--no_mic_data", "--no_log"])
    assert no_mic_args.no_mic_data is True
    assert no_mic_args.no_log is True


def test_format_strategy_log():
    """Test formatting extraction strategy log entries."""
    from amr_extraction.scan_supplements import format_strategy_log
    from amr_extraction.schemas import ColumnMapping, ColumnRole, SheetColumnMap

    classification = SheetClassification(
        sheet_name="Sheet1",
        contains_ast_data=True,
        has_mic_values=True,
        has_sir_calls=True,
        reasoning="Sheet contains paired MIC and SIR columns.",
    )
    col_map = SheetColumnMap(
        sheet_name="Sheet1",
        header_row_index=1,
        reasoning="Row 1 has drug abbreviations paired with SIR columns.",
        columns=[
            ColumnMapping(column_name="Isolate", role=ColumnRole.LOCAL_ID),
            ColumnMapping(column_name="SAMN", role=ColumnRole.PUBLIC_ACCESSION),
            ColumnMapping(column_name="AMP", role=ColumnRole.DRUG_MIC, drug_name="ampicillin", paired_with="Unnamed: 3"),
            ColumnMapping(column_name="Unnamed: 3", role=ColumnRole.DRUG_SIR, drug_name="ampicillin", paired_with="AMP"),
        ],
    )

    log_entry = format_strategy_log(
        excel_path=Path("Table_1.xlsx"),
        sheet_name="Sheet1",
        classification=classification,
        column_map=col_map,
        records_count=250,
    )

    assert "Table_1.xlsx" in log_entry
    assert "Sheet1" in log_entry
    assert "Sheet contains paired MIC and SIR columns." in log_entry
    assert "Row 1 has drug abbreviations" in log_entry
    assert "Header Row Index: 1" in log_entry
    assert "Isolate (role=local_id)" in log_entry
    assert "AMP" in log_entry
    assert "ampicillin" in log_entry
    assert "Extracted Records: 250" in log_entry


def test_main_cli_tsv(tmp_path, monkeypatch, capsys):
    """Test main function emitting sheet classification TSV and stderr warning."""
    test_file = tmp_path / "data.xlsx"
    test_file.write_text("mock")
    skipped_file = tmp_path / "doc.pdf"
    skipped_file.write_text("mock")

    # Mock query_fn and sheet classification
    mock_classifications = [
        SheetClassification(
            sheet_name="Table1",
            contains_ast_data=True,
            has_mic_values=True,
            has_sir_calls=False,
            reasoning="AST table",
        )
    ]

    monkeypatch.setattr(
        "amr_extraction.scan_supplements.classify_sheets",
        lambda excel_path, query_fn: mock_classifications,
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.query_structured",
        lambda **kwargs: None,
    )

    exit_code = main([str(tmp_path), "--tsv", "--no_mic_data"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "file_name\tsheet_name\tcontains_ast_data" in captured.out
    assert "Table1\tTrue\tTrue\tFalse\tAST table" in captured.out
    assert "WARNING: Skipped 1 non-Excel file(s)" in captured.err


def test_main_cli_default_mic_data(tmp_path, monkeypatch, capsys):
    """Test main function writes AST records to default scan_supplements.mic.tsv."""
    test_file = tmp_path / "35651495" / "data.xlsx"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("mock")

    # Change working directory so scan_supplements.mic.tsv is written in tmp_path
    monkeypatch.chdir(tmp_path)

    mock_classification = SheetClassification(
        sheet_name="Table1",
        contains_ast_data=True,
        has_mic_values=True,
        has_sir_calls=True,
        reasoning="AST table",
    )
    mock_record = ASTExtractionRecord(
        pubmed_id="35651495",
        source_sheet="Table1",
        isolate_name="ISO-1",
        accession=None,
        accession_type=None,
        organism="Salmonella",
        drug_raw="CIP",
        mic_operator="<=",
        mic_value="0.25",
        sir_call="S",
    )

    monkeypatch.setattr(
        "amr_extraction.scan_supplements.classify_sheets",
        lambda excel_path, query_fn: [mock_classification],
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.map_columns",
        lambda excel_path, sheet_name, query_fn: None,
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.extract_ast_records",
        lambda excel_path, sheet_name, column_map, pubmed_id: [mock_record],
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.query_structured",
        lambda **kwargs: None,
    )

    exit_code = main([str(test_file.parent)])
    assert exit_code == 0

    default_file = tmp_path / "scan_supplements.mic.tsv"
    assert default_file.exists()
    content = default_file.read_text(encoding="utf-8")
    assert "file_name\tsheet_name\tpubmed_id\tisolate_name" in content
    assert "data.xlsx\tTable1\t35651495\tISO-1" in content


def test_main_cli_mic_data(tmp_path, monkeypatch, capsys):
    """Test main function with --mic_data writing AST records to specified file."""
    test_file = tmp_path / "35651495" / "data.xlsx"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("mock")
    ast_output_file = tmp_path / "extracted_ast.tsv"

    mock_classification = SheetClassification(
        sheet_name="Table1",
        contains_ast_data=True,
        has_mic_values=True,
        has_sir_calls=True,
        reasoning="AST table",
    )
    mock_record = ASTExtractionRecord(
        pubmed_id="35651495",
        source_sheet="Table1",
        isolate_name="ISO-1",
        accession=None,
        accession_type=None,
        organism="Salmonella",
        drug_raw="CIP",
        mic_operator="<=",
        mic_value="0.25",
        sir_call="S",
    )

    monkeypatch.setattr(
        "amr_extraction.scan_supplements.classify_sheets",
        lambda excel_path, query_fn: [mock_classification],
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.map_columns",
        lambda excel_path, sheet_name, query_fn: None,
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.extract_ast_records",
        lambda excel_path, sheet_name, column_map, pubmed_id: [mock_record],
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.query_structured",
        lambda **kwargs: None,
    )

    exit_code = main([str(test_file.parent), "--mic_data", str(ast_output_file)])
    assert exit_code == 0

    # Verify AST records written to the specified file
    assert ast_output_file.exists()
    ast_content = ast_output_file.read_text(encoding="utf-8")
    assert "file_name\tsheet_name\tpubmed_id\tisolate_name" in ast_content
    assert "data.xlsx\tTable1\t35651495\tISO-1" in ast_content

    # Verify stdout still reports the scan summary
    captured = capsys.readouterr()
    assert "Supplementary Files MIC Scan Report" in captured.out
    assert "MIC: YES" in captured.out


def test_main_cli_writes_strategy_log(tmp_path, monkeypatch):
    """Test main function writes strategy report to default and custom log files."""
    test_file = tmp_path / "35651495" / "data.xlsx"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("mock")

    monkeypatch.chdir(tmp_path)

    from amr_extraction.schemas import ColumnMapping, ColumnRole, SheetColumnMap

    mock_classification = SheetClassification(
        sheet_name="Table1",
        contains_ast_data=True,
        has_mic_values=True,
        has_sir_calls=True,
        reasoning="AST table found with MICs",
    )
    mock_col_map = SheetColumnMap(
        sheet_name="Table1",
        header_row_index=0,
        reasoning="Standard AST columns",
        columns=[
            ColumnMapping(column_name="ID", role=ColumnRole.LOCAL_ID),
            ColumnMapping(column_name="AMP", role=ColumnRole.DRUG_MIC, drug_name="ampicillin"),
        ],
    )
    mock_record = ASTExtractionRecord(
        pubmed_id="35651495",
        source_sheet="Table1",
        isolate_name="ISO-1",
        drug_raw="AMP",
        mic_operator="<=",
        mic_value="1",
    )

    monkeypatch.setattr(
        "amr_extraction.scan_supplements.classify_sheets",
        lambda excel_path, query_fn: [mock_classification],
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.map_columns",
        lambda excel_path, sheet_name, query_fn: mock_col_map,
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.extract_ast_records",
        lambda excel_path, sheet_name, column_map, pubmed_id: [mock_record],
    )
    monkeypatch.setattr(
        "amr_extraction.scan_supplements.query_structured",
        lambda **kwargs: None,
    )

    # Test default log writing
    exit_code = main([str(test_file.parent)])
    assert exit_code == 0

    log_file = tmp_path / "scan_supplements.log"
    assert log_file.exists()
    log_content = log_file.read_text(encoding="utf-8")
    assert "data.xlsx" in log_content
    assert "Table1" in log_content
    assert "AST table found with MICs" in log_content
    assert "Standard AST columns" in log_content
    assert "AMP" in log_content

    # Test custom log filename
    custom_log = tmp_path / "my_custom.log"
    exit_code_custom = main([str(test_file.parent), "--log", str(custom_log)])
    assert exit_code_custom == 0
    assert custom_log.exists()
    assert "data.xlsx" in custom_log.read_text(encoding="utf-8")
