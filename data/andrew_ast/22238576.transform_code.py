# ============================================================
# Transformation code for table: 'Table_1.tsv'
# ============================================================

import re
import numpy as np
import pandas as pd

PERMITTED_DRUGS = [
    'amoxicillin/clavulanic acid', 'ampicillin', 'antibiotic', 'arbekacin', 'azithromycin',
    'biapenem', 'cefazolin', 'cefoxitin', 'ceftarolin', 'ceftaroline', 'chloramphenicol',
    'chlorhexidine gluconate', 'ciprofloxacin', 'clarithromycin', 'clindamycin', 'dalbavancin',
    'daptomycin', 'doripenem', 'erythromycin', 'florfenicol', 'fosfomycin', 'fusidic acid',
    'gentamicin', 'imipenem', 'kanamycin', 'levofloxacin', 'linezolid', 'meropenem',
    'methicillin', 'minocycline', 'moxifloxacin', 'mupirocin', 'norfloxacin', 'oritavancin',
    'oxacillin', 'penicillin', 'phosphomycin', 'quinupristin/dalfopristin', 'rifampin',
    'streptomycin', 'sulfamethoxazole/trimethoprim', 'tedizolid', 'teicoplanin', 'telavancin',
    'tetracycline', 'tiamulin', 'tigecycline', 'tobramycin', 'trimethoprim',
    'trimethoprim/sulfamethoxazole', 'trimethoprim/sulfonamide', 'vancomycin'
]

ABBREV_MAP = {
    'dp': 'daptomycin',
    'dap': 'daptomycin',
    'vn': 'vancomycin',
    'va': 'vancomycin',
    'van': 'vancomycin',
    'lzd': 'linezolid',
    'lnz': 'linezolid',
    'cip': 'ciprofloxacin',
    'ox': 'oxacillin',
    'oxa': 'oxacillin',
    'gen': 'gentamicin',
    'gm': 'gentamicin',
    'ery': 'erythromycin',
    'e': 'erythromycin',
    'cli': 'clindamycin',
    'cc': 'clindamycin',
    'cd': 'clindamycin',
    'rif': 'rifampin',
    'ra': 'rifampin',
    'tet': 'tetracycline',
    'te': 'tetracycline',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'tmp': 'trimethoprim',
    'amx': 'amoxicillin/clavulanic acid',
    'amc': 'amoxicillin/clavulanic acid',
    'amp': 'ampicillin',
    'cfz': 'cefazolin',
    'fox': 'cefoxitin',
    'cpt': 'ceftaroline',
    'chl': 'chloramphenicol',
    'c': 'chloramphenicol',
    'tgc': 'tigecycline',
    'tob': 'tobramycin',
    'nn': 'tobramycin',
    'kan': 'kanamycin',
    'k': 'kanamycin',
    'str': 'streptomycin',
    's': 'streptomycin',
    'ipm': 'imipenem',
    'mem': 'meropenem',
    'dor': 'doripenem',
    'fof': 'fosfomycin',
    'fd': 'fusidic acid',
    'mup': 'mupirocin',
    'nor': 'norfloxacin',
    'mfx': 'moxifloxacin',
    'mxf': 'moxifloxacin',
    'lvx': 'levofloxacin',
    'lcf': 'levofloxacin',
    'tcy': 'tetracycline',
    'min': 'minocycline',
    'dal': 'dalbavancin',
    'ori': 'oritavancin',
    'tvd': 'tedizolid',
    'tec': 'teicoplanin',
    'tlv': 'telavancin'
}


def _match_drug_column(col_name: str):
    """Map a column header to a permitted drug name or return None."""
    col_str = str(col_name).strip()
    clean = re.sub(r'[\(\[\{].*?[\)\]\}]', '', col_str)
    clean = re.sub(r'(?i)\bmic\b', '', clean)
    clean = clean.strip(' _-:\t').lower()

    if not clean:
        return None

    # Exact match in permitted list
    if clean in PERMITTED_DRUGS:
        return clean

    # Abbreviation match
    if clean in ABBREV_MAP:
        mapped = ABBREV_MAP[clean]
        if mapped in PERMITTED_DRUGS:
            return mapped

    # Substring / word match in permitted list
    for drug in PERMITTED_DRUGS:
        if drug in clean:
            return drug

    return None


