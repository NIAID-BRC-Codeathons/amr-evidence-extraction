# ============================================================
# Transformation code for table: 'Table_1.tsv'
# ============================================================

import re
import numpy as np
import pandas as pd

PERMITTED_DRUGS = {
    'amoxicillin/clavulanic acid', 'ampicillin', 'antibiotic', 'arbekacin',
    'azithromycin', 'biapenem', 'cefazolin', 'cefoxitin', 'ceftarolin',
    'ceftaroline', 'chloramphenicol', 'chlorhexidine gluconate', 'ciprofloxacin',
    'clarithromycin', 'clindamycin', 'dalbavancin', 'daptomycin', 'doripenem',
    'erythromycin', 'florfenicol', 'fosfomycin', 'fusidic acid', 'gentamicin',
    'imipenem', 'kanamycin', 'levofloxacin', 'linezolid', 'meropenem',
    'methicillin', 'minocycline', 'moxifloxacin', 'mupirocin', 'norfloxacin',
    'oritavancin', 'oxacillin', 'penicillin', 'phosphomycin',
    'quinupristin/dalfopristin', 'rifampin', 'streptomycin',
    'sulfamethoxazole/trimethoprim', 'tedizolid', 'teicoplanin', 'telavancin',
    'tetracycline', 'tiamulin', 'tigecycline', 'tobramycin', 'trimethoprim',
    'trimethoprim/sulfamethoxazole', 'trimethoprim/sulfonamide', 'vancomycin'
}

DRUG_MAP = {
    # Daptomycin / Vancomycin
    'dp': 'daptomycin',
    'dap': 'daptomycin',
    'dapt': 'daptomycin',
    'daptomycin': 'daptomycin',
    'vn': 'vancomycin',
    'van': 'vancomycin',
    'vanc': 'vancomycin',
    'va': 'vancomycin',
    'vancomycin': 'vancomycin',
    # Other common drugs and abbreviations
    'amx': 'amoxicillin/clavulanic acid',
    'amc': 'amoxicillin/clavulanic acid',
    'aug': 'amoxicillin/clavulanic acid',
    'augmentin': 'amoxicillin/clavulanic acid',
    'amoxicillin/clavulanic acid': 'amoxicillin/clavulanic acid',
    'amoxicillin-clavulanic acid': 'amoxicillin/clavulanic acid',
    'amoxicillin/clavulanate': 'amoxicillin/clavulanic acid',
    'amp': 'ampicillin',
    'ampicillin': 'ampicillin',
    'arb': 'arbekacin',
    'arbekacin': 'arbekacin',
    'azm': 'azithromycin',
    'azi': 'azithromycin',
    'azithromycin': 'azithromycin',
    'bpm': 'biapenem',
    'biapenem': 'biapenem',
    'cfz': 'cefazolin',
    'fzo': 'cefazolin',
    'cz': 'cefazolin',
    'cefazolin': 'cefazolin',
    'fox': 'cefoxitin',
    'cefoxitin': 'cefoxitin',
    'cpt': 'ceftaroline',
    'ceftaroline': 'ceftaroline',
    'ceftarolin': 'ceftaroline',
    'chl': 'chloramphenicol',
    'cam': 'chloramphenicol',
    'chloramphenicol': 'chloramphenicol',
    'chg': 'chlorhexidine gluconate',
    'chlorhexidine gluconate': 'chlorhexidine gluconate',
    'cip': 'ciprofloxacin',
    'cipro': 'ciprofloxacin',
    'ciprofloxacin': 'ciprofloxacin',
    'clr': 'clarithromycin',
    'cla': 'clarithromycin',
    'clarithromycin': 'clarithromycin',
    'cli': 'clindamycin',
    'clinda': 'clindamycin',
    'cc': 'clindamycin',
    'clindamycin': 'clindamycin',
    'dal': 'dalbavancin',
    'dalbavancin': 'dalbavancin',
    'dor': 'doripenem',
    'doripenem': 'doripenem',
    'ery': 'erythromycin',
    'erm': 'erythromycin',
    'erythromycin': 'erythromycin',
    'ffc': 'florfenicol',
    'florfenicol': 'florfenicol',
    'fos': 'fosfomycin',
    'fosfomycin': 'fosfomycin',
    'phosphomycin': 'phosphomycin',
    'fa': 'fusidic acid',
    'fus': 'fusidic acid',
    'fusidic acid': 'fusidic acid',
    'gen': 'gentamicin',
    'gm': 'gentamicin',
    'cn': 'gentamicin',
    'gentamicin': 'gentamicin',
    'ipm': 'imipenem',
    'imi': 'imipenem',
    'imp': 'imipenem',
    'imipenem': 'imipenem',
    'kan': 'kanamycin',
    'kanamycin': 'kanamycin',
    'lvx': 'levofloxacin',
    'lev': 'levofloxacin',
    'levo': 'levofloxacin',
    'levofloxacin': 'levofloxacin',
    'lnz': 'linezolid',
    'lzd': 'linezolid',
    'linezolid': 'linezolid',
    'mem': 'meropenem',
    'mer': 'meropenem',
    'mep': 'meropenem',
    'meropenem': 'meropenem',
    'met': 'methicillin',
    'methicillin': 'methicillin',
    'mno': 'minocycline',
    'min': 'minocycline',
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
    'ox': 'oxacillin',
    'oxa': 'oxacillin',
    'oxacillin': 'oxacillin',
    'pen': 'penicillin',
    'penicillin': 'penicillin',
    'q-d': 'quinupristin/dalfopristin',
    'qd': 'quinupristin/dalfopristin',
    'syn': 'quinupristin/dalfopristin',
    'synercid': 'quinupristin/dalfopristin',
    'quinupristin/dalfopristin': 'quinupristin/dalfopristin',
    'rif': 'rifampin',
    'ra': 'rifampin',
    'rifampin': 'rifampin',
    'rifampicin': 'rifampin',
    'str': 'streptomycin',
    'streptomycin': 'streptomycin',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'tmp/smx': 'trimethoprim/sulfamethoxazole',
    'trimethoprim/sulfamethoxazole': 'trimethoprim/sulfamethoxazole',
    'sulfamethoxazole/trimethoprim': 'sulfamethoxazole/trimethoprim',
    'trimethoprim/sulfonamide': 'trimethoprim/sulfonamide',
    'ted': 'tedizolid',
    'tzd': 'tedizolid',
    'tedizolid': 'tedizolid',
    'tec': 'teicoplanin',
    'teicoplanin': 'teicoplanin',
    'tlv': 'telavancin',
    'telavancin': 'telavancin',
    'tet': 'tetracycline',
    'tetracycline': 'tetracycline',
    'tia': 'tiamulin',
    'tiamulin': 'tiamulin',
    'tgc': 'tigecycline',
    'tig': 'tigecycline',
    'tigecycline': 'tigecycline',
    'tob': 'tobramycin',
    'tobramycin': 'tobramycin',
    'tmp': 'trimethoprim',
    'trimethoprim': 'trimethoprim',
}

