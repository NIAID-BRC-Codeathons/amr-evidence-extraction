#!/usr/bin/env python3
import argparse
import os
import re
import sys
import time
import pandas as pd
from typing import List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Pydantic schema for sheet discovery
# ---------------------------------------------------------------------------
class SheetSelection(BaseModel):
    sheet_name: str = Field(description="Name of the worksheet")
    contains_ast_data: bool = Field(
        description="True if sheet contains AST / antibiotic testing data (either quantitative MIC values or qualitative SIR interpretations)."
    )
    has_mic_values: bool = Field(
        description="True if sheet contains numeric or dilution MIC values (e.g. '4', '<=0.5', '32/16')."
    )
    has_sir_calls: bool = Field(
        description="True if sheet contains qualitative susceptibility interpretations ('S', 'I', 'R', 'Resistant', 'Susceptible', 'Intermediate')."
    )
    reasoning: str = Field(description="Brief explanation of the sheet contents and AST columns")

class WorkbookDiscovery(BaseModel):
    selected_sheets: List[SheetSelection] = Field(description="Assessment of all sheets in workbook")


def classify_single_sheet(
    sheet_name: str,
    preview_df: pd.DataFrame,
    client: genai.Client,
    token_tracker: dict
) -> SheetSelection:
    """Evaluates a single worksheet preview to classify whether it contains AST data (MIC or SIR)."""
    csv_sample = preview_df.head(8).to_csv(index=False)
    columns_list = list(preview_df.columns)

    prompt = f"""You are an expert bioinformatician evaluating a worksheet from an AST (antimicrobial susceptibility testing) Excel workbook.
Determine whether this sheet contains Antimicrobial Susceptibility Testing (AST) data, including quantitative MIC values and/or qualitative SIR calls.

Sheet Name: '{sheet_name}'
Column Names: {columns_list}
Data Preview (first 8 rows):
{csv_sample}

CRITERIA:
1. contains_ast_data = TRUE if the sheet has isolate measurements for antibiotics/antimicrobial drugs (either MIC values, SIR categories, or both).
2. has_mic_values = TRUE if antibiotic columns contain numeric or dilution values (e.g. '4', '0.25', '<=0.5', '>64', '32/16').
3. has_sir_calls = TRUE if antibiotic columns contain clinical interpretations (e.g. 'S', 'I', 'R', 'Susceptible', 'Resistant', 'Intermediate').
4. contains_ast_data = FALSE for general metadata, sample manifests, patient demographics, genomic metrics, QC tables, or summary statistics.

Explain your reasoning clearly in 'reasoning'.
"""

    t0 = time.time()
    response = client.models.generate_content(
        model="models/gemini-3.7-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SheetSelection,
            temperature=0.0,
        ),
    )
    elapsed = time.time() - t0

    in_tok = response.usage_metadata.prompt_token_count or 0 if response.usage_metadata else 0
    out_tok = response.usage_metadata.candidates_token_count or 0 if response.usage_metadata else 0
    token_tracker["calls"] += 1
    token_tracker["input_tokens"] += in_tok
    token_tracker["output_tokens"] += out_tok

    selection: SheetSelection = response.parsed
    selection.sheet_name = sheet_name

    if selection.has_mic_values and selection.has_sir_calls:
        status_tag = "[+] MIC + SIR  "
    elif selection.has_mic_values:
        status_tag = "[+] MIC VALUES "
    elif selection.has_sir_calls or selection.contains_ast_data:
        status_tag = "[+] SIR-ONLY   "
    else:
        status_tag = "[-] SKIPPED    "

    print(
        f"[{status_tag}] '{sheet_name}' ({elapsed:.1f}s, {in_tok + out_tok} tok) -> {selection.reasoning}",
        flush=True
    )

    return selection


