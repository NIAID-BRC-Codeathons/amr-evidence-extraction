# ==========================================================
# Transformation Code for Sheet: 'Table_2.XLSX::Sheet1'
# ==========================================================

import re
import numpy as np
import pandas as pd

# Standard abbreviations mapped to full drug names
DRUG_ABBREVIATIONS = {
    'AMK': 'Amikacin',
    'AMP': 'Ampicillin',
    'SAM': 'Ampicillin/sulbactam',
    'ATM': 'Aztreonam',
    'CZO': 'Cefazolin',
    'FEP': 'Cefepime',
    'CEF': 'Cephalothin',
    'MEM': 'Meropenem',
    'ETP': 'Ertapenem',
    'CXM': 'Cefuroxime',
    'GEN': 'Gentamicin',
    'CIP': 'Ciprofloxacin',
    'TZP': 'Piperacillin/tazobactam',
    'FOX': 'Cefoxitin',
    'TMP': 'Trimethoprim',
    'SXT': 'Sulfamethoxazole/trimethoprim',
    'SMX': 'Sulfamethoxazole',
    'CPD': 'Cefpodoxime',
    'CAZ': 'Ceftazidime',
    'TOB': 'Tobramycin',
    'TGC': 'Tigecycline',
    'TIM': 'Ticarcillin/clavulanic acid',
    'CRO': 'Ceftriaxone',
    'TET': 'Tetracycline',
    'COL': 'Colistin',
    'CST': 'Colistin',
    'AMX': 'Amoxicillin',
    'AMC': 'Amoxicillin/clavulanic acid',
    'AUG': 'Amoxicillin/clavulanic acid',
    'AZM': 'Azithromycin',
    'CHL': 'Chloramphenicol',
    'CLI': 'Clindamycin',
    'DOX': 'Doxycycline',
    'ERY': 'Erythromycin',
    'FFN': 'Florfenicol',
    'FOF': 'Fosfomycin',
    'IPM': 'Imipenem',
    'KAN': 'Kanamycin',
    'LNZ': 'Linezolid',
    'MIN': 'Minocycline',
    'NAL': 'Nalidixic acid',
    'NEO': 'Neomycin',
    'NIT': 'Nitrofurantoin',
    'OXA': 'Oxacillin',
    'PEN': 'Penicillin',
    'PIP': 'Piperacillin',
    'RIF': 'Rifampicin',
    'STR': 'Streptomycin',
    'TEC': 'Teicoplanin',
    'VAN': 'Vancomycin',
}

NON_DRUG_COL_PATTERNS = [
    r'unnamed',
    r'isolate',
    r'sample',
    r'specimen',
    r'strain',
    r'patient',
    r'species',
    r'organism',
    r'genus',
    r'panel',
    r'card',
    r'date',
    r'temperature',
    r'accession',
    r'biosample',
    r'qc',
    r'comment',
    r'note',
    r'run',
    r'batch',
]


def normalize_sir(sir_str: str):
    if not sir_str:
        return None
    s = sir_str.strip().upper()
    if s in ['S', 'SUSCEPTIBLE']:
        return 'S'
    if s in ['I', 'INTERMEDIATE']:
        return 'I'
    if s in ['R', 'RESISTANT']:
        return 'R'
    if s in ['SDD']:
        return 'SDD'
    if s in ['NS', 'NONSUSCEPTIBLE', 'NON-SUSCEPTIBLE']:
        return 'NS'
    return None


