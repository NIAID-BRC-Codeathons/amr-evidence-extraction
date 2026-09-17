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

from amr_extraction.excel_extractor import detect_header_row

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
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
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
            hdr = detect_header_row(excel_file, name)
            if hdr > 0:
                print(f"(header row {hdr})...", end=" ", flush=True)
            sample_df = pd.read_excel(excel_file, sheet_name=name, header=hdr, nrows=8)
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


VALID_MIC_SIGNS = {"=", ">", ">=", "<", "<="}
VALID_SIR_CALLS = {"S", "I", "R", "SDD", "NS"}
MIC_NUMERIC_PATTERN = re.compile(r"^\d+(\.\d+)?(/\d+(\.\d+)?)*$")

BIOSAMPLE_PATTERN = re.compile(r"^SAM(N|EA?|D)\d+(\.\d+)?$", re.IGNORECASE)
PUBLIC_ACCESSION_PATTERN = re.compile(r"(SAM[NED]\w*\d+|GC[AF]_\d+|[SED]RR\d+|[A-Z]{4,6}\d{6,8})", re.IGNORECASE)


def is_biosample_accession(val: Optional[str]) -> bool:
    """Returns True if the accession is a valid NCBI, EBI, or DDBJ BioSample accession."""
    if val is None or pd.isna(val):
        return False
    s = str(val).strip()
    return bool(BIOSAMPLE_PATTERN.match(s))


def needs_accession_enrichment(df: pd.DataFrame) -> bool:
    """Checks whether the extracted DataFrame has missing or non-BioSample accessions."""
    if df.empty or "accession" not in df.columns:
        return False
    for acc in df["accession"]:
        if not is_biosample_accession(acc):
            return True
    return False


def is_candidate_metadata_sheet(
    preview_df: pd.DataFrame,
    target_isolate_ids: set,
    target_accessions: set
) -> bool:
    """Checks if a sheet preview contains public accession patterns and overlaps with known identifiers."""
    if preview_df.empty:
        return False

    has_acc_col = False
    has_id_col = False

    clean_target_ids = {str(x).strip().lower() for x in target_isolate_ids if x and str(x).strip()}
    clean_target_accs = {str(x).strip().lower() for x in target_accessions if x and str(x).strip()}

    for col in preview_df.columns:
        vals = [str(v).strip() for v in preview_df[col].dropna() if str(v).strip()]
        if any(PUBLIC_ACCESSION_PATTERN.search(v) for v in vals):
            has_acc_col = True
        if any(v.lower() in clean_target_ids or v.lower() in clean_target_accs for v in vals):
            has_id_col = True

    return (has_acc_col and has_id_col) or (has_acc_col and len(preview_df) > 0 and len(clean_target_ids) > 0 and any(
        any(re.search(r"(sample|isolate|strain|cvm|specimen)", str(c).lower()) for c in preview_df.columns)
        for _ in [1]
    ))


def build_metadata_transformation_prompt(
    sheet_name: str,
    preview_df: pd.DataFrame
) -> str:
    """Build the LLM prompt to generate transformation code for an isolate metadata sheet."""
    csv_sample = preview_df.head(8).to_csv(index=False)
    columns_list = list(preview_df.columns)

    return f"""You are an expert Python data engineer writing robust Pandas transformation code for bioinformatics metadata.
Given the sample structure and top rows of a metadata / isolate accession worksheet:

Sheet Name: '{sheet_name}'
Column Names: {columns_list}
Data Preview (first 8 rows):
{csv_sample}

Task:
Write a Python function named `extract_metadata(df: pd.DataFrame) -> pd.DataFrame` that extracts mapping records between isolate identifiers and public database accessions.

Requirements:
1. Identify the isolate / sample ID column (e.g., Strain, Isolate ID, Sample ID, CVM_NUMBER, Lab ID, etc.) and map to 'isolate_id'.
2. Identify the public accession column:
   - Prioritize BioSample accessions (e.g., SAMN*, SAMEA*, SAMD*).
   - If no BioSample is present, use assembly accessions (GCA_*, GCF_*, WGS contigs) or SRA runs (ERR*, SRR*, DRR*).
   - Map this primary accession to 'accession'.
3. Identify secondary public accessions if the table contains multiple public IDs (e.g., GenBank/SRA run alongside BioSample):
   - Map this secondary public identifier to 'secondary_accession' (leave None if not present).
4. Discard rows where BOTH 'isolate_id' and 'accession' are missing/blank.
5. Return a pandas DataFrame with exactly these columns:
   ['isolate_id', 'accession', 'secondary_accession']

Rules for output:
- Return ONLY executable Python code (inside ```python ... ``` block).
- Do not call the function in the snippet, just define `extract_metadata(df: pd.DataFrame) -> pd.DataFrame` and any helper functions/imports (`import re`, `import pandas as pd`, `import numpy as np`).
- Ensure the code handles mixed data types gracefully (convert cell values to string before regex matching or filtering).
"""


