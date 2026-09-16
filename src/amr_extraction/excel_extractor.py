"""Excel AST extraction pipeline.

Uses a hybrid approach: LLM sheet classification and column mapping,
coupled with deterministic pandas unpivoting and MIC parsing.
"""

from collections.abc import Callable
from pathlib import Path
import re
from typing import Any
import pandas as pd

from amr_extraction.schemas import (
    ASTExtractionRecord,
    ColumnMapping,
    ColumnRole,
    SheetClassification,
    SheetColumnMap,
)

# Regular expressions for MIC string parsing
# Matches operators: <=, >=, <, >, =
# Matches values: numbers like 64, 0.25, or ratios like 32/16, 0.25/4.75, 8/152
MIC_PATTERN = re.compile(
    r"^\s*(?P<operator><=|>=|<|>|=)?\s*(?P<value>\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)\s*$"
)

NON_MIC_VALUES = {
    "s", "r", "i",
    "susceptible", "resistant", "intermediate",
    "nd", "na", "n/a", "none", "null", "-", ""
}


def parse_mic_string(raw: Any) -> tuple[str | None, str | None]:
    """Parse a raw MIC string into (operator, value).

    Examples:
        ">64" -> (">", "64")
        "<=0.5" -> ("<=", "0.5")
        "32/16" -> ("=", "32/16")
        "4" -> ("=", "4")
        "<0.25/4.75" -> ("<", "0.25/4.75")
        "S" -> (None, None)
    """
    if raw is None or pd.isna(raw):
        return None, None

    text = str(raw).strip()
    if not text or text.lower() in NON_MIC_VALUES:
        return None, None

    match = MIC_PATTERN.match(text)
    if not match:
        return None, None

    operator = match.group("operator") or "="
    # Normalize ratio whitespace if any: "32 / 16" -> "32/16"
    value = re.sub(r"\s*/\s*", "/", match.group("value"))
    return operator, value


def _infer_accession_type(accession: str | None) -> str | None:
    """Infer the accession type based on standard prefix conventions."""
    if not accession:
        return None
    acc = accession.strip().upper()
    if acc.startswith(("SAMN", "SAME", "SRS")):
        return "BioSample"
    if acc.startswith(("PRJN", "PRJE")):
        return "BioProject"
    if acc.startswith(("SRR", "ERR", "DRR")):
        return "SRA_Run"
    if acc.startswith(("SRX", "ERX", "DRX")):
        return "SRA_Experiment"
    return "Accession"


def detect_header_row(
    excel_path: str | Path,
    sheet_name: str,
    max_check_rows: int = 15,
) -> int:
    """Detect the 0-indexed row containing column headers.

    Examines the first max_check_rows of the worksheet without headers.
    Identifies the first row with substantial non-null string content,
    ignoring title rows that contain only 1-2 cells across the row.
    """
    df_raw = pd.read_excel(excel_path, sheet_name=sheet_name, header=None, nrows=max_check_rows)
    scores: list[tuple[int, int]] = []
    for idx, row in df_raw.iterrows():
        non_null_strings = sum(1 for v in row if isinstance(v, str) and v.strip())
        scores.append((non_null_strings, int(idx)))

    max_strings = max((s[0] for s in scores), default=0)
    if max_strings <= 1:
        return 0

    threshold = max(2, int(max_strings * 0.4))
    for count, idx in scores:
        if count >= threshold:
            return idx
    return 0


HEADER_KEYWORDS = {
    "cvm_number", "isolate", "isolate_id", "isolate id", "isolate_name",
    "sample", "sample_id", "sample id", "specimen", "sequencing_number",
    "accession", "nucleotide accession", "accession number",
    "genus", "organism", "species", "range measured", "cutoff",
    "cutoff (>= x)", "breakpoint",
}