def _parse_ast_cell(raw_val):
    """
    Parse an AST cell into (mic_sign, mic, sir_call, notes).
    Resolves range MICs (e.g., '1-2', '1–2') to the upper bound.
    """
    if raw_val is None or pd.isna(raw_val):
        return None, None, None, None

    s = str(raw_val).strip()
    if not s or s.lower() in ['nd', 'n/a', 'na', '-', '.', '', 'none']:
        return None, None, None, None

    sir_call = None
    mic_sign = None
    mic = None
    notes = None

    # Extract SIR call in parentheses: e.g. "4 (R)", "2 (S)"
    sir_paren = re.search(r'\(\s*(S|I|R|SDD|NS)\s*\)', s, re.IGNORECASE)
    if sir_paren:
        sir_call = sir_paren.group(1).upper()
        s = (s[:sir_paren.start()] + s[sir_paren.end():]).strip()
    elif s.upper() in ['S', 'I', 'R', 'SDD', 'NS']:
        return None, None, s.upper(), None

    s = s.strip()
    if not s:
        if sir_call:
            return None, None, sir_call, None
        return None, None, None, None

    # Match numeric ranges: e.g. "1-2", "1–2", "1—2", "1 to 2", "<= 1-2"
    range_match = re.match(
        r'^([<>=~]?)\s*(\d+(?:\.\d+)?)\s*(?:[-–—]|to)\s*(\d+(?:\.\d+)?)$',
        s, re.IGNORECASE
    )
    if range_match:
        prefix = range_match.group(1).strip()
        upper = range_match.group(3).strip()
        mic = upper  # AST standard: use higher bound of dilution range

        if prefix in ['<', '<=', '>', '>=', '=']:
            mic_sign = prefix
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"
        return mic_sign, mic, sir_call, notes

    # Check for inequality prefix
    has_explicit_sign = False
    ineq_match = re.match(r'^([<>=]=?|~)\s*(.*)$', s)
    if ineq_match and ineq_match.group(1):
        sign_part = ineq_match.group(1)
        rest = ineq_match.group(2).strip()
        if sign_part in ['<', '<=', '>', '>=', '=']:
            mic_sign = sign_part
            has_explicit_sign = True
        elif sign_part == '~':
            mic_sign = '='
            has_explicit_sign = True
        s = rest

    # Match numeric MIC or combination ratio (e.g. 32/16)
    num_match = re.match(r'^(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)*)', s)
    if num_match:
        mic = num_match.group(1)
        remaining = s[num_match.end():].strip()
        if not sir_call and remaining:
            rem_upper = remaining.upper()
            if rem_upper in ['S', 'I', 'R', 'SDD', 'NS']:
                sir_call = rem_upper

        if not has_explicit_sign:
            mic_sign = '='
            notes = "mic_sign '=' inferred"
        else:
            notes = None
    else:
        if s.upper() in ['S', 'I', 'R', 'SDD', 'NS']:
            sir_call = s.upper()

    if mic is None and sir_call is None:
        return None, None, None, None

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extracts all AST isolate measurements into a standardized unpivoted format.
    """
    output_cols = ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
    if df.empty:
        return pd.DataFrame(columns=output_cols)

    # 1. Identify drug columns
    drug_cols = {}
    for col in df.columns:
        matched = _match_drug_column(str(col))
        if matched:
            drug_cols[col] = matched

    # 2. Identify isolate ID column
    isolate_col = None
    for col in df.columns:
        c_str = str(col).lower()
        if any(k in c_str for k in ['isolate', 'strain', 'sample', 'specimen', 'patient', 'id']):
            isolate_col = col
            break

    if isolate_col is None:
        for col in df.columns:
            if col not in drug_cols:
                isolate_col = col
                break

    # 3. Identify public repository accession column (if any)
    accession_regex = re.compile(r'\b(SAM[NED][A-Z]?\d+|[ESD]RR\d+|[ESD]RS\d+|GC[AF]_\d+\.\d+)\b', re.IGNORECASE)
    accession_cols = []
    for col in df.columns:
        if col != isolate_col and col not in drug_cols:
            sample_vals = df[col].dropna().astype(str)
            if any(sample_vals.str.contains(accession_regex)):
                accession_cols.append(col)

    records = []
    for _, row in df.iterrows():
        # Extract isolate_id
        isolate_id = None
        if isolate_col is not None:
            raw_id = row[isolate_col]
            if pd.notna(raw_id):
                val_str = str(raw_id).strip()
                if val_str:
                    isolate_id = val_str

        # Extract accession(s)
        accession_val = None
        if accession_cols:
            accs = []
            for col in accession_cols:
                val = row[col]
                if pd.notna(val):
                    matches = accession_regex.findall(str(val))
                    accs.extend(matches)
            if accs:
                accession_val = ','.join(sorted(set(accs), key=accs.index))

        # Unpivot drug measurements
        for col, drug_name in drug_cols.items():
            cell_val = row[col]
            mic_sign, mic, sir_call, notes = _parse_ast_cell(cell_val)

            # Discard rows where both MIC and SIR call are missing/uninterpretable
            if mic is None and sir_call is None:
                continue

            records.append({
                'isolate_id': isolate_id,
                'accession': accession_val,
                'drug': drug_name,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes
            })

    return pd.DataFrame(records, columns=output_cols)

# ============================================================
# Transformation code for table: 'Table_2.tsv'
# ============================================================

import re
import numpy as np
import pandas as pd

PERMITTED_DRUGS = [
    'amoxicillin/clavulanic acid', 'ampicillin', 'antibiotic', 'arbekacin', 'azithromycin',
    'biapenem', 'cefazolin', 'cefoxitin', 'ceftarolin', 'ceftaroline', 'chloramphenicol',
    'chlorhexidine gluconate', 'ciprofloxacin', 'clarithromycin', 'clindamycin', 'dalbavancin',
    'daptomycin', 'doripenem', 'erythromycin', 'florfenicol', 'fosfomycin', 'fusidic acid',
    'gentamicin', 'imipenem', 'kanamycin', 'levofloxacin', 'linezolid', 'meropenem',
    'methicillin', 'minocycline', 'moxifloxacin', 'mupirocin', 'norfloxacin', 'oritavancin',
    'oxacillin', 'penicillin', 'phosphomycin', 'quinupristin/dalfopristin', 'rifampin',
    'streptomycin', 'sulfamethoxazole/trimethoprim', 'tedizolid', 'teicoplanin', 'telavancin',
    'tetracycline', 'tiamulin', 'tigecycline', 'tobramycin', 'trimethoprim',
    'trimethoprim/sulfamethoxazole', 'trimethoprim/sulfonamide', 'vancomycin'
]

DRUG_ABBREVIATIONS = {
    'dp': 'daptomycin',
    'dap': 'daptomycin',
    'vn': 'vancomycin',
    'va': 'vancomycin',
    'van': 'vancomycin',
    'amx': 'amoxicillin/clavulanic acid',
    'amc': 'amoxicillin/clavulanic acid',
    'amp': 'ampicillin',
    'abk': 'arbekacin',
    'azm': 'azithromycin',
    'bpm': 'biapenem',
    'cfz': 'cefazolin',
    'cz': 'cefazolin',
    'fox': 'cefoxitin',
    'cpt': 'ceftaroline',
    'chl': 'chloramphenicol',
    'chx': 'chlorhexidine gluconate',
    'cip': 'ciprofloxacin',
    'clr': 'clarithromycin',
    'cli': 'clindamycin',
    'cc': 'clindamycin',
    'dal': 'dalbavancin',
    'dor': 'doripenem',
    'ery': 'erythromycin',
    'ffc': 'florfenicol',
    'fos': 'fosfomycin',
    'fuc': 'fusidic acid',
    'fa': 'fusidic acid',
    'gen': 'gentamicin',
    'gm': 'gentamicin',
    'cn': 'gentamicin',
    'ipm': 'imipenem',
    'imi': 'imipenem',
    'kan': 'kanamycin',
    'lvx': 'levofloxacin',
    'lev': 'levofloxacin',
    'lnz': 'linezolid',
    'lzd': 'linezolid',
    'mem': 'meropenem',
    'mer': 'meropenem',
    'met': 'methicillin',
    'min': 'minocycline',
    'mno': 'minocycline',
    'mxf': 'moxifloxacin',
    'mox': 'moxifloxacin',
    'mup': 'mupirocin',
    'nor': 'norfloxacin',
    'ori': 'oritavancin',
    'ox': 'oxacillin',
    'oxa': 'oxacillin',
    'pen': 'penicillin',
    'q/d': 'quinupristin/dalfopristin',
    'q-d': 'quinupristin/dalfopristin',
    'rif': 'rifampin',
    'ra': 'rifampin',
    'str': 'streptomycin',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'cot': 'trimethoprim/sulfamethoxazole',
    'ted': 'tedizolid',
    'tec': 'teicoplanin',
    'tlv': 'telavancin',
    'tet': 'tetracycline',
    'te': 'tetracycline',
    'tcy': 'tetracycline',
    'tia': 'tiamulin',
    'tgc': 'tigecycline',
    'tig': 'tigecycline',
    'tob': 'tobramycin',
    'nn': 'tobramycin',
    'tmp': 'trimethoprim',
}

ACCESSION_REGEX = re.compile(r'\b(SAM[NED][A-Z]?\d+|SRS\d+|GC[AF]_\d+\.\d+|[EDS]RR\d+)\b', re.IGNORECASE)


def resolve_drug_name(col_name: str) -> str | None:
    text = str(col_name).strip()
    
    # Check if a permitted drug name is directly present
    text_lower = text.lower()
    for drug in sorted(PERMITTED_DRUGS, key=len, reverse=True):
        if re.search(r'\b' + re.escape(drug) + r'\b', text_lower):
            return drug

    # Strip units and common AST qualifiers
    cleaned = re.sub(r'\(.*?\)', '', text)
    cleaned = re.sub(r'\b(mic|disk|disc|zone|ug/ml|µg/ml|mg/l|mcg/ml)\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[^a-zA-Z0-9/ -]', '', cleaned).strip().lower()

    if cleaned in DRUG_ABBREVIATIONS:
        return DRUG_ABBREVIATIONS[cleaned]

    # Check words individually
    tokens = re.split(r'[\s/_-]+', cleaned)
    for token in tokens:
        if token in DRUG_ABBREVIATIONS:
            return DRUG_ABBREVIATIONS[token]
        for drug in PERMITTED_DRUGS:
            if token == drug.lower():
                return drug

    return None


def parse_mic_sir(val):
    if pd.isna(val):
        return None, None, None, None
    
    val_str = str(val).strip()
    if val_str == '' or val_str.upper() in {'ND', 'N/A', 'NA', '-', '.', 'NONE'}:
        return None, None, None, None

    sir_call = None
    sir_match = re.search(r'\b(SDD|NS|[SIR])\b', val_str, re.IGNORECASE)
    if sir_match:
        sir_call = sir_match.group(1).upper()
        # Remove SIR from cell string to parse MIC cleanly
        val_clean = re.sub(r'\b(SDD|NS|[SIR])\b', '', val_str, flags=re.IGNORECASE).strip()
        val_clean = re.sub(r'[()]', '', val_clean).strip()
    else:
        val_clean = val_str

    mic_sign = None
    mic = None
    notes = None

    sign_match = re.search(r'(<=|>=|<|>|=)', val_clean)
    num_match = re.search(r'(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)*)', val_clean)

    if num_match:
        mic = num_match.group(1)
        if sign_match:
            mic_sign = sign_match.group(1)
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"
    elif sir_call is not None:
        mic_sign = None
        mic = None
        notes = None
    else:
        return None, None, None, None

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes'])

    # 1. Identify isolate_id column
    id_col = None
    id_candidates = ['strain', 'isolate', 'sample', 'specimen', 'id', 'patient']
    for col in df.columns:
        if any(c in str(col).lower() for c in id_candidates):
            id_col = col
            break
    if id_col is None:
        id_col = df.columns[0]

    # 2. Identify accession columns
    accession_cols = []
    for col in df.columns:
        c_low = str(col).lower()
        if any(term in c_low for term in ['accession', 'biosample', 'sra', 'genbank', 'ena', 'ddbj']):
            accession_cols.append(col)

    # 3. Identify AST drug columns
    drug_col_map = {}
    for col in df.columns:
        if col == id_col or col in accession_cols:
            continue
        mapped_drug = resolve_drug_name(str(col))
        if mapped_drug is not None:
            drug_col_map[col] = mapped_drug

    # 4. Extract rows
    rows = []
    for _, row in df.iterrows():
        isolate_val = row[id_col]
        isolate_id = str(isolate_val).strip() if pd.notna(isolate_val) else None
        if isolate_id == '':
            isolate_id = None

        # Public accessions extraction
        accessions = []
        for col in accession_cols:
            cell_val = row[col]
            if pd.notna(cell_val):
                matches = ACCESSION_REGEX.findall(str(cell_val))
                accessions.extend(matches)

        # Check whole row if accession columns were not explicitly found
        if not accession_cols:
            for val in row:
                if pd.notna(val) and val != isolate_val:
                    matches = ACCESSION_REGEX.findall(str(val))
                    accessions.extend(matches)

        unique_accessions = sorted(list(set(accessions)))
        accession_str = ','.join(unique_accessions) if unique_accessions else None

        for col, drug in drug_col_map.items():
            cell_val = row[col]
            mic_sign, mic, sir_call, notes = parse_mic_sir(cell_val)
            
            # Discard if both mic and sir_call are missing
            if mic is None and sir_call is None:
                continue

            rows.append({
                'isolate_id': isolate_id,
                'accession': accession_str,
                'drug': drug,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes
            })

    result_df = pd.DataFrame(rows, columns=['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes'])
    return result_df

