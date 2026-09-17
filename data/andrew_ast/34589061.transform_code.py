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

DRUG_MAPPING = {
    'lnz': 'linezolid',
    'lzd': 'linezolid',
    'linezolid': 'linezolid',
    'tdz': 'tedizolid',
    'tzd': 'tedizolid',
    'tedizolid': 'tedizolid',
    'cip': 'ciprofloxacin',
    'ciprofloxacin': 'ciprofloxacin',
    'ery': 'erythromycin',
    'erythromycin': 'erythromycin',
    'van': 'vancomycin',
    'vancomycin': 'vancomycin',
    'dap': 'daptomycin',
    'daptomycin': 'daptomycin',
    'oxacillin': 'oxacillin',
    'oxa': 'oxacillin',
    'gentamicin': 'gentamicin',
    'gen': 'gentamicin',
    'gm': 'gentamicin',
    'tetracycline': 'tetracycline',
    'tet': 'tetracycline',
    'teicoplanin': 'teicoplanin',
    'tec': 'teicoplanin',
    'tigecycline': 'tigecycline',
    'tgc': 'tigecycline',
    'ampicillin': 'ampicillin',
    'amp': 'ampicillin',
    'clindamycin': 'clindamycin',
    'cli': 'clindamycin',
    'cc': 'clindamycin',
    'rifampin': 'rifampin',
    'rifampicin': 'rifampin',
    'rif': 'rifampin',
    'ra': 'rifampin',
}
for d in PERMITTED_DRUGS:
    DRUG_MAPPING[d.lower()] = d


def normalize_drug_name(text: str) -> str | None:
    if not text or pd.isna(text):
        return None
    s = str(text).strip().lower()
    s_clean = re.sub(r'[\(\[\{].*?[\)\]\}]', '', s).strip()
    s_clean = re.sub(
        r'\b(mic|mg/l|ug/ml|µg/ml|,|disc|disk)\b', '', s_clean
    ).strip()

    if s in DRUG_MAPPING:
        return DRUG_MAPPING[s]
    if s_clean in DRUG_MAPPING:
        return DRUG_MAPPING[s_clean]

    tokens = re.findall(r'[a-zA-Z/]+', s)
    for token in tokens:
        if token in DRUG_MAPPING:
            return DRUG_MAPPING[token]

    for drug in PERMITTED_DRUGS:
        if len(drug) > 3 and drug in s:
            return drug

    return None


