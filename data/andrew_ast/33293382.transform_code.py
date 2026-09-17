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

DRUG_ABBREVIATIONS = {
    'amc': 'amoxicillin/clavulanic acid',
    'amp': 'ampicillin',
    'an': 'amikacin',
    'cfz': 'cefazolin',
    'czo': 'cefazolin',
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
    'fof': 'fosfomycin',
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
    'mxf': 'moxifloxacin',
    'mox': 'moxifloxacin',
    'mup': 'mupirocin',
    'nor': 'norfloxacin',
    'ori': 'oritavancin',
    'oxa': 'oxacillin',
    'pen': 'penicillin',
    'qda': 'quinupristin/dalfopristin',
    'syn': 'quinupristin/dalfopristin',
    'rif': 'rifampin',
    'ra': 'rifampin',
    'str': 'streptomycin',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'tmp-smx': 'trimethoprim/sulfamethoxazole',
    'tzd': 'tedizolid',
    'tec': 'teicoplanin',
    'tlv': 'telavancin',
    'tet': 'tetracycline',
    'tia': 'tiamulin',
    'tgc': 'tigecycline',
    'tob': 'tobramycin',
    'nn': 'tobramycin',
    'tmp': 'trimethoprim',
    'van': 'vancomycin',
    'va': 'vancomycin',
}


def match_drug_column(col_name: str):
    """Identifies if a column name corresponds to a permitted antibiotic drug."""
    clean_col = str(col_name).strip().lower()
    # Remove units and common MIC annotations
    clean_text = re.sub(r'\(.*?\)|\[.*?\]', '', clean_col)
    clean_text = re.sub(r'\b(mic|mg/l|mg/liter|ug/ml|µg/ml|sir)\b', '', clean_text).strip()
    
    # Check abbreviations first
    if clean_text in DRUG_ABBREVIATIONS:
        target = DRUG_ABBREVIATIONS[clean_text]
        if target in PERMITTED_DRUGS:
            return target

    # Check permitted drugs sorted by length descending to match composite names first
    sorted_permitted = sorted(PERMITTED_DRUGS, key=len, reverse=True)
    for drug in sorted_permitted:
        pattern = r'(?<![a-z])' + re.escape(drug) + r'(?![a-z])'
        if re.search(pattern, clean_col):
            return drug
            
    return None


def parse_mic_sir(val):
    """Parses a raw AST cell value into mic_sign, mic, sir_call, and notes."""
    if pd.isna(val):
        return None, None, None, None
        
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ['nd', 'n/a', 'na', '-', '.', 'none']:
        return None, None, None, None

    # Parse qualitative SIR call
    sir_call = None
    sir_match = re.search(r'(?:\b|\()([SIR]|SDD|NS)(?:\b|\))', val_str, re.IGNORECASE)
    if sir_match:
        sir_call = sir_match.group(1).upper()
    else:
        if re.search(r'\b(susceptible[\s-]dose[\s-]dependent|sdd)\b', val_str, re.IGNORECASE):
            sir_call = 'SDD'
        elif re.search(r'\b(non[\s-]?susceptible|ns)\b', val_str, re.IGNORECASE):
            sir_call = 'NS'
        elif re.search(r'\bsusceptible\b', val_str, re.IGNORECASE):
            sir_call = 'S'
        elif re.search(r'\bresistant\b', val_str, re.IGNORECASE):
            sir_call = 'R'
        elif re.search(r'\bintermediate\b', val_str, re.IGNORECASE):
            sir_call = 'I'

    # Parse numeric MIC and inequality signs
    mic_match = re.search(r'(<=|>=|<|>|=|≤|≥)?\s*(\d+(?:\.\d+)?(?:\s*\/\s*\d+(?:\.\d+)?)*)', val_str)
    
    mic_sign = None
    mic = None
    notes = None

    if mic_match and mic_match.group(2):
        raw_sign = mic_match.group(1)
        raw_num = re.sub(r'\s+', '', mic_match.group(2))
        mic = raw_num
        
        if raw_sign:
            if raw_sign == '≤':
                mic_sign = '<='
            elif raw_sign == '≥':
                mic_sign = '>='
            else:
                mic_sign = raw_sign
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"

    if mic is None and sir_call is None:
        return None, None, None, None

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    # 1. Identify isolate_id column
    isolate_col = None
    for col in df.columns:
        if re.search(r'(isolate[_\s]*id|isolate|specimen|strain|sample[_\s]*id)', str(col), re.IGNORECASE):
            isolate_col = col
            break

    # 2. Extract public accession column(s)
    accession_pattern = r'\b(SAM[NEDA]\d+|SRS\d+|GC[AF]_\d+\.\d+|[ESD]RR\d+)\b'
    accession_cols = [
        c for c in df.columns 
        if c != isolate_col and any(k in str(c).lower() for k in ['accession', 'biosample', 'sra', 'run', 'genbank', 'ena'])
    ]
    
    # 3. Identify AST drug columns
    drug_cols = {}
    for col in df.columns:
        if col == isolate_col or col in accession_cols:
            continue
        standardized_drug = match_drug_column(str(col))
        if standardized_drug:
            drug_cols[col] = standardized_drug

    rows = []
    for idx, row in df.iterrows():
        # Resolve Isolate ID
        iso_id = None
        if isolate_col and pd.notna(row[isolate_col]):
            val_id = str(row[isolate_col]).strip()
            if val_id:
                iso_id = val_id

        # Resolve Accession
        acc_str = None
        found_accs = []
        for acc_c in accession_cols:
            if pd.notna(row[acc_c]):
                matches = re.findall(accession_pattern, str(row[acc_c]))
                found_accs.extend(matches)
        if found_accs:
            # Preserve order while removing duplicates
            seen = set()
            unique_accs = [x for x in found_accs if not (x in seen or seen.add(x))]
            acc_str = ','.join(unique_accs)

        # Process each drug column
        for col, drug_name in drug_cols.items():
            cell_val = row[col]
            mic_sign, mic, sir_call, notes = parse_mic_sir(cell_val)
            
            # Discard row if both mic and sir_call are missing
            if mic is None and sir_call is None:
                continue

            rows.append({
                'isolate_id': iso_id,
                'accession': acc_str,
                'drug': drug_name,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes
            })

    output_cols = ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
    if not rows:
        return pd.DataFrame(columns=output_cols)

    return pd.DataFrame(rows)[output_cols]

