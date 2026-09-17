# ============================================================
# Transformation code for table: 'TABLE_1.tsv'
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

DRUG_SYNONYMS = {
    'amx': 'amoxicillin/clavulanic acid',
    'amc': 'amoxicillin/clavulanic acid',
    'amp': 'ampicillin',
    'arb': 'arbekacin',
    'azm': 'azithromycin',
    'cfz': 'cefazolin',
    'fox': 'cefoxitin',
    'cpt': 'ceftaroline',
    'chl': 'chloramphenicol',
    'cip': 'ciprofloxacin',
    'clr': 'clarithromycin',
    'cli': 'clindamycin',
    'cc': 'clindamycin',
    'dal': 'dalbavancin',
    'dap': 'daptomycin',
    'dor': 'doripenem',
    'ery': 'erythromycin',
    'ffc': 'florfenicol',
    'fos': 'fosfomycin',
    'fus': 'fusidic acid',
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
    'mfx': 'moxifloxacin',
    'mox': 'moxifloxacin',
    'mup': 'mupirocin',
    'nor': 'norfloxacin',
    'ori': 'oritavancin',
    'oxa': 'oxacillin',
    'ox': 'oxacillin',
    'pen': 'penicillin',
    'rif': 'rifampin',
    'ra': 'rifampin',
    'rifampicin': 'rifampin',
    'str': 'streptomycin',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'cotrimoxazole': 'trimethoprim/sulfamethoxazole',
    'co-trimoxazole': 'trimethoprim/sulfamethoxazole',
    'tmp-smx': 'trimethoprim/sulfamethoxazole',
    'tzd': 'tedizolid',
    'tec': 'teicoplanin',
    'tlv': 'telavancin',
    'tet': 'tetracycline',
    'tia': 'tiamulin',
    'tgc': 'tigecycline',
    'tob': 'tobramycin',
    'tmp': 'trimethoprim',
    'van': 'vancomycin',
    'va': 'vancomycin'
}


def _match_drug_column(col_name: str):
    raw = str(col_name).strip().lower()
    
    # Exclude obvious non-AST columns
    non_ast_indicators = [
        'case', 'isolate', 'strain', 'sample', 'specimen', 'patient', 'source',
        'time', 'day', 'mlst', 'gene', 'diagnosis', 'other resistance', 'phenotype'
    ]
    if any(ind in raw for ind in non_ast_indicators):
        return None

    # Clean units and annotations
    cleaned = re.sub(r'\(.*?\)|\[.*?\]', '', raw)
    cleaned = re.sub(r'\b(mic|disc|disk|zone|mg/liter|mg/l|ug/ml|µg/ml)\b', '', cleaned)
    cleaned = cleaned.strip(' :_-')

    # Direct match in permitted list
    if cleaned in PERMITTED_DRUGS:
        return cleaned

    # Check synonyms/abbreviations
    if cleaned in DRUG_SYNONYMS:
        mapped = DRUG_SYNONYMS[cleaned]
        if mapped in PERMITTED_DRUGS:
            return mapped

    # Substring search in sorted permitted drugs (longest first)
    sorted_permitted = sorted(PERMITTED_DRUGS, key=len, reverse=True)
    for drug in sorted_permitted:
        # Match as word or bounded substring
        pattern = r'(?<![a-z0-9])' + re.escape(drug) + r'(?![a-z0-9])'
        if re.search(pattern, raw):
            return drug

    return None


def _parse_measurement(val):
    if pd.isna(val):
        return None, None, None, None

    val_str = str(val).strip()
    if not val_str or val_str.lower() in {'nan', 'none', 'null', 'nd', 'n/a', 'na', '-', '.', '/'}:
        return None, None, None, None

    # 1. Parse SIR call
    sir_call = None
    if re.search(r'\b(susceptible|sensitive)\b', val_str, re.IGNORECASE):
        sir_call = 'S'
    elif re.search(r'\b(resistant)\b', val_str, re.IGNORECASE):
        sir_call = 'R'
    elif re.search(r'\b(intermediate)\b', val_str, re.IGNORECASE):
        sir_call = 'I'
    elif re.search(r'\b(susceptible-dose dependent|sdd)\b', val_str, re.IGNORECASE):
        sir_call = 'SDD'
    elif re.search(r'\b(non-susceptible|nonsusceptible|ns)\b', val_str, re.IGNORECASE):
        sir_call = 'NS'
    else:
        m_sir = re.search(r'(?:[\(\[\{\s]|^)(SDD|NS|[SIR])(?:[\)\]\}\s]|$)', val_str)
        if m_sir:
            sir_call = m_sir.group(1).upper()

    # 2. Parse MIC and sign
    num_match = re.search(r'(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)', val_str)
    if num_match:
        mic = re.sub(r'\s+', '', num_match.group(1))
        sign_match = re.search(r'(<=|>=|≤|≥|<|>|=)', val_str)
        if sign_match:
            raw_sign = sign_match.group(1)
            mic_sign = '<=' if raw_sign == '≤' else ('>=' if raw_sign == '≥' else raw_sign)
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"
    else:
        mic = None
        mic_sign = None
        notes = None

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    output_cols = ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']

    # 1. Identify isolate_id column
    isolate_col = None
    isolate_patterns = [
        r'isolate[\s_]*id',
        r'specimen[\s_]*(?:id|number|no)',
        r'strain[\s_]*(?:id|name|number|no)?',
        r'sample[\s_]*(?:id|name|number|no)',
        r'patient[\s_]*isolate',
        r'\bisolate\b',
        r'\bsample\b',
        r'\bstrain\b'
    ]
    for pattern in isolate_patterns:
        for col in df.columns:
            if re.search(pattern, str(col), re.IGNORECASE):
                isolate_col = col
                break
        if isolate_col is not None:
            break

    # 2. Extract public accessions
    acc_patterns = r'\b(SAM[NED][A-Z]?\d+|[EEDS]RR\d+|[EEDS]RX\d+|[EEDS]RS\d+|GC[AF]_\d+\.\d+|PRJ[EDN][A-Z]\d+)\b'
    acc_cols = []
    for col in df.columns:
        if col == isolate_col:
            continue
        col_lower = str(col).lower()
        if any(term in col_lower for term in ['accession', 'biosample', 'sra', 'genbank', 'ena', 'ddbj']):
            acc_cols.append(col)

    # 3. Identify drug columns
    drug_cols = {}
    for col in df.columns:
        if col == isolate_col or col in acc_cols:
            continue
        mapped_drug = _match_drug_column(col)
        if mapped_drug:
            drug_cols[col] = mapped_drug

    # 4. Transform and unpivot
    records = []
    for _, row in df.iterrows():
        # Resolve isolate_id
        if isolate_col and pd.notna(row[isolate_col]):
            iso_val = str(row[isolate_col]).strip()
            iso_id = iso_val if iso_val else None
        else:
            iso_id = None

        # Resolve accession
        found_accs = []
        for col in acc_cols:
            val = row[col]
            if pd.notna(val):
                matches = re.findall(acc_patterns, str(val))
                for m in matches:
                    if m not in found_accs:
                        found_accs.append(m)
        accession = ','.join(found_accs) if found_accs else None

        # Process each drug measurement
        for col, drug in drug_cols.items():
            cell_val = row[col]
            mic_sign, mic, sir_call, notes = _parse_measurement(cell_val)

            # Discard rows where both mic and sir_call are missing
            if mic is None and sir_call is None:
                continue

            records.append({
                'isolate_id': iso_id,
                'accession': accession,
                'drug': drug,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes
            })

    result_df = pd.DataFrame(records, columns=output_cols)
    return result_df

