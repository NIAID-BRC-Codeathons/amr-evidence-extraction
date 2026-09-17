# ==========================================================
# Transformation Code for Sheet: 'Sheet 1'
# ==========================================================

import re
import pandas as pd
import numpy as np

# Mapping of common antimicrobial abbreviations to full names
DRUG_MAP = {
    'PEN': 'Penicillin',
    'BENZYLPENICILLIN': 'Benzylpenicillin',
    'PG': 'Benzylpenicillin',
    'AMP': 'Ampicillin',
    'AMX': 'Amoxicillin',
    'AMC': 'Amoxicillin-clavulanate',
    'AUG': 'Amoxicillin-clavulanate',
    'SAM': 'Ampicillin-sulbactam',
    'TZP': 'Piperacillin-tazobactam',
    'PIP': 'Piperacillin',
    'TIC': 'Ticarcillin',
    'TIM': 'Ticarcillin-clavulanate',
    'OXA': 'Oxacillin',
    'OX': 'Oxacillin',
    'MET': 'Methicillin',
    'FOX': 'Cefoxitin',
    'CFX': 'Cefoxitin',
    'CZO': 'Cefazolin',
    'CZ': 'Cefazolin',
    'FEP': 'Cefepime',
    'CTX': 'Cefotaxime',
    'CAZ': 'Ceftazidime',
    'CRO': 'Ceftriaxone',
    'CXM': 'Cefuroxime',
    'MEM': 'Meropenem',
    'IPM': 'Imipenem',
    'ETP': 'Ertapenem',
    'DOR': 'Doripenem',
    'CIP': 'Ciprofloxacin',
    'CI': 'Ciprofloxacin',
    'LVX': 'Levofloxacin',
    'LEV': 'Levofloxacin',
    'MXF': 'Moxifloxacin',
    'MFX': 'Moxifloxacin',
    'OFX': 'Ofloxacin',
    'NAL': 'Nalidixic acid',
    'GEN': 'Gentamicin',
    'GM': 'Gentamicin',
    'GENN': 'Gentamicin',
    'TOB': 'Tobramycin',
    'TM': 'Tobramycin',
    'AMK': 'Amikacin',
    'AN': 'Amikacin',
    'KAN': 'Kanamycin',
    'KM': 'Kanamycin',
    'STR': 'Streptomycin',
    'SPT': 'Spectinomycin',
    'ERY': 'Erythromycin',
    'ER': 'Erythromycin',
    'E': 'Erythromycin',
    'CLI': 'Clindamycin',
    'CD': 'Clindamycin',
    'CC': 'Clindamycin',
    'AZM': 'Azithromycin',
    'CLR': 'Clarithromycin',
    'LNZ': 'Linezolid',
    'LZD': 'Linezolid',
    'LZ': 'Linezolid',
    'TED': 'Tedizolid',
    'VAN': 'Vancomycin',
    'VA': 'Vancomycin',
    'TEC': 'Teicoplanin',
    'TP': 'Teicoplanin',
    'DAP': 'Daptomycin',
    'FUS': 'Fusidic acid',
    'FA': 'Fusidic acid',
    'TET': 'Tetracycline',
    'TE': 'Tetracycline',
    'TCY': 'Tetracycline',
    'DOX': 'Doxycycline',
    'MIN': 'Minocycline',
    'TGC': 'Tigecycline',
    'TMP': 'Trimethoprim',
    'TR': 'Trimethoprim',
    'SXT': 'Trimethoprim-sulfamethoxazole',
    'COT': 'Trimethoprim-sulfamethoxazole',
    'TS': 'Trimethoprim-sulfamethoxazole',
    'CHL': 'Chloramphenicol',
    'C': 'Chloramphenicol',
    'RIF': 'Rifampicin',
    'RI': 'Rifampicin',
    'RA': 'Rifampicin',
    'MUP': 'Mupirocin',
    'MU': 'Mupirocin',
    'COL': 'Colistin',
    'CST': 'Colistin',
    'POL': 'Polymyxin B',
    'NIT': 'Nitrofurantoin',
    'FOS': 'Fosfomycin',
    'QDA': 'Quinupristin-dalfopristin',
    'SYN': 'Quinupristin-dalfopristin',
}

# Standard panel sequence for this S. aureus AST dataset
DEFAULT_DRUGS_PANEL = [
    'Penicillin',
    'Oxacillin',
    'Gentamicin',
    'Tobramycin',
    'Erythromycin',
    'Clindamycin',
    'Daptomycin',
    'Fusidic acid',
    'Ciprofloxacin',
    'Trimethoprim',
    'Linezolid',
    'Rifampicin',
    'Tetracycline',
    'Teicoplanin',
    'Vancomycin',
    'Mupirocin',
    'Spectinomycin',
    'Trimethoprim-sulfamethoxazole',
    'Quaternary ammonium compound'
]

ACCESSION_REGEX = re.compile(
    r'\b(SAM[NEAD][A-Z0-9]*\d+|[EDS]R[SRAPXZ]\d+|GCA_\d+\.\d+|GCF_\d+\.\d+)\b',
    re.IGNORECASE
)

