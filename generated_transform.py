# ==========================================================
# Transformation Code for Sheet: 'Table_2.XLSX::Sheet1'
# ==========================================================

import re
import numpy as np
import pandas as pd

# Comprehensive mapping of common antimicrobial abbreviations to full names
DRUG_ABBREVIATIONS = {
    'AMK': 'Amikacin', 'AN': 'Amikacin', 'AMI': 'Amikacin',
    'AMP': 'Ampicillin', 'AM': 'Ampicillin',
    'SAM': 'Ampicillin/sulbactam', 'AMS': 'Ampicillin/sulbactam',
    'ATM': 'Aztreonam', 'AZT': 'Aztreonam',
    'CZO': 'Cefazolin', 'CFZ': 'Cefazolin', 'FAZ': 'Cefazolin', 'CZ': 'Cefazolin',
    'FEP': 'Cefepime', 'CPM': 'Cefepime',
    'CEF': 'Cephalothin', 'CEP': 'Cephalothin', 'KF': 'Cephalothin',
    'MEM': 'Meropenem', 'MRP': 'Meropenem', 'MER': 'Meropenem',
    'ETP': 'Ertapenem', 'ERT': 'Ertapenem',
    'CXM': 'Cefuroxime', 'CRX': 'Cefuroxime',
    'GEN': 'Gentamicin', 'GM': 'Gentamicin', 'CN': 'Gentamicin',
    'CIP': 'Ciprofloxacin', 'CIPRO': 'Ciprofloxacin',
    'TZP': 'Piperacillin/tazobactam', 'PTZ': 'Piperacillin/tazobactam', 'P/T': 'Piperacillin/tazobactam',
    'FOX': 'Cefoxitin', 'FX': 'Cefoxitin',
    'TMP': 'Trimethoprim', 'TM': 'Trimethoprim', 'TRIM': 'Trimethoprim',
    'SMX': 'Sulfamethoxazole', 'RL': 'Sulfamethoxazole',
    'SXT': 'Trimethoprim/sulfamethoxazole', 'COT': 'Trimethoprim/sulfamethoxazole', 'T/S': 'Trimethoprim/sulfamethoxazole',
    'CPD': 'Cefpodoxime', 'CPDX': 'Cefpodoxime', 'PX': 'Cefpodoxime',
    'CAZ': 'Ceftazidime', 'TAZ': 'Ceftazidime',
    'CZA': 'Ceftazidime/avibactam', 'CAZ/AVI': 'Ceftazidime/avibactam',
    'TOB': 'Tobramycin', 'NN': 'Tobramycin',
    'TGC': 'Tigecycline', 'TGCY': 'Tigecycline',
    'TIM': 'Ticarcillin/clavulanic acid', 'TCC': 'Ticarcillin/clavulanic acid',
    'CRO': 'Ceftriaxone', 'CTR': 'Ceftriaxone',
    'CTX': 'Cefotaxime', 'CTA': 'Cefotaxime',
    'TET': 'Tetracycline', 'TCY': 'Tetracycline', 'TE': 'Tetracycline',
    'COL': 'Colistin', 'CST': 'Colistin', 'CL': 'Colistin',
    'AMX': 'Amoxicillin', 'AML': 'Amoxicillin',
    'AMC': 'Amoxicillin/clavulanic acid', 'AUG': 'Amoxicillin/clavulanic acid',
    'LNZ': 'Linezolid', 'LZD': 'Linezolid',
    'ERY': 'Erythromycin', 'E': 'Erythromycin',
    'VAN': 'Vancomycin', 'VA': 'Vancomycin',
    'CHL': 'Chloramphenicol', 'C': 'Chloramphenicol', 'CLR': 'Chloramphenicol',
    'CLI': 'Clindamycin', 'CC': 'Clindamycin', 'CD': 'Clindamycin',
    'DOX': 'Doxycycline', 'DX': 'Doxycycline',
    'MIN': 'Minocycline', 'MNO': 'Minocycline', 'MI': 'Minocycline',
    'NIT': 'Nitrofurantoin', 'FM': 'Nitrofurantoin', 'NFT': 'Nitrofurantoin',
    'IPM': 'Imipenem', 'IMI': 'Imipenem',
    'DAP': 'Daptomycin', 'DAPTO': 'Daptomycin',
    'RIF': 'Rifampicin', 'RA': 'Rifampicin', 'RIFAMPIN': 'Rifampicin',
    'FOS': 'Fosfomycin', 'FOSFO': 'Fosfomycin', 'FOT': 'Fosfomycin',
    'NAL': 'Nalidixic acid', 'NA': 'Nalidixic acid',
    'PEN': 'Penicillin', 'P': 'Penicillin',
    'PIP': 'Piperacillin', 'PRL': 'Piperacillin',
    'AZM': 'Azithromycin', 'AZI': 'Azithromycin',
    'SPEC': 'Spectinomycin', 'SPT': 'Spectinomycin',
    'STR': 'Streptomycin',
    'KAN': 'Kanamycin', 'K': 'Kanamycin',
    'NEO': 'Neomycin', 'N': 'Neomycin',
    'NET': 'Netilmicin', 'NETIL': 'Netilmicin',
    'TEI': 'Teicoplanin', 'TEC': 'Teicoplanin',
    'TEM': 'Temocillin', 'TMC': 'Temocillin',
}

