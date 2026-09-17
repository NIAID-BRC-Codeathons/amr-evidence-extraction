# ==========================================================
# Transformation Code for Sheet: 'Table_2.XLSX::Sheet1'
# ==========================================================

import re
import numpy as np
import pandas as pd

PERMITTED_DRUGS = [
    'amoxicillin/clavulanic acid', 'ampicillin', 'antibiotic', 'arbekacin', 'azithromycin',
    'biapenem', 'cefazolin', 'cefoxitin', 'ceftarolin', 'ceftaroline', 'chloramphenicol',
    'chlorhexidine gluconate', 'ciprofloxacin', 'clarithromycin', 'clindamycin',
    'dalbavancin', 'daptomycin', 'doripenem', 'erythromycin', 'florfenicol',
    'fosfomycin', 'fusidic acid', 'gentamicin', 'imipenem', 'kanamycin',
    'levofloxacin', 'linezolid', 'meropenem', 'methicillin', 'minocycline',
    'moxifloxacin', 'mupirocin', 'norfloxacin', 'oritavancin', 'oxacillin',
    'penicillin', 'phosphomycin', 'quinupristin/dalfopristin', 'rifampin',
    'streptomycin', 'sulfamethoxazole/trimethoprim', 'tedizolid', 'teicoplanin',
    'telavancin', 'tetracycline', 'tiamulin', 'tigecycline', 'tobramycin',
    'trimethoprim', 'trimethoprim/sulfamethoxazole', 'trimethoprim/sulfonamide',
    'vancomycin'
]