def extract_ast_records(
    excel_path: str | Path,
    sheet_name: str,
    column_map: SheetColumnMap,
    pubmed_id: str,
) -> list[ASTExtractionRecord]:
    """Extract AST records from an Excel sheet deterministically using a column map.

    Args:
        excel_path: Path to the Excel file.
        sheet_name: Name of the worksheet.
        column_map: Pre-computed column mapping.
        pubmed_id: PubMed ID of the source paper.

    Returns:
        List of ASTExtractionRecord objects.
    """
    if column_map.header_row_index is not None and column_map.header_row_index > 0:
        header_row = column_map.header_row_index
    else:
        header_row = detect_header_row(excel_path, sheet_name)

    df = pd.read_excel(excel_path, sheet_name=sheet_name, header=header_row)

    # Categorize columns from mapping
    local_id_cols: list[str] = []
    accession_cols: list[str] = []
    organism_col: str | None = None
    mic_cols: list[ColumnMapping] = []
    paired_sir_map: dict[str, str] = {}  # mic_col_name -> sir_col_name
    sir_only_cols: list[ColumnMapping] = []

    for col_info in column_map.columns:
        if col_info.column_name not in df.columns:
            continue
        role = col_info.role
        if role == ColumnRole.LOCAL_ID:
            local_id_cols.append(col_info.column_name)
        elif role == ColumnRole.PUBLIC_ACCESSION:
            accession_cols.append(col_info.column_name)
        elif role == ColumnRole.ORGANISM:
            organism_col = col_info.column_name
        elif role == ColumnRole.DRUG_MIC:
            mic_cols.append(col_info)
            if col_info.paired_with and col_info.paired_with in df.columns:
                paired_sir_map[col_info.column_name] = col_info.paired_with
        elif role == ColumnRole.DRUG_SIR:
            sir_only_cols.append(col_info)

    # Also resolve paired columns by checking if a DRUG_SIR references a DRUG_MIC
    for col_info in column_map.columns:
        if col_info.role == ColumnRole.DRUG_SIR and col_info.paired_with:
            if col_info.paired_with not in paired_sir_map:
                paired_sir_map[col_info.paired_with] = col_info.column_name

    # Select primary isolate column
    primary_id_col = None
    if local_id_cols:
        # Prefer column with 'sequencing', 'isolate', or 'strain' in name if multiple
        for c in local_id_cols:
            if any(k in c.lower() for k in ["seq", "isolate", "strain"]):
                primary_id_col = c
                break
        if primary_id_col is None:
            primary_id_col = local_id_cols[0]
    elif accession_cols:
        primary_id_col = accession_cols[0]

    primary_acc_col = accession_cols[0] if accession_cols else None

    records: list[ASTExtractionRecord] = []

    for idx, row in df.iterrows():
        # Resolve isolate name
        if primary_id_col and pd.notna(row[primary_id_col]):
            isolate_name = str(row[primary_id_col]).strip()
        elif primary_acc_col and pd.notna(row[primary_acc_col]):
            isolate_name = str(row[primary_acc_col]).strip()
        else:
            isolate_name = f"isolate_{idx + 1}"

        # Guard against header or subheader rows accidentally parsed as data
        iso_clean = isolate_name.lower().strip()
        if iso_clean in HEADER_KEYWORDS:
            continue
        if primary_id_col and iso_clean == str(primary_id_col).lower().strip():
            continue
        if any(kw in iso_clean for kw in ("range measured", "cutoff")):
            continue

        # Resolve accession
        accession = None
        accession_type = None
        if primary_acc_col and pd.notna(row[primary_acc_col]):
            accession = str(row[primary_acc_col]).strip()
            accession_type = _infer_accession_type(accession)

        # Resolve organism
        organism = None
        if organism_col and pd.notna(row[organism_col]):
            organism = str(row[organism_col]).strip()

        # Extract MIC columns (with paired SIR if present)
        for mic_mapping in mic_cols:
            col_name = mic_mapping.column_name
            raw_mic_val = row[col_name]
            mic_op, mic_val = parse_mic_string(raw_mic_val)

            # SIR call from paired column
            sir_call = None
            sir_col = paired_sir_map.get(col_name)
            if sir_col and pd.notna(row[sir_col]):
                raw_sir = str(row[sir_col]).strip()
                if raw_sir and raw_sir.lower() not in NON_MIC_VALUES or raw_sir in {"S", "R", "I"}:
                    sir_call = raw_sir

            # If no paired column gave SIR, but raw_mic_val is an SIR value
            if sir_call is None and pd.notna(raw_mic_val):
                raw_s = str(raw_mic_val).strip()
                if raw_s in {"S", "R", "I", "Susceptible", "Resistant", "Intermediate"}:
                    sir_call = raw_s

            if mic_val is None and sir_call is None:
                continue

            record = ASTExtractionRecord(
                pubmed_id=pubmed_id,
                source_sheet=sheet_name,
                isolate_name=isolate_name,
                accession=accession,
                accession_type=accession_type,
                organism=organism,
                drug_raw=col_name,
                mic_operator=mic_op,
                mic_value=mic_val,
                sir_call=sir_call,
            )
            records.append(record)

    return records