def parse_mic_cell(val):
    if pd.isna(val):
        return None, None, None, None

    s = str(val).strip()
    if not s or s.lower() in [
        'nan',
        'none',
        'null',
        'nd',
        'n/a',
        '-',
        '.',
        'na',
        'neg',
        'pos',
    ]:
        return None, None, None, None

    # Replace European decimal comma with dot (e.g. 0,5 -> 0.5)
    s_clean = re.sub(r'(\d),(\d)', r'\1.\2', s)

    # Pattern for MIC with optional inequality sign and optional SIR call
    mic_sir_pattern = re.compile(
        r'^\s*(?P<sign><=|>=|≤|≥|<|>|=)?\s*'
        r'(?P<mic>\d+(?:\.\d+)?(?:\s*\/\s*\d+(?:\.\d+)?)*)\s*'
        r'(?:[\(\[\s]\s*(?P<sir>SDD|NS|S|I|R|SUSCEPTIBLE|INTERMEDIATE|RESISTANT|NONSUSCEPTIBLE)\s*[\)\]]?)?\s*$',
        re.IGNORECASE,
    )

    sir_only_pattern = re.compile(
        r'^\s*[\(\[]?\s*(?P<sir>SDD|NS|S|I|R|SUSCEPTIBLE|INTERMEDIATE|RESISTANT|NONSUSCEPTIBLE)\s*[\)\]]?\s*$',
        re.IGNORECASE,
    )

    m = mic_sir_pattern.match(s_clean)
    if m:
        raw_sign = m.group('sign')
        raw_mic = m.group('mic')
        raw_sir = m.group('sir')

        if raw_sign in ['≤', '<=']:
            mic_sign = '<='
            notes = None
        elif raw_sign in ['≥', '>=']:
            mic_sign = '>='
            notes = None
        elif raw_sign == '<':
            mic_sign = '<'
            notes = None
        elif raw_sign == '>':
            mic_sign = '>'
            notes = None
        elif raw_sign == '=':
            mic_sign = '='
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"

        mic = raw_mic.replace(' ', '')
        sir_call = normalize_sir(raw_sir)
        return mic_sign, mic, sir_call, notes

    m_sir = sir_only_pattern.match(s_clean)
    if m_sir:
        sir_call = normalize_sir(m_sir.group('sir'))
        return None, None, sir_call, None

    return None, None, None, None


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                'isolate_id',
                'accession',
                'drug',
                'mic_sign',
                'mic',
                'sir_call',
                'notes',
            ]
        )

    # 1. Identify isolate ID column
    isolate_col = None
    for col in df.columns:
        col_name = str(col).strip().lower()
        if any(
            k in col_name
            for k in [
                'isolate_id',
                'isolate',
                'specimen',
                'strain',
                'sample_id',
                'sample',
            ]
        ):
            isolate_col = col
            break

    if isolate_col is None:
        # Fallback to examining first columns (Unnamed: 0, Unnamed: 1, etc.)
        for col in df.columns[:5]:
            non_nulls = df[col].dropna().astype(str).str.strip()
            # Avoid columns that are entirely empty or look like species names
            if (
                len(non_nulls) > 0
                and not non_nulls.str.contains('^[A-Z][a-z]+ [a-z]+').all()
            ):
                isolate_col = col
                break

    # 2. Identify accession column(s)
    accession_cols = []
    acc_pattern = re.compile(
        r'\b(SAM[NED][A-Z]?\d+|SRS\d+|PRJ[NED][A-Z]?\d+|GCA_\d+\.\d+|GCF_\d+\.\d+|[SED]RR\d+|[SED]RX\d+|[SED]RA\d+)\b'
    )
    for col in df.columns:
        col_name = str(col).strip().lower()
        if any(
            k in col_name
            for k in ['accession', 'biosample', 'sra', 'genbank', 'ena']
        ):
            accession_cols.append(col)

    # 3. Identify drug columns
    drug_cols = []
    for col in df.columns:
        col_str = str(col).strip()
        col_lower = col_str.lower()

        # Skip isolate column, accession column, and known non-drug metadata
        if col == isolate_col or col in accession_cols:
            continue
        if any(re.search(pat, col_lower) for pat in NON_DRUG_COL_PATTERNS):
            continue

        drug_cols.append(col)

    # 4. Extract rows
    records = []
    for idx, row in df.iterrows():
        # Get isolate_id
        isolate_val = row[isolate_col] if isolate_col is not None else None
        if pd.isna(isolate_val) or str(isolate_val).strip() == '':
            continue
        isolate_id = str(isolate_val).strip()

        # Extract public accessions
        accessions = []
        for acc_col in accession_cols:
            val = row[acc_col]
            if pd.notna(val):
                found = acc_pattern.findall(str(val))
                accessions.extend(found)

        # Check full row for potential accession strings if none found in dedicated columns
        if not accessions:
            for val in row.values:
                if pd.notna(val):
                    found = acc_pattern.findall(str(val))
                    accessions.extend(found)

        accessions = list(dict.fromkeys(accessions))  # deduplicate preserving order
        accession_str = ','.join(accessions) if accessions else None

        # Parse each drug
        for drug_col in drug_cols:
            cell_val = row[drug_col]
            mic_sign, mic, sir_call, notes = parse_mic_cell(cell_val)

            # Discard cells without valid mic or sir_call
            if mic is None and sir_call is None:
                continue

            # Standardize drug name
            raw_drug = str(drug_col).strip()
            drug_upper = raw_drug.upper()
            drug_name = DRUG_ABBREVIATIONS.get(drug_upper, raw_drug)

            records.append(
                {
                    'isolate_id': isolate_id,
                    'accession': accession_str,
                    'drug': drug_name,
                    'mic_sign': mic_sign,
                    'mic': mic,
                    'sir_call': sir_call,
                    'notes': notes,
                }
            )

    result_df = pd.DataFrame(
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
    return result_df

# ==========================================================
# Transformation Code for Sheet: 'Table_1.XLSX::Sheet1'
# ==========================================================

import re
import numpy as np
import pandas as pd


def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Extracts mapping records between isolate identifiers and public database accessions."""
    df_clean = df.copy()

    # Identify isolate ID column
    isolate_col = None
    for col in df_clean.columns:
        col_str = str(col).strip()
        if re.search(
            r"^(?:id\b|isolate|strain|sample[\s_-]*id|cvm[\s_-]*number|lab[\s_-]*id)",
            col_str,
            re.IGNORECASE,
        ):
            isolate_col = col
            break

    if isolate_col is None:
        # Fallback search for any column containing 'id'
        for col in df_clean.columns:
            if re.search(r"\bid\b", str(col), re.IGNORECASE):
                isolate_col = col
                break

    # Identify accession columns
    ers_cols = []
    err_cols = []
    other_acc_cols = []

    for col in df_clean.columns:
        col_str = str(col).strip()
        if re.search(r"ers|biosample|samea|samn|samd", col_str, re.IGNORECASE):
            ers_cols.append(col)
        elif re.search(
            r"err|srr|drr|run[\s_-]*accession", col_str, re.IGNORECASE
        ):
            err_cols.append(col)
        elif (
            re.search(r"accession", col_str, re.IGNORECASE)
            and col != isolate_col
        ):
            other_acc_cols.append(col)

    records = []
    for idx, row in df_clean.iterrows():
        # Extract isolate ID
        iso_val = ""
        if isolate_col is not None and pd.notna(row[isolate_col]):
            val_str = str(row[isolate_col]).strip()
            if val_str and val_str.lower() not in ["nan", "none", "null"]:
                iso_val = val_str

        # Extract primary / all accessions
        primary_accs = []
        secondary_accs = []

        all_candidate_cols = ers_cols + err_cols + other_acc_cols
        # If no specific columns matched, check across all columns
        if not all_candidate_cols:
            all_candidate_cols = [c for c in df_clean.columns if c != isolate_col]

        for col in all_candidate_cols:
            if pd.notna(row[col]):
                val = str(row[col]).strip()
                if val and val.lower() not in ["nan", "none", "null"]:
                    # Match accession patterns
                    found = re.findall(
                        r"\b(?:[E|S|D]RS\d+|[E|S|D]RR\d+|SAM[NED][A-Z]?\d+|GCA_\d+\.\d+|GCF_\d+\.\d+|[A-Z]{1,2}\d{5,8}(?:\.\d+)?)\b",
                        val,
                        re.IGNORECASE,
                    )
                    if found:
                        for acc in found:
                            if acc not in primary_accs:
                                primary_accs.append(acc)
                            if re.match(
                                r"^[E|S|D]RR\d+", acc, re.IGNORECASE
                            ) and (acc not in secondary_accs):
                                secondary_accs.append(acc)
                    elif col in ers_cols + err_cols + other_acc_cols:
                        if val not in primary_accs:
                            primary_accs.append(val)
                        if col in err_cols and val not in secondary_accs:
                            secondary_accs.append(val)

        accession_str = (
            ",".join(primary_accs) if primary_accs else None
        )
        sec_acc_str = (
            ",".join(secondary_accs) if secondary_accs else None
        )
        iso_str = iso_val if iso_val else None

        # Discard if both isolate_id and accession are missing/blank
        if iso_str is None and accession_str is None:
            continue

        records.append(
            {
                "isolate_id": iso_str,
                "accession": accession_str,
                "secondary_accession": sec_acc_str,
            }
        )

    result_df = pd.DataFrame(
        records, columns=["isolate_id", "accession", "secondary_accession"]
    )
    return result_df