DRUG_MAPPING = {
    # amoxicillin/clavulanic acid
    'amoxicillin/clavulanic acid': 'amoxicillin/clavulanic acid',
    'amoxicillin/clavulanate': 'amoxicillin/clavulanic acid',
    'amoxicillin-clavulanic acid': 'amoxicillin/clavulanic acid',
    'amoxicillin-clavulanate': 'amoxicillin/clavulanic acid',
    'amoxicillin+clavulanic acid': 'amoxicillin/clavulanic acid',
    'amoxicillin+clavulanate': 'amoxicillin/clavulanic acid',
    'amoxicillin clavulanic acid': 'amoxicillin/clavulanic acid',
    'amoxicillin clavulanate': 'amoxicillin/clavulanic acid',
    'amox/clav': 'amoxicillin/clavulanic acid',
    'amc': 'amoxicillin/clavulanic acid',
    'aug': 'amoxicillin/clavulanic acid',
    'augmentin': 'amoxicillin/clavulanic acid',
    # ampicillin
    'ampicillin': 'ampicillin',
    'amp': 'ampicillin',
    'am': 'ampicillin',
    # antibiotic
    'antibiotic': 'antibiotic',
    # arbekacin
    'arbekacin': 'arbekacin',
    'abk': 'arbekacin',
    # azithromycin
    'azithromycin': 'azithromycin',
    'azm': 'azithromycin',
    'azi': 'azithromycin',
    # biapenem
    'biapenem': 'biapenem',
    'bpm': 'biapenem',
    # cefazolin
    'cefazolin': 'cefazolin',
    'cfz': 'cefazolin',
    'cz': 'cefazolin',
    'czo': 'cefazolin',
    'faz': 'cefazolin',
    # cefoxitin
    'cefoxitin': 'cefoxitin',
    'fox': 'cefoxitin',
    'cxt': 'cefoxitin',
    # ceftarolin / ceftaroline
    'ceftarolin': 'ceftarolin',
    'ceftaroline': 'ceftaroline',
    'cpt': 'ceftaroline',
    'cfl': 'ceftaroline',
    # chloramphenicol
    'chloramphenicol': 'chloramphenicol',
    'chl': 'chloramphenicol',
    'cam': 'chloramphenicol',
    'chlo': 'chloramphenicol',
    # chlorhexidine gluconate
    'chlorhexidine gluconate': 'chlorhexidine gluconate',
    'chlorhexidine': 'chlorhexidine gluconate',
    'chx': 'chlorhexidine gluconate',
    # ciprofloxacin
    'ciprofloxacin': 'ciprofloxacin',
    'cip': 'ciprofloxacin',
    'cp': 'ciprofloxacin',
    'cipro': 'ciprofloxacin',
    # clarithromycin
    'clarithromycin': 'clarithromycin',
    'clr': 'clarithromycin',
    'cla': 'clarithromycin',
    # clindamycin
    'clindamycin': 'clindamycin',
    'cli': 'clindamycin',
    'cc': 'clindamycin',
    'cd': 'clindamycin',
    'clinda': 'clindamycin',
    # dalbavancin
    'dalbavancin': 'dalbavancin',
    'dal': 'dalbavancin',
    # daptomycin
    'daptomycin': 'daptomycin',
    'dap': 'daptomycin',
    'dpm': 'daptomycin',
    # doripenem
    'doripenem': 'doripenem',
    'dor': 'doripenem',
    # erythromycin
    'erythromycin': 'erythromycin',
    'ery': 'erythromycin',
    'e': 'erythromycin',
    'erm': 'erythromycin',
    # florfenicol
    'florfenicol': 'florfenicol',
    'ffc': 'florfenicol',
    'flo': 'florfenicol',
    # fosfomycin
    'fosfomycin': 'fosfomycin',
    'fos': 'fosfomycin',
    'ff': 'fosfomycin',
    # fusidic acid
    'fusidic acid': 'fusidic acid',
    'fus': 'fusidic acid',
    'fa': 'fusidic acid',
    # gentamicin
    'gentamicin': 'gentamicin',
    'gentamycin': 'gentamicin',
    'gen': 'gentamicin',
    'gm': 'gentamicin',
    'cn': 'gentamicin',
    'gentamicin c': 'gentamicin',
    # imipenem
    'imipenem': 'imipenem',
    'ipm': 'imipenem',
    'imi': 'imipenem',
    'imp': 'imipenem',
    # kanamycin
    'kanamycin': 'kanamycin',
    'kan': 'kanamycin',
    'kanamycin a': 'kanamycin',
    # levofloxacin
    'levofloxacin': 'levofloxacin',
    'lfx': 'levofloxacin',
    'lev': 'levofloxacin',
    'lvx': 'levofloxacin',
    # linezolid
    'linezolid': 'linezolid',
    'lnz': 'linezolid',
    'lzd': 'linezolid',
    # meropenem
    'meropenem': 'meropenem',
    'mem': 'meropenem',
    'mer': 'meropenem',
    'mero': 'meropenem',
    # methicillin
    'methicillin': 'methicillin',
    'met': 'methicillin',
    # minocycline
    'minocycline': 'minocycline',
    'min': 'minocycline',
    'mno': 'minocycline',
    # moxifloxacin
    'moxifloxacin': 'moxifloxacin',
    'mxf': 'moxifloxacin',
    'mox': 'moxifloxacin',
    # mupirocin
    'mupirocin': 'mupirocin',
    'mup': 'mupirocin',
    # norfloxacin
    'norfloxacin': 'norfloxacin',
    'nor': 'norfloxacin',
    'nfx': 'norfloxacin',
    # oritavancin
    'oritavancin': 'oritavancin',
    'ori': 'oritavancin',
    # oxacillin
    'oxacillin': 'oxacillin',
    'oxa': 'oxacillin',
    'ox': 'oxacillin',
    # penicillin
    'penicillin': 'penicillin',
    'pen': 'penicillin',
    'penicillin g': 'penicillin',
    # phosphomycin
    'phosphomycin': 'phosphomycin',
    # quinupristin/dalfopristin
    'quinupristin/dalfopristin': 'quinupristin/dalfopristin',
    'quinupristin+dalfopristin': 'quinupristin/dalfopristin',
    'quinupristin-dalfopristin': 'quinupristin/dalfopristin',
    'quinupristin dalfopristin': 'quinupristin/dalfopristin',
    'q/d': 'quinupristin/dalfopristin',
    'synercid': 'quinupristin/dalfopristin',
    # rifampin
    'rifampin': 'rifampin',
    'rifampicin': 'rifampin',
    'rif': 'rifampin',
    'ra': 'rifampin',
    'rd': 'rifampin',
    # streptomycin
    'streptomycin': 'streptomycin',
    'str': 'streptomycin',
    # sulfamethoxazole/trimethoprim
    'sulfamethoxazole/trimethoprim': 'sulfamethoxazole/trimethoprim',
    'sulfamethoxazole-trimethoprim': 'sulfamethoxazole/trimethoprim',
    'sulfamethoxazole+trimethoprim': 'sulfamethoxazole/trimethoprim',
    # tedizolid
    'tedizolid': 'tedizolid',
    'tzd': 'tedizolid',
    # teicoplanin
    'teicoplanin': 'teicoplanin',
    'tec': 'teicoplanin',
    # telavancin
    'telavancin': 'telavancin',
    'tla': 'telavancin',
    # tetracycline
    'tetracycline': 'tetracycline',
    'tet': 'tetracycline',
    'te': 'tetracycline',
    'tc': 'tetracycline',
    # tiamulin
    'tiamulin': 'tiamulin',
    'tia': 'tiamulin',
    # tigecycline
    'tigecycline': 'tigecycline',
    'tgc': 'tigecycline',
    'tig': 'tigecycline',
    # tobramycin
    'tobramycin': 'tobramycin',
    'tob': 'tobramycin',
    'tm': 'tobramycin',
    'nn': 'tobramycin',
    # trimethoprim
    'trimethoprim': 'trimethoprim',
    'tmp': 'trimethoprim',
    'w': 'trimethoprim',
    # trimethoprim/sulfamethoxazole
    'trimethoprim/sulfamethoxazole': 'trimethoprim/sulfamethoxazole',
    'trimethoprim-sulfamethoxazole': 'trimethoprim/sulfamethoxazole',
    'trimethoprim+sulfamethoxazole': 'trimethoprim/sulfamethoxazole',
    'trimethoprim sulfamethoxazole': 'trimethoprim/sulfamethoxazole',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'cotrimoxazole': 'trimethoprim/sulfamethoxazole',
    'co-trimoxazole': 'trimethoprim/sulfamethoxazole',
    # trimethoprim/sulfonamide
    'trimethoprim/sulfonamide': 'trimethoprim/sulfonamide',
    'trimethoprim-sulfonamide': 'trimethoprim/sulfonamide',
    'trimethoprim+sulfonamide': 'trimethoprim/sulfonamide',
    # vancomycin
    'vancomycin': 'vancomycin',
    'van': 'vancomycin',
    'va': 'vancomycin'
}