def _generate_sheet_preview(df: pd.DataFrame, max_rows: int = 6) -> str:
    """Generate a clean markdown preview of DataFrame head for LLM prompt."""
    preview_df = df.head(max_rows)
    return preview_df.to_csv(index=False)


def classify_sheets(
    excel_path: str | Path,
    query_fn: Callable[..., Any],
) -> list[SheetClassification]:
    """Classify sheets in an Excel workbook for AST data presence.

    Args:
        excel_path: Path to the Excel workbook.
        query_fn: Callable to send structured LLM queries.

    Returns:
        List of SheetClassification objects.
    """
    excel_file = pd.ExcelFile(excel_path)
    sheet_names = excel_file.sheet_names

    classifications: list[SheetClassification] = []

    for name in sheet_names:
        hdr = detect_header_row(excel_path, name)
        df_preview = pd.read_excel(excel_path, sheet_name=name, header=hdr, nrows=8)
        preview_csv = _generate_sheet_preview(df_preview)

        prompt = f"""You are an expert microbiologist analyzing supplementary data files from scientific papers on antimicrobial resistance (AMR).

Analyze this worksheet preview and determine whether it contains antimicrobial susceptibility testing (AST) data such as Minimum Inhibitory Concentration (MIC) values or SIR (Susceptible/Intermediate/Resistant) interpretations.

Sheet Name: "{name}"
Total preview columns: {len(df_preview.columns)}
Columns: {list(df_preview.columns)}

Preview Data (first few rows):
```csv
{preview_csv}
```

Determine:
1. contains_ast_data: Does this sheet contain AST measurements (MIC or SIR) for antimicrobial drugs?
2. has_mic_values: Does it contain quantitative MIC values (e.g., numbers, operators like <=, >=, >, <, ratios like 32/16)?
3. has_sir_calls: Does it contain categorical SIR calls (S, I, R, Susceptible, Resistant, Intermediate)?
4. reasoning: Brief 1-2 sentence explanation of your classification.
"""
        result = query_fn(prompt=prompt, response_schema=SheetClassification)
        classifications.append(result)

    return classifications


