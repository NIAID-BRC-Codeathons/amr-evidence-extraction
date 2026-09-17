# ==========================================================
# Transformation Code for Sheet: 'Sheet 1'
# ==========================================================

import re
import numpy as np
import pandas as pd

# Drug name dictionary mapping abbreviations and synonyms to standard full drug names
DRUG_MAP = {
    'PEN': 'Penicillin',
    'BENZYLPENICILLIN': 'Benzylpenicillin',
    'AMP': 'Ampicillin',
    'AMX': 'Amoxicillin',
    'OXA': 'Oxacillin',
    'FOX': 'Cefoxitin',
    'GEN': 'Gentamicin',
    'TOB': 'Tobramycin',
    'KAN': 'Kanamycin',
    'AMK': 'Amikacin',
    'STR': 'Streptomycin',
    'SPT': 'Spectinomycin',
    'ERY': 'Erythromycin',
    'CLI': 'Clindamycin',
    'LNZ': 'Linezolid',
    'FUS': 'Fusidic acid',
    'TET': 'Tetracycline',
    'DOX': 'Doxycycline',
    'MIN': 'Minocycline',
    'TGC': 'Tigecycline',
    'CIP': 'Ciprofloxacin',
    'LVX': 'Levofloxacin',
    'MXF': 'Moxifloxacin',
    'VAN': 'Vancomycin',
    'TEC': 'Teicoplanin',
    'DAP': 'Daptomycin',
    'TMP': 'Trimethoprim',
    'SXT': 'Trimethoprim-sulfamethoxazole',
    'SMX': 'Sulfamethoxazole',
    'CHL': 'Chloramphenicol',
    'FOF': 'Fosfomycin',
    'RIF': 'Rifampicin',
    'MUP': 'Mupirocin',
    'NIT': 'Nitrofurantoin',
    'COL': 'Colistin',
    'CZA': 'Ceftazidime-avibactam',
    'TZP': 'Piperacillin-tazobactam',
    'SAM': 'Ampicillin-sulbactam',
    'AMC': 'Amoxicillin-clavulanic acid',
    'CRO': 'Ceftriaxone',
    'CTX': 'Cefotaxime',
    'CAZ': 'Ceftazidime',
    'FEP': 'Cefepime',
    'MEM': 'Meropenem',
    'IPM': 'Imipenem',
    'ETP': 'Ertapenem',
    'QAC': 'Quaternary ammonium compounds',
}

# Standard European S. aureus AST panel corresponding to repeating MIC/RIS columns
DEFAULT_PANEL = [
    'Penicillin',
    'Cefoxitin',
    'Gentamicin',
    'Tobramycin',
    'Erythromycin',
    'Clindamycin',
    'Linezolid',
    'Fusidic acid',
    'Tetracycline',
    'Ciprofloxacin',
    'Vancomycin',
    'Trimethoprim',
    'Chloramphenicol',
    'Teicoplanin',
    'Fosfomycin',
    'Rifampicin',
    'Streptomycin',
    'Mupirocin',
    'Quaternary ammonium compounds',
]

ACCESSION_PATTERN = re.compile(
    r'\b(?:SAM[NED][A-Z]?\d+|[ESD]R[RPXSA]\d+|GC[AF]_\d+\.\d+)\b'
)

SIR_PATTERN = re.compile(r'\b(SDD|NS|[SIR])\b', re.IGNORECASE)
MIC_PATTERN = re.compile(
    r'(<=|>=|<|>|=)?\s*([0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+(?:\.[0-9]+)?)?)'
)


def _normalize_drug_name(name: str) -> str:
    cleaned = re.sub(
        r'(_mic|_sir|_ris|\bmic\b|\br/i/s\b|\brisk\b|\binterpretation\b)',
        '',
        name,
        flags=re.IGNORECASE,
    ).strip(' _-.:')
    upper_cleaned = cleaned.upper()
    return DRUG_MAP.get(upper_cleaned, cleaned)


def _parse_mic_cell(val):
    if pd.isna(val):
        return None, None, None
    s = str(val).strip()
    if not s or s in {'-', 'ND', 'N/A', 'NA', '.', 'not recorded'}:
        return None, None, None

    match = MIC_PATTERN.search(s)
    if match and match.group(2):
        sign = match.group(1)
        mic_val = match.group(2).replace(' ', '')
        if sign:
            return sign, mic_val, None
        else:
            return '=', mic_val, "mic_sign '=' inferred"
    return None, None, None