def normalize_sir(val):
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().upper()
    if s in ['S', 'I', 'R', 'SDD', 'NS']:
        return s
    # Check if contained in parentheses or prefixed
    m = re.search(r'\b(SDD|NS|[SIR])\b', s)
    if m:
        return m.group(1)
    return None

def parse_mic_value(val):
    if val is None or pd.isna(val):
        return None, None, None
    s = str(val).strip()
    if s in ['', '-', 'ND', 'N/A', 'NA', '.', 'nan', 'None']:
        return None, None, None

    # Check for inequality sign and numeric part
    match = re.search(r'(<=|>=|<|>|=)?\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)', s)
    if match:
        sign, mic = match.groups()
        if sign:
            return sign, mic.replace(" ", ""), None
        else:
            return '=', mic.replace(" ", ""), "mic_sign '=' inferred"
    return None, None, None

def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    # 1. Clean column names
    df = df.copy()
    raw_cols = list(df.columns)
    clean_col_names = [str(c).strip() for c in raw_cols]
    df.columns = clean_col_names

    # 2. Identify isolate_id column
    isolate_col = None
    for c in df.columns:
        if re.search(r'sample\s*id|isolate|specimen|strain', c, re.IGNORECASE):
            isolate_col = c
            break

    # 3. Identify accession column(s)
    accession_cols = [
        c for c in df.columns
        if re.search(r'accession|ena|biosample|sra|genbank|assembly', c, re.IGNORECASE)
    ]

    # Pre-extract isolate IDs and public accessions
    n_rows = len(df)
    isolate_ids = []
    accessions = []

    for idx in range(n_rows):
        # Isolate ID
        if isolate_col is not None:
            val = df.iloc[idx][isolate_col]
            iso_id = str(val).strip() if pd.notna(val) else None
        else:
            iso_id = None
        isolate_ids.append(iso_id)

        # Accession
        found_accs = []
        for ac_col in accession_cols:
            val = df.iloc[idx][ac_col]
            if pd.notna(val):
                matches = ACCESSION_REGEX.findall(str(val))
                for m in matches:
                    m_clean = m.strip()
                    if m_clean not in found_accs:
                        found_accs.append(m_clean)
        accessions.append(','.join(found_accs) if found_accs else None)

    # 4. Extract AST measurements
    # Check if we have paired MIC / R/I/S repeated columns
    mic_cols = [c for c in df.columns if re.match(r'^MIC(?:\.\d+)?$', c, re.IGNORECASE)]
    records = []

    if mic_cols:
        # Paired structure: MIC, R/I/S, Genotype triples
        for i in range(len(DEFAULT_DRUGS_PANEL)):
            m_col = 'MIC' if i == 0 else f'MIC.{i}'
            s_col = 'R/I/S' if i == 0 else f'R/I/S.{i}'

            if m_col not in df.columns and s_col not in df.columns:
                continue

            drug_name = DEFAULT_DRUGS_PANEL[i] if i < len(DEFAULT_DRUGS_PANEL) else f'Drug_{i+1}'

            for idx in range(n_rows):
                m_val = df.iloc[idx][m_col] if m_col in df.columns else None
                s_val = df.iloc[idx][s_col] if s_col in df.columns else None

                mic_sign, mic, notes = parse_mic_value(m_val)
                sir_call = normalize_sir(s_val)

                # Also try to extract SIR from MIC column if missing
                if sir_call is None and pd.notna(m_val):
                    sir_call = normalize_sir(m_val)

                # Discard if both mic and sir_call are missing
                if mic is None and sir_call is None:
                    continue

                records.append({
                    'isolate_id': isolate_ids[idx],
                    'accession': accessions[idx],
                    'drug': drug_name,
                    'mic_sign': mic_sign,
                    'mic': mic,
                    'sir_call': sir_call,
                    'notes': notes
                })
    else:
        # General wide-format extraction for drug-named columns
        non_drug_regex = re.compile(
            r'sample|isolate|specimen|strain|patient|age|sex|gender|date|status|cc|st|'
            r'clonal|sequence\s*type|accession|ena|genotype',
            re.IGNORECASE
        )
        drug_columns = [c for c in df.columns if not non_drug_regex.search(c)]

        for col in drug_columns:
            clean_name = col.strip()
            drug_name = DRUG_MAP.get(clean_name.upper(), clean_name)

            for idx in range(n_rows):
                val = df.iloc[idx][col]
                mic_sign, mic, notes = parse_mic_value(val)
                sir_call = normalize_sir(val)

                if mic is None and sir_call is None:
                    continue

                records.append({
                    'isolate_id': isolate_ids[idx],
                    'accession': accessions[idx],
                    'drug': drug_name,
                    'mic_sign': mic_sign,
                    'mic': mic,
                    'sir_call': sir_call,
                    'notes': notes
                })

    out_cols = ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
    if not records:
        return pd.DataFrame(columns=out_cols)

    return pd.DataFrame(records)[out_cols]

