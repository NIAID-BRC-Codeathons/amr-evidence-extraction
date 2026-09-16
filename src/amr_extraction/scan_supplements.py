#!/usr/bin/env python3
"""Command-line script to scan supplementary files for AST/MIC data."""

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from datetime import datetime
from amr_extraction.schemas import ASTExtractionRecord, ColumnRole, SheetClassification, SheetColumnMap
from amr_extraction.excel_extractor import (
    classify_sheets,
    detect_header_row,
    extract_ast_records,
    map_columns,
)
from amr_extraction.llm import query_structured

EXCEL_EXTENSIONS = {".xlsx", ".xls"}
DEFAULT_MIC_DATA_FILE = Path("scan_supplements.mic.tsv")
DEFAULT_LOG_FILE = Path("scan_supplements.log")


def format_strategy_log(
    excel_path: Path,
    sheet_name: str,
    classification: SheetClassification,
    column_map: SheetColumnMap | None = None,
    records_count: int | None = None,
) -> str:
    """Format the strategy and decisions chosen for a sheet into a readable log block."""
    lines = [
        f"--- File: {excel_path.name} | Sheet: '{sheet_name}' ---",
        "Sheet Classification Decision:",
        f"  Contains AST Data: {classification.contains_ast_data}",
        f"  Has MIC Values: {classification.has_mic_values}",
        f"  Has SIR Calls: {classification.has_sir_calls}",
        f"  Classification Reasoning: {classification.reasoning}",
    ]
    if column_map is not None:
        hdr = column_map.header_row_index if column_map.header_row_index is not None else 0
        lines.append("Column Mapping Strategy:")
        lines.append(f"  Header Row Index: {hdr}")
        lines.append(f"  Layout Reasoning: {column_map.reasoning}")

        # Summarize columns by role
        local_ids = [c.column_name for c in column_map.columns if c.role == ColumnRole.LOCAL_ID]
        accessions = [c.column_name for c in column_map.columns if c.role == ColumnRole.PUBLIC_ACCESSION]
        organisms = [c.column_name for c in column_map.columns if c.role == ColumnRole.ORGANISM]
        drug_mics = [c for c in column_map.columns if c.role == ColumnRole.DRUG_MIC]
        drug_sirs = [c for c in column_map.columns if c.role == ColumnRole.DRUG_SIR]

        if local_ids:
            lines.append(f"  Local ID Columns: {', '.join(f'{c} (role=local_id)' for c in local_ids)}")
        if accessions:
            lines.append(f"  Accession Columns: {', '.join(f'{c} (role=public_accession)' for c in accessions)}")
        if organisms:
            lines.append(f"  Organism Columns: {', '.join(organisms)}")

        if drug_mics:
            mic_desc = []
            for d in drug_mics:
                desc = f"{d.column_name}"
                if d.drug_name:
                    desc += f" (drug={d.drug_name})"
                if d.paired_with:
                    desc += f" [paired with SIR col: {d.paired_with}]"
                mic_desc.append(desc)
            lines.append(f"  Drug MIC Columns ({len(drug_mics)}): {'; '.join(mic_desc)}")

        if drug_sirs:
            lines.append(f"  Drug SIR Columns ({len(drug_sirs)}): {', '.join(c.column_name for c in drug_sirs)}")

    if records_count is not None:
        lines.append("Extraction Outcome:")
        lines.append(f"  Extracted Records: {records_count}")

    lines.append("")
    return "\n".join(lines)


def infer_pmid_from_path(path: Path) -> str:
    """Attempt to infer a PubMed ID (7-9 digits) from path parts."""
    parts = list(path.resolve().parts)
    for part in reversed(parts):
        match = re.search(r"(?<!\d)(\d{7,9})(?!\d)", part)
        if match:
            return match.group(1)
    return "UNKNOWN"