NON_DRUG_KEYWORDS = {
    'unnamed', 'species', 'organism', 'panel', 'method', 'date', 'source',
    'temperature', 'growth', 'notes', 'qc', 'qc_status', 'media', 'medium',
    'incubation', 'run_id', 'comment', 'comments', 'interpretation', 'patient',
    'hospital', 'ward', 'doctor', 'location', 'time', 'sample_type', 'specimen_type'
}

PUBLIC_ACCESSION_REGEX = re.compile(
    r'\b(SAM[NED][A-Z]?\d+|SRS\d+|GC[AF]_\d+\.\d+|[ESD]RR\d+)\b',
    re.IGNORECASE
)


def normalize_drug_name(name: str) -> str:
    name_clean = str(name).strip()
    upper_name = name_clean.upper()
    if upper_name in DRUG_ABBREVIATIONS:
        return DRUG_ABBREVIATIONS[upper_name]
    return name_clean


def parse_ast_value(raw_val):
    if pd.isna(raw_val):
        return None
    val = str(raw_val).strip()
    if not val or val.lower() in {'nan', 'none', 'null', 'nd', 'n/a', 'na', '-', '.', '/', 'neg', 'pos'}:
        return None

    # Replace comma decimal separator between digits (e.g., '0,5' -> '0.5')
    val_clean = re.sub(r'(\d+),(\d+)', r'\1.\2', val)

    # Reject non-AST text / gene annotations (e.g. blaTEM-1D, parC (p.S80I))
    letters_only = re.sub(r'[^a-zA-Z]', '', val_clean).upper()
    valid_sir_combos = {
        '', 'S', 'I', 'R', 'SDD', 'NS', 'SUSCEPTIBLE', 'INTERMEDIATE',
        'RESISTANT', 'SENSITIVE', 'NONSUSCEPTIBLE', 'SUSCEPTIBLEDOSEDEPENDENT'
    }
    if letters_only not in valid_sir_combos:
        return None

    # Check for SIR interpretation call
    sir_call = None
    val_upper = val_clean.upper()
    if re.search(r'\bSUSCEPTIBLE[- ]DOSE[- ]DEPENDENT\b', val_upper) or re.search(r'\bSDD\b', val_upper):
        sir_call = 'SDD'
    elif re.search(r'\bNON[- ]SUSCEPTIBLE\b', val_upper) or re.search(r'\bNS\b', val_upper):
        sir_call = 'NS'
    elif re.search(r'\b(SUSCEPTIBLE|SENSITIVE)\b', val_upper):
        sir_call = 'S'
    elif re.search(r'\bINTERMEDIATE\b', val_upper):
        sir_call = 'I'
    elif re.search(r'\bRESISTANT\b', val_upper):
        sir_call = 'R'
    else:
        m_sir = re.search(r'(?:\(|\b)(SDD|NS|S|I|R)(?:\)|\b)', val_upper)
        if m_sir:
            sir_call = m_sir.group(1)

    # Check for MIC numeric measurement and sign
    mic_match = re.search(r'([<=≥≤><=]*)\s*(\d+(?:\.\d+)?(?:\s*\/\s*\d+(?:\.\d+)?)*)', val_clean)
    mic = None
    mic_sign = None
    notes = None

    if mic_match:
        raw_sign = mic_match.group(1).strip()
        raw_num = mic_match.group(2).strip().replace(' ', '')

        if '≤' in raw_sign or '<=' in raw_sign:
            mic_sign = '<='
        elif '≥' in raw_sign or '>=' in raw_sign:
            mic_sign = '>='
        elif '<' in raw_sign:
            mic_sign = '<'
        elif '>' in raw_sign:
            mic_sign = '>'
        elif '=' in raw_sign:
            mic_sign = '='
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"

        mic = raw_num

    if mic is None and sir_call is None:
        return None

    return {
        'mic_sign': mic_sign,
        'mic': mic,
        'sir_call': sir_call,
        'notes': notes
    }


