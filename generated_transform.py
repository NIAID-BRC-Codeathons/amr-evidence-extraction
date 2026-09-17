# ==========================================================
# Transformation Code for Sheet: 'Table_2.XLSX::Sheet1'
# ==========================================================

import re
import numpy as np
import pandas as pd

# Mapping of common AST drug abbreviations to standardized full names
DRUG_ABBREVIATIONS = {
    'AMK': 'Amikacin',
    'AMP': 'Ampicillin',
    'SAM': 'Ampicillin/Sulbactam',
    'ATM': 'Aztreonam',
    'CZO': 'Cefazolin',
    'CFZ': 'Cefazolin',
    'FAZ': 'Cefazolin',
    'FEP': 'Cefepime',
    'CPM': 'Cefepime',
    'CEF': 'Cephalothin',
    'MEM': 'Meropenem',
    'ETP': 'Ertapenem',
    'CXM': 'Cefuroxime',
    'GEN': 'Gentamicin',
    'CIP': 'Ciprofloxacin',
    'TZP': 'Piperacillin/Tazobactam',
    'FOX': 'Cefoxitin',
    'TMP': 'Trimethoprim',
    'SXT': 'Sulfamethoxazole/Trimethoprim',
    'SMX': 'Sulfamethoxazole',
    'CPD': 'Cefpodoxime',
    'CAZ': 'Ceftazidime',
    'TOB': 'Tobramycin',
    'TGC': 'Tigecycline',
    'TIM': 'Ticarcillin/Clavulanic Acid',
    'CRO': 'Ceftriaxone',
    'TET': 'Tetracycline',
    'CST': 'Colistin',
    'COL': 'Colistin',
    'AMX': 'Amoxicillin',
    'AMC': 'Amoxicillin/Clavulanic Acid',
    'AUG': 'Amoxicillin/Clavulanic Acid',
    'APR': 'Apramycin',
    'AZM': 'Azithromycin',
    'CHL': 'Chloramphenicol',
    'CLI': 'Clindamycin',
    'CC': 'Clindamycin',
    'DOX': 'Doxycycline',
    'ERY': 'Erythromycin',
    'E': 'Erythromycin',
    'FFN': 'Florfenicol',
    'FOF': 'Fosfomycin',
    'IPM': 'Imipenem',
    'IMI': 'Imipenem',
    'KAN': 'Kanamycin',
    'K': 'Kanamycin',
    'LNZ': 'Linezolid',
    'LZD': 'Linezolid',
    'MIN': 'Minocycline',
    'NAL': 'Nalidixic Acid',
    'NEO': 'Neomycin',
    'NET': 'Netilmicin',
    'PEN': 'Penicillin',
    'P': 'Penicillin',
    'PIP': 'Piperacillin',
    'RIF': 'Rifampicin',
    'RA': 'Rifampicin',
    'SIS': 'Sisomicin',
    'SPT': 'Spectinomycin',
    'STR': 'Streptomycin',
    'S': 'Streptomycin',
    'TEC': 'Teicoplanin',
    'TEL': 'Telithromycin',
    'TIC': 'Ticarcillin',
    'VAN': 'Vancomycin',
    'VA': 'Vancomycin',
}

SIR_MAP = {
    'S': 'S',
    'I': 'I',
    'R': 'R',
    'SDD': 'SDD',
    'NS': 'NS',
    'SUSCEPTIBLE': 'S',
    'INTERMEDIATE': 'I',
    'RESISTANT': 'R',
    'NON-SUSCEPTIBLE': 'NS',
    'SUSCEPTIBLE-DOSE DEPENDENT': 'SDD',
}

ACCESSION_PATTERN = re.compile(
    r'\b(SAM[NED][A-Z]?\d+|SRS\d+|GCA_\d+\.\d+|GCF_\d+\.\d+|[ESD]RR\d+)\b',
    re.IGNORECASE,
)

NON_DRUG_COLS = {
    'temperature',
    'species',
    'organism',
    'panel',
    'qc',
    'date',
    'patient',
    'hospital',
    'source',
    'gender',
    'age',
    'specimen',
    'id',
    'isolate',
    'sample',
    'strain',
}