ACCESSION_RE = re.compile(r'\b(SAM[NED][A-Z0-9]?\d+|SRS\d+|GC[AF]_\d+\.\d+|[ESD]RR\d+)\b')


def normalize_sign(raw_sign: str | None) -> str | None:
    if not raw_sign:
        return None
    raw_sign = raw_sign.strip()
    if raw_sign in ('<=', '≤'):
        return '<='
    elif raw_sign in ('>=', '≥'):
        return '>='
    elif raw_sign in ('<', '>', '='):
        return raw_sign
    return None


def normalize_sir(raw_sir: str | None) -> str | None:
    if not raw_sir:
        return None
    s = raw_sir.strip().upper()
    sir_map = {
        'S': 'S', 'SUSCEPTIBLE': 'S',
        'I': 'I', 'INTERMEDIATE': 'I',
        'R': 'R', 'RESISTANT': 'R',
        'SDD': 'SDD', 'SUSCEPTIBLE-DOSE DEPENDENT': 'SDD', 'SUSCEPTIBLE DOSE DEPENDENT': 'SDD',
        'NS': 'NS', 'NON-SUSCEPTIBLE': 'NS', 'NONSUSCEPTIBLE': 'NS'
    }
    return sir_map.get(s, None)


def parse_ast_cell(val):
    if pd.isna(val):
        return None, None, None, None
    s = str(val).strip()
    if not s or s.lower() in {'nan', 'none', 'null', 'nd', 'n/a', 'na', '-', '.', '/', 'not tested'}:
        return None, None, None, None

    # Replace comma between digits with dot (e.g. 0,5 -> 0.5)
    s_clean = re.sub(r'(\d+),(\d+)', r'\1.\2', s)

    # Pure SIR call check
    sir_map = {
        'S': 'S', 'SUSCEPTIBLE': 'S',
        'I': 'I', 'INTERMEDIATE': 'I',
        'R': 'R', 'RESISTANT': 'R',
        'SDD': 'SDD', 'SUSCEPTIBLE-DOSE DEPENDENT': 'SDD', 'SUSCEPTIBLE DOSE DEPENDENT': 'SDD',
        'NS': 'NS', 'NON-SUSCEPTIBLE': 'NS', 'NONSUSCEPTIBLE': 'NS'
    }
    if s_clean.upper() in sir_map:
        return None, None, sir_map[s_clean.upper()], None

    sign_pattern = r'(?P<sign><=|>=|<=?|>=?|≤|≥|<|>|=)'
    num_pattern = r'(?P<mic>\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)'
    sir_pattern = r'(?P<sir>SDD|NS|SUSCEPTIBLE|INTERMEDIATE|RESISTANT|[SIR])'

    # Pattern 1: sign? mic (sir)?
    p1 = re.compile(rf'^\s*{sign_pattern}?\s*{num_pattern}\s*(?:[\(\[\s]\s*{sir_pattern}\s*[\)\]]?)?\s*$', re.I)
    m1 = p1.match(s_clean)
    if m1:
        raw_sign = m1.group('sign')
        raw_mic = m1.group('mic')
        raw_sir = m1.group('sir')

        mic = re.sub(r'\s*/\s*', '/', raw_mic)
        sir_call = normalize_sir(raw_sir)
        if raw_sign:
            mic_sign = normalize_sign(raw_sign)
            notes = None
        else:
            mic_sign = '='
            notes = "mic_sign '=' inferred"
        return mic_sign, mic, sir_call, notes

    # Pattern 2: sir (sign? mic)
    p2 = re.compile(rf'^\s*{sir_pattern}\s*(?:[\(\[\s]\s*{sign_pattern}?\s*{num_pattern}\s*[\)\]]?)?\s*$', re.I)
    m2 = p2.match(s_clean)
    if m2:
        raw_sir = m2.group('sir')
        raw_sign = m2.group('sign')
        raw_mic = m2.group('mic')

        sir_call = normalize_sir(raw_sir)
        if raw_mic:
            mic = re.sub(r'\s*/\s*', '/', raw_mic)
            if raw_sign:
                mic_sign = normalize_sign(raw_sign)
                notes = None
            else:
                mic_sign = '='
                notes = "mic_sign '=' inferred"
        else:
            mic_sign = None
            mic = None
            notes = None
        return mic_sign, mic, sir_call, notes

    return None, None, None, None


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    output_cols = ['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes']
    if df is None or df.empty:
        return pd.DataFrame(columns=output_cols)

    # 1. Identify valid drug columns and map them
    drug_col_map = {}
    for col in df.columns:
        col_str = str(col).strip().lower()
        if col_str in DRUG_MAPPING:
            drug_col_map[col] = DRUG_MAPPING[col_str]

    # 2. Identify Isolate ID column
    isolate_col = None
    # Check explicitly named columns
    for col in df.columns:
        c_str = str(col).strip().lower()
        if re.search(r'\b(isolate|specimen|sample|strain|patient)\b', c_str) and not re.search(r'source|date|type|site', c_str):
            isolate_col = col
            break
        elif re.search(r'\bid\b', c_str) and not re.search(r'source|date|type|site', c_str):
            isolate_col = col
            break

    # If not found, inspect non-drug columns
    if isolate_col is None:
        non_drug_cols = [c for c in df.columns if c not in drug_col_map]
        for col in non_drug_cols:
            vals = df[col].dropna().astype(str).str.strip()
            vals = vals[vals != ''].tolist()
            if not vals:
                continue
            # Skip if species/genus
            if any('coli' in v.lower() or 'aureus' in v.lower() or 'klebsiella' in v.lower() for v in vals[:5]):
                continue
            # Skip if panel/method
            if any(k in v.lower() for k in ['gn3f', 'frcol', 'sensititre', 'vitek', 'panel'] for v in vals[:5]):
                continue
            # Skip if pure accession
            if all(ACCESSION_RE.match(v) for v in vals[:5]):
                continue
            isolate_col = col
            break

    # 3. Identify Accession columns
    acc_cols = []
    for col in df.columns:
        if col in drug_col_map or col == isolate_col:
            continue
        col_str = str(col).strip().lower()
        if any(k in col_str for k in ['accession', 'biosample', 'sra_run', 'run_accession', 'assembly_accession']):
            acc_cols.append(col)
        else:
            sample_vals = df[col].dropna().astype(str).str.strip()
            if not sample_vals.empty:
                matches = sample_vals.apply(lambda x: bool(ACCESSION_RE.search(x)))
                if matches.mean() > 0.5:
                    acc_cols.append(col)

    # Pre-extract accessions per row index
    row_accessions = {}
    for idx in df.index:
        found_accs = []
        for ac in acc_cols:
            val = str(df.at[idx, ac]) if pd.notna(df.at[idx, ac]) else ''
            for acc in ACCESSION_RE.findall(val):
                if acc not in found_accs:
                    found_accs.append(acc)
        row_accessions[idx] = ','.join(found_accs) if found_accs else None

    # 4. Extract records
    records = []
    for idx in df.index:
        # Get isolate_id
        iso_id = None
        if isolate_col is not None and pd.notna(df.at[idx, isolate_col]):
            val_str = str(df.at[idx, isolate_col]).strip()
            if val_str and val_str.lower() not in {'nan', 'none', 'null'}:
                iso_id = val_str

        acc_val = row_accessions.get(idx, None)

        for col, drug_name in drug_col_map.items():
            cell_val = df.at[idx, col]
            mic_sign, mic, sir_call, notes = parse_ast_cell(cell_val)
            if mic is None and sir_call is None:
                continue

            records.append({
                'isolate_id': iso_id,
                'accession': acc_val,
                'drug': drug_name,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes
            })

    result_df = pd.DataFrame(records, columns=output_cols)
    return result_df

