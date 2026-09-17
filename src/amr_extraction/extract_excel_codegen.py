#!/usr/bin/env python3
import argparse
import os
import re
import sys
import time
from pathlib import Path
import pandas as pd
from typing import List, Optional
from pydantic import BaseModel, Field
import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from amr_extraction.excel_extractor import detect_header_row

DEFAULT_MODEL = "models/gemini-3.8-flash"
_RETRYABLE_HTTP_CODES = {429, 503}
_CODEGEN_RETRY_DELAYS = [5, 15, 30]  # seconds; 3 attempts before giving up


def _generate_content_with_retry(client: genai.Client, model: str, contents, config, context: str = ""):
    """Wraps client.models.generate_content() with retry-with-backoff for transient failures:
    Gemini 429 (rate limit) / 503 (overload) responses, and raw network-transport errors
    (dropped connections, timeouts -- e.g. httpx.RemoteProtocolError, seen in practice on large
    generated-code responses that take a while to stream back). Without this, any transient
    hiccup crashes the whole script instead of just costing a short retry. Mirrors the retry
    logic in amr_extraction.llm.query_structured(), which this module doesn't share directly
    since it manages its own genai.Client rather than going through that provider dispatcher."""
    attempt = 0
    while True:
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except genai_errors.APIError as e:
            code = getattr(e, "code", None)
            if code not in _RETRYABLE_HTTP_CODES or attempt >= len(_CODEGEN_RETRY_DELAYS):
                raise
            reason = f"HTTP {code}"
        except httpx.TransportError as e:
            if attempt >= len(_CODEGEN_RETRY_DELAYS):
                raise
            reason = f"network error ({type(e).__name__}: {e})"

        delay = _CODEGEN_RETRY_DELAYS[attempt]
        attempt += 1
        label = f" [{context}]" if context else ""
        print(
            f"\n[!] Gemini request failed: {reason}{label} -- retrying in {delay}s "
            f"(attempt {attempt}/{len(_CODEGEN_RETRY_DELAYS)})...",
            file=sys.stderr,
        )
        time.sleep(delay)
DEFAULT_ANTIBIOTICS_PATH = str(Path(__file__).resolve().parent / "antibiotics.list.txt")