def _parse_sir_cell(val):
    if pd.isna(val):
        return None
    s = str(val).strip()
    if not s or s in {'-', 'ND', 'N/A', 'NA', '.', 'not recorded'}:
        return None
    match = SIR_PATTERN.search(s)
    if match:
        return match.group(1).upper()
    return None


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 1. Identify isolate ID column
    isolate_col = None
    for col in df.columns:
        norm = str(col).strip().lower()
        if any(
            k in norm
            for k in [
                'sample id',
                'sample_id',
                'isolate id',
                'isolate_id',
                'specimen',
                'strain',
                'patient isolate',
            ]
        ):
            isolate_col = col
            break

    # 2. Identify accession column(s)
    accession_cols = [
        col
        for col in df.columns
        if any(
            k in str(col).strip().lower()
            for k in ['accession', 'ena', 'ncbi', 'biosample', 'sra', 'srr']
        )
    ]

    # Pre-extract isolate IDs and accessions per row
    num_rows = len(df)
    isolate_ids = []
    accessions = []

    for idx in range(num_rows):
        row = df.iloc[idx]

        # Isolate ID
        if isolate_col is not None and pd.notna(row[isolate_col]):
            iso_val = str(row[isolate_col]).strip()
            isolate_ids.append(iso_val if iso_val else None)
        else:
            isolate_ids.append(None)

        # Accession
        found_accs = []
        if accession_cols:
            for acc_col in accession_cols:
                val = str(row[acc_col]) if pd.notna(row[acc_col]) else ''
                matches = ACCESSION_PATTERN.findall(val)
                for m in matches:
                    if m not in found_accs:
                        found_accs.append(m)
        else:
            # Fallback search across all text in the row
            row_str = ' '.join([str(v) for v in row if pd.notna(v)])
            matches = ACCESSION_PATTERN.findall(row_str)
            for m in matches:
                if m not in found_accs:
                    found_accs.append(m)

        accessions.append(','.join(found_accs) if found_accs else None)

    # 3. Detect AST columns
    # Check if we have standard indexed MIC, R/I/S columns (e.g. MIC, MIC.1, R/I/S, R/I/S.1)
    mic_cols = [
        col
        for col in df.columns
        if re.match(r'^MIC(\.\d+)?$', str(col).strip(), re.IGNORECASE)
    ]
    ris_cols = [
        col
        for col in df.columns
        if re.match(
            r'^(R/I/S|RIS|SIR)(\.\d+)?$', str(col).strip(), re.IGNORECASE
        )
    ]

    records = []

    if mic_cols:
        # Paired/tripled indexed AST format
        for i, mic_c in enumerate(mic_cols):
            # Corresponding RIS column
            ris_c = None
            suffix = (
                re.search(r'\.(\d+)$', str(mic_c).strip())
                if '.' in str(mic_c)
                else None
            )
            idx_num = suffix.group(1) if suffix else ''

            for r_col in ris_cols:
                r_suffix = (
                    re.search(r'\.(\d+)$', str(r_col).strip())
                    if '.' in str(r_col)
                    else None
                )
                r_num = r_suffix.group(1) if r_suffix else ''
                if idx_num == r_num:
                    ris_c = r_col
                    break

            drug_name = (
                DEFAULT_PANEL[i]
                if i < len(DEFAULT_PANEL)
                else f'Antimicrobial_{i+1}'
            )

            for row_idx in range(num_rows):
                mic_raw = df[mic_c].iloc[row_idx]
                ris_raw = df[ris_c].iloc[row_idx] if ris_c else None

                sign, mic_val, notes = _parse_mic_cell(mic_raw)
                sir_val = _parse_sir_cell(ris_raw)

                # Check if SIR is inside the MIC cell if not found in RIS cell
                if sir_val is None:
                    sir_val = _parse_sir_cell(mic_raw)

                if mic_val is None and sir_val is None:
                    continue

                records.append(
                    {
                        'isolate_id': isolate_ids[row_idx],
                        'accession': accessions[row_idx],
                        'drug': drug_name,
                        'mic_sign': sign,
                        'mic': mic_val,
                        'sir_call': sir_val,
                        'notes': notes,
                    }
                )
    else:
        # Drug names explicitly in column headers
        ignore_keywords = [
            'case status',
            'sample id',
            'patient',
            'age',
            'sex',
            'accession',
            'clonal',
            'sequence type',
            'st',
            'cc',
            'genotype',
            'specimen',
            'date',
            'source',
            'species',
            'qc',
        ]
        drug_columns = []
        for col in df.columns:
            col_lower = str(col).strip().lower()
            if any(k in col_lower for k in ignore_keywords):
                continue
            drug_columns.append(col)

        for col in drug_columns:
            drug_name = _normalize_drug_name(str(col))
            for row_idx in range(num_rows):
                val = df[col].iloc[row_idx]
                sign, mic_val, notes = _parse_mic_cell(val)
                sir_val = _parse_sir_cell(val)

                if mic_val is None and sir_val is None:
                    continue

                records.append(
                    {
                        'isolate_id': isolate_ids[row_idx],
                        'accession': accessions[row_idx],
                        'drug': drug_name,
                        'mic_sign': sign,
                        'mic': mic_val,
                        'sir_call': sir_val,
                        'notes': notes,
                    }
                )

    out_df = pd.DataFrame(
        records,
        columns=[
            'isolate_id',
            'accession',
            'drug',
            'mic_sign',
            'mic',
            'sir_call',
            'notes',
        ],
    )
    return out_df