def normalize_drug_name(name: str) -> str:
    name_clean = str(name).strip()
    upper_name = name_clean.upper()
    if upper_name in DRUG_ABBREVIATIONS:
        return DRUG_ABBREVIATIONS[upper_name]
    # Standardize multi-component drug names (e.g. ampicillin/sulbactam -> Ampicillin/Sulbactam)
    parts = re.split(r'([/+\-])', name_clean)
    return ''.join(p.capitalize() if p not in ['/', '+', '-'] else p for p in parts)


def parse_ast_cell(val):
    if pd.isna(val):
        return None, None, None, None

    s = str(val).strip()
    if not s or s.lower() in {'nan', 'none', 'null', 'nd', 'n/a', 'na', '-', '.', '/'}:
        return None, None, None, None

    # Normalize decimal commas to dots and inequality symbols
    s_norm = re.sub(r'(\d+),(\d+)', r'\1.\2', s)
    s_norm = s_norm.replace('≤', '<=').replace('≥', '>=')

    # Pure SIR call
    if s_norm.upper() in SIR_MAP:
        return None, None, SIR_MAP[s_norm.upper()], None

    # Pattern: [Sign] [MIC value/ratio] [optional (SIR) or SIR]
    pattern = r'^(<=|>=|<|>|=)?\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)\s*(?:\(?\s*([A-Za-z]+)\s*\)?)?$'
    m = re.match(pattern, s_norm)
    if m:
        sign_part, num_part, sir_part = m.groups()
        mic = re.sub(r'\s*/\s*', '/', num_part)

        if sign_part:
            mic_sign = sign_part
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"

        sir_call = None
        if sir_part and sir_part.upper() in SIR_MAP:
            sir_call = SIR_MAP[sir_part.upper()]

        return mic_sign, mic, sir_call, notes

    return None, None, None, None


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
        )

    # 1. Identify isolate_id and metadata columns
    isolate_col = None
    cols = list(df.columns)

    # Check for named isolate ID column
    for col in cols:
        col_str = str(col).lower()
        if any(k in col_str for k in ['isolate', 'sample', 'specimen', 'strain', 'id', 'patient']):
            isolate_col = col
            break

    # If headers are 'Unnamed', check the first non-empty text columns
    if isolate_col is None:
        for col in cols[:5]:
            non_na = df[col].dropna().astype(str).str.strip()
            # If values look like isolate identifiers (e.g. 1D-001)
            if len(non_na) > 0 and not non_na.str.contains(r'^[<>=≤≥]?\d').any():
                isolate_col = col
                break

    if isolate_col is None and len(cols) > 1:
        isolate_col = cols[1]

    # 2. Extract public accessions if present
    def extract_accessions_from_row(row):
        found = []
        for v in row:
            if pd.notna(v):
                matches = ACCESSION_PATTERN.findall(str(v))
                for m in matches:
                    if m not in found:
                        found.append(m)
        return ','.join(found) if found else None

    # 3. Identify candidate drug columns
    drug_cols = []
    for col in cols:
        col_name = str(col).strip()
        if col == isolate_col or col_name.lower().startswith('unnamed:'):
            continue
        if col_name.lower() in NON_DRUG_COLS:
            continue
        drug_cols.append(col)

    # 4. Iterate and extract records
    records = []
    for _, row in df.iterrows():
        raw_id = row[isolate_col] if isolate_col is not None else None
        isolate_id = str(raw_id).strip() if pd.notna(raw_id) and str(raw_id).strip() != '' else None
        
        # Skip rows that don't have an isolate ID or are annotation-only rows
        if not isolate_id:
            continue

        accession = extract_accessions_from_row(row)

        for col in drug_cols:
            val = row[col]
            mic_sign, mic, sir_call, notes = parse_ast_cell(val)

            # Discard if both mic and sir_call are missing
            if mic is None and sir_call is None:
                continue

            drug_name = normalize_drug_name(col)
            records.append({
                'isolate_id': isolate_id,
                'accession': accession,
                'drug': drug_name,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes,
            })

    result_df = pd.DataFrame(
        records,
        columns=['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
    )
    return result_df

# ==========================================================
# Transformation Code for Sheet: 'Table_1.XLSX::Sheet1'
# ==========================================================

import re
import numpy as np
import pandas as pd


def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Extracts mapping records between isolate identifiers and public database accessions

    from bioinformatics metadata worksheets.
    """
    df = df.copy()

    # Identify isolate ID column
    isolate_id_col = None
    isolate_col_patterns = [
        r"^id\b",
        r"^id\s*\(\d+\)",
        r"isolate",
        r"sample[-_\s]*id",
        r"strain",
        r"cvm_number",
        r"lab[-_\s]*id",
    ]
    for pattern in isolate_col_patterns:
        for col in df.columns:
            if re.search(pattern, str(col).strip(), re.IGNORECASE):
                isolate_id_col = col
                break
        if isolate_id_col is not None:
            break

    # If not found by pattern, fallback to first non-empty/non-unnamed column
    if isolate_id_col is None:
        for col in df.columns:
            if not str(col).startswith("Unnamed:"):
                isolate_id_col = col
                break

    # Regular expressions for accession types
    biosample_pattern = re.compile(
        r"\b(SAMN\d+|SAMEA\d+|SAMD\d+|ERS\d+|SRS\d+|DRS\d+)\b", re.IGNORECASE
    )
    all_accession_pattern = re.compile(
        r"\b(SAMN\d+|SAMEA\d+|SAMD\d+|ERS\d+|SRS\d+|DRS\d+|"
        r"[SED]RR\d+|[SED]RX\d+|[SED]RP\d+|PRJ[NED][A-Z]\d+|"
        r"GC[AF]_\d+\.\d+|[A-Z]{4,6}\d{6,8}(\.\d+)?)\b",
        re.IGNORECASE,
    )

    # Detect accession columns
    accession_cols = []
    for col in df.columns:
        col_str = str(col)
        # Check column name
        if re.search(
            r"accession|run|sample|ers|err|srr|sra|biosample|bioproject",
            col_str,
            re.IGNORECASE,
        ):
            # Check if values actually match accessions
            sample_vals = (
                df[col].dropna().astype(str).head(20).tolist()
            )
            if any(all_accession_pattern.search(v) for v in sample_vals):
                accession_cols.append(col)
        else:
            sample_vals = (
                df[col].dropna().astype(str).head(20).tolist()
            )
            if sum(bool(all_accession_pattern.search(v)) for v in sample_vals) >= max(
                1, len(sample_vals) * 0.5
            ):
                accession_cols.append(col)

    records = []
    for _, row in df.iterrows():
        # Extract isolate ID
        iso_val = None
        if isolate_id_col is not None and pd.notna(row[isolate_id_col]):
            val_str = str(row[isolate_id_col]).strip()
            if val_str and val_str.lower() != "nan":
                iso_val = val_str

        # Extract accessions
        primary_accs = []
        secondary_accs = []
        all_accs = []

        for col in accession_cols:
            if pd.notna(row[col]):
                val = str(row[col]).strip()
                matches = all_accession_pattern.findall(val)
                for m in matches:
                    acc_str = m[0] if isinstance(m, tuple) else m
                    acc_str = acc_str.strip()
                    if acc_str and acc_str not in all_accs:
                        all_accs.append(acc_str)
                        if biosample_pattern.match(acc_str):
                            if acc_str not in primary_accs:
                                primary_accs.append(acc_str)
                        else:
                            if acc_str not in secondary_accs:
                                secondary_accs.append(acc_str)

        acc_str = ",".join(all_accs) if all_accs else None
        sec_str = ",".join(secondary_accs) if secondary_accs else None

        # Discard rows where BOTH isolate_id and accession are missing
        if iso_val is None and acc_str is None:
            continue

        records.append(
            {
                "isolate_id": iso_val,
                "accession": acc_str,
                "secondary_accession": sec_str,
            }
        )

    result_df = pd.DataFrame(
        records, columns=["isolate_id", "accession", "secondary_accession"]
    )
    return result_df

