#!/usr/bin/env python3
"""Run the same LLM code-gen AST extraction used by extract_excel_codegen.py, but against the
already-extracted main-text AST tables under <ast-finder output>/ast_tables/<pmid>/*.tsv instead
of downloaded Excel supplements.

Background: find_ast_evidence.py's step 4 pulls any main-text tables that look AST-related out of
each paper's PMC full-text XML and saves each one as its own TSV under
ast_tables/<pmid>/<table_label>.tsv (a '# <caption>' comment line, then a real header row). This
script feeds each of those TSVs through the same LLM-generated-pandas-code approach as
extract_excel_codegen.py: ask the model to write a transform_sheet(df) function that reshapes
whatever's in the table into the same long-format schema used for supplement extraction
(isolate_id, accession columns, drug, mic_sign, mic, sir_call, notes), execute that code locally,
QC-validate the result (retrying once with the QC errors fed back if anything fails), and write
the combined output as a TSV.

IMPORTANT CAVEATS:
  1. Unlike the raw per-isolate spreadsheets extract_excel_codegen.py usually sees, many
     main-text AST tables are already-aggregated summaries (accuracy/concordance stats per drug,
     resistant-vs-susceptible counts per species, etc.) with no per-isolate ID or accession at
     all. The QC rules here (same ones extract_excel_codegen.py uses) require every record to
     have an isolate_id or accession, so a purely aggregate table will legitimately produce zero
     valid records -- that's an accurate reflection of the source table, not a bug in this script.
  2. The accession columns (bioproject_accession, biosample_accession, assembly_accession,
     genbank_accessions, refseq_accessions, sra_accession, other_accessions) will be empty in
     EVERY row this script produces, even for tables that extract real per-isolate records --
     journal main-text tables report strain names / clinical data, not deposited-database
     identifiers. Those live in the paper's Data Availability statement / supplementary files
     instead. Two ways to fill them in afterward: extract_excel_codegen.py against a downloaded
     supplement, if one has accessions in it, or
     scripts/query_pmids_to_find_ast/match_isolates_to_biosample.py, which resolves the
     BioProject accession find_ast_evidence.py already found for a PMID against NCBI and matches
     BioSample strain names to this script's isolate_id values (see that script's docstring).

USAGE
    # Batch mode (default): process every PMID folder under --tables-root, writing one output
    # TSV per PMID into --outdir. Just running it with no arguments processes the same
    # ast_tables/ -> andrew_ast/ pair find_ast_evidence.py and extract_excel_codegen.py already
    # use in this repo:
    python scripts/ast_tables_codegen/extract_ast_tables_codegen.py

    # Same, but explicit:
    python scripts/ast_tables_codegen/extract_ast_tables_codegen.py \\
        --tables-root scripts/query_pmids_to_find_ast/output/ast_tables \\
        --outdir data/andrew_ast

    # Single PMID's table folder only (mirrors extract_excel_codegen.py's --supp-dir):
    python scripts/ast_tables_codegen/extract_ast_tables_codegen.py \\
        --tables-dir scripts/query_pmids_to_find_ast/output/ast_tables/29729180 \\
        -o data/andrew_ast/29729180.ast_tables.tsv

    # A single table file:
    python scripts/ast_tables_codegen/extract_ast_tables_codegen.py \\
        scripts/query_pmids_to_find_ast/output/ast_tables/29729180/Table_2.tsv \\
        -o data/andrew_ast/29729180.table2.tsv

OUTPUT
    One TSV per PMID (batch mode: <outdir>/<pmid>.ast_tables.tsv), using the same
    EXPECTED_OUTPUT_COLUMNS schema as extract_excel_codegen.py's andrew_ast/<pmid>.mic.tsv files,
    so the two are safe to concatenate/compare. Batch mode also writes
    <outdir>/<pmid>.transform_code.py per PMID with the LLM-generated pandas code, for
    inspection/debugging, same as extract_excel_codegen.py's --save-code.

REQUIRES
    GOOGLE_API_KEY (same as extract_excel_codegen.py -- this reuses that module's Gemini client
    and prompt/QC logic directly rather than amr_extraction.llm's provider dispatch, so
    --llm-provider/ollama support from find_ast_evidence.py does not apply here).
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Add src/ to sys.path so this runs standalone without `pip install -e .` first, same convention
# as find_ast_evidence.py.
_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import amr_extraction.llm  # noqa: F401  (side effect: auto-loads .env for GOOGLE_API_KEY)
from google import genai

from amr_extraction.extract_excel_codegen import (
    DEFAULT_ANTIBIOTICS_PATH,
    execute_generated_code,
    extract_pmid_from_paths,
    finalize_extracted_dataframe,
    generate_transformation_code,
    load_antibiotics_list,
    validate_extracted_records,
)

DEFAULT_TABLES_ROOT = "scripts/query_pmids_to_find_ast/output/ast_tables"
DEFAULT_OUTDIR = "data/andrew_ast"
DEFAULT_SINGLE_OUTPUT = "gemini_ast_tables_codegen.tsv"


def read_ast_table(path: str) -> tuple[pd.DataFrame, Optional[str]]:
    """Reads one ast_tables/<pmid>/<label>.tsv file. These are written by
    find_ast_evidence.py's extract_tables_from_xml() with a leading '# <caption>' comment line
    before the real header row, so this skips any leading '#'-prefixed lines (collecting the
    first one as the table's caption, useful context for the LLM prompt) before handing the rest
    to pandas.

    A number of these tables also have a SECOND non-'#' line that is a merged/spanning
    sub-header artifact from the original HTML/XML table (e.g. a lone "MIC (µg/mL)" label that
    spans many drug columns, represented here as mostly-empty tab-separated cells). That line
    has far fewer tab-separated fields than the real per-column header directly below it.
    pandas silently mis-parses that mismatch -- rather than raising, it can shove the real
    header's extra fields into the DataFrame's index instead of turning them into columns,
    which hides the isolate/strain-name column from every downstream consumer (observed in the
    wild: an isolate_id column full of generic "isolate_1".."isolate_17" placeholders instead
    of the real strain names, because the LLM never saw a 'Strain' column to map from -- see
    git history / PR discussion for the concrete case).

    Detect and skip exactly ONE such short leading line, and only when doing so lines the next
    line's width up with the data rows that follow it. This is intentionally conservative: a few
    tables here have a genuine two-row header (two real, differently-shaped label rows, e.g. a
    top-level grouping row like 'Etest | PAP-AUC' over per-column sub-labels) that this same
    'shorter than what follows' pattern would also match, but skipping there would need to merge
    two header rows, not discard one -- so this leaves those alone and lets them fall through to
    pandas' own ragged-row error (caught by the caller) rather than risk quietly eating a real
    data row as a fake header.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    caption: Optional[str] = None
    idx = 0
    while idx < len(lines) and lines[idx].lstrip().startswith("#"):
        if caption is None:
            caption = lines[idx].lstrip("#").strip()
        idx += 1

    remaining = lines[idx:]
    non_blank = [line for line in remaining if line.strip()]
    if len(non_blank) >= 3:
        counts = [line.count("\t") + 1 for line in non_blank[:3]]
        header_count, next_count, data_count = counts
        if header_count < next_count and next_count == data_count:
            skipped = 0
            for line in remaining:
                skipped += 1
                if line.strip():
                    break
            idx += skipped

    skip = idx
    df = pd.read_csv(path, sep="\t", skiprows=skip)
    return df, caption


# str(nan) and str(inf)/str(-inf) are valid tokens in Python's repr() of a tuple/list containing
# a float NaN or infinity (e.g. str((x, float("nan")))), but they are NOT valid `ast` literal
# syntax on their own -- ast.literal_eval("(1, nan)") raises SyntaxError even though the string
# genuinely is a dumped collection. Neutralize them (quote them) before the fallback parse so
# real-world rows with missing/NaN values don't slip past this check.
_BARE_NAN_RE = re.compile(r"(?<![\w.])nan(?![\w])")
_BARE_INF_RE = re.compile(r"(?<![\w.])-?inf(?![\w])")


def _looks_like_dumped_collection(val) -> bool:
    """True if val is a string that itself looks like the repr of a Python tuple/list/dict --
    a sign the LLM's generated transform code accidentally assigned an entire row (or a slice
    of one) to a single field instead of a single scalar value (observed in the wild: an
    isolate_id column filled with strings like "('KG-03', '24', '0.5', ...)" or, with a missing
    value in the mix, "('N315', nan, '1', '0.5', ...)"). Caught here as an extra QC pass beyond
    validate_extracted_records(), which only checks that isolate_id/accession are non-blank, not
    that they're a sane shape."""
    if val is None:
        return False
    s = str(val).strip()
    if len(s) < 2 or s[0] not in "([{" or s[-1] not in ")]}":
        return False

    def _try_parse(text: str) -> bool:
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return False
        return isinstance(parsed, (tuple, list, dict))

    if _try_parse(s):
        return True

    # Fallback: neutralize bare nan/inf tokens (invalid `ast` literal syntax, but valid inside a
    # real Python repr) and retry, so a tuple/list containing a NaN is still recognized.
    neutralized = _BARE_NAN_RE.sub("'nan'", s)
    neutralized = _BARE_INF_RE.sub("'inf'", neutralized)
    if neutralized != s:
        return _try_parse(neutralized)
    return False


def _normalize_numeric_id(val):
    """Strips the spurious trailing '.0' pandas adds when a numeric-looking ID column gets cast
    to float (e.g. an isolate_id column containing 105 becomes '105.0' after a groupby/melt),
    so IDs read the way they would in the source table."""
    if val is None:
        return val
    s = str(val).strip()
    m = re.match(r"^(\d+)\.0$", s)
    return m.group(1) if m else val


def process_pmid_tables(
    tables_dir: str,
    output_tsv: str,
    client: "genai.Client",
    token_tracker: dict,
    antibiotics_list: list[str],
    pmid: Optional[str] = None,
    save_code_path: Optional[str] = None,
    only_filename: Optional[str] = None,
) -> int:
    """Runs the code-gen transform on every *.tsv AST table in tables_dir (or just
    only_filename, if given), combines the valid results, and writes output_tsv.

    Returns the number of valid records written (0 if none, in which case no file is written).
    """
    resolved_pmid = pmid or extract_pmid_from_paths(supp_dir=tables_dir)

    if only_filename:
        table_files = [only_filename]
    else:
        table_files = sorted(
            f for f in os.listdir(tables_dir)
            if f.lower().endswith(".tsv") and not f.startswith((".", "~$"))
        )

    if not table_files:
        print(f"[!] No .tsv table files found in '{tables_dir}'.", file=sys.stderr)
        return 0

    all_dfs: list[pd.DataFrame] = []
    generated_scripts: dict[str, str] = {}

    for fname in table_files:
        fpath = os.path.join(tables_dir, fname)
        table_label = os.path.splitext(fname)[0]
        print(f"\n--- Table: '{fname}' ---", flush=True)

        try:
            full_df, caption = read_ast_table(fpath)
        except Exception as e:
            print(f"[!] Error reading '{fname}': {e}", file=sys.stderr)
            continue

        if full_df.empty or len(full_df.columns) < 2:
            print(f"[*] Skipping '{fname}': empty or not a real table.", flush=True)
            continue

        print(
            f"[+] Loaded {len(full_df)} rows and {len(full_df.columns)} columns."
            + (f" Caption: {caption}" if caption else ""),
            flush=True,
        )
        prompt_label = f"{table_label} ({caption})" if caption else table_label

        max_attempts = 2
        table_valid_df = None
        last_code = None
        qc_errors = None
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                print(f"[*] [Retry {attempt}/{max_attempts}] Regenerating transformation code...", flush=True)
            else:
                print(f"[*] [Attempt {attempt}/{max_attempts}] Generating transformation code...", flush=True)

            code = generate_transformation_code(
                prompt_label, full_df, client, token_tracker,
                previous_errors=qc_errors, antibiotics_list=antibiotics_list,
            )
            last_code = code

            try:
                raw_df = execute_generated_code(code, full_df)
            except Exception as err:
                print(f"[!] Error executing generated code for '{fname}': {err}", file=sys.stderr)
                qc_errors = [f"Code execution raised exception: {err}"]
                continue

            # Normalize numeric-ID float artifacts (105 -> '105.0' -> '105') before QC.
            if "isolate_id" in raw_df.columns:
                raw_df["isolate_id"] = raw_df["isolate_id"].apply(_normalize_numeric_id)

            valid_df, invalid_df, errors = validate_extracted_records(raw_df)

            # Extra QC beyond validate_extracted_records(): catch the LLM occasionally dumping
            # an entire row (as a tuple/list/dict repr) into isolate_id or accession instead of
            # a single scalar value -- validate_extracted_records only checks non-blank, not shape.
            if not valid_df.empty:
                dumped_mask = valid_df.apply(
                    lambda r: _looks_like_dumped_collection(r.get("isolate_id"))
                    or _looks_like_dumped_collection(r.get("accession")),
                    axis=1,
                )
                if dumped_mask.any():
                    bad_rows = valid_df[dumped_mask]
                    valid_df = valid_df[~dumped_mask].reset_index(drop=True)
                    invalid_df = pd.concat([invalid_df, bad_rows], ignore_index=True)
                    errors = list(errors) + [
                        f"Row: isolate_id/accession looks like a dumped Python tuple/list/dict "
                        f"('{r.get('isolate_id')}') instead of a single value -- the generated "
                        f"code likely assigned an entire row/slice instead of one field"
                        for _, r in bad_rows.iterrows()
                    ]

            if len(invalid_df) == 0:
                print(f"[OK] All {len(valid_df)} extracted record(s) passed QC.", flush=True)
                table_valid_df = valid_df
                break

            qc_errors = errors
            print(f"[!] QC found {len(invalid_df)} invalid record(s) of {len(raw_df)}.", flush=True)
            if attempt < max_attempts:
                print("[*] Retrying with QC error feedback...", flush=True)
            else:
                print("[!] Sample QC failure reasons:", file=sys.stderr)
                for err_msg in errors[:5]:
                    print(f"    - {err_msg}", file=sys.stderr)
                print(
                    f"[*] Omitted {len(invalid_df)} invalid record(s); retaining "
                    f"{len(valid_df)} valid record(s).",
                    flush=True,
                )
                table_valid_df = valid_df

        generated_scripts[fname] = last_code or ""

        if table_valid_df is not None and not table_valid_df.empty:
            tdf = table_valid_df.copy()
            tdf.insert(0, "sheet_name", table_label)
            tdf.insert(0, "file_name", fname)
            all_dfs.append(tdf)
        elif table_valid_df is not None:
            print(
                f"[!] No valid records retained for '{fname}' -- often expected: many main-text "
                f"AST tables are aggregate summaries without per-isolate IDs, which the QC rules "
                f"require (see this script's module docstring).",
                file=sys.stderr,
            )

    if not all_dfs:
        print(f"[!] No valid AST records extracted from any table in '{tables_dir}'.", file=sys.stderr)
        return 0

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = finalize_extracted_dataframe(combined, pmid=resolved_pmid)

    out_dir = os.path.dirname(output_tsv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    combined.to_csv(output_tsv, sep="\t", index=False, na_rep="")
    print(f"[OK] Wrote {len(combined)} record(s) to '{output_tsv}'", flush=True)

    if save_code_path and generated_scripts:
        with open(save_code_path, "w") as f:
            for name, code in generated_scripts.items():
                f.write(f"# {'=' * 60}\n# Transformation code for table: '{name}'\n# {'=' * 60}\n\n")
                f.write(code + "\n\n")
        print(f"[OK] Saved generated transform code to '{save_code_path}'", flush=True)

    return len(combined)


def run_batch(tables_root: str, outdir: str, client: "genai.Client", token_tracker: dict, antibiotics_list: list[str]) -> None:
    if not os.path.isdir(tables_root):
        print(f"[!] --tables-root not found: '{tables_root}'", file=sys.stderr)
        sys.exit(1)

    pmid_dirs = sorted(
        d for d in os.listdir(tables_root)
        if os.path.isdir(os.path.join(tables_root, d)) and not d.startswith(".")
    )
    if not pmid_dirs:
        print(f"[!] No PMID subfolders found under '{tables_root}'.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(outdir, exist_ok=True)

    total = 0
    wrote_records = 0
    empty = 0
    errored: list[str] = []

    for pmid in pmid_dirs:
        pmid_dir = os.path.join(tables_root, pmid)
        has_tsv = any(f.lower().endswith(".tsv") for f in os.listdir(pmid_dir))
        if not has_tsv:
            continue

        total += 1
        print(f"\n{'=' * 60}\n[*] PMID {pmid} ({total}/? folders with .tsv files)\n{'=' * 60}", flush=True)

        out_tsv = os.path.join(outdir, f"{pmid}.ast_tables.tsv")
        save_code = os.path.join(outdir, f"{pmid}.transform_code.py")
        try:
            n = process_pmid_tables(
                tables_dir=pmid_dir,
                output_tsv=out_tsv,
                client=client,
                token_tracker=token_tracker,
                antibiotics_list=antibiotics_list,
                pmid=pmid,
                save_code_path=save_code,
            )
        except Exception as e:  # noqa: BLE001 - one bad PMID should not kill the whole batch
            print(f"[!] PMID {pmid} failed: {e}", file=sys.stderr)
            errored.append(pmid)
            continue

        if n > 0:
            wrote_records += n
        else:
            empty += 1

    print(f"\n{'=' * 60}")
    print("BATCH SUMMARY")
    print(f"{'=' * 60}")
    print(f"  PMID folders with .tsv tables: {total}")
    print(f"  Produced output (>=1 valid record): {total - empty - len(errored)}")
    print(f"  No valid records (see caveat in module docstring): {empty}")
    print(f"  Errored: {len(errored)}" + (f" ({', '.join(errored)})" if errored else ""))
    print(f"  Total valid records written across all PMIDs: {wrote_records}")
    print(f"{'=' * 60}\n")


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "table", nargs="?", default=None,
        help="Path to a single ast_tables/<pmid>/<label>.tsv file to process (optional if "
             "--tables-dir or --tables-root is used instead).",
    )
    parser.add_argument("-o", "--output", default=None, help=f"Output TSV file for single-table/--tables-dir mode (default: {DEFAULT_SINGLE_OUTPUT})")
    parser.add_argument("--save-code", default=None, help="File to save generated Python code to, for single-table/--tables-dir mode")
    parser.add_argument("--tables-dir", default=None, help="Directory containing one PMID's already-extracted *.tsv AST tables (mirrors extract_excel_codegen.py's --supp-dir)")
    parser.add_argument("--tables-root", default=None, metavar="DIR", help=f"Batch mode: root directory of <pmid>/ subfolders to process (default when no other mode is given: {DEFAULT_TABLES_ROOT})")
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR, help=f"Batch mode output directory, one <pmid>.ast_tables.tsv per PMID (default: {DEFAULT_OUTDIR})")
    parser.add_argument("--antibiotics-list", default=None, help="Path to a text file containing standard antibiotic names (one per line)")
    parser.add_argument("--pmid", default=None, help="Override PMID (single-table/--tables-dir mode only; otherwise inferred from the path)")
    return parser


def main() -> None:
    parser = build_cli_parser()
    args = parser.parse_args()

    antibiotics_path = args.antibiotics_list if args.antibiotics_list is not None else DEFAULT_ANTIBIOTICS_PATH
    antibiotics_list = load_antibiotics_list(antibiotics_path)
    print(f"[*] Loaded {len(antibiotics_list)} standard antibiotics from '{antibiotics_path}'", flush=True)

    print("[*] Initializing Gemini client...", flush=True)
    client = genai.Client()
    token_tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    if args.table:
        tables_dir = os.path.dirname(os.path.abspath(args.table)) or "."
        only_filename = os.path.basename(args.table)
        output_tsv = args.output or DEFAULT_SINGLE_OUTPUT
        process_pmid_tables(
            tables_dir=tables_dir, output_tsv=output_tsv, client=client,
            token_tracker=token_tracker, antibiotics_list=antibiotics_list,
            pmid=args.pmid, save_code_path=args.save_code, only_filename=only_filename,
        )
    elif args.tables_dir:
        output_tsv = args.output or DEFAULT_SINGLE_OUTPUT
        process_pmid_tables(
            tables_dir=args.tables_dir, output_tsv=output_tsv, client=client,
            token_tracker=token_tracker, antibiotics_list=antibiotics_list,
            pmid=args.pmid, save_code_path=args.save_code,
        )
    else:
        tables_root = args.tables_root or DEFAULT_TABLES_ROOT
        run_batch(tables_root, args.outdir, client, token_tracker, antibiotics_list)
        return

    total_tokens = token_tracker["input_tokens"] + token_tracker["output_tokens"]
    print("\n" + "=" * 55)
    print("PERFORMANCE & TOKEN USAGE REPORT (CODE GENERATION)")
    print("=" * 55)
    print(f"  Total LLM Calls:   {token_tracker['calls']}")
    print(f"  Input Tokens:      {token_tracker['input_tokens']:,}")
    print(f"  Output Tokens:     {token_tracker['output_tokens']:,}")
    print(f"  Total Tokens:      {total_tokens:,}")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