# ==========================================================
# Transformation Code for Sheet: 'Table_1.XLSX::Sheet1'
# ==========================================================

import re
import numpy as np
import pandas as pd


def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Extracts mapping records between isolate identifiers and public database accessions."""
    # 1. Identify isolate / sample ID column
    isolate_col = None
    isolate_patterns = [
        r"^(id(\s*\(\d+\))?|isolate([_\s]*id)?|sample([_\s]*id)?|strain|specimen([_\s]*id)?|lab([_\s]*id)?|cvm_number)$",
        r"(isolate|sample)[_\s]*id",
        r"^id\b",
    ]

    for pat in isolate_patterns:
        for col in df.columns:
            clean_col = str(col).strip()
            if re.search(pat, clean_col, re.IGNORECASE):
                isolate_col = col
                break
        if isolate_col:
            break

    # Fallback: if not found, search for any column with 'id' or 'sample' that is not QC/Accession
    if not isolate_col:
        for col in df.columns:
            clean_col = str(col).strip().lower()
            if (
                "id" in clean_col or "sample" in clean_col
            ) and "accession" not in clean_col:
                isolate_col = col
                break

    # 2. Identify public repository accession columns
    accession_cols = []
    for col in df.columns:
        clean_col = str(col).strip()
        if re.search(
            r"(accession|biosample|sra|ena|run|assembly)", clean_col, re.IGNORECASE
        ):
            accession_cols.append(col)

    # Patterns for BioSample vs. other public accessions
    biosample_pattern = re.compile(
        r"^(SAM[NED][A-Z]?\d+|[ESD]RS\d+)$", re.IGNORECASE
    )
    general_accession_pattern = re.compile(
        r"\b(SAM[NED][A-Z]?\d+|[ESD]R[SRXP]\d+|GC[AF]_\d+\.\d+|[A-Z]{1,2}\d{5,8}|[A-Z]{4}\d{8,10})\b",
        re.IGNORECASE,
    )

    records = []
    for _, row in df.iterrows():
        # Extract isolate ID
        iso_val = ""
        if isolate_col is not None and pd.notna(row[isolate_col]):
            iso_str = str(row[isolate_col]).strip()
            if iso_str.lower() not in ("", "nan", "none", "null"):
                iso_val = iso_str

        # Extract all accessions from identified accession columns
        row_accessions = []
        for col in accession_cols:
            val = row[col]
            if pd.notna(val):
                val_str = str(val).strip()
                if val_str.lower() not in ("", "nan", "none", "null"):
                    # Find accession tokens matching standard repository patterns
                    tokens = general_accession_pattern.findall(val_str)
                    if tokens:
                        for token in tokens:
                            if token not in row_accessions:
                                row_accessions.append(token)
                    else:
                        # If no token extracted by regex, use raw value if not trivial
                        if val_str not in row_accessions:
                            row_accessions.append(val_str)

        # Categorize into BioSample vs. secondary (non-BioSample)
        secondary_accs = [
            acc for acc in row_accessions if not biosample_pattern.match(acc)
        ]

        accession_str = (
            ",".join(row_accessions) if row_accessions else np.nan
        )
        secondary_str = (
            ",".join(secondary_accs) if secondary_accs else None
        )
        isolate_id_val = iso_val if iso_val != "" else np.nan

        # Discard rows where BOTH isolate_id and accession are missing/blank
        if pd.isna(isolate_id_val) and pd.isna(accession_str):
            continue

        records.append(
            {
                "isolate_id": isolate_id_val,
                "accession": accession_str,
                "secondary_accession": secondary_str,
            }
        )

    result_df = pd.DataFrame(
        records, columns=["isolate_id", "accession", "secondary_accession"]
    )
    return result_df