def parse_measurement(cell_value: str):
    if pd.isna(cell_value):
        return None, None, None, None
    val = str(cell_value).strip()
    if val in ('', 'nan', 'None', 'ND', 'N/A', 'NA', '-', '–', '—'):
        return None, None, None, None

    sir_call = None
    sir_match = re.search(r'\b(SDD|NS|[SIR])\b', val, re.I)
    sir_paren = re.search(r'[\(\[\{]\s*(SDD|NS|[SIR])\s*[\)\]\}]', val, re.I)
    if sir_paren:
        sir_call = sir_paren.group(1).upper()
        val = re.sub(r'[\(\[\{]\s*(SDD|NS|[SIR])\s*[\)\]\}]', '', val, flags=re.I).strip()
    elif val.upper() in ('S', 'I', 'R', 'SDD', 'NS'):
        sir_call = val.upper()
        return None, None, sir_call, None

    # Replace en-dash / em-dash with hyphen
    val = val.replace('–', '-').replace('—', '-')

    # Check for inequality sign
    sign_match = re.search(r'^(<=|>=|<|>|=|≤|≥)', val)
    mic_sign = None
    notes = None
    if sign_match:
        raw_sign = sign_match.group(1)
        mic_sign = '<=' if raw_sign == '≤' else ('>=' if raw_sign == '≥' else raw_sign)
        val = val[len(raw_sign):].strip()
    else:
        mic_sign = '='
        notes = "mic_sign '=' inferred"

    # Remove non-numeric annotations except '/', '.', '-'
    clean_val = re.sub(r'[^\d./-]', '', val).strip()
    if not clean_val:
        return None, None, sir_call, None

    # Combination ratio e.g. 32/16
    ratio_match = re.match(r'^(\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?)$', clean_val)
    if ratio_match:
        mic = clean_val.replace(' ', '')
        return mic_sign, mic, sir_call, notes

    # Range e.g. 2-4 or 4-8 -> take upper bound
    range_match = re.match(r'^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$', clean_val)
    if range_match:
        mic = range_match.group(2)
        return mic_sign, mic, sir_call, notes

    # Single numeric value
    num_match = re.match(r'^(\d+(?:\.\d+)?)$', clean_val)
    if num_match:
        mic = num_match.group(1)
        return mic_sign, mic, sir_call, notes

    return None, None, sir_call, None


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
        )

    # 1. Identify accession columns
    accession_cols = [
        col for col in df.columns
        if re.search(r'accession|biosample|bioproject', str(col), re.I)
    ]

    # 2. Check if drug headers exist in df.columns or in row 0
    drug_cols = {}
    for col_idx, col in enumerate(df.columns):
        drug = normalize_drug_name(str(col))
        if drug:
            drug_cols[col_idx] = drug

    start_row = 0
    if not drug_cols and len(df) > 0:
        row_0_drugs = {}
        for col_idx in range(df.shape[1]):
            val = df.iloc[0, col_idx]
            drug = normalize_drug_name(str(val))
            if drug:
                row_0_drugs[col_idx] = drug
        if row_0_drugs:
            drug_cols = row_0_drugs
            start_row = 1

    # 3. Identify isolate ID column
    isolate_col_idx = None
    for col_idx, col in enumerate(df.columns):
        if col_idx in drug_cols:
            continue
        if re.search(r'\b(isolate|sample|specimen|strain|patient|subject|id)\b', str(col), re.I):
            isolate_col_idx = col_idx
            break

    if isolate_col_idx is None:
        for col_idx, col in enumerate(df.columns):
            if col_idx not in drug_cols and col not in accession_cols:
                isolate_col_idx = col_idx
                break

    records = []
    for row_idx in range(start_row, len(df)):
        row = df.iloc[row_idx]

        # Extract Isolate ID
        raw_iso = row.iloc[isolate_col_idx] if isolate_col_idx is not None else None
        if pd.notna(raw_iso) and str(raw_iso).strip() not in ('', 'nan', 'None'):
            val_str = str(raw_iso).strip()
            if val_str.endswith('.0'):
                isolate_id = val_str[:-2]
            else:
                isolate_id = val_str
        else:
            isolate_id = f"isolate_{row_idx - start_row + 1}"

        # Extract Public Accession
        accessions = []
        for acc_col in accession_cols:
            acc_val = row[acc_col]
            if pd.notna(acc_val):
                found = re.findall(
                    r'\b(?:SAM[NED][A-Z]?\d+|PRJ[NED][A-Z]?\d+|[EGD]RR\d+|GC[AF]_\d+\.\d+)\b',
                    str(acc_val)
                )
                accessions.extend(found)
        accession = ','.join(dict.fromkeys(accessions)) if accessions else None

        # Extract drug measurements
        for col_idx, drug in drug_cols.items():
            cell_val = row.iloc[col_idx]
            mic_sign, mic, sir_call, notes = parse_measurement(cell_val)

            if mic is None and sir_call is None:
                continue

            records.append({
                'isolate_id': isolate_id,
                'accession': accession,
                'drug': drug,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes
            })

    output_df = pd.DataFrame(
        records,
        columns=['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
    )
    return output_df

# ============================================================
# Transformation code for table: 'TABLE_2.tsv'
# ============================================================

import re
import numpy as np
import pandas as pd

PERMITTED_DRUGS = [
    'amoxicillin/clavulanic acid', 'ampicillin', 'antibiotic', 'arbekacin',
    'azithromycin', 'biapenem', 'cefazolin', 'cefoxitin', 'ceftarolin',
    'ceftaroline', 'chloramphenicol', 'chlorhexidine gluconate',
    'ciprofloxacin', 'clarithromycin', 'clindamycin', 'dalbavancin',
    'daptomycin', 'doripenem', 'erythromycin', 'florfenicol', 'fosfomycin',
    'fusidic acid', 'gentamicin', 'imipenem', 'kanamycin', 'levofloxacin',
    'linezolid', 'meropenem', 'methicillin', 'minocycline', 'moxifloxacin',
    'mupirocin', 'norfloxacin', 'oritavancin', 'oxacillin', 'penicillin',
    'phosphomycin', 'quinupristin/dalfopristin', 'rifampin', 'streptomycin',
    'sulfamethoxazole/trimethoprim', 'tedizolid', 'teicoplanin', 'telavancin',
    'tetracycline', 'tiamulin', 'tigecycline', 'tobramycin', 'trimethoprim',
    'trimethoprim/sulfamethoxazole', 'trimethoprim/sulfonamide', 'vancomycin'
]

DRUG_SYNONYMS = {
    'amc': 'amoxicillin/clavulanic acid',
    'amoxicillin-clavulanic acid': 'amoxicillin/clavulanic acid',
    'amoxicillin/clavulanate': 'amoxicillin/clavulanic acid',
    'augmentin': 'amoxicillin/clavulanic acid',
    'amp': 'ampicillin',
    'ampicillin': 'ampicillin',
    'arbekacin': 'arbekacin',
    'azm': 'azithromycin',
    'azithromycin': 'azithromycin',
    'biapenem': 'biapenem',
    'cfz': 'cefazolin',
    'cz': 'cefazolin',
    'cefazolin': 'cefazolin',
    'fox': 'cefoxitin',
    'cefoxitin': 'cefoxitin',
    'cpt': 'ceftaroline',
    'ceftarolin': 'ceftarolin',
    'ceftaroline': 'ceftaroline',
    'chl': 'chloramphenicol',
    'c': 'chloramphenicol',
    'chloramphenicol': 'chloramphenicol',
    'chg': 'chlorhexidine gluconate',
    'chlorhexidine gluconate': 'chlorhexidine gluconate',
    'cip': 'ciprofloxacin',
    'ciprofloxacin': 'ciprofloxacin',
    'clr': 'clarithromycin',
    'cla': 'clarithromycin',
    'clarithromycin': 'clarithromycin',
    'cli': 'clindamycin',
    'cc': 'clindamycin',
    'clindamycin': 'clindamycin',
    'dal': 'dalbavancin',
    'dalbavancin': 'dalbavancin',
    'dap': 'daptomycin',
    'dpc': 'daptomycin',
    'daptomycin': 'daptomycin',
    'dor': 'doripenem',
    'doripenem': 'doripenem',
    'ery': 'erythromycin',
    'e': 'erythromycin',
    'erythromycin': 'erythromycin',
    'ffc': 'florfenicol',
    'florfenicol': 'florfenicol',
    'fos': 'fosfomycin',
    'fosfomycin': 'fosfomycin',
    'phosphomycin': 'phosphomycin',
    'fus': 'fusidic acid',
    'fusidic acid': 'fusidic acid',
    'fusidate': 'fusidic acid',
    'gen': 'gentamicin',
    'gm': 'gentamicin',
    'cn': 'gentamicin',
    'gentamicin': 'gentamicin',
    'gentamycin': 'gentamicin',
    'ipm': 'imipenem',
    'imi': 'imipenem',
    'imipenem': 'imipenem',
    'kan': 'kanamycin',
    'k': 'kanamycin',
    'kanamycin': 'kanamycin',
    'lvx': 'levofloxacin',
    'lev': 'levofloxacin',
    'levofloxacin': 'levofloxacin',
    'lzd': 'linezolid',
    'lnz': 'linezolid',
    'lz': 'linezolid',
    'linezolid': 'linezolid',
    'mem': 'meropenem',
    'mer': 'meropenem',
    'meropenem': 'meropenem',
    'met': 'methicillin',
    'methicillin': 'methicillin',
    'min': 'minocycline',
    'mno': 'minocycline',
    'minocycline': 'minocycline',
    'mxf': 'moxifloxacin',
    'mox': 'moxifloxacin',
    'moxifloxacin': 'moxifloxacin',
    'mup': 'mupirocin',
    'mupirocin': 'mupirocin',
    'nor': 'norfloxacin',
    'norfloxacin': 'norfloxacin',
    'ori': 'oritavancin',
    'oritavancin': 'oritavancin',
    'oxa': 'oxacillin',
    'ox': 'oxacillin',
    'oxacillin': 'oxacillin',
    'pen': 'penicillin',
    'p': 'penicillin',
    'penicillin': 'penicillin',
    'syn': 'quinupristin/dalfopristin',
    'quinupristin/dalfopristin': 'quinupristin/dalfopristin',
    'quinupristin-dalfopristin': 'quinupristin/dalfopristin',
    'synercid': 'quinupristin/dalfopristin',
    'qd': 'quinupristin/dalfopristin',
    'rif': 'rifampin',
    'ra': 'rifampin',
    'rifampin': 'rifampin',
    'rifampicin': 'rifampin',
    'str': 'streptomycin',
    's': 'streptomycin',
    'streptomycin': 'streptomycin',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'tmp/smx': 'trimethoprim/sulfamethoxazole',
    'tmp-smx': 'trimethoprim/sulfamethoxazole',
    'cotrimoxazole': 'trimethoprim/sulfamethoxazole',
    'co-trimoxazole': 'trimethoprim/sulfamethoxazole',
    'trimethoprim/sulfamethoxazole': 'trimethoprim/sulfamethoxazole',
    'trimethoprim-sulfamethoxazole': 'trimethoprim/sulfamethoxazole',
    'tzd': 'tedizolid',
    'tedizolid': 'tedizolid',
    'tec': 'teicoplanin',
    'teicoplanin': 'teicoplanin',
    'tlv': 'telavancin',
    'telavancin': 'telavancin',
    'tet': 'tetracycline',
    'te': 'tetracycline',
    'tcy': 'tetracycline',
    'tetracycline': 'tetracycline',
    'tia': 'tiamulin',
    'tiamulin': 'tiamulin',
    'tgc': 'tigecycline',
    'tig': 'tigecycline',
    'tigecycline': 'tigecycline',
    'tob': 'tobramycin',
    'nn': 'tobramycin',
    'tobramycin': 'tobramycin',
    'tmp': 'trimethoprim',
    'w': 'trimethoprim',
    'trimethoprim': 'trimethoprim',
    'van': 'vancomycin',
    'va': 'vancomycin',
    'vancomycin': 'vancomycin',
}

ACCESSION_PATTERN = re.compile(
    r'\b(SAM[NED][A-Z]?\d+|SRS\d+|GC[AF]_\d+\.\d+|[SED]RR\d+|[SED]RX\d+|[SED]RS\d+)\b',
    re.IGNORECASE
)


def match_drug_name(col_name: str):
    clean = str(col_name).strip().lower()
    clean = re.sub(r'[\(\[\{].*?[\)\]\}]', '', clean)
    clean = re.sub(r'\b(mic|sir|call|interpretation|mg/l|ug/ml|µg/ml|value|range)\b', '', clean)
    clean = re.sub(r'[^a-z0-9/\-]', ' ', clean).strip()

    if clean in DRUG_SYNONYMS:
        matched = DRUG_SYNONYMS[clean]
        if matched in PERMITTED_DRUGS:
            return matched

    tokens = clean.split()
    for t in tokens:
        if t in DRUG_SYNONYMS:
            matched = DRUG_SYNONYMS[t]
            if matched in PERMITTED_DRUGS:
                return matched
    return None


def parse_mic_sir(val):
    if pd.isna(val):
        return None, None, None, None
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ['nd', 'n/a', 'na', '-', '–', 'none', 'nan', '.', 'm**', 'range']:
        return None, None, None, None

    # Normalize dashes and minus signs
    val_clean = val_str.replace('−', '-').replace('–', '-').replace('—', '-')

    # Extract SIR call if present
    sir_call = None
    m_sir = re.search(r'[\(\[\{]?\b(SDD|NS|susceptible|resistant|intermediate|[SIR])\b[\)\]\}]?', val_clean, re.I)
    if m_sir:
        call = m_sir.group(1).upper()
        if call.startswith('SUSC') or call == 'S':
            sir_call = 'S'
        elif call.startswith('RES') or call == 'R':
            sir_call = 'R'
        elif call.startswith('INTER') or call == 'I':
            sir_call = 'I'
        elif call == 'SDD':
            sir_call = 'SDD'
        elif call == 'NS':
            sir_call = 'NS'
        # Remove matched SIR call from string for MIC parsing
        val_clean = val_clean[:m_sir.start()] + val_clean[m_sir.end():]
        val_clean = val_clean.strip(' ()[]{},;')

    # If it is a range (e.g. "0.25-1", "0.5-2"), it is not a valid single isolate numeric MIC
    if re.search(r'\d+\.?\d*\s*-\s*\d+\.?\d*', val_clean):
        return None, None, sir_call, None

    # Check for combination ratio (e.g., "32/16", "<= 0.25/4.75")
    ratio_match = re.search(r'([<>]=?|=)?\s*(\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?)', val_clean)
    if ratio_match:
        sign = ratio_match.group(1)
        ratio = re.sub(r'\s+', '', ratio_match.group(2))
        if sign:
            return sign, ratio, sir_call, None
        else:
            return '=', ratio, sir_call, "mic_sign '=' inferred"

    # Check for single numeric MIC (e.g., "<=0.03", ">4", "0.5")
    num_match = re.search(r'([<>]=?|=)?\s*(\d+(?:\.\d+)?)', val_clean)
    if num_match:
        sign = num_match.group(1)
        num = num_match.group(2)
        if sign:
            return sign, num, sir_call, None
        else:
            return '=', num, sir_call, "mic_sign '=' inferred"

    return None, None, sir_call, None


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    output_cols = ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']

    if df.empty:
        return pd.DataFrame(columns=output_cols)

    work_df = df.copy()

    # Detect if row 0 should be promoted to column headers
    first_col_name = str(work_df.columns[0]).lower()
    if 'unnamed' in first_col_name and len(work_df) > 0:
        first_row_vals = work_df.iloc[0].astype(str).tolist()
        potential_drugs = [match_drug_name(v) for v in first_row_vals]
        if any(potential_drugs):
            work_df.columns = [
                str(work_df.columns[i]) if pd.isna(first_row_vals[i]) or first_row_vals[i].strip() == ''
                else first_row_vals[i].strip()
                for i in range(len(work_df.columns))
            ]
            work_df = work_df.iloc[1:].reset_index(drop=True)

    # 1. Identify isolate_id column
    isolate_col = None
    for col in work_df.columns:
        c = str(col).strip()
        if re.search(r'^(isolate|strain|sample|specimen|patient)([_\s]?(id|no|num|number|name|code))?$', c, re.I):
            isolate_col = col
            break
    if not isolate_col:
        for col in work_df.columns:
            c = str(col).strip().lower()
            if c in ['isolate', 'strain', 'sample', 'specimen', 'id']:
                isolate_col = col
                break

    # 2. Identify accession columns
    accession_cols = []
    for col in work_df.columns:
        if col == isolate_col:
            continue
        c = str(col).strip().lower()
        if re.search(r'\b(accession|biosample|sra|run_accession|assembly)\b', c):
            accession_cols.append(col)
        else:
            sample_vals = work_df[col].dropna().astype(str).str.strip().head(10)
            if len(sample_vals) > 0:
                matches = sample_vals.apply(lambda x: bool(ACCESSION_PATTERN.search(x)))
                if matches.mean() > 0.5:
                    accession_cols.append(col)

    # 3. Identify drug columns
    drug_cols = {}
    for col in work_df.columns:
        if col == isolate_col or col in accession_cols:
            continue
        matched = match_drug_name(col)
        if matched:
            drug_cols[col] = matched

    if not drug_cols:
        return pd.DataFrame(columns=output_cols)

    # Build isolate_id and accession series
    n_rows = len(work_df)
    if isolate_col:
        iso_series = work_df[isolate_col].astype(str).str.strip().replace({'nan': None, 'None': None, '': None})
    else:
        iso_series = pd.Series([None] * n_rows, index=work_df.index)

    if accession_cols:
        def extract_accessions(row):
            found = []
            for col in accession_cols:
                val = str(row[col]) if pd.notna(row[col]) else ''
                matches = ACCESSION_PATTERN.findall(val)
                for m in matches:
                    if m not in found:
                        found.append(m)
            return ','.join(found) if found else None
        acc_series = work_df.apply(extract_accessions, axis=1)
    else:
        acc_series = pd.Series([None] * n_rows, index=work_df.index)

    records = []
    for orig_col, drug_name in drug_cols.items():
        col_vals = work_df[orig_col]
        for idx, val in col_vals.items():
            iso = iso_series.at[idx]
            acc = acc_series.at[idx]

            # Mandatory validation: Must have at least isolate_id or accession
            if (iso is None or iso == '') and (acc is None or acc == ''):
                continue

            mic_sign, mic, sir_call, notes = parse_mic_sir(val)

            # Discard rows where BOTH mic and sir_call are empty/missing
            if (mic is None or mic == '') and (sir_call is None or sir_call == ''):
                continue

            records.append({
                'isolate_id': iso if iso else None,
                'accession': acc if acc else None,
                'drug': drug_name,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes
            })

    if not records:
        return pd.DataFrame(columns=output_cols)

    return pd.DataFrame(records)[output_cols]