def discover_files(directory: Path, recursive: bool = False) -> tuple[list[Path], list[Path]]:
    """Discover Excel files and track non-Excel files in directory.

    Returns:
        tuple of (excel_files, skipped_files) sorted by path.
    """
    excel_files: list[Path] = []
    skipped_files: list[Path] = []

    if recursive:
        candidates = directory.rglob("*")
    else:
        candidates = directory.glob("*")

    for p in candidates:
        if p.is_file():
            if p.suffix.lower() in EXCEL_EXTENSIONS:
                excel_files.append(p)
            else:
                skipped_files.append(p)

    return sorted(excel_files), sorted(skipped_files)


def format_sheet_summary_tsv(results: list[tuple[Path, SheetClassification]]) -> str:
    """Format sheet classification results as TSV."""
    headers = [
        "file_name",
        "sheet_name",
        "contains_ast_data",
        "has_mic_values",
        "has_sir_calls",
        "reasoning",
    ]
    rows = ["\t".join(headers)]
    for file_path, c in results:
        clean_reasoning = (c.reasoning or "").replace("\t", " ").replace("\n", " ")
        row = [
            file_path.name,
            c.sheet_name,
            str(c.contains_ast_data),
            str(c.has_mic_values),
            str(c.has_sir_calls),
            clean_reasoning,
        ]
        rows.append("\t".join(row))
    return "\n".join(rows) + "\n"


def format_sheet_summary_text(
    results: list[tuple[Path, SheetClassification]],
    total_excel_files: int,
    skipped_files_count: int,
) -> str:
    """Format sheet classification results as human-readable text."""
    lines = [
        "============================================================",
        "             Supplementary Files MIC Scan Report",
        "============================================================",
        f"Scanned {total_excel_files} Excel file(s) ({len(results)} sheet(s) evaluated).",
    ]
    if skipped_files_count > 0:
        lines.append(f"Note: {skipped_files_count} non-Excel file(s) were not evaluated.")
    lines.append("------------------------------------------------------------")

    if not results:
        lines.append("No Excel files or sheets found to evaluate.")
        lines.append("============================================================")
        return "\n".join(lines) + "\n"

    any_mic = False
    for file_path, c in results:
        has_mic = "YES" if c.has_mic_values else "NO"
        has_ast = "YES" if c.contains_ast_data else "NO"
        has_sir = "YES" if c.has_sir_calls else "NO"
        if c.has_mic_values:
            any_mic = True
        lines.append(f"File:  {file_path.name}")
        lines.append(f"Sheet: {c.sheet_name}")
        lines.append(f"AST:   {has_ast} | MIC: {has_mic} | SIR: {has_sir}")
        if c.reasoning:
            lines.append(f"Note:  {c.reasoning}")
        lines.append("------------------------------------------------------------")

    lines.append(f"Overall Result: MIC data {'FOUND' if any_mic else 'NOT FOUND'}")
    lines.append("============================================================")
    return "\n".join(lines) + "\n"