ACCESSION_REGEX = re.compile(
    r'\b((?:SAMN|SAMEA|SAMD|SRS|DRS|ERS)\d+|(?:GCF_|GCA_)\d+\.\d+|(?:SRR|ERR|DRR)\d+)\b',
    re.I
)


def extract_drug(col_name: str) -> str | None:
    """Extract and standardize antimicrobial drug name against the permitted list."""
    if not col_name or not isinstance(col_name, str):
        return None
    cleaned = col_name.strip()
    
    # Exclude general/metadata section phrases that are not specific drugs
    lower_orig = cleaned.lower()
    if lower_orig in {'antibiotic susceptibility', 'antibiotic testing', 'antibiotic sensitivity'}:
        return None

    # Strip units and common MIC annotations
    cleaned = re.sub(r'\(?\s*(?:µg|ug|mg)\s*\/\s*(?:ml|l)\s*\)?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(?:mic|sir|bp|breakpoint|interp|interpretation|zone|disk)\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[\(\)\[\]_\-\/]', ' ', cleaned).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().lower()

    if not cleaned:
        return None

    # Direct match in DRUG_MAP
    if cleaned in DRUG_MAP:
        candidate = DRUG_MAP[cleaned]
        return candidate if candidate in PERMITTED_DRUGS else None

    # Token match
    tokens = cleaned.split()
    for tok in tokens:
        if tok in DRUG_MAP:
            candidate = DRUG_MAP[tok]
            if candidate in PERMITTED_DRUGS:
                return candidate

    # Substring match (longer keys first)
    for k in sorted(DRUG_MAP.keys(), key=len, reverse=True):
        if len(k) > 2 and re.search(r'\b' + re.escape(k) + r'\b', cleaned):
            candidate = DRUG_MAP[k]
            if candidate in PERMITTED_DRUGS:
                return candidate

    return None


