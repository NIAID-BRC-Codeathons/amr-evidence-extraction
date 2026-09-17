# ============================================================
# Transformation code for table: 'TABLE_1.tsv'
# ============================================================

import re
import numpy as np
import pandas as pd

PERMITTED_DRUGS = [
    'amoxicillin/clavulanic acid',
    'ampicillin',
    'antibiotic',
    'arbekacin',
    'azithromycin',
    'biapenem',
    'cefazolin',
    'cefoxitin',
    'ceftarolin',
    'ceftaroline',
    'chloramphenicol',
    'chlorhexidine gluconate',
    'ciprofloxacin',
    'clarithromycin',
    'clindamycin',
    'dalbavancin',
    'daptomycin',
    'doripenem',
    'erythromycin',
    'florfenicol',
    'fosfomycin',
    'fusidic acid',
    'gentamicin',
    'imipenem',
    'kanamycin',
    'levofloxacin',
    'linezolid',
    'meropenem',
    'methicillin',
    'minocycline',
    'moxifloxacin',
    'mupirocin',
    'norfloxacin',
    'oritavancin',
    'oxacillin',
    'penicillin',
    'phosphomycin',
    'quinupristin/dalfopristin',
    'rifampin',
    'streptomycin',
    'sulfamethoxazole/trimethoprim',
    'tedizolid',
    'teicoplanin',
    'telavancin',
    'tetracycline',
    'tiamulin',
    'tigecycline',
    'tobramycin',
    'trimethoprim',
    'trimethoprim/sulfamethoxazole',
    'trimethoprim/sulfonamide',
    'vancomycin',
]

# Mapping drug abbreviations/variants to standardized permitted drug names
DRUG_ALIAS_MAP = {
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
    'c': 'chloramphenicol',
    'cip': 'ciprofloxacin',
    'clr': 'clarithromycin',
    'cli': 'clindamycin',
    'cc': 'clindamycin',
    'dal': 'dalbavancin',
    'dap': 'daptomycin',
    'dor': 'doripenem',
    'ery': 'erythromycin',
    'e': 'erythromycin',
    'ffc': 'florfenicol',
    'fos': 'fosfomycin',
    'fuc': 'fusidic acid',
    'fa': 'fusidic acid',
    'gen': 'gentamicin',
    'gm': 'gentamicin',
    'ipm': 'imipenem',
    'kan': 'kanamycin',
    'k': 'kanamycin',
    'lvx': 'levofloxacin',
    'lev': 'levofloxacin',
    'lnz': 'linezolid',
    'lzd': 'linezolid',
    'lz': 'linezolid',
    'mem': 'meropenem',
    'met': 'methicillin',
    'me': 'methicillin',
    'min': 'minocycline',
    'mxf': 'moxifloxacin',
    'mup': 'mupirocin',
    'nor': 'norfloxacin',
    'ori': 'oritavancin',
    'oxa': 'oxacillin',
    'ox': 'oxacillin',
    'pen': 'penicillin',
    'p': 'penicillin',
    'q/d': 'quinupristin/dalfopristin',
    'rif': 'rifampin',
    'ra': 'rifampin',
    'str': 'streptomycin',
    's': 'streptomycin',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'tdz': 'tedizolid',
    'tzd': 'tedizolid',
    'txd': 'tedizolid',
    'tec': 'teicoplanin',
    'tla': 'telavancin',
    'tet': 'tetracycline',
    'te': 'tetracycline',
    'tia': 'tiamulin',
    'tgc': 'tigecycline',
    'tob': 'tobramycin',
    'nn': 'tobramycin',
    'tmp': 'trimethoprim',
    'w': 'trimethoprim',
    'van': 'vancomycin',
    'va': 'vancomycin',
}

# Populate permitted names into map
for drug in PERMITTED_DRUGS:
    DRUG_ALIAS_MAP[drug.lower()] = drug