def map_columns(
    excel_path: str | Path,
    sheet_name: str,
    query_fn: Callable[..., Any],
) -> SheetColumnMap:
    """Map columns of an Excel worksheet to semantic AST roles using an LLM.

    Args:
        excel_path: Path to the Excel file.
        sheet_name: Name of the worksheet.
        query_fn: Callable to send structured LLM queries.

    Returns:
        SheetColumnMap with roles assigned to each column.
    """
    hdr = detect_header_row(excel_path, sheet_name)
    df_preview = pd.read_excel(excel_path, sheet_name=sheet_name, header=hdr, nrows=8)
    preview_csv = _generate_sheet_preview(df_preview)

    prompt = f"""You are an expert in antimicrobial susceptibility testing (AST) and clinical microbiology data curation.

Analyze the columns of this worksheet and assign a semantic role to each column.

Worksheet Name: "{sheet_name}"
Columns to classify:
{list(df_preview.columns)}

Preview Data (first few rows):
```csv
{preview_csv}
```

Allowed Column Roles:
- "local_id": Local isolate identifier, strain name, or specimen ID (e.g., "Sequencing number", "Specimen number", "Isolate ID").
- "public_accession": Public repository accession (e.g., BioSample accession SAMN*, GenBank, SRA).
- "organism": Species or taxonomic name (e.g. "Salmonella enterica").
- "drug_mic": Column containing MIC values for a specific antimicrobial agent (often abbreviated, e.g., AMP, CIP, TET, CAZ).
- "drug_sir": Column containing SIR category interpretations (S, I, R) for an antibiotic.
- "drug_mic_and_sir": Column containing both MIC and SIR combined.
- "metadata": Demographic, clinical, or epidemiological metadata (e.g., Age, Gender, Year, Symptom, Serotype).
- "skip": Empty, index, or irrelevant columns.

CRITICAL INSTRUCTIONS FOR PAIRED COLUMNS:
In many Excel tables, an antibiotic abbreviation column contains MIC values (e.g., "AMP" with values ">64", "<2"), and the immediately adjacent unnamed column (e.g., "Unnamed: 14") contains the corresponding SIR interpretations ("R", "S").
When you detect this pattern:
- Mark the drug name column as "drug_mic", fill in "drug_name" (e.g. "ampicillin"), and set "paired_with" to the adjacent column name.
- Mark the adjacent unnamed column as "drug_sir", fill in "drug_name", and set "paired_with" to the drug column name.

Provide:
1. sheet_name: "{sheet_name}"
2. header_row_index: {hdr} (or integer row index if headers start on a different row).
3. reasoning: A concise 1-sentence summary of the layout. Keep reasoning short.
4. columns: A ColumnMapping item for EVERY single column listed in "Columns to classify". You MUST classify all {len(df_preview.columns)} columns.
"""
    result = query_fn(prompt=prompt, response_schema=SheetColumnMap)
    if (result.header_row_index is None or result.header_row_index == 0) and hdr > 0:
        result.header_row_index = hdr
    return result


def extract_from_excel(
    excel_path: str | Path,
    pubmed_id: str,
    query_fn: Callable[..., Any],
) -> list[ASTExtractionRecord]:
    """End-to-end extraction from an Excel supplementary file.

    1. Classifies sheets in the workbook.
    2. Selects relevant AST sheets (preferring those with MIC data).
    3. Maps columns using the LLM.
    4. Deterministically unpivots and extracts records.

    Args:
        excel_path: Path to the Excel file.
        pubmed_id: PubMed ID of the publication.
        query_fn: Callable for structured LLM queries.

    Returns:
        List of all extracted ASTExtractionRecord items.
    """
    classifications = classify_sheets(excel_path=excel_path, query_fn=query_fn)

    # Filter sheets with AST data
    ast_sheets = [c for c in classifications if c.contains_ast_data]
    if not ast_sheets:
        return []

    # Prefer sheets with MIC values; if none, use sheets with SIR calls
    mic_sheets = [c for c in ast_sheets if c.has_mic_values]
    target_sheets = mic_sheets if mic_sheets else ast_sheets

    all_records: list[ASTExtractionRecord] = []
    for sheet_info in target_sheets:
        col_map = map_columns(
            excel_path=excel_path,
            sheet_name=sheet_info.sheet_name,
            query_fn=query_fn,
        )
        records = extract_ast_records(
            excel_path=excel_path,
            sheet_name=sheet_info.sheet_name,
            column_map=col_map,
            pubmed_id=pubmed_id,
        )
        all_records.extend(records)

    return all_records