def generate_metadata_code(
    sheet_name: str,
    preview_df: pd.DataFrame,
    client: genai.Client,
    token_tracker: dict
) -> str:
    """Prompts Gemini to generate a Python metadata extraction function for this table layout."""
    prompt = build_metadata_transformation_prompt(sheet_name, preview_df)

    print(f"[*] Requesting metadata extraction code for sheet '{sheet_name}' from Gemini...", end=" ", flush=True)
    t0 = time.time()
    response = client.models.generate_content(
        model="models/gemini-3.7-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    elapsed = time.time() - t0

    in_tok = response.usage_metadata.prompt_token_count or 0 if response.usage_metadata else 0
    out_tok = response.usage_metadata.candidates_token_count or 0 if response.usage_metadata else 0
    token_tracker["calls"] += 1
    token_tracker["input_tokens"] += in_tok
    token_tracker["output_tokens"] += out_tok

    print(f"done in {elapsed:.1f}s | Tokens: {in_tok:,} in / {out_tok:,} out", flush=True)

    code_text = response.text
    match = re.search(r"```(?:python)?\s*\n(.*?)\n```", code_text, re.DOTALL)
    if match:
        code_text = match.group(1)

    return code_text


def execute_metadata_code(code_str: str, df: pd.DataFrame) -> pd.DataFrame:
    """Safely compiles and runs the generated extract_metadata function in a dedicated namespace."""
    local_scope = {"pd": pd, "np": pd.np if hasattr(pd, "np") else None}
    exec(code_str, local_scope)

    if "extract_metadata" not in local_scope:
        raise ValueError("Generated code did not contain an 'extract_metadata' function.")

    extract_fn = local_scope["extract_metadata"]
    result_df = extract_fn(df.copy())
    return result_df


def enrich_ast_with_metadata(
    ast_df: pd.DataFrame,
    metadata_df: pd.DataFrame
) -> pd.DataFrame:
    """Enriches AST DataFrame with BioSample or assembly accessions from metadata mapping."""
    if ast_df.empty or metadata_df.empty:
        return ast_df.copy()

    res_df = ast_df.copy()

    # Build isolate_id -> accession map (first non-empty)
    iso_to_acc = {}
    for _, row in metadata_df.iterrows():
        iso = str(row.get("isolate_id", "")).strip() if pd.notna(row.get("isolate_id")) else ""
        acc = str(row.get("accession", "")).strip() if pd.notna(row.get("accession")) else ""
        if iso and acc and iso not in iso_to_acc and acc.lower() not in {"none", "nan", "null"}:
            iso_to_acc[iso] = acc

    # Build secondary_accession -> accession map
    sec_to_acc = {}
    for _, row in metadata_df.iterrows():
        sec = str(row.get("secondary_accession", "")).strip() if pd.notna(row.get("secondary_accession")) else ""
        acc = str(row.get("accession", "")).strip() if pd.notna(row.get("accession")) else ""
        if sec and acc and sec not in sec_to_acc and acc.lower() not in {"none", "nan", "null"}:
            sec_to_acc[sec] = acc

    def clean_str(val):
        if val is None or pd.isna(val):
            return None
        s = str(val).strip()
        return s if s and s.lower() not in {"none", "nan", "null"} else None

    for idx in range(len(res_df)):
        iso = clean_str(res_df.at[idx, "isolate_id"])
        curr_acc = clean_str(res_df.at[idx, "accession"])
        notes_val = clean_str(res_df.at[idx, "notes"])

        # If already has BioSample accession, keep it
        if is_biosample_accession(curr_acc):
            continue

        new_acc = None
        # 1. Match by isolate_id
        if iso and iso in iso_to_acc:
            new_acc = iso_to_acc[iso]
        # 2. Fallback match by secondary accession / current non-biosample accession
        elif curr_acc and curr_acc in sec_to_acc:
            new_acc = sec_to_acc[curr_acc]
        elif curr_acc and curr_acc in iso_to_acc:
            new_acc = iso_to_acc[curr_acc]

        if new_acc:
            # If upgrading non-BioSample to BioSample, record note provenance
            if curr_acc and not is_biosample_accession(curr_acc) and is_biosample_accession(new_acc):
                orig_note = f"original accession: {curr_acc}"
                if notes_val:
                    res_df.at[idx, "notes"] = f"{notes_val}; {orig_note}"
                else:
                    res_df.at[idx, "notes"] = orig_note
            res_df.at[idx, "accession"] = new_acc

    return res_df


def validate_extracted_records(
    df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Validates extracted AST records against QC rules.

    Rules:
    - drug: must be non-blank.
    - identifier: at least one of isolate_id or accession must be non-blank.
    - sir_call: if present, must be in {'S', 'I', 'R', 'SDD', 'NS'}.
    - mic / mic_sign:
      - If sir_call is present, both mic and mic_sign may be blank.
        However, if either is present, both must be valid.
      - If sir_call is absent, both mic and mic_sign are strictly required.
      - When present, mic_sign must be in {'=', '>', '>=', '<', '<='}.
      - When present, mic must match MIC_NUMERIC_PATTERN (e.g. '4', '0.25', '32/16').

    Returns:
        tuple of (valid_df, invalid_df, error_messages)
    """
    if df.empty:
        return df.copy(), df.copy(), []

    valid_mask = []
    errors = []

    def is_blank(val) -> bool:
        if val is None or pd.isna(val):
            return True
        s = str(val).strip()
        return s == "" or s.lower() in {"none", "nan", "null"}

    for idx, row in df.iterrows():
        row_errors = []

        # 1. Drug check
        drug_val = row.get("drug")
        if is_blank(drug_val):
            row_errors.append(f"Row {idx}: missing required 'drug'")

        # 2. Identifier check (at least one of isolate_id or accession must be present)
        iso_val = row.get("isolate_id")
        acc_val = row.get("accession")
        if is_blank(iso_val) and is_blank(acc_val):
            row_errors.append(f"Row {idx}: missing identifier (both 'isolate_id' and 'accession' are blank)")

        # 3. sir_call check
        sir_val = row.get("sir_call")
        has_sir = not is_blank(sir_val)
        if has_sir:
            sir_clean = str(sir_val).strip().upper()
            if sir_clean not in VALID_SIR_CALLS:
                row_errors.append(f"Row {idx}: invalid sir_call '{sir_val}' (must be one of {sorted(VALID_SIR_CALLS)})")

        # 4. mic_sign and mic check
        mic_sign_val = row.get("mic_sign")
        mic_val = row.get("mic")
        has_sign = not is_blank(mic_sign_val)
        has_mic = not is_blank(mic_val)

        if not has_sir:
            # When sir_call is absent, both mic_sign and mic are strictly required
            if not has_mic or not has_sign:
                row_errors.append(f"Row {idx}: missing mic/mic_sign and no sir_call provided")

        # Validate mic_sign if present
        if has_sign:
            sign_clean = str(mic_sign_val).strip()
            if sign_clean not in VALID_MIC_SIGNS:
                row_errors.append(f"Row {idx}: invalid mic_sign '{mic_sign_val}' (must be one of {sorted(VALID_MIC_SIGNS)})")

        # Validate mic if present
        if has_mic:
            mic_clean = str(mic_val).strip()
            if not MIC_NUMERIC_PATTERN.match(mic_clean):
                row_errors.append(f"Row {idx}: non-numeric mic value '{mic_val}'")

        if row_errors:
            valid_mask.append(False)
            errors.extend(row_errors)
        else:
            valid_mask.append(True)

    valid_df = df[valid_mask].copy().reset_index(drop=True)
    invalid_df = df[[not m for m in valid_mask]].copy().reset_index(drop=True)
    return valid_df, invalid_df, errors


def build_transformation_prompt(
    sheet_name: str,
    preview_df: pd.DataFrame,
    previous_errors: Optional[List[str]] = None,
) -> str:
    """Build the LLM prompt to generate transformation code for an AST sheet."""
    csv_sample = preview_df.head(8).to_csv(index=False)
    columns_list = list(preview_df.columns)

    error_feedback = ""
    if previous_errors:
        error_list_text = "\n".join(f"- {err}" for err in previous_errors[:10])
        error_feedback = f"""
IMPORTANT: ATTEMPT 1 FAILED QC CHECKS:
The code generated on the previous attempt produced records with the following validation failures:
{error_list_text}

Please fix your transformation logic so that all extracted rows strictly adhere to the requirements below.
"""

    return f"""You are an expert Python data engineer writing robust Pandas transformation code for bioinformatics.
Given the sample structure and top rows of an AST (antimicrobial susceptibility testing) Excel worksheet:

Sheet Name: '{sheet_name}'
Column Names: {columns_list}
Data Preview (first 8 rows):
{csv_sample}
{error_feedback}
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
    token_tracker: dict,
    previous_errors: Optional[List[str]] = None,
) -> str:
    """Prompts Gemini to generate a pure Python transformation function for this table layout."""
    prompt = build_transformation_prompt(sheet_name, preview_df, previous_errors=previous_errors)

    print(f"[*] Requesting transformation code for sheet '{sheet_name}' from Gemini...", end=" ", flush=True)
    t0 = time.time()
    response = client.models.generate_content(
        model="models/gemini-3.7-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
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


def discover_and_apply_metadata(
    current_df: pd.DataFrame,
    primary_excel_path: str,
    processed_sheets: list[str],
    supp_dir: Optional[str],
    client: genai.Client,
    token_tracker: dict,
    generated_scripts: dict,
) -> pd.DataFrame:
    """Discovers metadata sheets in current workbook or supp_dir and enriches current_df with BioSample accessions."""
    if not needs_accession_enrichment(current_df):
        return current_df

    target_isolate_ids = set(current_df["isolate_id"].dropna().unique())
    target_accessions = set(current_df["accession"].dropna().unique())

    # 1. Search remaining sheets in primary Excel workbook
    print("[*] Checking remaining sheets in current workbook for BioSample metadata mapping...", flush=True)
    try:
        primary_file = pd.ExcelFile(primary_excel_path)
        candidate_sheets = [s for s in primary_file.sheet_names if s not in processed_sheets]
        for c_sheet in candidate_sheets:
            hdr = detect_header_row(primary_file, c_sheet)
            sample_df = pd.read_excel(primary_file, sheet_name=c_sheet, header=hdr, nrows=8)
            if is_candidate_metadata_sheet(sample_df, target_isolate_ids, target_accessions):
                print(f"[+] Found candidate metadata mapping sheet: '{c_sheet}' in '{os.path.basename(primary_excel_path)}'", flush=True)
                full_sheet_df = pd.read_excel(primary_file, sheet_name=c_sheet, header=hdr)
                meta_code = generate_metadata_code(c_sheet, full_sheet_df, client, token_tracker)
                generated_scripts[f"{os.path.basename(primary_excel_path)}::{c_sheet}"] = meta_code
                meta_df = execute_metadata_code(meta_code, full_sheet_df)
                current_df = enrich_ast_with_metadata(current_df, meta_df)
                if not needs_accession_enrichment(current_df):
                    print("[+] All isolate records successfully enriched with BioSample accessions.", flush=True)
                    return current_df
    except Exception as e:
        print(f"[!] Warning while checking workbook sheets for metadata: {e}", file=sys.stderr)

    if not needs_accession_enrichment(current_df):
        return current_df

    # 2. Search other .xlsx / .xls files in supp_dir
    if supp_dir and os.path.isdir(supp_dir):
        print(f"[*] Searching supplementary directory '{supp_dir}' for BioSample metadata mapping...", flush=True)
        primary_abs = os.path.abspath(primary_excel_path)
        for fname in sorted(os.listdir(supp_dir)):
            if fname.startswith(("~$", ".")) or not fname.lower().endswith((".xlsx", ".xls")):
                continue
            fpath = os.path.join(supp_dir, fname)
            if os.path.abspath(fpath) == primary_abs:
                continue

            try:
                supp_file = pd.ExcelFile(fpath)
                for s_name in supp_file.sheet_names:
                    hdr = detect_header_row(supp_file, s_name)
                    sample_df = pd.read_excel(supp_file, sheet_name=s_name, header=hdr, nrows=8)
                    if is_candidate_metadata_sheet(sample_df, target_isolate_ids, target_accessions):
                        print(f"[+] Found candidate metadata mapping sheet: '{s_name}' in '{fname}'", flush=True)
                        full_sheet_df = pd.read_excel(supp_file, sheet_name=s_name, header=hdr)
                        meta_code = generate_metadata_code(s_name, full_sheet_df, client, token_tracker)
                        generated_scripts[f"{fname}::{s_name}"] = meta_code
                        meta_df = execute_metadata_code(meta_code, full_sheet_df)
                        current_df = enrich_ast_with_metadata(current_df, meta_df)
                        if not needs_accession_enrichment(current_df):
                            print("[+] All isolate records successfully enriched with BioSample accessions.", flush=True)
                            return current_df
            except Exception as e:
                print(f"[!] Warning while inspecting '{fname}': {e}", file=sys.stderr)

    return current_df


def process_excel_with_code_gen(
    excel_path: str,
    output_tsv: str = "gemini_ast_codegen.tsv",
    sheet_name: Optional[str] = None,
    save_code_path: Optional[str] = "generated_transform.py",
    supp_dir: Optional[str] = None,
):
    if supp_dir is None:
        supp_dir = os.path.dirname(os.path.abspath(excel_path))

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

    # 2. For each relevant sheet, generate code & execute locally (with QC and retry)
    for cur_sheet in sheets_to_process:
        print(f"\n--- Sheet: '{cur_sheet}' ---", flush=True)
        print(f"[*] Reading full sheet data...", flush=True)
        hdr = detect_header_row(excel_file, cur_sheet)
        if hdr > 0:
            print(f"[*] Detected column headers at row {hdr} (skipping title rows).", flush=True)
        full_df = pd.read_excel(excel_file, sheet_name=cur_sheet, header=hdr)
        print(f"[+] Loaded {len(full_df)} rows and {len(full_df.columns)} columns.", flush=True)

        max_attempts = 2
        sheet_valid_df = None
        last_code = None
        qc_errors = None

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                print(f"[*] [Retry Attempt {attempt}/{max_attempts}] Generating improved transformation code...", flush=True)
            else:
                print(f"[*] [Attempt {attempt}/{max_attempts}] Generating transformation code...", flush=True)

            code = generate_transformation_code(
                cur_sheet, full_df, client, token_tracker, previous_errors=qc_errors
            )
            last_code = code

            print(f"[*] Executing transformation code locally on {len(full_df)} rows...", end=" ", flush=True)
            t_exec_start = time.time()
            try:
                raw_transformed_df = execute_generated_code(code, full_df)
                t_exec_elapsed = time.time() - t_exec_start
                print(f"done in {t_exec_elapsed:.3f}s -> produced {len(raw_transformed_df)} records.", flush=True)
            except Exception as err:
                print(f"\n[!] Error executing generated code for sheet '{cur_sheet}': {err}", file=sys.stderr)
                qc_errors = [f"Code execution raised exception: {err}"]
                continue

            valid_df, invalid_df, errors = validate_extracted_records(raw_transformed_df)
            if len(invalid_df) == 0:
                print(f"[OK] All {len(valid_df)} extracted records passed QC.", flush=True)
                sheet_valid_df = valid_df
                break
            else:
                qc_errors = errors
                print(f"[!] QC check found {len(invalid_df)} invalid record(s) out of {len(raw_transformed_df)}.", flush=True)
                if attempt < max_attempts:
                    print(f"[*] Retrying code generation with QC error feedback...", flush=True)
                else:
                    print(f"\n[!] Failure: Sheet '{cur_sheet}' failed QC on Attempt {max_attempts}.", file=sys.stderr)
                    print(f"[!] Script failed to convert {len(invalid_df)} record(s) accurately.", file=sys.stderr)
                    print(f"[!] Sample QC failure reasons:", file=sys.stderr)
                    for err_msg in errors[:5]:
                        print(f"    - {err_msg}", file=sys.stderr)
                    print(f"[*] Omitted {len(invalid_df)} invalid record(s); retaining {len(valid_df)} valid record(s) for final TSV.", flush=True)
                    sheet_valid_df = valid_df

        generated_scripts[cur_sheet] = last_code

        if sheet_valid_df is not None and not sheet_valid_df.empty:
            finalized_df = finalize_extracted_dataframe(sheet_valid_df, excel_path, cur_sheet)
            all_extracted_dfs.append(finalized_df)
        elif sheet_valid_df is not None and sheet_valid_df.empty:
            print(f"[!] Warning: No valid records retained for sheet '{cur_sheet}'.", file=sys.stderr)

    if all_extracted_dfs:
        combined_df = pd.concat(all_extracted_dfs, ignore_index=True)

        # 3. If accessions are missing or non-BioSample, search metadata sheets to enrich
        if needs_accession_enrichment(combined_df):
            print("\n[*] Checking for BioSample accession mappings across sheets and supplementary files...", flush=True)
            combined_df = discover_and_apply_metadata(
                combined_df,
                primary_excel_path=excel_path,
                processed_sheets=sheets_to_process,
                supp_dir=supp_dir,
                client=client,
                token_tracker=token_tracker,
                generated_scripts=generated_scripts,
            )

        out_dir = os.path.dirname(output_tsv)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
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
    parser.add_argument("--supp-dir", default=None, help="Directory containing additional supplementary spreadsheets (.xlsx, .xls) to search for BioSample metadata mapping (default: same directory as input file)")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    process_excel_with_code_gen(
        args.excel_file,
        output_tsv=args.output,
        sheet_name=args.sheet,
        save_code_path=args.save_code,
        supp_dir=args.supp_dir,
    )