def resolve_drug_name(col_name: str) -> str | None:
    """Resolve a column header to a standardized permitted drug name, or None."""
    cleaned = re.sub(r'[\s_]+', ' ', str(col_name).strip().lower())
    # Remove common qualifiers like MIC, (MIC), mg/L, ug/ml
    cleaned = re.sub(r'\b(mic|breakpoint|call|sir|interpretation)\b', '', cleaned)
    cleaned = re.sub(r'\(.*?\)', '', cleaned)
    cleaned = re.sub(r'\[.*?\]', '', cleaned)
    cleaned = cleaned.strip()

    if cleaned in DRUG_ALIAS_MAP:
        return DRUG_ALIAS_MAP[cleaned]

    for alias, standard in DRUG_ALIAS_MAP.items():
        if alias == cleaned:
            return standard

    return None


def parse_measurement(raw_val: object):
    """
    Parse an AST cell value into (mic_sign, mic, sir_call, notes).
    Returns (None, None, None, None) if missing or uninterpretable.
    """
    if pd.isna(raw_val):
        return None, None, None, None

    val_str = str(raw_val).strip()
    if not val_str or val_str.lower() in ['nd', 'n/a', 'na', '-', '–', '−', '.', 'none']:
        return None, None, None, None

    sir_call = None
    norm_sir_map = {'s': 'S', 'i': 'I', 'r': 'R', 'sdd': 'SDD', 'ns': 'NS'}

    # 1. Check if entire cell is a qualitative SIR call
    if val_str.lower() in norm_sir_map:
        return None, None, norm_sir_map[val_str.lower()], None

    # 2. Extract parenthesized SIR call if present: e.g. "4 (R)"
    m_paren = re.search(r'\((SDD|NS|[SIR])\)', val_str, re.IGNORECASE)
    if m_paren:
        sir_call = norm_sir_map[m_paren.group(1).lower()]
        val_str = re.sub(r'\((SDD|NS|[SIR])\)', '', val_str, flags=re.IGNORECASE).strip()
    else:
        # Check trailing SIR: e.g. "4 R"
        m_trail = re.search(r'\s+(SDD|NS|[SIR])$', val_str, re.IGNORECASE)
        if m_trail:
            sir_call = norm_sir_map[m_trail.group(1).lower()]
            val_str = val_str[:m_trail.start()].strip()

    # 3. Check for MIC range: e.g. "2–4", "2-4", "4–8"
    range_match = re.search(
        r'^([<>=]*)\s*(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)$', val_str
    )
    if range_match:
        prefix = range_match.group(1)
        upper_bound = range_match.group(3)
        mic = upper_bound
        if prefix in ['<', '<=', '>', '>=', '=']:
            mic_sign = prefix
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"
        return mic_sign, mic, sir_call, notes

    # 4. Standard single MIC or combination ratio (e.g. "32/16", ">32", "0.25")
    mic_match = re.search(
        r'([<>=]*)\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)', val_str
    )
    if mic_match and mic_match.group(2):
        prefix = mic_match.group(1)
        mic_val = re.sub(r'\s+', '', mic_match.group(2))
        if prefix in ['<', '<=', '>', '>=', '=']:
            mic_sign = prefix
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"
        return mic_sign, mic_val, sir_call, notes

    if sir_call:
        return None, None, sir_call, None

    return None, None, None, None


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforms an AST worksheet into a standardized unpivoted format with
    MIC values and SIR calls.
    """
    if df.empty:
        return pd.DataFrame(
            columns=['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
        )

    # 1. Identify public accession columns
    accession_cols = []
    acc_pattern = re.compile(
        r'\b(SAM[NED][A-Z]?\d+|PRJ[A-Z]{2}\d+|[SED]RR\d+|GC[AF]_\d+\.\d+)\b'
    )
    for col in df.columns:
        c_str = str(col).lower()
        if any(term in c_str for term in ['accession', 'biosample', 'sra', 'assembly']):
            accession_cols.append(col)

    # 2. Identify antimicrobial drug columns
    drug_cols = {}
    for col in df.columns:
        resolved = resolve_drug_name(col)
        if resolved is not None:
            drug_cols[col] = resolved

    # 3. Identify isolate ID column
    id_col = None
    # Check for explicit ID column headers
    for col in df.columns:
        if col in drug_cols or col in accession_cols:
            continue
        c_lower = str(col).lower().strip()
        if any(term in c_lower for term in ['isolate', 'strain', 'sample', 'specimen', 'patient', 'subculture', 'id', 'name']):
            id_col = col
            break

    # Fallback to the first non-drug, non-accession column if no explicit ID header
    if id_col is None:
        for col in df.columns:
            if col not in drug_cols and col not in accession_cols:
                id_col = col
                break

    # Extract isolate IDs, handling merged cells via forward-fill
    if id_col is not None:
        isolate_series = df[id_col].ffill()
    else:
        isolate_series = pd.Series([None] * len(df), index=df.index)

    # 4. Process accession per row (strictly public repository IDs, no fallback)
    row_accessions = []
    for idx in range(len(df)):
        found_accs = []
        for col in accession_cols:
            val = str(df.iloc[idx][col]).strip()
            matches = acc_pattern.findall(val)
            found_accs.extend(matches)
        if found_accs:
            row_accessions.append(','.join(sorted(set(found_accs))))
        else:
            row_accessions.append(None)

    # 5. Extract AST rows
    records = []
    for row_idx in range(len(df)):
        isolate_val = isolate_series.iloc[row_idx]
        iso_id = str(isolate_val).strip() if pd.notna(isolate_val) and str(isolate_val).strip() != '' else None
        acc_val = row_accessions[row_idx]

        for orig_col, std_drug in drug_cols.items():
            cell_val = df.iloc[row_idx][orig_col]
            mic_sign, mic, sir_call, notes = parse_measurement(cell_val)

            # Discard records where both MIC and SIR call are missing/uninterpretable
            if mic is None and sir_call is None:
                continue

            records.append({
                'isolate_id': iso_id,
                'accession': acc_val,
                'drug': std_drug,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes,
            })

    result_df = pd.DataFrame(records)
    cols = ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
    if result_df.empty:
        return pd.DataFrame(columns=cols)

    return result_df[cols]

# ============================================================
# Transformation code for table: 'TABLE_2.tsv'
# ============================================================

import re
import numpy as np
import pandas as pd

PERMITTED_DRUGS = [
    'amoxicillin/clavulanic acid', 'ampicillin', 'antibiotic', 'arbekacin', 'azithromycin',
    'biapenem', 'cefazolin', 'cefoxitin', 'ceftarolin', 'ceftaroline',
    'chloramphenicol', 'chlorhexidine gluconate', 'ciprofloxacin', 'clarithromycin',
    'clindamycin', 'dalbavancin', 'daptomycin', 'doripenem', 'erythromycin',
    'florfenicol', 'fosfomycin', 'fusidic acid', 'gentamicin', 'imipenem',
    'kanamycin', 'levofloxacin', 'linezolid', 'meropenem', 'methicillin',
    'minocycline', 'moxifloxacin', 'mupirocin', 'norfloxacin', 'oritavancin',
    'oxacillin', 'penicillin', 'phosphomycin', 'quinupristin/dalfopristin',
    'rifampin', 'streptomycin', 'sulfamethoxazole/trimethoprim', 'tedizolid',
    'teicoplanin', 'telavancin', 'tetracycline', 'tiamulin', 'tigecycline',
    'tobramycin', 'trimethoprim', 'trimethoprim/sulfamethoxazole',
    'trimethoprim/sulfonamide', 'vancomycin'
]

DRUG_MAP = {
    'van': 'vancomycin',
    'vanc': 'vancomycin',
    'vancomycin': 'vancomycin',
    'va': 'vancomycin',
    'tec': 'teicoplanin',
    'teic': 'teicoplanin',
    'teicoplanin': 'teicoplanin',
    'dlb': 'dalbavancin',
    'dal': 'dalbavancin',
    'dalba': 'dalbavancin',
    'dalbavancin': 'dalbavancin',
    'tlv': 'telavancin',
    'tela': 'telavancin',
    'telavancin': 'telavancin',
    'ori': 'oritavancin',
    'orita': 'oritavancin',
    'oritavancin': 'oritavancin',
    'dap': 'daptomycin',
    'dapto': 'daptomycin',
    'daptomycin': 'daptomycin',
    'rif': 'rifampin',
    'rifampin': 'rifampin',
    'rifampicin': 'rifampin',
    'ra': 'rifampin',
    'lnz': 'linezolid',
    'lzd': 'linezolid',
    'linezolid': 'linezolid',
    'cip': 'ciprofloxacin',
    'cipro': 'ciprofloxacin',
    'ciprofloxacin': 'ciprofloxacin',
    'ery': 'erythromycin',
    'erythromycin': 'erythromycin',
    'cli': 'clindamycin',
    'cc': 'clindamycin',
    'clindamycin': 'clindamycin',
    'gen': 'gentamicin',
    'gm': 'gentamicin',
    'gentamicin': 'gentamicin',
    'ox': 'oxacillin',
    'oxa': 'oxacillin',
    'oxacillin': 'oxacillin',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'cotrimoxazole': 'trimethoprim/sulfamethoxazole',
    'tmp/smx': 'trimethoprim/sulfamethoxazole',
    'trimethoprim/sulfamethoxazole': 'trimethoprim/sulfamethoxazole',
    'tet': 'tetracycline',
    'tetracycline': 'tetracycline',
    'tig': 'tigecycline',
    'tgc': 'tigecycline',
    'tigecycline': 'tigecycline',
    'amc': 'amoxicillin/clavulanic acid',
    'amoxicillin/clavulanic acid': 'amoxicillin/clavulanic acid',
    'amp': 'ampicillin',
    'ampicillin': 'ampicillin',
    'cpt': 'ceftaroline',
    'ceftaroline': 'ceftaroline',
    'ceftarolin': 'ceftarolin',
    'fox': 'cefoxitin',
    'cefoxitin': 'cefoxitin',
    'cfz': 'cefazolin',
    'cefazolin': 'cefazolin',
    'chl': 'chloramphenicol',
    'chloramphenicol': 'chloramphenicol',
    'dori': 'doripenem',
    'doripenem': 'doripenem',
    'imi': 'imipenem',
    'ipm': 'imipenem',
    'imipenem': 'imipenem',
    'mem': 'meropenem',
    'mero': 'meropenem',
    'meropenem': 'meropenem',
    'pen': 'penicillin',
    'penicillin': 'penicillin',
    'qd': 'quinupristin/dalfopristin',
    'q/d': 'quinupristin/dalfopristin',
    'quinupristin/dalfopristin': 'quinupristin/dalfopristin',
    'txd': 'tedizolid',
    'tedizolid': 'tedizolid',
    'tob': 'tobramycin',
    'tobramycin': 'tobramycin',
    'mup': 'mupirocin',
    'mupirocin': 'mupirocin',
    'fd': 'fusidic acid',
    'fusidic acid': 'fusidic acid',
    'fos': 'fosfomycin',
    'fosfomycin': 'fosfomycin',
}


def normalize_drug_name(col_name: str):
    raw = str(col_name).strip()
    cleaned = re.sub(r'[\(\[\{].*?[\)\]\}]', '', raw)
    cleaned = re.sub(r'(?i)\b(mic|disc|disk|zone|mg/l|ug/ml|µg/ml)\b', '', cleaned)
    cleaned = cleaned.strip().lower()

    if cleaned in DRUG_MAP:
        return DRUG_MAP[cleaned]
    if raw.lower() in DRUG_MAP:
        return DRUG_MAP[raw.lower()]

    for d in PERMITTED_DRUGS:
        if d in cleaned:
            return d
    return None


def parse_ast_cell(val):
    if pd.isna(val):
        return None, None, None, None

    s = str(val).strip()
    if not s:
        return None, None, None, None

    # Replace unicode dash/inequality characters
    s = s.replace('–', '-').replace('—', '-').replace('−', '-')
    s = s.replace('≤', '<=').replace('≥', '>=')

    # Non-AST or missing indicators
    if s.lower() in ['nan', 'none', 'nd', 'n/a', 'na', '-', '.', '', 'null', 'not tested']:
        return None, None, None, None

    # Detect ranges: e.g. "1-4", "0.25-4", "2 and 16", "1 to 4" (ranges are not valid single MIC values)
    if re.search(r'\d+(\.\d+)?\s*(-|\bto\b|\band\b)\s*\d+(\.\d+)?', s, re.IGNORECASE):
        return None, None, None, None

    # Extract SIR call
    sir_call = None
    sir_match = re.search(r'\b(SDD|NS|[SIR])\b', s)
    if sir_match:
        sir_call = sir_match.group(1).upper()
        # Remove SIR call text to isolate numeric part
        s_no_sir = re.sub(r'[\(\[\{]?\b(SDD|NS|[SIR])\b[\)\]\}]?', '', s).strip()
    else:
        s_no_sir = s

    # Match numeric MIC or combination ratio (e.g. 32/16, 0.25/4.75, 4, 0.5)
    mic_pattern = r'^(<=|>=|<|>|=)?\s*(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)'
    mic_match = re.search(mic_pattern, s_no_sir)

    mic_sign = None
    mic = None
    notes = None

    if mic_match:
        sign = mic_match.group(1)
        num = mic_match.group(2)
        mic = num
        if sign:
            mic_sign = sign
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    result_columns = ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
    if df is None or df.empty:
        return pd.DataFrame(columns=result_columns)

    # 1. Identify isolate ID column
    isolate_col = None
    isolate_patterns = [
        r'\b(isolate[\s_]*id|strain[\s_]*id|sample[\s_]*id|specimen[\s_]*id|patient[\s_]*id)\b',
        r'\b(isolate[\s_]*no|strain[\s_]*no|sample[\s_]*no|specimen[\s_]*no)\b',
        r'\b(isolate|strain|sample|specimen|patient)\b',
        r'^id$'
    ]
    for col in df.columns:
        c_str = str(col).strip().lower()
        if normalize_drug_name(col) is not None:
            continue
        for pat in isolate_patterns:
            if re.search(pat, c_str):
                isolate_col = col
                break
        if isolate_col:
            break

    # 2. Identify accession column(s)
    accession_cols = []
    acc_pat = re.compile(r'\b(SAM[NED][A-Z]?\d+|SRS\d+|SRR\d+|ERR\d+|DRR\d+|GC[AF]_\d+\.\d+)\b')
    for col in df.columns:
        if col == isolate_col or normalize_drug_name(col) is not None:
            continue
        c_str = str(col).strip().lower()
        if re.search(r'\b(accession|biosample|sra|run_accession|assembly)\b', c_str):
            accession_cols.append(col)
        else:
            # Check sample values in the column
            sample_vals = df[col].dropna().astype(str).head(10)
            if sample_vals.apply(lambda x: bool(acc_pat.search(x))).any():
                accession_cols.append(col)

    # 3. Identify drug columns
    drug_cols = {}
    for col in df.columns:
        if col == isolate_col or col in accession_cols:
            continue
        norm_drug = normalize_drug_name(col)
        if norm_drug and norm_drug in PERMITTED_DRUGS:
            drug_cols[col] = norm_drug

    if not drug_cols:
        return pd.DataFrame(columns=result_columns)

    records = []
    for idx, row in df.iterrows():
        # Resolve isolate_id
        isolate_id = None
        if isolate_col is not None and pd.notna(row[isolate_col]):
            val = str(row[isolate_col]).strip()
            if val and val.lower() not in ['nan', 'none', '']:
                isolate_id = val

        # Resolve accession
        accessions = []
        for ac in accession_cols:
            if pd.notna(row[ac]):
                matches = acc_pat.findall(str(row[ac]))
                accessions.extend(matches)
        accession = ','.join(sorted(set(accessions))) if accessions else None

        # Mandatory identifier check: record must have isolate_id or accession
        if not isolate_id and not accession:
            continue

        for orig_col, drug_name in drug_cols.items():
            cell_val = row[orig_col]
            mic_sign, mic, sir_call, notes = parse_ast_cell(cell_val)

            # Discard rows where BOTH mic and sir_call are empty/uninterpretable
            if mic is None and sir_call is None:
                continue

            records.append({
                'isolate_id': isolate_id,
                'accession': accession,
                'drug': drug_name,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes
            })

    return pd.DataFrame(records, columns=result_columns)

