# ==========================================================
# Transformation Code for Sheet: 'Table_2.XLSX::PATRIC'
# ==========================================================

import re
import numpy as np
import pandas as pd

# Standard permitted drugs list
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

# Common abbreviations mapping to permitted drug names
DRUG_ABBREVIATIONS = {
    "amc": "amoxicillin/clavulanic acid",
    "amp": "ampicillin",
    "azm": "azithromycin",
    "cfz": "cefazolin",
    "fox": "cefoxitin",
    "cpt": "ceftaroline",
    "chl": "chloramphenicol",
    "cip": "ciprofloxacin",
    "clr": "clarithromycin",
    "cli": "clindamycin",
    "dal": "dalbavancin",
    "dap": "daptomycin",
    "dor": "doripenem",
    "ery": "erythromycin",
    "ffc": "florfenicol",
    "fos": "fosfomycin",
    "fuc": "fusidic acid",
    "gen": "gentamicin",
    "ipm": "imipenem",
    "kan": "kanamycin",
    "lfx": "levofloxacin",
    "lev": "levofloxacin",
    "lnz": "linezolid",
    "mem": "meropenem",
    "met": "methicillin",
    "min": "minocycline",
    "mfx": "moxifloxacin",
    "mup": "mupirocin",
    "nor": "norfloxacin",
    "ori": "oritavancin",
    "oxa": "oxacillin",
    "pen": "penicillin",
    "qda": "quinupristin/dalfopristin",
    "rif": "rifampin",
    "str": "streptomycin",
    "sxt": "trimethoprim/sulfamethoxazole",
    "tzd": "tedizolid",
    "tec": "teicoplanin",
    "tlv": "telavancin",
    "tet": "tetracycline",
    "tia": "tiamulin",
    "tgc": "tigecycline",
    "tob": "tobramycin",
    "tmp": "trimethoprim",
    "van": "vancomycin",
}


def _match_drug_name(col_name: str):
    """Matches a column header to a permitted drug name or returns None."""
    cleaned = col_name.strip().lower()

    # Direct permitted match
    for drug in PERMITTED_DRUGS:
        if cleaned == drug:
            return drug

    # Check common abbreviations
    if cleaned in DRUG_ABBREVIATIONS:
        return DRUG_ABBREVIATIONS[cleaned]

    # Remove common suffixes/modifiers like 'resistance', 'susceptibility', 'mic', etc.
    stripped = re.sub(
        r"\b(resistance|resistant|susceptibility|susceptible|mic|sir|zone|disk|disc)\b",
        "",
        cleaned,
    ).strip()
    stripped = re.sub(r"[\(\)\[\]_,\.\-:]", " ", stripped).strip()
    stripped = " ".join(stripped.split())

    if stripped in DRUG_ABBREVIATIONS:
        return DRUG_ABBREVIATIONS[stripped]

    for drug in PERMITTED_DRUGS:
        if stripped == drug:
            return drug

    # Substring search if word boundaries match
    for drug in sorted(PERMITTED_DRUGS, key=lambda x: -len(x)):
        if re.search(r"\b" + re.escape(drug) + r"\b", cleaned):
            return drug

    return None