def find_metadata_columns(df: pd.DataFrame):
    isolate_col = None
    accession_cols = []

    # Identify by column header names
    for col in df.columns:
        col_str = str(col).strip().lower()
        if any(k in col_str for k in ['biosample', 'sra', 'accession', 'genbank', 'ena']):
            accession_cols.append(col)
        elif any(k in col_str for k in ['isolate_id', 'sample_id', 'specimen_id', 'strain_id', 'isolate', 'sample', 'specimen', 'strain']) and isolate_col is None:
            isolate_col = col

    # Inspect data for public accessions
    for col in df.columns:
        if col in accession_cols or col == isolate_col:
            continue
        sample_vals = df[col].dropna().astype(str).head(20)
        if len(sample_vals) > 0 and sample_vals.apply(lambda x: bool(PUBLIC_ACCESSION_REGEX.search(x))).mean() > 0.5:
            accession_cols.append(col)

    # If isolate_col still None, find the first non-numeric/non-species ID column
    if isolate_col is None:
        for col in df.columns:
            if col in accession_cols:
                continue
            sample_vals = df[col].dropna().astype(str).tolist()
            if not sample_vals:
                continue
            first_vals = [v.strip() for v in sample_vals[:10] if v.strip()]
            if not first_vals:
                continue
            is_numeric_ast = all(bool(re.match(r'^[<=≥≤><=]?\s*\d', v)) for v in first_vals)
            is_species = any(' ' in v and any(b in v.lower() for b in ['coli', 'aureus', 'aeruginosa', 'pneumoniae', 'baumannii']) for v in first_vals)
            if not is_numeric_ast and not is_species:
                isolate_col = col
                break

    return isolate_col, accession_cols


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    isolate_col, accession_cols = find_metadata_columns(df)

    # Identify valid drug columns
    drug_cols = []
    for col in df.columns:
        if col == isolate_col or col in accession_cols:
            continue
        col_str = str(col).strip().lower()
        if any(col_str.startswith(kw) or col_str == kw for kw in NON_DRUG_KEYWORDS):
            continue
        drug_cols.append(col)

    records = []

    for _, row in df.iterrows():
        # Extract isolate ID
        iso_id = None
        if isolate_col is not None and pd.notna(row[isolate_col]):
            val = str(row[isolate_col]).strip()
            if val and val.lower() not in {'nan', 'none', 'null', '-'}:
                iso_id = val

        # Extract public accessions
        accessions = []
        for acc_col in accession_cols:
            if pd.notna(row[acc_col]):
                found = PUBLIC_ACCESSION_REGEX.findall(str(row[acc_col]))
                accessions.extend(found)

        # Also search isolate_col in case it contains an accession
        if isolate_col is not None and pd.notna(row[isolate_col]):
            found = PUBLIC_ACCESSION_REGEX.findall(str(row[isolate_col]))
            accessions.extend(found)

        accession_str = ','.join(sorted(set(accessions))) if accessions else None

        # Skip rows with no isolate identifier or accession (e.g. annotation-only or empty rows)
        if not iso_id and not accession_str:
            continue

        for col in drug_cols:
            raw_val = row[col]
            parsed = parse_ast_value(raw_val)
            if parsed is None:
                continue

            records.append({
                'isolate_id': iso_id,
                'accession': accession_str,
                'drug': normalize_drug_name(col),
                'mic_sign': parsed['mic_sign'],
                'mic': parsed['mic'],
                'sir_call': parsed['sir_call'],
                'notes': parsed['notes']
            })

    columns = ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
    if not records:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(records)[columns]

