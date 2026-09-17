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

SYNONYMS = {
    'amc': 'amoxicillin/clavulanic acid',
    'amx/clv': 'amoxicillin/clavulanic acid',
    'amoxicillin-clavulanic acid': 'amoxicillin/clavulanic acid',
    'amoxicillin-clavulanate': 'amoxicillin/clavulanic acid',
    'amoxicillin/clavulanate': 'amoxicillin/clavulanic acid',
    'augmentin': 'amoxicillin/clavulanic acid',
    'amp': 'ampicillin',
    'abk': 'arbekacin',
    'azm': 'azithromycin',
    'azithro': 'azithromycin',
    'bip': 'biapenem',
    'cfz': 'cefazolin',
    'cz': 'cefazolin',
    'czo': 'cefazolin',
    'fox': 'cefoxitin',
    'cpt': 'ceftaroline',
    'chl': 'chloramphenicol',
    'chg': 'chlorhexidine gluconate',
    'cip': 'ciprofloxacin',
    'cpfx': 'ciprofloxacin',
    'clr': 'clarithromycin',
    'cam': 'clarithromycin',
    'cla': 'clarithromycin',
    'cli': 'clindamycin',
    'cldm': 'clindamycin',
    'cc': 'clindamycin',
    'cd': 'clindamycin',
    'dal': 'dalbavancin',
    'dap': 'daptomycin',
    'dapto': 'daptomycin',
    'dor': 'doripenem',
    'ery': 'erythromycin',
    'em': 'erythromycin',
    'e': 'erythromycin',
    'ffc': 'florfenicol',
    'fos': 'fosfomycin',
    'fom': 'fosfomycin',
    'fa': 'fusidic acid',
    'fd': 'fusidic acid',
    'fusidate': 'fusidic acid',
    'gen': 'gentamicin',
    'gm': 'gentamicin',
    'cn': 'gentamicin',
    'genta': 'gentamicin',
    'ipm': 'imipenem',
    'imi': 'imipenem',
    'kan': 'kanamycin',
    'k': 'kanamycin',
    'lvx': 'levofloxacin',
    'lev': 'levofloxacin',
    'lvfx': 'levofloxacin',
    'lnz': 'linezolid',
    'lzd': 'linezolid',
    'mem': 'meropenem',
    'mer': 'meropenem',
    'met': 'methicillin',
    'me': 'methicillin',
    'min': 'minocycline',
    'mino': 'minocycline',
    'mxf': 'moxifloxacin',
    'mox': 'moxifloxacin',
    'mup': 'mupirocin',
    'nor': 'norfloxacin',
    'ori': 'oritavancin',
    'oxa': 'oxacillin',
    'ox': 'oxacillin',
    'pen': 'penicillin',
    'p': 'penicillin',
    'pcg': 'penicillin',
    'qpr/dpr': 'quinupristin/dalfopristin',
    'q/d': 'quinupristin/dalfopristin',
    'qd': 'quinupristin/dalfopristin',
    'synercid': 'quinupristin/dalfopristin',
    'rif': 'rifampin',
    'rifampicin': 'rifampin',
    'rfp': 'rifampin',
    'ra': 'rifampin',
    'str': 'streptomycin',
    's': 'streptomycin',
    'sxt': 'trimethoprim/sulfamethoxazole',
    'st': 'trimethoprim/sulfamethoxazole',
    's/t': 'trimethoprim/sulfamethoxazole',
    'tmp/smx': 'trimethoprim/sulfamethoxazole',
    'smx/tmp': 'trimethoprim/sulfamethoxazole',
    'cotrimoxazole': 'trimethoprim/sulfamethoxazole',
    'co-trimoxazole': 'trimethoprim/sulfamethoxazole',
    'ted': 'tedizolid',
    'tzd': 'tedizolid',
    'tec': 'teicoplanin',
    'teic': 'teicoplanin',
    'tlv': 'telavancin',
    'tet': 'tetracycline',
    'tc': 'tetracycline',
    'te': 'tetracycline',
    'tia': 'tiamulin',
    'tgc': 'tigecycline',
    'tig': 'tigecycline',
    'tob': 'tobramycin',
    'to': 'tobramycin',
    'nn': 'tobramycin',
    'tmp': 'trimethoprim',
    'van': 'vancomycin',
    'vcm': 'vancomycin',
    'va': 'vancomycin',
    'v': 'vancomycin',
}

DRUG_MAP = {d.lower(): d for d in PERMITTED_DRUGS}
DRUG_MAP.update(SYNONYMS)


def clean_header(name: str) -> str:
    s = str(name).strip()
    s = re.sub(
        r'[\(\[]?\s*(?:μg|ug|mg)\s*/\s*(?:ml|l)\s*[\)\]]?',
        '',
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r'\bmic\b', '', s, flags=re.IGNORECASE)
    return s.strip()


def resolve_drug_column(name: str):
    cleaned = clean_header(name).lower()
    if not cleaned:
        return None

    if cleaned in DRUG_MAP:
        return [DRUG_MAP[cleaned]]

    if '/' in cleaned:
        parts = [p.strip() for p in cleaned.split('/')]
        resolved = [DRUG_MAP.get(p) for p in parts]
        if all(resolved):
            return resolved

    return None