def format_mic_data_tsv(records: list[tuple[Path, str, ASTExtractionRecord]]) -> str:
    """Format extracted AST records as TSV."""
    headers = [
        "file_name",
        "sheet_name",
        "pubmed_id",
        "isolate_name",
        "accession",
        "accession_type",
        "organism",
        "drug_raw",
        "mic_operator",
        "mic_value",
        "sir_call",
    ]
    rows = ["\t".join(headers)]
    for file_path, sheet_name, r in records:
        row = [
            file_path.name,
            sheet_name,
            r.pubmed_id or "",
            r.isolate_name or "",
            r.accession or "",
            r.accession_type or "",
            r.organism or "",
            r.drug_raw or "",
            r.mic_operator or "",
            r.mic_value or "",
            r.sir_call or "",
        ]
        rows.append("\t".join(row))
    return "\n".join(rows) + "\n"


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Scan supplementary files in a directory to detect and extract MIC/AST data."
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Path to directory containing supplementary files.",
    )
    parser.add_argument(
        "--tsv",
        action="store_true",
        help="Output sheet classification summary as TSV.",
    )
    parser.add_argument(
        "--mic_data",
        type=Path,
        nargs="?",
        const=DEFAULT_MIC_DATA_FILE,
        default=DEFAULT_MIC_DATA_FILE,
        metavar="FILE",
        help=f"Extract and write full AST records as TSV to the specified file (default: {DEFAULT_MIC_DATA_FILE}).",
    )
    parser.add_argument(
        "--no_mic_data",
        action="store_true",
        help="Disable automatic extraction and writing of MIC data.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        nargs="?",
        const=DEFAULT_LOG_FILE,
        default=DEFAULT_LOG_FILE,
        metavar="FILE",
        help=f"Log file to record chosen extraction strategy and decisions (default: {DEFAULT_LOG_FILE}).",
    )
    parser.add_argument(
        "--no_log",
        action="store_true",
        help="Disable writing extraction strategy log.",
    )
    parser.add_argument(
        "--pmid",
        type=str,
        default=None,
        help="PubMed ID (default: inferred from directory path or 'UNKNOWN').",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Scan directory recursively for supplementary files.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write sheet scan report to a file instead of stdout.",
    )
    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    args = parse_args(argv)

    if args.no_mic_data:
        args.mic_data = None
    if args.no_log:
        args.log = None

    if not args.directory.exists() or not args.directory.is_dir():
        sys.stderr.write(f"Error: Directory does not exist: {args.directory}\n")
        return 1

    pmid = args.pmid or infer_pmid_from_path(args.directory)
    excel_files, skipped_files = discover_files(args.directory, recursive=args.recursive)

    if skipped_files:
        sys.stderr.write(
            f"WARNING: Skipped {len(skipped_files)} non-Excel file(s) (only .xlsx/.xls supported)\n"
        )

    sheet_results: list[tuple[Path, SheetClassification]] = []
    ast_records: list[tuple[Path, str, ASTExtractionRecord]] = []
    strategy_logs: list[str] = []

    for excel_path in excel_files:
        try:
            classifications = classify_sheets(excel_path=excel_path, query_fn=query_structured)
        except Exception as e:
            sys.stderr.write(f"Error classifying {excel_path.name}: {e}\n")
            continue

        for c in classifications:
            sheet_results.append((excel_path, c))

            if args.mic_data and c.has_mic_values:
                try:
                    col_map = map_columns(
                        excel_path=excel_path,
                        sheet_name=c.sheet_name,
                        query_fn=query_structured,
                    )
                    records = extract_ast_records(
                        excel_path=excel_path,
                        sheet_name=c.sheet_name,
                        column_map=col_map,
                        pubmed_id=pmid,
                    )
                    for r in records:
                        ast_records.append((excel_path, c.sheet_name, r))

                    if args.log:
                        strategy_logs.append(
                            format_strategy_log(
                                excel_path=excel_path,
                                sheet_name=c.sheet_name,
                                classification=c,
                                column_map=col_map,
                                records_count=len(records),
                            )
                        )
                except Exception as e:
                    sys.stderr.write(
                        f"Error extracting records from {excel_path.name} [{c.sheet_name}]: {e}\n"
                    )
            elif args.log:
                strategy_logs.append(
                    format_strategy_log(
                        excel_path=excel_path,
                        sheet_name=c.sheet_name,
                        classification=c,
                    )
                )

    # If --mic_data was specified, write extracted AST records to the target file
    if args.mic_data:
        ast_tsv = format_mic_data_tsv(ast_records)
        args.mic_data.write_text(ast_tsv, encoding="utf-8")

    # If --log was specified, write the extraction strategy report
    if args.log and strategy_logs:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_header = (
            "============================================================\n"
            "   AMR Evidence Extraction Strategy Log\n"
            f"   Timestamp: {timestamp}\n"
            f"   Directory: {args.directory.resolve()}\n"
            "============================================================\n\n"
        )
        args.log.write_text(log_header + "\n".join(strategy_logs), encoding="utf-8")

    # Output the sheet scan summary
    if args.tsv:
        output_text = format_sheet_summary_tsv(sheet_results)
    else:
        output_text = format_sheet_summary_text(
            sheet_results,
            total_excel_files=len(excel_files),
            skipped_files_count=len(skipped_files),
        )

    if args.output:
        args.output.write_text(output_text, encoding="utf-8")
    else:
        sys.stdout.write(output_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