# ==========================================================
# Transformation Code for Sheet: 'Table_1.XLSX::Sheet1'
# ==========================================================

import re
import numpy as np
import pandas as pd


def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Extract mapping records between isolate identifiers and public database accessions."""
    # Create a working copy
    df_work = df.copy()

    # Identify Isolate ID column
    id_col = None
    id_candidates = [
        "id(1)",
        "id",
        "isolate_id",
        "isolate",
        "isolate id",
        "sample_id",
        "sample id",
        "cvm_number",
        "lab id",
        "strain",
    ]
    for col in df_work.columns:
        clean_col = str(col).strip().lower()
        if clean_col in id_candidates:
            id_col = col
            break

    if id_col is None:
        # Fallback to the first column matching 'id' or first non-unnamed column
        for col in df_work.columns:
            if "id" in str(col).lower() and "unnamed" not in str(col).lower():
                id_col = col
                break
        if id_col is None and len(df_work.columns) > 1:
            id_col = df_work.columns[1]

    # Identify accession columns
    # Regex patterns for public accessions
    biosample_pattern = re.compile(
        r"\b(?:SAM[NEDAG][A-Z]?\d+|[EDS]RS\d+)\b", re.IGNORECASE
    )
    secondary_pattern = re.compile(
        r"\b(?:[EDS]RR\d+|[EDS]RX\d+|PRJ[A-Z]+\d+|GC[AF]_\d+\.\d+|[A-Z]{2}\d{6}(?:\.\d+)?|[A-Z]{4,6}\d{6,8}(?:\.\d+)?)\b",
        re.IGNORECASE,
    )
    general_accession_pattern = re.compile(
        r"\b(?:SAM[NEDAG][A-Z]?\d+|[EDS]R[SRX]\d+|PRJ[A-Z]+\d+|GC[AF]_\d+\.\d+|[A-Z]{2}\d{6}(?:\.\d+)?|[A-Z]{4,6}\d{6,8}(?:\.\d+)?)\b",
        re.IGNORECASE,
    )

    # Detect candidate accession columns based on name
    acc_cols = [
        col
        for col in df_work.columns
        if any(
            kw in str(col).lower()
            for kw in ["accession", "ers", "err", "srr", "sra", "biosample"]
        )
    ]

    # If no explicit columns found by name, scan all columns except isolate_id
    if not acc_cols:
        acc_cols = [col for col in df_work.columns if col != id_col]

    records = []
    for _, row in df_work.iterrows():
        # Extract isolate ID
        raw_id = row[id_col] if id_col in df_work.columns else None
        if pd.notna(raw_id) and str(raw_id).strip() != "":
            isolate_id = str(raw_id).strip()
        else:
            isolate_id = None

        # Extract accessions from candidate columns
        row_accessions = []
        row_secondary = []

        for col in acc_cols:
            val = row[col]
            if pd.notna(val):
                val_str = str(val).strip()
                matches = general_accession_pattern.findall(val_str)
                for m in matches:
                    m_clean = m.strip()
                    if m_clean and m_clean not in row_accessions:
                        row_accessions.append(m_clean)
                    if secondary_pattern.match(m_clean) and not biosample_pattern.match(
                        m_clean
                    ):
                        if m_clean not in row_secondary:
                            row_secondary.append(m_clean)

        accession_str = (
            ",".join(row_accessions) if len(row_accessions) > 0 else None
        )
        secondary_acc_str = (
            ",".join(row_secondary) if len(row_secondary) > 0 else None
        )

        records.append(
            {
                "isolate_id": isolate_id,
                "accession": accession_str,
                "secondary_accession": secondary_acc_str,
            }
        )

    res_df = pd.DataFrame(records)

    # Discard rows where BOTH 'isolate_id' and 'accession' are missing/blank
    res_df = res_df.dropna(subset=["isolate_id", "accession"], how="all")
    res_df = res_df[
        ~(
            (res_df["isolate_id"].astype(str).str.strip().isin(["", "None", "nan"]))
            & (
                res_df["accession"]
                .astype(str)
                .str.strip()
                .isin(["", "None", "nan"])
            )
        )
    ]

    return res_df[["isolate_id", "accession", "secondary_accession"]].reset_index(
        drop=True
    )