def parse_mic_sir(val):
    """Parse cell value into mic_sign, mic, sir_call, and notes."""
    if pd.isna(val):
        return None, None, None, None
    
    if isinstance(val, float) and val.is_integer():
        s = str(int(val)).strip()
    else:
        s = str(val).strip()

    if not s or s.lower() in {'nan', 'none', 'nd', 'n/a', 'na', '-', '.', ''}:
        return None, None, None, None

    # Normalize en-dash and em-dash to standard hyphen
    s = s.replace('–', '-').replace('—', '-')

    # Extract SIR call
    sir_call = None
    sir_match = re.search(r'(?:[\(\[\s]|^)(S|I|R|SDD|NS)(?:[\)\]\s]|$)', s, re.I)
    if sir_match:
        sir_call = sir_match.group(1).upper()
        s_clean = (s[:sir_match.start()] + ' ' + s[sir_match.end():]).strip()
    else:
        s_clean = s

    mic_sign = None
    mic = None
    notes = None

    sign_match = re.match(r'^(<=|>=|<|>|=)\s*(.*)$', s_clean)
    if sign_match:
        mic_sign = sign_match.group(1)
        rest = sign_match.group(2).strip()
    else:
        rest = s_clean

    # Clean MIC value (e.g. 0.25, 1, 1-2, 32/16)
    mic_val_match = re.search(r'(\d+(?:\.\d+)?(?:\s*[\/\-]\s*\d+(?:\.\d+)?)*)', rest)
    if mic_val_match:
        mic = mic_val_match.group(1).replace(' ', '')
        if mic_sign is None:
            mic_sign = '='
            notes = "mic_sign '=' inferred"
    elif sir_call is None and rest.upper() in {'S', 'I', 'R', 'SDD', 'NS'}:
        sir_call = rest.upper()

    if mic is None and sir_call is None:
        return None, None, None, None

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """Transform AST sheet into standardized long format with MIC and SIR values."""
    if df.empty:
        return pd.DataFrame(columns=['isolate_id', 'accession', 'drug', 'mic_sign', 'mic', 'sir_call', 'notes'])

    df = df.copy()

    # Step 1: Detect and handle subheader rows containing drug / MIC annotations
    if len(df) > 0:
        row0 = df.iloc[0]
        row0_strs = [str(x).strip() for x in row0 if pd.notna(x) and str(x).strip() != '']
        has_mic_header = any(
            re.search(r'\bmic\b|\bug\/ml\b|\bmg\/l\b|\bµg\/ml\b', s, re.I) or extract_drug(s) is not None
            for s in row0_strs
        )
        if has_mic_header:
            new_cols = []
            for i in range(len(df.columns)):
                top = str(df.columns[i]).strip()
                if top.lower().startswith('unnamed:'):
                    top = ''
                sub = str(df.iloc[0, i]).strip() if pd.notna(df.iloc[0, i]) else ''
                if sub.lower() in {'nan', 'none'}:
                    sub = ''
                
                if sub and top:
                    if re.search(r'\bmic\b|\bug\/ml\b|\bmg\/l\b', sub, re.I) or extract_drug(sub):
                        new_cols.append(sub)
                    else:
                        new_cols.append(f"{top} {sub}".strip())
                elif sub:
                    new_cols.append(sub)
                else:
                    new_cols.append(top)
            
            df.columns = new_cols
            df = df.iloc[1:].reset_index(drop=True)

    # Step 2: Identify drug testing columns
    drug_cols = {}
    for col in df.columns:
        drug_name = extract_drug(str(col))
        if drug_name:
            drug_cols[col] = drug_name

    non_drug_cols = [c for c in df.columns if c not in drug_cols]

    # Step 3: Identify accession column(s)
    accession_cols = []
    for col in non_drug_cols:
        col_str = str(col).lower()
        if 'accession' in col_str or 'biosample' in col_str or 'sra' in col_str or 'genbank' in col_str:
            accession_cols.append(col)
        else:
            # Check column content for repository accession patterns
            sample_vals = df[col].dropna().astype(str).head(10)
            if sample_vals.apply(lambda x: bool(ACCESSION_REGEX.search(x))).any():
                accession_cols.append(col)

    # Step 4: Identify isolate ID column
    candidate_id_cols = [c for c in non_drug_cols if c not in accession_cols]
    isolate_col = None

    id_keywords = re.compile(r'isolate|strain|sample|specimen|patient|pair|series|case|subject|identifier|id', re.I)
    for c in candidate_id_cols:
        if id_keywords.search(str(c)):
            isolate_col = c
            break

    # Fallback to the first available non-drug, non-accession column
    if isolate_col is None and candidate_id_cols:
        isolate_col = candidate_id_cols[0]

    # Clean and forward-fill isolate_id (handles vertically merged Excel cells in pairs/series)
    if isolate_col is not None:
        df[isolate_col] = (
            df[isolate_col]
            .astype(str)
            .str.strip()
            .replace('', np.nan)
            .replace('nan', np.nan)
            .replace('None', np.nan)
        )
        df[isolate_col] = df[isolate_col].ffill()
        df[isolate_col] = df[isolate_col].astype(str).str.strip(" '\",")
        df[isolate_col] = df[isolate_col].replace('nan', None).replace('None', None).replace('', None)

    # Step 5: Unpivot and parse AST measurements
    records = []
    for idx, row in df.iterrows():
        # Resolve isolate_id
        isolate_id = None
        if isolate_col is not None:
            val = row.get(isolate_col)
            if pd.notna(val) and str(val).strip() and str(val).strip().lower() not in {'nan', 'none'}:
                isolate_id = str(val).strip()

        # Resolve accession
        accessions_found = []
        for ac_col in accession_cols:
            val = row.get(ac_col)
            if pd.notna(val):
                matches = ACCESSION_REGEX.findall(str(val))
                accessions_found.extend(matches)
        accession_str = ','.join(dict.fromkeys(accessions_found)) if accessions_found else None

        # Parse AST drug measurements
        for col, drug_name in drug_cols.items():
            cell_val = row.get(col)
            mic_sign, mic, sir_call, notes = parse_mic_sir(cell_val)
            if mic is None and sir_call is None:
                continue

            records.append({
                'isolate_id': isolate_id,
                'accession': accession_str,
                'drug': drug_name,
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
# Transformation code for table: 'Table_2.tsv'
# ============================================================

import re
from typing import Optional
import numpy as np
import pandas as pd

PERMITTED_DRUGS = [
    "amoxicillin/clavulanic acid",
    "ampicillin",
    "antibiotic",
    "arbekacin",
    "azithromycin",
    "biapenem",
    "cefazolin",
    "cefoxitin",
    "ceftarolin",
    "ceftaroline",
    "chloramphenicol",
    "chlorhexidine gluconate",
    "ciprofloxacin",
    "clarithromycin",
    "clindamycin",
    "dalbavancin",
    "daptomycin",
    "doripenem",
    "erythromycin",
    "florfenicol",
    "fosfomycin",
    "fusidic acid",
    "gentamicin",
    "imipenem",
    "kanamycin",
    "levofloxacin",
    "linezolid",
    "meropenem",
    "methicillin",
    "minocycline",
    "moxifloxacin",
    "mupirocin",
    "norfloxacin",
    "oritavancin",
    "oxacillin",
    "penicillin",
    "phosphomycin",
    "quinupristin/dalfopristin",
    "rifampin",
    "streptomycin",
    "sulfamethoxazole/trimethoprim",
    "tedizolid",
    "teicoplanin",
    "telavancin",
    "tetracycline",
    "tiamulin",
    "tigecycline",
    "tobramycin",
    "trimethoprim",
    "trimethoprim/sulfamethoxazole",
    "trimethoprim/sulfonamide",
    "vancomycin",
]

DRUG_ABBREVIATIONS = {
    "dp": "daptomycin",
    "dap": "daptomycin",
    "dapto": "daptomycin",
    "vn": "vancomycin",
    "van": "vancomycin",
    "va": "vancomycin",
    "vanc": "vancomycin",
    "vanco": "vancomycin",
    "lnz": "linezolid",
    "lzd": "linezolid",
    "cip": "ciprofloxacin",
    "cpx": "ciprofloxacin",
    "ery": "erythromycin",
    "erm": "erythromycin",
    "cli": "clindamycin",
    "cln": "clindamycin",
    "cc": "clindamycin",
    "cd": "clindamycin",
    "gen": "gentamicin",
    "gm": "gentamicin",
    "cn": "gentamicin",
    "oxa": "oxacillin",
    "ox": "oxacillin",
    "pen": "penicillin",
    "rif": "rifampin",
    "ra": "rifampin",
    "rifa": "rifampin",
    "tet": "tetracycline",
    "te": "tetracycline",
    "tcy": "tetracycline",
    "tgc": "tigecycline",
    "tg": "tigecycline",
    "cpt": "ceftaroline",
    "cft": "ceftaroline",
    "cfz": "cefazolin",
    "cz": "cefazolin",
    "kz": "cefazolin",
    "fox": "cefoxitin",
    "cxt": "cefoxitin",
    "sxt": "trimethoprim/sulfamethoxazole",
    "stx": "trimethoprim/sulfamethoxazole",
    "cot": "trimethoprim/sulfamethoxazole",
    "tmp": "trimethoprim",
    "tob": "tobramycin",
    "tobra": "tobramycin",
    "min": "minocycline",
    "mino": "minocycline",
    "mxf": "moxifloxacin",
    "moxi": "moxifloxacin",
    "lvx": "levofloxacin",
    "levo": "levofloxacin",
    "amp": "ampicillin",
    "amc": "amoxicillin/clavulanic acid",
    "aug": "amoxicillin/clavulanic acid",
    "bpm": "biapenem",
    "ipm": "imipenem",
    "imp": "imipenem",
    "imi": "imipenem",
    "mem": "meropenem",
    "mer": "meropenem",
    "mero": "meropenem",
    "dor": "doripenem",
    "dal": "dalbavancin",
    "ori": "oritavancin",
    "tel": "telavancin",
    "tec": "teicoplanin",
    "teic": "teicoplanin",
    "tdz": "tedizolid",
    "tzd": "tedizolid",
    "fa": "fusidic acid",
    "fd": "fusidic acid",
    "fus": "fusidic acid",
    "mup": "mupirocin",
    "chx": "chlorhexidine gluconate",
    "qd": "quinupristin/dalfopristin",
    "syn": "quinupristin/dalfopristin",
    "fos": "fosfomycin",
    "chl": "chloramphenicol",
    "cam": "chloramphenicol",
    "kan": "kanamycin",
    "str": "streptomycin",
    "abk": "arbekacin",
    "azm": "azithromycin",
    "azi": "azithromycin",
    "clr": "clarithromycin",
    "cla": "clarithromycin",
    "ffc": "florfenicol",
    "nor": "norfloxacin",
    "met": "methicillin",
    "tia": "tiamulin",
}


def _is_header_row(series: pd.Series) -> bool:
    text = " ".join(series.dropna().astype(str).str.lower())
    header_keywords = [
        "mic",
        "ug/ml",
        "mg/l",
        "µg/ml",
        "breakpoint",
        "sir",
        "interpretation",
        "susceptibility",
        "disc",
        "disk",
    ]
    return any(kw in text for kw in header_keywords)


def _identify_drug(col_name: str) -> Optional[str]:
    col_lower = str(col_name).strip().lower()

    multi_word_drugs = [
        "amoxicillin/clavulanic acid",
        "sulfamethoxazole/trimethoprim",
        "trimethoprim/sulfamethoxazole",
        "trimethoprim/sulfonamide",
        "quinupristin/dalfopristin",
        "fusidic acid",
        "chlorhexidine gluconate",
    ]
    for d in multi_word_drugs:
        pattern = (
            re.escape(d).replace(r"\/", r"[\/\s\-]").replace(r"\ ", r"[\s\-]")
        )
        if re.search(r"\b" + pattern + r"\b", col_lower):
            return d

    for d in PERMITTED_DRUGS:
        if d in multi_word_drugs or d == "antibiotic":
            continue
        if re.search(r"\b" + re.escape(d) + r"\b", col_lower):
            return d

    tokens = re.findall(r"[a-zA-Z]+", col_lower)
    for tok in tokens:
        if tok in DRUG_ABBREVIATIONS:
            return DRUG_ABBREVIATIONS[tok]

    if re.search(r"\bantibiotic\b", col_lower):
        if not re.search(
            r"\b(susceptibility|sensitivity|profile|testing|table)\b", col_lower
        ):
            return "antibiotic"

    return None


def _parse_ast_values(mic_raw, sir_raw=None):
    mic_sign = None
    mic = None
    sir_call = None
    notes = None

    if sir_raw is not None and pd.notna(sir_raw):
        s_str = str(sir_raw).strip().upper()
        if s_str in ["S", "SUSCEPTIBLE", "SENSITIVE"]:
            sir_call = "S"
        elif s_str in ["I", "INTERMEDIATE"]:
            sir_call = "I"
        elif s_str in ["R", "RESISTANT"]:
            sir_call = "R"
        elif s_str in ["SDD", "SUSCEPTIBLE-DOSE DEPENDENT"]:
            sir_call = "SDD"
        elif s_str in ["NS", "NON-SUSCEPTIBLE"]:
            sir_call = "NS"

    if mic_raw is not None and pd.notna(mic_raw):
        if isinstance(mic_raw, float) and mic_raw.is_integer():
            val_str = str(int(mic_raw))
        else:
            val_str = str(mic_raw).strip()

        if val_str.lower() not in [
            "nd",
            "n/a",
            "na",
            "-",
            ".",
            "",
            "none",
            "nan",
            "neg",
            "nt",
        ]:
            if not sir_call:
                paren_m = re.search(
                    r"[\(\[\{]([SIR]|SDD|NS|Susceptible|Intermediate|Resistant|Non-susceptible)[\)\]\}]",
                    val_str,
                    re.IGNORECASE,
                )
                if paren_m:
                    raw_s = paren_m.group(1).upper()
                    if raw_s.startswith("SUSC") or raw_s == "S":
                        sir_call = "S"
                    elif raw_s.startswith("INT") or raw_s == "I":
                        sir_call = "I"
                    elif raw_s.startswith("RES") or raw_s == "R":
                        sir_call = "R"
                    elif raw_s == "SDD":
                        sir_call = "SDD"
                    elif raw_s.startswith("NON") or raw_s == "NS":
                        sir_call = "NS"
                    val_str = re.sub(
                        r"[\(\[\{][^\)\]\}]+[\)\]\}]", "", val_str
                    ).strip()
                elif val_str.lower() in ["s", "susceptible", "sensitive"]:
                    sir_call = "S"
                    val_str = ""
                elif val_str.lower() in ["i", "intermediate"]:
                    sir_call = "I"
                    val_str = ""
                elif val_str.lower() in ["r", "resistant"]:
                    sir_call = "R"
                    val_str = ""
                elif val_str.lower() in ["sdd"]:
                    sir_call = "SDD"
                    val_str = ""
                elif val_str.lower() in ["ns", "non-susceptible"]:
                    sir_call = "NS"
                    val_str = ""
                else:
                    trail_m = re.search(
                        r"\s+([SIR]|SDD|NS)$", val_str, re.IGNORECASE
                    )
                    if trail_m:
                        raw_s = trail_m.group(1).upper()
                        sir_call = raw_s
                        val_str = val_str[: trail_m.start()].strip()

            mic_m = re.search(
                r"(<=|>=|<|>|=)?\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)",
                val_str,
            )
            if mic_m:
                sign = mic_m.group(1)
                num = mic_m.group(2).replace(" ", "")
                if sign:
                    mic_sign = sign
                    notes = None
                else:
                    mic_sign = "="
                    notes = "mic_sign '=' inferred"
                mic = num

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "isolate_id",
                "accession",
                "drug",
                "mic_sign",
                "mic",
                "sir_call",
                "notes",
            ]
        )

    working_df = df.copy()

    # Detect and collapse multi-row headers
    while len(working_df) > 0 and _is_header_row(working_df.iloc[0]):
        sub_row = working_df.iloc[0]
        new_cols = []
        for c, h in zip(working_df.columns, sub_row):
            c_str = (
                str(c).strip()
                if pd.notna(c) and not str(c).lower().startswith("unnamed")
                else ""
            )
            h_str = str(h).strip() if pd.notna(h) else ""
            if h_str.lower() in ["nan", "none"]:
                h_str = ""

            if c_str and h_str:
                new_cols.append(f"{c_str} - {h_str}")
            elif h_str:
                new_cols.append(h_str)
            else:
                new_cols.append(c_str)

        working_df.columns = new_cols
        if isinstance(working_df.index, pd.RangeIndex):
            working_df = working_df.iloc[1:].reset_index(drop=True)
        else:
            working_df = working_df.iloc[1:]

    # Identify drug vs non-drug columns
    drug_columns = {}
    non_drug_cols = []

    for col in working_df.columns:
        drug = _identify_drug(col)
        if drug:
            is_sir = bool(
                re.search(
                    r"\b(sir|interp|interpretation|category|call)\b",
                    str(col).lower(),
                )
            )
            if drug not in drug_columns:
                drug_columns[drug] = {"mic": None, "sir": None}
            if is_sir:
                drug_columns[drug]["sir"] = col
            else:
                drug_columns[drug]["mic"] = col
        else:
            non_drug_cols.append(col)

    # Isolate ID detection
    isolate_col = None
    for c in non_drug_cols:
        c_lower = str(c).lower()
        if any(
            re.search(r"\b" + re.escape(kw) + r"\b", c_lower)
            for kw in ["isolate", "strain", "specimen", "sample", "patient"]
        ):
            isolate_col = c
            break
    if not isolate_col:
        for c in non_drug_cols:
            if str(c).lower() in ["id", "isolate_id", "strain_id", "sample_id"]:
                isolate_col = c
                break

    use_index_for_isolate = False
    if (
        not isolate_col
        and not isinstance(working_df.index, pd.RangeIndex)
        and working_df.index.notna().any()
    ):
        idx_strs = [str(x).strip() for x in working_df.index if pd.notna(x)]
        if idx_strs and not all(x.isdigit() for x in idx_strs):
            use_index_for_isolate = True

    # Public repository accession detection
    acc_regex = re.compile(
        r"\b(SAM[NED][A-Z]?\d+|[EDS]RR\d+|[EDS]RS\d+|[EDS]RX\d+|GC[AF]_\d+\.\d+)\b",
        re.IGNORECASE,
    )
    acc_cols = []
    for c in non_drug_cols:
        c_lower = str(c).lower()
        if any(
            k in c_lower
            for k in [
                "accession",
                "biosample",
                "bioproject",
                "sra",
                "genbank",
                "ena",
            ]
        ):
            acc_cols.append(c)
        else:
            sample_vals = working_df[c].dropna().astype(str).head(10)
            if any(acc_regex.search(v) for v in sample_vals):
                acc_cols.append(c)

    # Transform records
    rows = []
    for idx, row in working_df.iterrows():
        # Resolve isolate_id
        if isolate_col and pd.notna(row[isolate_col]):
            iso_val = str(row[isolate_col]).strip()
            isolate_id = iso_val if iso_val else None
        elif use_index_for_isolate and pd.notna(idx):
            iso_val = str(idx).strip()
            isolate_id = iso_val if iso_val else None
        else:
            isolate_id = None

        # Resolve public accession
        found_accessions = []
        for ac in acc_cols:
            val = row[ac]
            if pd.notna(val):
                matches = acc_regex.findall(str(val))
                for m in matches:
                    if m not in found_accessions:
                        found_accessions.append(m)
        accession = ",".join(found_accessions) if found_accessions else None

        # Extract per drug
        for drug, col_pair in drug_columns.items():
            mic_col = col_pair["mic"]
            sir_col = col_pair["sir"]

            mic_raw = row[mic_col] if mic_col else None
            sir_raw = row[sir_col] if sir_col else None

            mic_sign, mic, sir_call, notes = _parse_ast_values(mic_raw, sir_raw)

            if mic is None and sir_call is None:
                continue

            rows.append(
                {
                    "isolate_id": isolate_id,
                    "accession": accession,
                    "drug": drug,
                    "mic_sign": mic_sign,
                    "mic": mic,
                    "sir_call": sir_call,
                    "notes": notes,
                }
            )

    result_df = pd.DataFrame(
        rows,
        columns=[
            "isolate_id",
            "accession",
            "drug",
            "mic_sign",
            "mic",
            "sir_call",
            "notes",
        ],
    )
    return result_df

