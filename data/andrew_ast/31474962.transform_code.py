# ============================================================
# Transformation code for table: 'TABLE_1.tsv'
# ============================================================

import re
import numpy as np
import pandas as pd

# Permitted drug names strictly allowed in output
PERMITTED_DRUGS = {
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
}

# Mapping of abbreviations / column headers to standardized drug names
DRUG_NAME_MAP = {
    "van": "vancomycin",
    "teic": "teicoplanin",
    "dap": "daptomycin",
    "lzd": "linezolid",
    "lnz": "linezolid",
    "abk": "arbekacin",
    "oxa": "oxacillin",
    "amp": "ampicillin",
    "ipm": "imipenem",
    "mepm": "meropenem",
    "mem": "meropenem",
    "bipm": "biapenem",
    "drpm": "doripenem",
    "dor": "doripenem",
    "lvfx": "levofloxacin",
    "lfx": "levofloxacin",
    "cpfx": "ciprofloxacin",
    "cip": "ciprofloxacin",
    "mino": "minocycline",
    "min": "minocycline",
    "st": "trimethoprim/sulfamethoxazole",
    "sxt": "trimethoprim/sulfamethoxazole",
    "tmp/smx": "trimethoprim/sulfamethoxazole",
    "qpr/dpr": "quinupristin/dalfopristin",
    "qd": "quinupristin/dalfopristin",
    "quinupristin/dalfopristin": "quinupristin/dalfopristin",
    "erythromycin": "erythromycin",
    "clindamycin": "clindamycin",
}


def parse_mic_cell(val):
    """Parses a cell value into (mic_sign, mic, sir_call, notes)."""
    if pd.isna(val):
        return None, None, None, None

    val_str = str(val).strip()
    if not val_str or val_str.lower() in {
        "nan",
        "none",
        "nd",
        "n/a",
        "-",
        ".",
        "nr",
        "null",
    }:
        return None, None, None, None

    sir_call = None
    # Match standard SIR calls: (S), (I), (R), (SDD), (NS) or standalone/trailing
    sir_match = re.search(
        r"(?:\((SDD|NS|[SIR])\)|[\s,;](SDD|NS|[SIR])$|^([SIR]|SDD|NS)$)",
        val_str,
        re.I,
    )
    if sir_match:
        sir_call = (
            sir_match.group(1) or sir_match.group(2) or sir_match.group(3)
        ).upper()
        val_str = re.sub(
            r"\((SDD|NS|[SIR])\)|[\s,;](SDD|NS|[SIR])$|^([SIR]|SDD|NS)$",
            "",
            val_str,
            flags=re.I,
        ).strip()

    mic_sign = None
    mic = None
    notes = None

    sign_match = re.search(r"^(<=|>=|<|>|=)\s*(.+)$", val_str)
    if sign_match:
        mic_sign = sign_match.group(1)
        mic_part = sign_match.group(2).strip()
    elif re.search(r"\d", val_str):
        mic_sign = "="
        mic_part = val_str
        notes = "mic_sign '=' inferred"
    else:
        mic_part = None

    if mic_part:
        # Extract numeric MIC or ratio (e.g., 32/16 or 0.25)
        m = re.search(r"(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*)", mic_part)
        if m:
            raw_mic = m.group(1).replace(" ", "")
            parts = raw_mic.split("/")
            clean_parts = []
            for p in parts:
                try:
                    f = float(p)
                    if f.is_integer():
                        clean_parts.append(str(int(f)))
                    else:
                        clean_parts.append(p)
                except ValueError:
                    clean_parts.append(p)
            mic = "/".join(clean_parts)

    if mic is None and sir_call is None:
        return None, None, None, None

    if mic is None:
        mic_sign = None
        notes = None

    return mic_sign, mic, sir_call, notes


def transform_sheet(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 1. Identify isolate ID column
    isolate_col = None
    for col in df.columns:
        col_clean = str(col).strip().lower()
        if any(
            k in col_clean
            for k in [
                "strain",
                "isolate",
                "sample",
                "specimen",
                "id",
                "patient isolate",
            ]
        ):
            isolate_col = col
            break

    # 2. Identify accession column
    accession_cols = []
    for col in df.columns:
        col_clean = str(col).strip().lower()
        if "accession" in col_clean or "biosample" in col_clean:
            accession_cols.append(col)

    # 3. Handle combined drug column EM/CLDM if present
    for col in list(df.columns):
        if str(col).strip().upper() == "EM/CLDM":

            def split_em(v):
                if pd.isna(v):
                    return np.nan
                s = str(v).strip()
                return s.split("/")[0] if "/" in s else s

            def split_cldm(v):
                if pd.isna(v):
                    return np.nan
                s = str(v).strip()
                return s.split("/")[1] if "/" in s else s

            df["erythromycin"] = df[col].apply(split_em)
            df["clindamycin"] = df[col].apply(split_cldm)
            df = df.drop(columns=[col])

    # 4. Identify AST drug columns
    drug_mapping = {}
    for col in df.columns:
        if col == isolate_col or col in accession_cols:
            continue
        col_clean = str(col).strip().lower()
        if col_clean in DRUG_NAME_MAP:
            std_drug = DRUG_NAME_MAP[col_clean]
            if std_drug in PERMITTED_DRUGS:
                drug_mapping[col] = std_drug
        elif col_clean in PERMITTED_DRUGS:
            drug_mapping[col] = col_clean

    records = []
    for _, row in df.iterrows():
        isolate_id = (
            str(row[isolate_col]).strip()
            if isolate_col and pd.notna(row[isolate_col])
            else None
        )

        accession = None
        if accession_cols:
            found_accs = []
            for ac in accession_cols:
                val = row[ac]
                if pd.notna(val):
                    acc_matches = re.findall(
                        r"\b(?:SAM[NED][A-Z]?\d+|SRS\d+|GC[AF]_\d+\.\d+|[SED]RR\d+)\b",
                        str(val),
                    )
                    found_accs.extend(acc_matches)
            if found_accs:
                accession = ",".join(sorted(set(found_accs)))

        for col, drug_name in drug_mapping.items():
            cell_val = row[col]
            mic_sign, mic, sir_call, notes = parse_mic_cell(cell_val)

            # Discard if both mic and sir_call are missing
            if mic is None and sir_call is None:
                continue

            records.append(
                {
                    "isolate_id": isolate_id,
                    "accession": accession,
                    "drug": drug_name,
                    "mic_sign": mic_sign,
                    "mic": mic,
                    "sir_call": sir_call,
                    "notes": notes,
                }
            )

    output_cols = [
        "isolate_id",
        "accession",
        "drug",
        "mic_sign",
        "mic",
        "sir_call",
        "notes",
    ]
    if not records:
        return pd.DataFrame(columns=output_cols)

    return pd.DataFrame(records)[output_cols]