def _parse_cell_value(val, col_name: str):
    """Parses cell value into mic_sign, mic, sir_call, notes."""
    if pd.isna(val):
        return None, None, None, None

    s = str(val).strip()
    if s == "" or s.upper() in {"ND", "N/A", "NA", "-", "NOT DETERMINED", "."}:
        return None, None, None, None

    mic_sign = None
    mic = None
    sir_call = None
    notes = None

    # Check for resistance indicator in column name (e.g. 'Linezolid Resistance' -> Yes=R, No=S)
    is_res_col = bool(re.search(r"\b(resist|resistance|resistant)\b", col_name, re.I))
    is_susc_col = bool(
        re.search(r"\b(suscept|susceptibility|susceptible)\b", col_name, re.I)
    )

    s_upper = s.upper()

    # Handle Yes / No / Positive / Negative calls
    if s_upper in {"YES", "Y", "POS", "POSITIVE", "+", "R"}:
        if is_res_col or s_upper in {"R"}:
            sir_call = "R"
        elif is_susc_col:
            sir_call = "S"
    elif s_upper in {"NO", "N", "NEG", "NEGATIVE", "S"}:
        if is_res_col or s_upper in {"S"}:
            sir_call = "S"
        elif is_susc_col:
            sir_call = "R"
    elif s_upper in {"I", "INTERMEDIATE"}:
        sir_call = "I"
    elif s_upper in {"SDD"}:
        sir_call = "SDD"
    elif s_upper in {"NS", "NON-SUSCEPTIBLE"}:
        sir_call = "NS"

    # Check for embedded SIR in parentheses, e.g., "4 (R)" or "32 [S]"
    sir_match = re.search(r"[\(\[\{]([SIR]|SDD|NS)[\)\]\}]", s, re.I)
    if sir_match:
        sir_call = sir_match.group(1).upper()
        s = re.sub(r"[\(\[\{][a-zA-Z\s]+[\)\]\}]", "", s).strip()

    # Check for MIC patterns like '<=0.5', '> 32', '32/16', '0.25', etc.
    mic_match = re.search(
        r"(<=|>=|<|>|=)?\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)", s
    )
    if mic_match:
        sign, val_str = mic_match.groups()
        val_str = re.sub(r"\s+", "", val_str)  # normalize ratio spacing '32 / 16' -> '32/16'
        mic = val_str
        if sign:
            mic_sign = sign
        else:
            mic_sign = "="
            notes = "mic_sign '=' inferred"

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """Transforms AST worksheet into standardized unpivoted format."""
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

    # 1. Identify isolate_id column
    isolate_col = None
    candidate_isolate_cols = [
        "strain",
        "isolate",
        "isolate id",
        "isolate_id",
        "sample id",
        "sample_id",
        "specimen number",
        "specimen id",
        "genome name",
    ]
    col_map_lower = {col.lower().strip(): col for col in df.columns}
    for cand in candidate_isolate_cols:
        if cand in col_map_lower:
            isolate_col = col_map_lower[cand]
            break

    # 2. Identify public accession columns
    accession_cols = [
        col
        for col in df.columns
        if "accession" in col.lower()
        and col != isolate_col
    ]

    def build_accession(row):
        accs = []
        for col in accession_cols:
            val = row[col]
            if pd.notna(val):
                val_str = str(val).strip()
                if (
                    val_str
                    and val_str.upper() not in {"ND", "N/A", "NA", "-", "NONE"}
                ):
                    # In case multiple accessions are in one cell
                    parts = re.split(r"[,;\s]+", val_str)
                    for p in parts:
                        p_clean = p.strip()
                        if p_clean and p_clean not in accs:
                            accs.append(p_clean)
        return ",".join(accs) if accs else None

    # Pre-extract accessions for all rows
    if accession_cols:
        accession_series = df.apply(build_accession, axis=1)
    else:
        accession_series = pd.Series([None] * len(df), index=df.index)

    # 3. Identify drug columns and map to permitted drug names
    drug_cols = {}
    for col in df.columns:
        if col == isolate_col or col in accession_cols:
            continue
        mapped_drug = _match_drug_name(col)
        if mapped_drug:
            drug_cols[col] = mapped_drug

    # If no drug columns identified, return empty DataFrame schema
    if not drug_cols:
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

    # 4. Unpivot and parse
    records = []
    for idx, row in df.iterrows():
        isolate_id = str(row[isolate_col]).strip() if isolate_col and pd.notna(row[isolate_col]) else None
        if isolate_id and isolate_id.upper() in {"ND", "N/A", "NA", ""}:
            isolate_id = None

        acc = accession_series.loc[idx]

        for col, drug in drug_cols.items():
            cell_val = row[col]
            mic_sign, mic, sir_call, notes = _parse_cell_value(cell_val, col)

            # Discard rows where BOTH mic and sir_call are empty/missing
            if mic is None and sir_call is None:
                continue

            records.append(
                {
                    "isolate_id": isolate_id,
                    "accession": acc,
                    "drug": drug,
                    "mic_sign": mic_sign,
                    "mic": mic,
                    "sir_call": sir_call,
                    "notes": notes,
                }
            )

    result_df = pd.DataFrame(
        records,
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

# ==========================================================
# Transformation Code for Sheet: 'Table_4.XLSX::Лист1'
# ==========================================================

import re
import numpy as np
import pandas as pd

PERMITTED_DRUGS = {
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
}

DRUG_NAME_MAP = {
    'oxa': 'oxacillin',
    'fox': 'cefoxitin',
    'lnz': 'linezolid',
    'tdz': 'tedizolid',
    'van': 'vancomycin',
    'ori': 'oritavancin',
    'dal': 'dalbavancin',
    'tlv': 'telavancin',
    'tec': 'teicoplanin',
    'dap': 'daptomycin',
    'tgc': 'tigecycline',
    'tet': 'tetracycline',
    'cpt': 'ceftaroline',
    'rif': 'rifampin',
    'cip': 'ciprofloxacin',
    'mxf': 'moxifloxacin',
    'gen': 'gentamicin',
    'mup': 'mupirocin',
    'fus': 'fusidic acid',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'ery': 'erythromycin',
    'cli': 'clindamycin',
    'amc': 'amoxicillin/clavulanic acid',
    'aug': 'amoxicillin/clavulanic acid',
    'amp': 'ampicillin',
    'abk': 'arbekacin',
    'azm': 'azithromycin',
    'bpm': 'biapenem',
    'cfz': 'cefazolin',
    'czo': 'cefazolin',
    'chl': 'chloramphenicol',
    'clr': 'clarithromycin',
    'dor': 'doripenem',
    'ffc': 'florfenicol',
    'fof': 'fosfomycin',
    'fos': 'fosfomycin',
    'ipm': 'imipenem',
    'imi': 'imipenem',
    'kan': 'kanamycin',
    'lvx': 'levofloxacin',
    'lev': 'levofloxacin',
    'mem': 'meropenem',
    'mer': 'meropenem',
    'met': 'methicillin',
    'min': 'minocycline',
    'nor': 'norfloxacin',
    'pen': 'penicillin',
    'qda': 'quinupristin/dalfopristin',
    'str': 'streptomycin',
    'tob': 'tobramycin',
    'tmp': 'trimethoprim',
}

ACCESSION_PATTERN = re.compile(
    r'\b(SAM[NED][A-Za-z0-9]+|PRJ[NED][A-Za-z0-9]+|[ESD]R[RPXSA]\d+|GC[AF]_\d+(?:\.\d+)?)\b'
)


def _resolve_drug_name(col_name: str) -> str | None:
    cleaned = col_name.strip().lower()

    if cleaned in PERMITTED_DRUGS:
        return cleaned

    if cleaned in DRUG_NAME_MAP:
        mapped = DRUG_NAME_MAP[cleaned]
        if mapped in PERMITTED_DRUGS:
            return mapped

    cleaned_alpha = re.sub(r'[^a-z0-9/]', '', cleaned)
    if cleaned_alpha in DRUG_NAME_MAP:
        mapped = DRUG_NAME_MAP[cleaned_alpha]
        if mapped in PERMITTED_DRUGS:
            return mapped

    for drug in PERMITTED_DRUGS:
        pattern = r'\b' + re.escape(drug) + r'\b'
        if re.search(pattern, cleaned):
            return drug

    return None


def _parse_cell(val) -> tuple[str | None, str | None, str | None, str | None]:
    if val is None or pd.isna(val):
        return None, None, None, None

    s = str(val).strip()
    if not s or s.upper() in {'ND', 'N/A', 'NA', '-', '.', 'NEG', 'POS'}:
        return None, None, None, None

    sir_call = None
    sir_match = re.search(
        r'(?:\((S|I|R|SDD|NS)\)|\b(S|I|R|SDD|NS)\b|'
        r'\b(SUSCEPTIBLE|INTERMEDIATE|RESISTANT|NON-SUSCEPTIBLE)\b)',
        s,
        re.IGNORECASE,
    )
    if sir_match:
        matched_str = (
            sir_match.group(1) or sir_match.group(2) or sir_match.group(3)
        ).upper()
        norm_map = {
            'SUSCEPTIBLE': 'S',
            'INTERMEDIATE': 'I',
            'RESISTANT': 'R',
            'NON-SUSCEPTIBLE': 'NS',
        }
        sir_call = norm_map.get(matched_str, matched_str)

    clean_s = re.sub(
        r'\(?(?:SUSCEPTIBLE|INTERMEDIATE|RESISTANT|NON-SUSCEPTIBLE|SDD|NS|[SIR])\)?',
        '',
        s,
        flags=re.IGNORECASE,
    ).strip()

    mic = None
    mic_sign = None
    notes = None

    mic_match = re.search(
        r'(<=|>=|[<>=])?\s*([0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+(?:\.[0-9]+)?)*)',
        clean_s,
    )
    if mic_match:
        explicit_sign = mic_match.group(1)
        raw_mic = mic_match.group(2)

        if raw_mic:
            mic = re.sub(r'\s+', '', raw_mic)
            if explicit_sign:
                mic_sign = explicit_sign
            else:
                mic_sign = '='
                notes = "mic_sign '=' inferred"

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    output_cols = [
        'isolate_id',
        'accession',
        'drug',
        'mic_sign',
        'mic',
        'sir_call',
        'notes',
    ]
    if df.empty:
        return pd.DataFrame(columns=output_cols)

    isolate_col = None
    isolate_candidates = ['isolate', 'specimen', 'sample', 'strain', 'id']
    for cand in isolate_candidates:
        for col in df.columns:
            cleaned_col = str(col).strip().lower()
            if cleaned_col == cand or cleaned_col == f'{cand}_id' or cleaned_col == f'{cand} id':
                isolate_col = col
                break
        if isolate_col:
            break

    if not isolate_col:
        for cand in isolate_candidates:
            for col in df.columns:
                if cand in str(col).strip().lower():
                    isolate_col = col
                    break
            if isolate_col:
                break

    acc_keywords = ['accession', 'biosample', 'sra', 'bioproject', 'genbank', 'assembly', 'run']
    acc_cols = [
        col for col in df.columns
        if col != isolate_col and any(k in str(col).strip().lower() for k in acc_keywords)
    ]

    drug_col_map = {}
    for col in df.columns:
        if col == isolate_col or col in acc_cols:
            continue
        standardized_name = _resolve_drug_name(str(col))
        if standardized_name:
            drug_col_map[col] = standardized_name

    records = []
    for idx, row in df.iterrows():
        isolate_id = str(row[isolate_col]).strip() if isolate_col and pd.notna(row[isolate_col]) else None
        if isolate_id == '':
            isolate_id = None

        found_accessions = []
        for ac_col in acc_cols:
            val = row[ac_col]
            if pd.notna(val):
                for match in ACCESSION_PATTERN.findall(str(val)):
                    if match not in found_accessions:
                        found_accessions.append(match)

        accession = ','.join(found_accessions) if found_accessions else None

        for col, drug in drug_col_map.items():
            mic_sign, mic, sir_call, notes = _parse_cell(row[col])
            if mic is None and sir_call is None:
                continue

            records.append({
                'isolate_id': isolate_id,
                'accession': accession,
                'drug': drug,
                'mic_sign': mic_sign,
                'mic': mic,
                'sir_call': sir_call,
                'notes': notes,
            })

    return pd.DataFrame(records, columns=output_cols)

# ==========================================================
# Transformation Code for Sheet: 'Table_1.XLSX::Лист1'
# ==========================================================

import re
import numpy as np
import pandas as pd


def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Extract mapping records between isolate identifiers and public database accessions.

    Returns a DataFrame with columns: ['isolate_id', 'accession',
    'secondary_accession'].
    """
    output_cols = ["isolate_id", "accession", "secondary_accession"]
    if df.empty:
        return pd.DataFrame(columns=output_cols)

    def clean_val(val):
        if pd.isna(val):
            return None
        s = str(val).strip()
        if s.lower() in {
            "",
            "nan",
            "none",
            "null",
            "na",
            "n/a",
            "-",
            ".",
            "not applicable",
        }:
            return None
        return s

    # 1. Identify isolate / sample ID column
    isolate_col = None
    isolate_patterns = [
        r"^(isolate[_\s]?id|strain[_\s]?id|sample[_\s]?id|cvm[_\s]?number|lab[_\s]?id)$",
        r"^(isolate|strain)$",
        r"^(sample)$",
        r"(isolate|strain)",
        r"(sample[_\s]?id|lab[_\s]?id)",
    ]
    for pat in isolate_patterns:
        for col in df.columns:
            col_clean = str(col).strip()
            if "biosample" in col_clean.lower():
                continue
            if re.search(pat, col_clean, re.IGNORECASE):
                isolate_col = col
                break
        if isolate_col is not None:
            break

    # 2. Identify accession columns
    biosample_cols = []
    secondary_cols = []
    generic_accession_cols = []

    biosample_regex = re.compile(
        r"^(SAM[NED][A-Z]?\d+|SRS\d+|ERS\d+|DRS\d+)", re.I
    )
    secondary_regex = re.compile(
        r"^([SED]R[RAXPUZ]\d+|PRJ[NED][A-Z]?\d+|GC[AF]_\d+\.\d+)", re.I
    )

    for col in df.columns:
        if col == isolate_col:
            continue
        c_str = str(col).strip().lower()

        if "biosample" in c_str:
            biosample_cols.append(col)
        elif any(
            k in c_str
            for k in ["sra", "bioproject", "run", "experiment", "assembly"]
        ):
            secondary_cols.append(col)
        elif "accession" in c_str:
            generic_accession_cols.append(col)
        else:
            # Check non-null values for known public repository prefixes
            sample_vals = [
                clean_val(v)
                for v in df[col].dropna().head(20)
                if clean_val(v) is not None
            ]
            if sample_vals:
                bio_match = sum(
                    bool(biosample_regex.match(v)) for v in sample_vals
                )
                sec_match = sum(
                    bool(secondary_regex.match(v)) for v in sample_vals
                )
                if bio_match / len(sample_vals) >= 0.5:
                    biosample_cols.append(col)
                elif sec_match / len(sample_vals) >= 0.5:
                    secondary_cols.append(col)

    all_acc_cols = []
    for c in biosample_cols + secondary_cols + generic_accession_cols:
        if c not in all_acc_cols:
            all_acc_cols.append(c)

    # 3. Extract and combine accessions per row
    records = []
    for _, row in df.iterrows():
        iso_id = clean_val(row[isolate_col]) if isolate_col is not None else None

        biosample_vals = []
        sec_vals = []

        for col in all_acc_cols:
            raw = clean_val(row[col])
            if not raw:
                continue
            # Split comma/semicolon delimited accession tokens
            tokens = [
                clean_val(t)
                for t in re.split(r"[,;]+", raw)
                if clean_val(t) is not None
            ]

            for tok in tokens:
                if col in biosample_cols or biosample_regex.match(tok):
                    biosample_vals.append(tok)
                else:
                    sec_vals.append(tok)

        # Deduplicate while preserving order
        biosample_vals = list(dict.fromkeys(biosample_vals))
        sec_vals = list(dict.fromkeys(sec_vals))

        combined_accs = list(dict.fromkeys(biosample_vals + sec_vals))

        accession = ",".join(combined_accs) if combined_accs else None
        secondary_accession = ",".join(sec_vals) if sec_vals else None

        # 4. Discard rows where BOTH isolate_id and accession are missing/blank
        if not iso_id and not accession:
            continue

        records.append(
            {
                "isolate_id": iso_id,
                "accession": accession,
                "secondary_accession": secondary_accession,
            }
        )

    return pd.DataFrame(records, columns=output_cols)