def discover_relevant_sheets(excel_path: str, client: genai.Client, token_tracker: dict) -> List[str]:
    """Inspects and classifies each sheet in real-time, reporting classifications as they are determined.
    Prefers sheets with quantitative MIC data if present; otherwise collects SIR-only sheets."""
    excel_file = pd.ExcelFile(excel_path)
    sheet_names = excel_file.sheet_names

    print(f"[*] Discovering relevant sheets in workbook ({len(sheet_names)} total sheets)...", flush=True)

    mic_sheets = []
    sir_sheets = []

    for idx, name in enumerate(sheet_names, start=1):
        print(f"[*] [{idx}/{len(sheet_names)}] Inspecting sheet '{name}'...", end=" ", flush=True)
        try:
            sample_df = pd.read_excel(excel_file, sheet_name=name, nrows=8)
            selection = classify_single_sheet(name, sample_df, client, token_tracker)
            if selection.has_mic_values:
                mic_sheets.append(name)
            elif selection.contains_ast_data or selection.has_sir_calls:
                sir_sheets.append(name)
        except Exception as e:
            print(f"[!] Error previewing sheet '{name}': {e}", flush=True)

    if mic_sheets:
        print(f"[+] Selected {len(mic_sheets)} sheet(s) with MIC data (and any associated SIR calls): {mic_sheets}\n", flush=True)
        return mic_sheets
    elif sir_sheets:
        print(f"[*] No quantitative MIC sheets found. Collecting {len(sir_sheets)} sheet(s) with SIR calls: {sir_sheets}\n", flush=True)
        return sir_sheets
    else:
        print(f"[!] Discovery complete: No AST (MIC or SIR) data found in workbook.\n", flush=True)
        return []


EXPECTED_OUTPUT_COLUMNS = [
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


def build_transformation_prompt(sheet_name: str, preview_df: pd.DataFrame) -> str:
    """Build the LLM prompt to generate transformation code for an AST sheet."""
    csv_sample = preview_df.head(8).to_csv(index=False)
    columns_list = list(preview_df.columns)

    return f"""You are an expert Python data engineer writing robust Pandas transformation code for bioinformatics.
Given the sample structure and top rows of an AST (antimicrobial susceptibility testing) Excel worksheet:

Sheet Name: '{sheet_name}'
Column Names: {columns_list}
Data Preview (first 8 rows):
{csv_sample}

Task:
Write a Python function named `transform_sheet(df: pd.DataFrame) -> pd.DataFrame` that extracts all AST isolate measurements into a standardized unpivoted format with both MIC values and SIR calls.

Requirements:
1. Identify the sample / isolate ID column (e.g. Specimen number, Strain name, Sample ID, Patient isolate ID, etc.) and map to 'isolate_id'. Leave blank (or None) if missing.
2. Extract the 'accession' column:
   - Identify public repository accessions (e.g., BioSample accessions like SAMN*, SAMEA*, SAMD*, SRS*, or GenBank/ENA/DDBJ assembly/run accessions like GCA_*, GCF_*, ERR*, SRR*).
   - IMPORTANT: Do NOT fall back to using the isolate identifier. If no public database accession exists, leave 'accession' blank (None or np.nan).
3. Identify all antibiotic / antimicrobial testing columns. Ignore non-AST metadata columns (patient demographics, date, source, species, QC, etc.).
4. Unpivot (melt) the drug columns into long format, setting the drug name to 'drug'.
5. Parse the measurement values per isolate and drug:
   - 'mic_sign': Inequality sign ('<', '<=', '>', '>=', '='). If a numeric MIC has no prefix symbol (e.g. '4', '0.25', '32/16'), set 'mic_sign' to '='. If there is no numeric MIC (e.g. SIR-only cell), set to None (or np.nan).
   - 'mic': The clean numeric MIC value or combination ratio string (e.g., '32/16', '0.25/4.75', '4', '0.5'). If cell only contains qualitative SIR call (e.g. 'S', 'I', 'R'), set to None (or np.nan).
   - 'sir_call': Qualitative interpretation call normalized to standard categories: 'S', 'I', 'R', 'SDD', or 'NS'. If a cell contains both MIC and SIR (e.g., '4 (R)' or separate columns), extract and normalize the SIR call into this column. If no SIR call is present or determinable, set to None (or np.nan).
   - 'notes': If a numeric MIC was present without an inequality prefix and you assigned 'mic_sign' to '=', record "mic_sign '=' inferred". If an explicit inequality sign was already present or no numeric MIC exists, leave 'notes' blank (None or np.nan).
   - Discard rows where BOTH 'mic' and 'sir_call' are empty/missing/NaN/uninterpretable (e.g., 'ND', 'N/A', '-').
6. Return a pandas DataFrame with exactly these columns:
   ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']

Rules for output:
- Return ONLY executable Python code (inside ```python ... ``` block).
- Do not call the function in the snippet, just define `transform_sheet(df: pd.DataFrame) -> pd.DataFrame` and any helper functions/imports (`import re`, `import pandas as pd`, `import numpy as np`).
- Ensure the code handles mixed data types gracefully (convert cell values to string before regex matching or filtering).
"""


def generate_transformation_code(
    sheet_name: str,
    preview_df: pd.DataFrame,
    client: genai.Client,
    token_tracker: dict
) -> str:
    """Prompts Gemini to generate a pure Python transformation function for this table layout."""
    prompt = build_transformation_prompt(sheet_name, preview_df)

    print(f"[*] Requesting transformation code for sheet '{sheet_name}' from Gemini...", end=" ", flush=True)
    t0 = time.time()
    response = client.models.generate_content(
        model="models/gemini-3.7-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
        ),
    )
    elapsed = time.time() - t0

    in_tok = response.usage_metadata.prompt_token_count or 0 if response.usage_metadata else 0
    out_tok = response.usage_metadata.candidates_token_count or 0 if response.usage_metadata else 0
    token_tracker["calls"] += 1
    token_tracker["input_tokens"] += in_tok
    token_tracker["output_tokens"] += out_tok

    print(f"done in {elapsed:.1f}s | Tokens: {in_tok:,} in / {out_tok:,} out", flush=True)

    # Extract code from markdown fences if present
    code_text = response.text
    match = re.search(r"```(?:python)?\s*\n(.*?)\n```", code_text, re.DOTALL)
    if match:
        code_text = match.group(1)

    return code_text