def load_antibiotics_list(path: Optional[str] = None) -> list[str]:
    """Loads standard antibiotic names from a text file.

    If path is None, loads from DEFAULT_ANTIBIOTICS_PATH.
    Raises FileNotFoundError if the file does not exist.
    """
    target_path = path if path is not None else DEFAULT_ANTIBIOTICS_PATH
    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Antibiotics list file not found: {target_path}")
    with open(target_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

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
    response = _generate_content_with_retry(
        client, model=DEFAULT_MODEL, contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SheetSelection,
            temperature=0.0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
        context=f"classify_single_sheet: {sheet_name}",
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


ACCESSION_COLUMNS = [
    "bioproject_accession",
    "biosample_accession",
    "assembly_accession",
    "genbank_accessions",
    "refseq_accessions",
    "sra_accession",
    "other_accessions",
]

EXPECTED_OUTPUT_COLUMNS = [
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


VALID_MIC_SIGNS = {"=", ">", ">=", "<", "<="}
VALID_SIR_CALLS = {"S", "I", "R", "SDD", "NS"}
MIC_NUMERIC_PATTERN = re.compile(r"^\d+(\.\d+)?(/\d+(\.\d+)?)*$")

PMID_PATTERN = re.compile(r"\b\d{7,8}\b")


def extract_pmid_from_paths(
    excel_path: Optional[str] = None,
    supp_dir: Optional[str] = None,
) -> Optional[str]:
    """Extracts a 7-8 digit PubMed ID from path components, checking excel_path first, then supp_dir."""
    for p in [excel_path, supp_dir]:
        if not p:
            continue
        parts = os.path.normpath(str(p)).split(os.sep)
        for part in reversed(parts):
            matches = PMID_PATTERN.findall(part)
            if matches:
                return matches[0]
    return None


BIOPROJECT_PATTERN = re.compile(r"^PRJ(NA|EB|DB)?[A-Z]?\d+$", re.IGNORECASE)
BIOSAMPLE_PATTERN = re.compile(r"^SAM(N|EA?|D)\d+(\.\d+)?$", re.IGNORECASE)
ASSEMBLY_PATTERN = re.compile(r"^GC[AF]_\d+(\.\d+)?$", re.IGNORECASE)
REFSEQ_PATTERN = re.compile(r"^(NZ_|NC_|NM_|NR_|NP_|XM_|XR_|XP_)[A-Z]{2,6}_?\d+(\.\d+)?$", re.IGNORECASE)
SRA_PATTERN = re.compile(r"^[SED]R[RAXPXZS]\d+$", re.IGNORECASE)
GENBANK_PATTERN = re.compile(r"^([A-Z]{1,2}\d{5,6}|[A-Z]{4,6}\d{2}\d{6,8}|[A-Z]{4,6}\d{6,8})(\.\d+)?$", re.IGNORECASE)
PUBLIC_ACCESSION_PATTERN = re.compile(r"(PRJ\w*\d+|SAM[NED]\w*\d+|GC[AF]_\d+|[SED]R[RAXPXZS]\d+|[A-Z]{1,6}\d{5,8})", re.IGNORECASE)


def extract_accession_tokens(val: Any) -> list[str]:
    """Extracts individual accession strings from a scalar value or delimited string."""
    if val is None or pd.isna(val):
        return []
    s = str(val).strip()
    if not s or s.lower() in {"none", "nan", "null", "-"}:
        return []
    parts = re.split(r"[,;\s]+", s)
    tokens = []
    for p in parts:
        p_clean = p.strip().strip("'\"")
        if p_clean and p_clean.lower() not in {"none", "nan", "null", "-"}:
            tokens.append(p_clean)
    return tokens


def format_combined_accessions(accessions: list[str]) -> Optional[str]:
    """Deduplicates and sorts accessions with BioSample first, comma-separated without spaces."""
    if not accessions:
        return None

    seen = set()
    biosamples = []
    others = []

    for acc in accessions:
        for token in extract_accession_tokens(acc):
            key = token.upper()
            if key in seen:
                continue
            seen.add(key)
            if is_biosample_accession(token):
                biosamples.append(token)
            else:
                others.append(token)

    biosamples.sort()
    others.sort()
    all_sorted = biosamples + others
    return ",".join(all_sorted) if all_sorted else None


def split_accession_tokens(accessions: Any) -> dict[str, Optional[str]]:
    """Classifies accession tokens into the 7 typed categories."""
    tokens = extract_accession_tokens(accessions)
    buckets: dict[str, list[str]] = {col: [] for col in ACCESSION_COLUMNS}
    seen: dict[str, set[str]] = {col: set() for col in ACCESSION_COLUMNS}

    for tok in tokens:
        clean_tok = tok.strip()
        tok_upper = clean_tok.upper()
        if BIOPROJECT_PATTERN.match(clean_tok):
            col = "bioproject_accession"
        elif BIOSAMPLE_PATTERN.match(clean_tok):
            col = "biosample_accession"
        elif ASSEMBLY_PATTERN.match(clean_tok):
            col = "assembly_accession"
        elif REFSEQ_PATTERN.match(clean_tok):
            col = "refseq_accessions"
        elif SRA_PATTERN.match(clean_tok):
            col = "sra_accession"
        elif GENBANK_PATTERN.match(clean_tok):
            col = "genbank_accessions"
        else:
            col = "other_accessions"

        if tok_upper not in seen[col]:
            seen[col].add(tok_upper)
            buckets[col].append(clean_tok)

    result = {}
    for col in ACCESSION_COLUMNS:
        items = buckets[col]
        if items:
            items.sort()
            result[col] = ",".join(items)
        else:
            result[col] = None

    return result


def is_biosample_accession(val: Optional[str]) -> bool:
    """Returns True if the accession is a valid NCBI, EBI, or DDBJ BioSample accession."""
    if val is None or pd.isna(val):
        return False
    s = str(val).strip()
    return bool(BIOSAMPLE_PATTERN.match(s))


def contains_biosample_accession(val: Optional[str]) -> bool:
    """Returns True if val contains at least one valid BioSample accession."""
    tokens = extract_accession_tokens(val)
    return any(is_biosample_accession(t) for t in tokens)


def needs_accession_enrichment(df: pd.DataFrame) -> bool:
    """Checks whether the extracted DataFrame has missing or non-BioSample accessions."""
    if df.empty or "accession" not in df.columns:
        return False
    for acc in df["accession"]:
        if not contains_biosample_accession(acc):
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
2. Identify all public repository accession columns (e.g. BioSample accessions like SAMN*, SAMEA*, SAMD*; SRA/ENA runs like SRR*, ERR*, DRR*; assemblies like GCA_*, GCF_*; or GenBank nucleotide accessions).
   - If the worksheet has multiple accession columns, combine all found public accessions for each isolate into a comma-delimited string (e.g. 'SAMN12345678,ERR123456') and map to 'accession'.
   - If only a single accession column is found, map it to 'accession'.
3. Secondary accession column:
   - For backwards compatibility, you may also populate 'secondary_accession' with non-BioSample public accessions (or None if not present).
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
    response = _generate_content_with_retry(
        client, model=DEFAULT_MODEL, contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
        context=f"generate_metadata_code: {sheet_name}",
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
    """Enriches AST DataFrame with all BioSample or public accessions from metadata mapping."""
    if ast_df.empty or metadata_df.empty:
        return ast_df.copy()

    res_df = ast_df.copy()

    # Build isolate_id -> list of accessions and token -> list of accessions
    iso_to_accs: dict[str, list[str]] = {}
    sec_to_accs: dict[str, list[str]] = {}

    for _, row in metadata_df.iterrows():
        iso = str(row.get("isolate_id", "")).strip() if pd.notna(row.get("isolate_id")) else ""
        row_accs = []
        for col in ["accession", "secondary_accession"]:
            if col in metadata_df.columns:
                row_accs.extend(extract_accession_tokens(row.get(col)))
        for col in metadata_df.columns:
            if col not in {"isolate_id", "accession", "secondary_accession"} and "accession" in col.lower():
                row_accs.extend(extract_accession_tokens(row.get(col)))

        if iso and row_accs:
            if iso not in iso_to_accs:
                iso_to_accs[iso] = []
            iso_to_accs[iso].extend(row_accs)

        for acc in row_accs:
            if acc not in sec_to_accs:
                sec_to_accs[acc] = []
            sec_to_accs[acc].extend(row_accs)

    def clean_str(val):
        if val is None or pd.isna(val):
            return None
        s = str(val).strip()
        return s if s and s.lower() not in {"none", "nan", "null"} else None

    for idx in range(len(res_df)):
        iso = clean_str(res_df.at[idx, "isolate_id"])
        curr_acc = clean_str(res_df.at[idx, "accession"])
        curr_acc_tokens = extract_accession_tokens(curr_acc)
        notes_val = clean_str(res_df.at[idx, "notes"])

        matched_accs = []
        # 1. Match by isolate_id
        if iso and iso in iso_to_accs:
            matched_accs.extend(iso_to_accs[iso])
        # 2. Fallback match by current accession tokens
        if not matched_accs and curr_acc_tokens:
            for tok in curr_acc_tokens:
                if tok in sec_to_accs:
                    matched_accs.extend(sec_to_accs[tok])
                elif tok in iso_to_accs:
                    matched_accs.extend(iso_to_accs[tok])

        if matched_accs:
            had_biosample = any(is_biosample_accession(t) for t in curr_acc_tokens)
            all_tokens = curr_acc_tokens + matched_accs
            formatted = format_combined_accessions(all_tokens)
            has_biosample = any(is_biosample_accession(t) for t in extract_accession_tokens(formatted))

            # If upgrading non-BioSample to BioSample, record note provenance
            if not had_biosample and has_biosample and curr_acc:
                orig_note = f"original accession: {curr_acc}"
                if notes_val:
                    if orig_note not in notes_val:
                        res_df.at[idx, "notes"] = f"{notes_val}; {orig_note}"
                else:
                    res_df.at[idx, "notes"] = orig_note

            res_df.at[idx, "accession"] = formatted
        elif curr_acc_tokens:
            res_df.at[idx, "accession"] = format_combined_accessions(curr_acc_tokens)

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
        has_acc = not is_blank(acc_val) or any(not is_blank(row.get(c)) for c in ACCESSION_COLUMNS if c in row)
        if is_blank(iso_val) and not has_acc:
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
    antibiotics_list: Optional[List[str]] = None,
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

    antibiotics_instructions = ""
    if antibiotics_list:
        valid_drugs_str = ", ".join(f"'{d}'" for d in antibiotics_list)
        antibiotics_instructions = f"\n   - CRITICAL: You MUST standardize all extracted drug names against the following permitted list: [{valid_drugs_str}]. Do NOT output any drug name that is not strictly in this list (case-insensitive mapping is fine, but output exactly the name from this list). If the column is not an antimicrobial drug, ignore it."

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
   - If the sheet contains multiple accession columns, combine all found public accessions into a comma-delimited string in 'accession' (e.g. 'SAMN12345678,ERR123456').
   - IMPORTANT: Do NOT fall back to using the isolate identifier. If no public database accession exists, leave 'accession' blank (None or np.nan).
3. Identify all antibiotic / antimicrobial testing columns. Ignore non-AST metadata columns (patient demographics, date, source, species, QC, interpretation, etc.). The column must represent a specific antimicrobial drug.
4. Unpivot (melt) the drug columns into long format, setting the drug name to 'drug'.
   - IMPORTANT: If the column headers are drug abbreviations (e.g. 'LNZ', 'CIP', 'ERY'), you must resolve them to their full drug names (e.g. 'Linezolid', 'Ciprofloxacin', 'Erythromycin') in the 'drug' column. Do not output abbreviations.{antibiotics_instructions}
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
    antibiotics_list: Optional[List[str]] = None,
) -> str:
    """Prompts Gemini to generate a pure Python transformation function for this table layout."""
    prompt = build_transformation_prompt(sheet_name, preview_df, previous_errors=previous_errors, antibiotics_list=antibiotics_list)

    print(f"[*] Requesting transformation code for sheet '{sheet_name}' from Gemini...", end=" ", flush=True)
    t0 = time.time()
    response = _generate_content_with_retry(
        client, model=DEFAULT_MODEL, contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
        context=f"generate_transformation_code: {sheet_name}",
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


def finalize_extracted_dataframe(
    df: pd.DataFrame,
    file_path: Optional[str] = None,
    sheet_name: Optional[str] = None,
    pmid: Optional[str] = None,
) -> pd.DataFrame:
    """Prepends pmid, file_name, and sheet_name, splits accessions into typed columns, and ensures expected schema."""
    res = df.copy()
    if pmid is not None and "pmid" not in res.columns:
        res.insert(0, "pmid", pmid)
    elif pmid is not None:
        res["pmid"] = pmid

    if sheet_name is not None and "sheet_name" not in res.columns:
        res.insert(0, "sheet_name", sheet_name)
    elif sheet_name is not None:
        res["sheet_name"] = sheet_name

    if file_path is not None and "file_name" not in res.columns:
        res.insert(0, "file_name", os.path.basename(file_path))
    elif file_path is not None:
        res["file_name"] = os.path.basename(file_path)

    if "accession" in res.columns:
        parsed_dicts = [split_accession_tokens(val) for val in res["accession"]]
        parsed_df = pd.DataFrame(parsed_dicts, index=res.index)
        for col in ACCESSION_COLUMNS:
            res[col] = parsed_df[col]
        res.drop(columns=["accession"], inplace=True)

    for col in EXPECTED_OUTPUT_COLUMNS:
        if col not in res.columns:
            res[col] = None

    return res[EXPECTED_OUTPUT_COLUMNS]


def discover_and_apply_metadata(
    current_df: pd.DataFrame,
    primary_excel_path: Optional[str] = None,
    processed_sheets: Optional[list[str]] = None,
    supp_dir: Optional[str] = None,
    client: Optional[genai.Client] = None,
    token_tracker: Optional[dict] = None,
    generated_scripts: Optional[dict] = None,
    processed_sheets_by_file: Optional[dict[str, list[str]]] = None,
) -> pd.DataFrame:
    """Discovers metadata sheets in current workbook and supp_dir and enriches current_df with all public accessions."""
    target_isolate_ids = set(current_df["isolate_id"].dropna().unique())
    target_accessions = set()
    for val in current_df["accession"].dropna().unique():
        target_accessions.update(extract_accession_tokens(val))

    # 1. Search remaining sheets in primary Excel workbook (if provided)
    if primary_excel_path and os.path.exists(primary_excel_path):
        print("[*] Checking remaining sheets in current workbook for BioSample metadata mapping...", flush=True)
        try:
            primary_file = pd.ExcelFile(primary_excel_path)
            candidate_sheets = [s for s in primary_file.sheet_names if s not in (processed_sheets or [])]
            for c_sheet in candidate_sheets:
                hdr = detect_header_row(primary_file, c_sheet)
                sample_df = pd.read_excel(primary_file, sheet_name=c_sheet, header=hdr, nrows=8)
                if is_candidate_metadata_sheet(sample_df, target_isolate_ids, target_accessions):
                    print(f"[+] Found candidate metadata mapping sheet: '{c_sheet}' in '{os.path.basename(primary_excel_path)}'", flush=True)
                    full_sheet_df = pd.read_excel(primary_file, sheet_name=c_sheet, header=hdr)
                    meta_code = generate_metadata_code(c_sheet, full_sheet_df, client, token_tracker)
                    if generated_scripts is not None:
                        generated_scripts[f"{os.path.basename(primary_excel_path)}::{c_sheet}"] = meta_code
                    meta_df = execute_metadata_code(meta_code, full_sheet_df)
                    current_df = enrich_ast_with_metadata(current_df, meta_df)
                    target_accessions = set()
                    for val in current_df["accession"].dropna().unique():
                        target_accessions.update(extract_accession_tokens(val))
        except Exception as e:
            print(f"[!] Warning while checking workbook sheets for metadata: {e}", file=sys.stderr)

    # 2. Search other .xlsx / .xls files in supp_dir
    if supp_dir and os.path.isdir(supp_dir):
        print(f"[*] Searching supplementary directory '{supp_dir}' for BioSample metadata mapping...", flush=True)
        primary_abs = os.path.abspath(primary_excel_path) if primary_excel_path else None
        for fname in sorted(os.listdir(supp_dir)):
            if fname.startswith(("~$", ".")) or not fname.lower().endswith((".xlsx", ".xls")):
                continue
            fpath = os.path.join(supp_dir, fname)
            abs_fpath = os.path.abspath(fpath)
            if primary_abs and abs_fpath == primary_abs:
                continue

            already_processed = set()
            if processed_sheets_by_file and abs_fpath in processed_sheets_by_file:
                already_processed = set(processed_sheets_by_file[abs_fpath])

            try:
                supp_file = pd.ExcelFile(fpath)
                candidate_sheets = [s for s in supp_file.sheet_names if s not in already_processed]
                for s_name in candidate_sheets:
                    hdr = detect_header_row(supp_file, s_name)
                    sample_df = pd.read_excel(supp_file, sheet_name=s_name, header=hdr, nrows=8)
                    if is_candidate_metadata_sheet(sample_df, target_isolate_ids, target_accessions):
                        print(f"[+] Found candidate metadata mapping sheet: '{s_name}' in '{fname}'", flush=True)
                        full_sheet_df = pd.read_excel(supp_file, sheet_name=s_name, header=hdr)
                        meta_code = generate_metadata_code(s_name, full_sheet_df, client, token_tracker)
                        if generated_scripts is not None:
                            generated_scripts[f"{fname}::{s_name}"] = meta_code
                        meta_df = execute_metadata_code(meta_code, full_sheet_df)
                        current_df = enrich_ast_with_metadata(current_df, meta_df)
                        target_accessions = set()
                        for val in current_df["accession"].dropna().unique():
                            target_accessions.update(extract_accession_tokens(val))
            except Exception as e:
                print(f"[!] Warning while inspecting '{fname}': {e}", file=sys.stderr)

    return current_df


def process_excel_with_code_gen(
    excel_path: Optional[str] = None,
    output_tsv: str = "gemini_ast_codegen.tsv",
    sheet_name: Optional[str] = None,
    save_code_path: Optional[str] = "generated_transform.py",
    supp_dir: Optional[str] = None,
    antibiotics_list_path: Optional[str] = None,
    pmid: Optional[str] = None,
):
    if excel_path is None and supp_dir is None:
        print("[!] Error: Either excel_path or supp_dir must be provided.", file=sys.stderr)
        return

    resolved_pmid = pmid
    if not resolved_pmid:
        resolved_pmid = extract_pmid_from_paths(excel_path=excel_path, supp_dir=supp_dir)
        if resolved_pmid:
            print(f"[*] Inferred PMID '{resolved_pmid}' from input path.", flush=True)
        else:
            print("[!] Warning: No PMID specified and none could be inferred from input path.", flush=True)
    else:
        print(f"[*] Using specified PMID '{resolved_pmid}'.", flush=True)

    if excel_path is not None and supp_dir is None:
        supp_dir = os.path.dirname(os.path.abspath(excel_path))

    target_files = []
    if excel_path is not None:
        target_files = [excel_path]
    elif supp_dir and os.path.isdir(supp_dir):
        for fname in sorted(os.listdir(supp_dir)):
            if fname.startswith(("~$", ".")) or not fname.lower().endswith((".xlsx", ".xls")):
                continue
            target_files.append(os.path.join(supp_dir, fname))

    if not target_files:
        print(f"[!] Notice: No Excel files (.xlsx, .xls) found to process.", file=sys.stderr)
        return

    target_antibiotics_path = antibiotics_list_path if antibiotics_list_path is not None else DEFAULT_ANTIBIOTICS_PATH
    antibiotics_list = load_antibiotics_list(target_antibiotics_path)
    print(f"[*] Loaded {len(antibiotics_list)} standard antibiotics from '{target_antibiotics_path}'", flush=True)

    token_tracker = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    start_total_time = time.time()

    print("[*] Initializing Gemini client...", flush=True)
    client = genai.Client()

    all_extracted_dfs = []
    generated_scripts = {}
    processed_sheets_by_file = {}

    for file_path in target_files:
        base_name = os.path.basename(file_path)
        if len(target_files) > 1:
            print(f"\n==================================================", flush=True)
            print(f"[*] Processing Excel file: '{base_name}'", flush=True)
            print(f"==================================================", flush=True)

        try:
            excel_file = pd.ExcelFile(file_path)
        except Exception as e:
            print(f"[!] Error opening Excel file '{file_path}': {e}", file=sys.stderr)
            continue

        # 1. Discover sheets
        if sheet_name:
            if sheet_name in excel_file.sheet_names:
                sheets_to_process = [sheet_name]
            else:
                if len(target_files) == 1:
                    print(f"[!] Error: Sheet '{sheet_name}' not found. Available: {excel_file.sheet_names}", file=sys.stderr)
                    sys.exit(1)
                else:
                    sheets_to_process = []
        else:
            sheets_to_process = discover_relevant_sheets(file_path, client, token_tracker)

        processed_sheets_by_file[os.path.abspath(file_path)] = sheets_to_process

        if not sheets_to_process:
            print(f"[*] No AST sheets found in '{base_name}'.", flush=True)
            continue

        # 2. For each relevant sheet, generate code & execute locally (with QC and retry)
        for cur_sheet in sheets_to_process:
            print(f"\n--- Sheet: '{cur_sheet}' (in {base_name}) ---", flush=True)
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
                    cur_sheet, full_df, client, token_tracker, previous_errors=qc_errors, antibiotics_list=antibiotics_list
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

            script_key = f"{base_name}::{cur_sheet}" if len(target_files) > 1 else cur_sheet
            generated_scripts[script_key] = last_code

            if sheet_valid_df is not None and not sheet_valid_df.empty:
                sheet_df = sheet_valid_df.copy()
                sheet_df.insert(0, "sheet_name", cur_sheet)
                sheet_df.insert(0, "file_name", base_name)
                all_extracted_dfs.append(sheet_df)
            elif sheet_valid_df is not None and sheet_valid_df.empty:
                print(f"[!] Warning: No valid records retained for sheet '{cur_sheet}'.", file=sys.stderr)

    if all_extracted_dfs:
        combined_df = pd.concat(all_extracted_dfs, ignore_index=True)

        # 3. Discover and merge all accessions from metadata sheets in workbook and supplementary files
        print("\n[*] Checking for accession mappings across sheets and supplementary files...", flush=True)
        primary_processed = (
            processed_sheets_by_file.get(os.path.abspath(excel_path), [])
            if excel_path and os.path.abspath(excel_path) in processed_sheets_by_file
            else []
        )
        combined_df = discover_and_apply_metadata(
            combined_df,
            primary_excel_path=excel_path,
            processed_sheets=primary_processed,
            supp_dir=supp_dir,
            client=client,
            token_tracker=token_tracker,
            generated_scripts=generated_scripts,
            processed_sheets_by_file=processed_sheets_by_file,
        )

        combined_df = finalize_extracted_dataframe(combined_df, pmid=resolved_pmid)

        out_dir = os.path.dirname(output_tsv)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        combined_df.to_csv(output_tsv, sep="\t", index=False, na_rep="")
        print(f"\n[OK] Successfully wrote {len(combined_df)} total records to '{output_tsv}'", flush=True)
    else:
        print("[!] Notice: No worksheets with AST data (MIC or SIR) were found.", file=sys.stderr)
        print("[!] No output file generated.", file=sys.stderr)
        return

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


def build_cli_parser() -> argparse.ArgumentParser:
    """Builds and returns the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Extract AST records by using Gemini to synthesize and execute local Pandas transformation code."
    )
    parser.add_argument("excel_file", nargs="?", default=None, help="Path to the Excel file to process (optional if --supp-dir is specified)")
    parser.add_argument("-s", "--sheet", default=None, help="Specific sheet name to process (default: auto-discover AST sheets)")
    parser.add_argument("-o", "--output", default="gemini_ast_codegen.tsv", help="Output TSV file (default: gemini_ast_codegen.tsv)")
    parser.add_argument("--save-code", default="generated_transform.py", help="File to save generated Python code (default: generated_transform.py)")
    parser.add_argument("--supp-dir", default=None, help="Directory containing additional supplementary spreadsheets (.xlsx, .xls) to scan or search for BioSample metadata mapping (default: same directory as input file)")
    parser.add_argument("--antibiotics-list", default=DEFAULT_ANTIBIOTICS_PATH, help="Path to a text file containing standard antibiotic names (one per line). Extracted drugs will be standardized to this list.")
    parser.add_argument("--pmid", default=None, help="PubMed ID associated with the dataset (if not specified, inferred from path)")
    return parser


if __name__ == "__main__":
    parser = build_cli_parser()

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    if not args.excel_file and not args.supp_dir:
        parser.error("Either excel_file or --supp-dir must be provided.")

    process_excel_with_code_gen(
        excel_path=args.excel_file,
        output_tsv=args.output,
        sheet_name=args.sheet,
        save_code_path=args.save_code,
        supp_dir=args.supp_dir,
        antibiotics_list_path=args.antibiotics_list,
        pmid=args.pmid,
    )