def parse_mic_cell(val):
    if pd.isna(val):
        return None

    s = str(val).strip()
    if s.lower() in [
        '',
        'nan',
        'none',
        '-',
        '--',
        'nd',
        'na',
        'n/a',
        '.',
        'neg',
        'pos',
        'this study',
    ]:
        return None

    sir_call = None

    paren_match = re.search(
        r'[\(\[]\s*(SDD|NS|[SIR])\s*[\)\]]', s, re.IGNORECASE
    )
    if paren_match:
        sir_call = paren_match.group(1).upper()
        s = re.sub(
            r'[\(\[]\s*(?:SDD|NS|[SIR])\s*[\)\]]', '', s, flags=re.IGNORECASE
        ).strip()
    elif s.upper() in ['S', 'I', 'R', 'SDD', 'NS']:
        sir_call = s.upper()
        s = ''
    else:
        end_match = re.search(r'\s+(SDD|NS|[SIR])$', s, re.IGNORECASE)
        if end_match:
            sir_call = end_match.group(1).upper()
            s = s[: end_match.start()].strip()

    mic_sign = None
    mic = None
    notes = None

    if s:
        s_norm = s.replace('≤', '<=').replace('≥', '>=')
        m_mic = re.search(
            r'(<=|>=|<|>|=)?\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)', s_norm
        )
        if m_mic:
            sign_part = m_mic.group(1)
            num_part = re.sub(r'\s+', '', m_mic.group(2))
            mic = num_part
            if sign_part:
                mic_sign = sign_part
                notes = None
            else:
                mic_sign = '='
                notes = "mic_sign '=' inferred"

    if mic is None and sir_call is None:
        return None

    return {
        'mic_sign': mic_sign,
        'mic': mic,
        'sir_call': sir_call,
        'notes': notes,
    }


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

    working_df = df.copy()

    unnamed_count = sum(
        1 for c in working_df.columns if str(c).startswith('Unnamed:')
    )
    row0_vals = [
        str(x).strip() for x in working_df.iloc[0].values if pd.notna(x)
    ]
    row0_has_drugs = any(
        resolve_drug_column(v) is not None for v in row0_vals
    )
    col_has_drugs = any(
        resolve_drug_column(c) is not None for c in working_df.columns
    )

    if (
        unnamed_count >= len(working_df.columns) / 2 or row0_has_drugs
    ) and not col_has_drugs:
        new_cols = []
        for c, r0 in zip(working_df.columns, working_df.iloc[0]):
            r0_str = str(r0).strip() if pd.notna(r0) else ''
            if r0_str and r0_str.lower() not in ['nan', 'none']:
                new_cols.append(r0_str)
            else:
                new_cols.append(str(c))
        working_df = working_df.iloc[1:].copy()
        working_df.columns = new_cols

    isolate_col = None
    accession_col = None

    for col in working_df.columns:
        c_clean = str(col).strip().lower()
        if not isolate_col and re.match(
            r'^(isolate|sample|strain|specimen|patient|patient[_\s]?isolate|id|no\.?|isolate[_\s]?id|sample[_\s]?id)$',
            c_clean,
        ):
            isolate_col = col
        if not accession_col and re.search(
            r'accession|biosample|sra|genbank', c_clean
        ):
            accession_col = col

    drug_col_map = {}
    for col in working_df.columns:
        if col in (isolate_col, accession_col):
            continue
        resolved = resolve_drug_column(col)
        if resolved:
            drug_col_map[col] = resolved

    records = []

    for row_idx, (idx, row) in enumerate(working_df.iterrows()):
        isolate_id = None
        if isolate_col and pd.notna(row[isolate_col]):
            val_str = str(row[isolate_col]).strip()
            if val_str and val_str.lower() not in ['nan', 'none']:
                if re.match(r'^\d+\.0$', val_str):
                    val_str = val_str[:-2]
                isolate_id = val_str

        if not isolate_id and pd.notna(idx):
            idx_str = str(idx).strip()
            if idx_str and idx_str.lower() not in ['nan', 'none']:
                if re.match(r'^\d+\.0$', idx_str):
                    idx_str = idx_str[:-2]
                isolate_id = idx_str

        if not isolate_id:
            isolate_id = f'isolate_{row_idx + 1}'

        accession = None
        if accession_col and pd.notna(row[accession_col]):
            text = str(row[accession_col]).strip()
            found = re.findall(
                r'\b(?:SAMN\d+|SAMEA\d+|SAMD\d+|SRS\d+|GCA_\d+\.\d+|GCF_\d+\.\d+|[ESD]RR\d+)\b',
                text,
            )
            if found:
                accession = ','.join(dict.fromkeys(found))

        for col, drugs in drug_col_map.items():
            cell_val = row[col]
            if pd.isna(cell_val):
                continue

            cell_str = str(cell_val).strip()
            if cell_str.lower() in [
                '',
                'nan',
                'none',
                '-',
                '--',
                'nd',
                'na',
                'n/a',
                '.',
                'this study',
            ]:
                continue

            if len(drugs) > 1 and '/' in cell_str:
                parts = [p.strip() for p in cell_str.split('/')]
                if len(parts) == len(drugs):
                    for d_name, p_val in zip(drugs, parts):
                        parsed = parse_mic_cell(p_val)
                        if parsed:
                            records.append(
                                {
                                    'isolate_id': isolate_id,
                                    'accession': accession,
                                    'drug': d_name,
                                    'mic_sign': parsed['mic_sign'],
                                    'mic': parsed['mic'],
                                    'sir_call': parsed['sir_call'],
                                    'notes': parsed['notes'],
                                }
                            )
                    continue

            for d_name in drugs:
                parsed = parse_mic_cell(cell_str)
                if parsed:
                    records.append(
                        {
                            'isolate_id': isolate_id,
                            'accession': accession,
                            'drug': d_name,
                            'mic_sign': parsed['mic_sign'],
                            'mic': parsed['mic'],
                            'sir_call': parsed['sir_call'],
                            'notes': parsed['notes'],
                        }
                    )

    out_df = pd.DataFrame(
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
    return out_df