def execute_generated_code(code_str: str, df: pd.DataFrame) -> pd.DataFrame:
    """Safely compiles and runs the generated transform_sheet function in a dedicated namespace."""
    local_scope = {"pd": pd, "np": pd.np if hasattr(pd, "np") else None}
    exec(code_str, local_scope)

    if "transform_sheet" not in local_scope:
        raise ValueError("Generated code did not contain a 'transform_sheet' function.")

    transform_fn = local_scope["transform_sheet"]
    result_df = transform_fn(df.copy())
    return result_df


def finalize_extracted_dataframe(df: pd.DataFrame, file_path: str, sheet_name: str) -> pd.DataFrame:
    """Prepends file_name and sheet_name and ensures all expected columns exist in order."""
    res = df.copy()
    base_file_name = os.path.basename(file_path)
    res.insert(0, "sheet_name", sheet_name)
    res.insert(0, "file_name", base_file_name)

    for col in EXPECTED_OUTPUT_COLUMNS:
        if col not in res.columns:
            res[col] = None

    return res[EXPECTED_OUTPUT_COLUMNS]


def process_excel_with_code_gen(
    excel_path: str,
    output_tsv: str = "gemini_ast_codegen.tsv",
    sheet_name: Optional[str] = None,
    save_code_path: Optional[str] = "generated_transform.py"
):
    token_tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    start_total_time = time.time()

    print("[*] Initializing Gemini client...", flush=True)
    client = genai.Client()

    excel_file = pd.ExcelFile(excel_path)

    # 1. Discover sheets
    if sheet_name:
        if sheet_name not in excel_file.sheet_names:
            print(f"[!] Error: Sheet '{sheet_name}' not found. Available: {excel_file.sheet_names}", file=sys.stderr)
            sys.exit(1)
        sheets_to_process = [sheet_name]
    else:
        sheets_to_process = discover_relevant_sheets(excel_path, client, token_tracker)

    if not sheets_to_process:
        print("[!] Notice: No worksheets with AST data (MIC or SIR) were found.", file=sys.stderr)
        print("[!] No output file generated.", file=sys.stderr)
        return

    all_extracted_dfs = []
    generated_scripts = {}

    # 2. For each relevant sheet, generate code & execute locally
    for cur_sheet in sheets_to_process:
        print(f"\n--- Sheet: '{cur_sheet}' ---", flush=True)
        print(f"[*] Reading full sheet data...", flush=True)
        full_df = pd.read_excel(excel_file, sheet_name=cur_sheet)
        print(f"[+] Loaded {len(full_df)} rows and {len(full_df.columns)} columns.", flush=True)

        # Generate transformation code via LLM
        code = generate_transformation_code(cur_sheet, full_df, client, token_tracker)
        generated_scripts[cur_sheet] = code

        # Run generated transformation locally
        print(f"[*] Executing transformation code locally on {len(full_df)} rows...", end=" ", flush=True)
        t_exec_start = time.time()
        try:
            transformed_df = execute_generated_code(code, full_df)
            t_exec_elapsed = time.time() - t_exec_start
            print(f"done in {t_exec_elapsed:.3f}s -> produced {len(transformed_df)} records.", flush=True)

            finalized_df = finalize_extracted_dataframe(transformed_df, excel_path, cur_sheet)
            all_extracted_dfs.append(finalized_df)
        except Exception as err:
            print(f"\n[!] Error executing generated code for sheet '{cur_sheet}': {err}", file=sys.stderr)
            print("\nGenerated Code was:\n", code, file=sys.stderr)

    if all_extracted_dfs:
        combined_df = pd.concat(all_extracted_dfs, ignore_index=True)
        combined_df.to_csv(output_tsv, sep="\t", index=False, na_rep="")
        print(f"\n[OK] Successfully wrote {len(combined_df)} total records to '{output_tsv}'", flush=True)

    # Save generated code to file for inspection / reuse
    if save_code_path and generated_scripts:
        with open(save_code_path, "w") as f:
            for s_name, s_code in generated_scripts.items():
                f.write(f"# ==========================================================\n")
                f.write(f"# Transformation Code for Sheet: '{s_name}'\n")
                f.write(f"# ==========================================================\n\n")
                f.write(s_code + "\n\n")
        print(f"[OK] Saved generated Python transformation script to '{save_code_path}'")

    total_time = time.time() - start_total_time
    total_tokens = token_tracker["input_tokens"] + token_tracker["output_tokens"]

    print("\n" + "=" * 55)
    print("PERFORMANCE & TOKEN USAGE REPORT (CODE GENERATION)")
    print("=" * 55)
    print(f"  Total Duration:    {total_time:.2f} seconds")
    print(f"  Total LLM Calls:   {token_tracker['calls']}")
    print(f"  Input Tokens:      {token_tracker['input_tokens']:,}")
    print(f"  Output Tokens:     {token_tracker['output_tokens']:,}")
    print(f"  Total Tokens:      {total_tokens:,}")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract AST records by using Gemini to synthesize and execute local Pandas transformation code."
    )
    parser.add_argument("excel_file", help="Path to the Excel file to process")
    parser.add_argument("-s", "--sheet", default=None, help="Specific sheet name to process (default: auto-discover AST sheets)")
    parser.add_argument("-o", "--output", default="gemini_ast_codegen.tsv", help="Output TSV file (default: gemini_ast_codegen.tsv)")
    parser.add_argument("--save-code", default="generated_transform.py", help="File to save generated Python code (default: generated_transform.py)")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    process_excel_with_code_gen(
        args.excel_file,
        output_tsv=args.output,
        sheet_name=args.sheet,
        save_code_path=args.save_code
    )
