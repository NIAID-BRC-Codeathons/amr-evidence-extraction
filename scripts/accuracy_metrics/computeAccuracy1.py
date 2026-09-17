'''
python computeAccuracy1.py [llm output tsv] [dataset ground truth] --output [output tsv for full matches] > [output txt for summary stats]
'''

#!/usr/bin/env python3

import argparse
import re
from collections import defaultdict

import pandas as pd


# ============================================================
# Configuration
# ============================================================

GT_ACCESSION_COLUMNS = [
    "genome.biosample_accession",
    "genome.assembly_accession",
    "genome.genbank_accessions",
    "genome.refseq_accessions",
    "genome.sra_accession",
]

EXTRACTED_ACCESSION_COLUMNS = [
    "biosample_accession",
    "assembly_accession",
    "genbank_accessions",
    "refseq_accessions",
    "sra_accession",
    "other_accessions",
]


# ------------------------------------------------------------
# Antibiotic aliases
# ------------------------------------------------------------

DRUG_ALIASES = {
    "rifampicin": "rifampin",

    "co-trimoxazole": "trimethoprim/sulfamethoxazole",
    "cotrimoxazole": "trimethoprim/sulfamethoxazole",
    "trimethoprim-sulfamethoxazole":
        "trimethoprim/sulfamethoxazole",
    "trimethoprim sulfamethoxazole":
        "trimethoprim/sulfamethoxazole",
}


# ============================================================
# General string normalization
# ============================================================

def clean_string(value):
    """
    Convert null-like values to an empty string and strip
    surrounding whitespace.
    """

    if value is None:
        return ""

    value = str(value).strip()

    if value.lower() in {
        "",
        "nan",
        "none",
        "na",
        "n/a",
        "-"
    }:
        return ""

    return value


# ============================================================
# Accession normalization
# ============================================================

def accession_variants(value):
    """
    Generate equivalent representations of an accession.

    Normal accessions are uppercased.

    Assembly accessions receive additional normalization.

    Example:

        GCF_001658655.1

    produces:

        GCF_001658655.1
        GCF_001658655
        GCA_001658655.1
        GCA_001658655
    """

    value = clean_string(value).upper()

    if not value:
        return set()

    variants = {value}

    match = re.match(
        r"^(GC[AF]_\d+)(?:\.(\d+))?$",
        value
    )

    if match:

        base = match.group(1)
        version = match.group(2)

        variants.add(base)

        if base.startswith("GCF_"):
            other_base = "GCA_" + base[4:]
        else:
            other_base = "GCF_" + base[4:]

        variants.add(other_base)

        if version:

            variants.add(
                base + "." + version
            )

            variants.add(
                other_base + "." + version
            )

    return variants


def split_accessions(value):
    """
    Split fields containing one or more accessions.

    Handles:
        whitespace
        comma
        semicolon
        pipe

    Returns all normalized accession variants.
    """

    value = clean_string(value)

    if not value:
        return set()

    parts = re.split(
        r"[,;|\s]+",
        value
    )

    accessions = set()

    for part in parts:

        if not part:
            continue

        accessions.update(
            accession_variants(part)
        )

    return accessions


# ============================================================
# Drug normalization
# ============================================================

def normalize_drug(value):
    """
    Normalize antibiotic names before comparison.
    """

    value = clean_string(value).lower()

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return DRUG_ALIASES.get(
        value,
        value
    )


# ============================================================
# S / I / R / NS / NR normalization
# ============================================================

def normalize_sir(value):
    """
    Normalize categorical AST calls.

    Canonical representations:

        S  = susceptible
        I  = intermediate
        R  = resistant
        NS = non-susceptible
        NR = non-resistant

    NS is intentionally NOT converted to R.
    NR is intentionally NOT converted to S.

    Unknown values return an empty string.
    """

    value = clean_string(value).lower()

    # Normalize Unicode dashes.
    value = value.replace("\u2010", "-")
    value = value.replace("\u2011", "-")
    value = value.replace("\u2012", "-")
    value = value.replace("\u2013", "-")
    value = value.replace("\u2014", "-")

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    mapping = {

        # Susceptible
        "s": "S",
        "susceptible": "S",
        "susceptibility": "S",

        # Intermediate
        "i": "I",
        "intermediate": "I",

        # Resistant
        "r": "R",
        "resistant": "R",
        "resistance": "R",

        # Non-susceptible
        "ns": "NS",
        "non-susceptible": "NS",
        "non susceptible": "NS",
        "nonsusceptible": "NS",
        "non-susceptibility": "NS",
        "non susceptibility": "NS",
        "nonsusceptibility": "NS",

        # Non-resistant
        "nr": "NR",
        "non-resistant": "NR",
        "non resistant": "NR",
        "nonresistant": "NR",
        "non-resistance": "NR",
        "non resistance": "NR",
        "nonresistance": "NR",
    }

    return mapping.get(
        value,
        ""
    )


# ============================================================
# MIC normalization
# ============================================================

def normalize_mic_sign(value):
    """
    Normalize MIC inequality symbols.

        ≤  -> <=
        ≥  -> >=
        == -> =
    """

    value = clean_string(value)

    value = value.replace(
        "≤",
        "<="
    )

    value = value.replace(
        "≥",
        ">="
    )

    if value in {
        "=",
        "=="
    }:
        return "="

    if value in {
        "<",
        "<=",
        ">",
        ">="
    }:
        return value

    return ""


def normalize_number(value):
    """
    Normalize numeric MIC values.

    Examples:

        2       -> 2
        2.0     -> 2
        2.00    -> 2
        0.50    -> 0.5

    Non-simple values are retained as strings.
    """

    value = clean_string(value)

    if not value:
        return ""

    try:

        number = float(value)

        if number.is_integer():

            return str(
                int(number)
            )

        return format(
            number,
            ".12g"
        )

    except ValueError:

        return value.lower()


# ============================================================
# Ground-truth accession index
# ============================================================

def build_ground_truth_accession_index(gt):
    """
    Build:

        accession -> set(genome_id)

    Any supported accession associated with a genome can
    therefore identify that genome.
    """

    accession_to_genomes = defaultdict(set)

    for _, row in gt.iterrows():

        genome_id = clean_string(
            row.get(
                "genome_id",
                ""
            )
        )

        if not genome_id:
            continue

        for column in GT_ACCESSION_COLUMNS:

            for accession in split_accessions(
                row.get(
                    column,
                    ""
                )
            ):

                accession_to_genomes[
                    accession
                ].add(
                    genome_id
                )

    return accession_to_genomes


# ============================================================
# Extracted accession collection
# ============================================================

def get_extracted_accessions(row):
    """
    Collect every accession supplied by the LLM for an
    extracted AST record.
    """

    accessions = set()

    for column in EXTRACTED_ACCESSION_COLUMNS:

        for accession in split_accessions(
            row.get(
                column,
                ""
            )
        ):

            accessions.add(
                accession
            )

    return accessions


# ============================================================
# Genome matching
# ============================================================

def match_genome(
    row,
    accession_index
):
    """
    Match an extracted record to a ground-truth genome.

    ANY accession from the extracted record can match ANY
    accession associated with a ground-truth genome.

    Returns:

        genome_id
        matching_accessions
        match_status
    """

    extracted_accessions = (
        get_extracted_accessions(row)
    )

    if not extracted_accessions:

        return (
            "",
            "",
            "NO_ACCESSIONS"
        )

    matched_genomes = defaultdict(set)

    for accession in extracted_accessions:

        genome_ids = accession_index.get(
            accession,
            set()
        )

        for genome_id in genome_ids:

            matched_genomes[
                genome_id
            ].add(
                accession
            )

    if not matched_genomes:

        return (
            "",
            "",
            "NO_GENOME_MATCH"
        )

    if len(matched_genomes) > 1:

        genomes = sorted(
            matched_genomes.keys()
        )

        return (
            "",
            "",
            "AMBIGUOUS:" + ",".join(genomes)
        )

    genome_id = next(
        iter(matched_genomes)
    )

    accessions = sorted(
        matched_genomes[genome_id]
    )

    return (
        genome_id,
        ",".join(accessions),
        "MATCHED"
    )


# ============================================================
# Ground-truth genome/drug lookup
# ============================================================

def build_ground_truth_lookup(gt):
    """
    Build:

        (genome_id, normalized_drug)
            -> ground-truth row indices
    """

    lookup = defaultdict(list)

    for idx, row in gt.iterrows():

        genome_id = clean_string(
            row.get(
                "genome_id",
                ""
            )
        )

        drug = normalize_drug(
            row.get(
                "antibiotic",
                ""
            )
        )

        if not genome_id:
            continue

        if not drug:
            continue

        lookup[
            (
                genome_id,
                drug
            )
        ].append(
            idx
        )

    return lookup


# ============================================================
# Main comparison
# ============================================================

def compare(
    extracted,
    gt
):

    print(
        "Building ground-truth accession index..."
    )

    accession_index = (
        build_ground_truth_accession_index(gt)
    )

    print(
        "Unique accession keys:",
        len(accession_index)
    )

    print(
        "Building genome/drug lookup..."
    )

    gt_lookup = (
        build_ground_truth_lookup(gt)
    )

    results = []

    print(
        "Comparing extracted records..."
    )

    for extracted_index, row in extracted.iterrows():

        # ----------------------------------------------------
        # PMID
        # ----------------------------------------------------

        pmid = clean_string(
            row.get(
                "pmid",
                ""
            )
        )

        # ----------------------------------------------------
        # Genome matching
        # ----------------------------------------------------

        (
            genome_id,
            matched_accessions,
            genome_status
        ) = match_genome(
            row,
            accession_index
        )

        # ----------------------------------------------------
        # Drug
        # ----------------------------------------------------

        raw_drug = clean_string(
            row.get(
                "drug",
                ""
            )
        )

        drug = normalize_drug(
            raw_drug
        )

        # ----------------------------------------------------
        # Categorical phenotype
        # ----------------------------------------------------

        raw_extracted_sir = clean_string(
            row.get(
                "sir_call",
                ""
            )
        )

        extracted_sir = normalize_sir(
            raw_extracted_sir
        )

        # ----------------------------------------------------
        # MIC
        # ----------------------------------------------------

        raw_extracted_mic_sign = clean_string(
            row.get(
                "mic_sign",
                ""
            )
        )

        raw_extracted_mic = clean_string(
            row.get(
                "mic",
                ""
            )
        )

        extracted_mic_sign = normalize_mic_sign(
            raw_extracted_mic_sign
        )

        extracted_mic = normalize_number(
            raw_extracted_mic
        )

        # ----------------------------------------------------
        # Base result
        # ----------------------------------------------------

        result = {

            "extracted_row":
                extracted_index + 2,

            "pmid":
                pmid,

            "isolate_id":
                row.get(
                    "isolate_id",
                    ""
                ),

            "drug":
                raw_drug,

            "normalized_drug":
                drug,

            "genome_id":
                genome_id,

            "matched_accessions":
                matched_accessions,

            "genome_match_status":
                genome_status,

            "extracted_sir_raw":
                raw_extracted_sir,

            "extracted_sir":
                extracted_sir,

            "ground_truth_sir_raw":
                "",

            "ground_truth_sir":
                "",

            "sir_result":
                "NOT_EVALUATED",

            "extracted_mic_sign_raw":
                raw_extracted_mic_sign,

            "extracted_mic_raw":
                raw_extracted_mic,

            "extracted_mic_sign":
                extracted_mic_sign,

            "extracted_mic":
                extracted_mic,

            "ground_truth_mic_sign":
                "",

            "ground_truth_mic":
                "",

            "mic_result":
                "NOT_EVALUATED",
        }

        # ----------------------------------------------------
        # Genome could not be matched.
        # ----------------------------------------------------

        if genome_status != "MATCHED":

            results.append(
                result
            )

            continue

        # ----------------------------------------------------
        # Find genome + drug in ground truth.
        # ----------------------------------------------------

        candidates = gt_lookup.get(
            (
                genome_id,
                drug
            ),
            []
        )

        if not candidates:

            result[
                "sir_result"
            ] = "NO_GT_DRUG"

            result[
                "mic_result"
            ] = "NO_GT_DRUG"

            results.append(
                result
            )

            continue

        gt_rows = gt.loc[
            candidates
        ]

        # ====================================================
        # Categorical phenotype comparison
        # ====================================================

        gt_sir_values = set()
        gt_sir_raw_values = set()

        for value in gt_rows[
            "resistant_phenotype"
        ]:

            raw_value = clean_string(
                value
            )

            if raw_value:

                gt_sir_raw_values.add(
                    raw_value
                )

            normalized_value = normalize_sir(
                value
            )

            if normalized_value:

                gt_sir_values.add(
                    normalized_value
                )

        result[
            "ground_truth_sir_raw"
        ] = ",".join(
            sorted(
                gt_sir_raw_values
            )
        )

        result[
            "ground_truth_sir"
        ] = ",".join(
            sorted(
                gt_sir_values
            )
        )

        # ----------------------------------------------------
        # SIR state logic
        #
        # EXTRACTED    GT          RESULT
        # ---------    --------    -------------------
        # yes          yes         compare
        # yes          no          NO_GT_VALUE
        # no           yes         MISSING_EXTRACTION
        # no           no          NOT_APPLICABLE
        #
        # A raw but unrecognized LLM call counts as an
        # attempted extraction.
        # ----------------------------------------------------

        extracted_sir_present = bool(
            raw_extracted_sir
        )

        gt_sir_present = bool(
            gt_sir_values
        )

        # Both sides have a categorical value.
        if extracted_sir_present and gt_sir_present:

            if extracted_sir:

                if extracted_sir in gt_sir_values:

                    result[
                        "sir_result"
                    ] = "CORRECT"

                else:

                    result[
                        "sir_result"
                    ] = "INCORRECT"

            else:

                result[
                    "sir_result"
                ] = "UNRECOGNIZED_CALL"

        # LLM extracted a categorical call, but GT has none.
        elif extracted_sir_present and not gt_sir_present:

            result[
                "sir_result"
            ] = "NO_GT_VALUE"

        # GT has a categorical call, but LLM extracted none.
        elif not extracted_sir_present and gt_sir_present:

            result[
                "sir_result"
            ] = "MISSING_EXTRACTION"

        # Neither side contains categorical SIR data.
        else:

            result[
                "sir_result"
            ] = "NOT_APPLICABLE"

        # ====================================================
        # MIC comparison
        # ====================================================

        gt_mics = set()

        for _, gt_row in gt_rows.iterrows():

            gt_mic = normalize_number(
                gt_row.get(
                    "measurement_value",
                    ""
                )
            )

            gt_sign = normalize_mic_sign(
                gt_row.get(
                    "measurement_sign",
                    ""
                )
            )

            # Blank sign with a numeric MIC is treated as
            # an exact measurement.
            if gt_mic and not gt_sign:

                gt_sign = "="

            if gt_mic:

                gt_mics.add(
                    (
                        gt_sign,
                        gt_mic
                    )
                )

        if gt_mics:

            result[
                "ground_truth_mic_sign"
            ] = ",".join(
                sorted(
                    set(
                        x[0]
                        for x in gt_mics
                    )
                )
            )

            result[
                "ground_truth_mic"
            ] = ",".join(
                sorted(
                    set(
                        x[1]
                        for x in gt_mics
                    )
                )
            )

        # ----------------------------------------------------
        # MIC state logic
        #
        # EXTRACTED    GT          RESULT
        # ---------    --------    -------------------
        # yes          yes         compare
        # yes          no          NO_GT_VALUE
        # no           yes         MISSING_EXTRACTION
        # no           no          NOT_APPLICABLE
        # ----------------------------------------------------

        extracted_mic_present = bool(
            extracted_mic
        )

        gt_mic_present = bool(
            gt_mics
        )

        # Both sides contain MIC values.
        if extracted_mic_present and gt_mic_present:

            ex_sign = (
                extracted_mic_sign
                or "="
            )

            if (
                ex_sign,
                extracted_mic
            ) in gt_mics:

                result[
                    "mic_result"
                ] = "CORRECT"

            else:

                result[
                    "mic_result"
                ] = "INCORRECT"

        # LLM extracted MIC, but GT has no MIC.
        elif extracted_mic_present and not gt_mic_present:

            result[
                "mic_result"
            ] = "NO_GT_VALUE"

        # GT has MIC, but LLM extracted none.
        elif not extracted_mic_present and gt_mic_present:

            result[
                "mic_result"
            ] = "MISSING_EXTRACTION"

        # Neither side contains an MIC.
        else:

            result[
                "mic_result"
            ] = "NOT_APPLICABLE"

        results.append(
            result
        )

    return pd.DataFrame(
        results
    )


# ============================================================
# Metrics
# ============================================================

def calculate_metrics(results):

    total = len(results)

    # ========================================================
    # Genome matching
    # ========================================================

    matched_genome = (
        results[
            "genome_match_status"
        ] == "MATCHED"
    ).sum()

    no_genome = (
        results[
            "genome_match_status"
        ] == "NO_GENOME_MATCH"
    ).sum()

    no_accessions = (
        results[
            "genome_match_status"
        ] == "NO_ACCESSIONS"
    ).sum()

    ambiguous = (
        results[
            "genome_match_status"
        ]
        .str.startswith(
            "AMBIGUOUS"
        )
    ).sum()

    print()
    print("=" * 60)
    print("GENOME MATCHING")
    print("=" * 60)

    print(
        "Extracted rows:                ",
        total
    )

    print(
        "Genome matched:                ",
        matched_genome
    )

    print(
        "No genome match:               ",
        no_genome
    )

    print(
        "No accessions supplied:        ",
        no_accessions
    )

    print(
        "Ambiguous genome match:        ",
        ambiguous
    )

    if total:

        print(
            "Genome match rate:              {:.2%}".format(
                matched_genome
                / total
            )
        )

    print()
    print(
        "Genome match status breakdown:"
    )

    print(
        results[
            "genome_match_status"
        ]
        .value_counts()
        .to_string()
    )

    # ========================================================
    # Genome + drug matching
    # ========================================================

    no_gt_drug = (
        results[
            "sir_result"
        ] == "NO_GT_DRUG"
    ).sum()

    print()
    print("=" * 60)
    print("GENOME + DRUG MATCHING")
    print("=" * 60)

    print(
        "Matched genome, missing GT drug:",
        no_gt_drug
    )

    # ========================================================
    # Categorical phenotype extraction
    # ========================================================

    sir_correct = (
        results[
            "sir_result"
        ] == "CORRECT"
    ).sum()

    sir_incorrect = (
        results[
            "sir_result"
        ] == "INCORRECT"
    ).sum()

    sir_missing = (
        results[
            "sir_result"
        ] == "MISSING_EXTRACTION"
    ).sum()

    sir_unrecognized = (
        results[
            "sir_result"
        ] == "UNRECOGNIZED_CALL"
    ).sum()

    sir_no_gt_value = (
        results[
            "sir_result"
        ] == "NO_GT_VALUE"
    ).sum()

    sir_not_applicable = (
        results[
            "sir_result"
        ] == "NOT_APPLICABLE"
    ).sum()

    sir_no_gt_drug = (
        results[
            "sir_result"
        ] == "NO_GT_DRUG"
    ).sum()

    sir_not_evaluated = (
        results[
            "sir_result"
        ] == "NOT_EVALUATED"
    ).sum()

    # Rows where both sides contain usable categorical calls.
    sir_compared = (
        sir_correct
        + sir_incorrect
    )

    # Rows where GT actually contains a categorical phenotype.
    sir_gt_available = (
        sir_correct
        + sir_incorrect
        + sir_missing
        + sir_unrecognized
    )

    # Rows where the LLM attempted to extract categorical data.
    sir_extracted = (
        sir_correct
        + sir_incorrect
        + sir_unrecognized
        + sir_no_gt_value
    )

    print()
    print("=" * 60)
    print("S/I/R/NS/NR EXTRACTION")
    print("=" * 60)

    print(
        "LLM categorical calls:         ",
        sir_extracted
    )

    print(
        "Correct calls:                 ",
        sir_correct
    )

    print(
        "Incorrect calls:               ",
        sir_incorrect
    )

    print(
        "Missing LLM calls:             ",
        sir_missing
    )

    print(
        "Unrecognized LLM calls:        ",
        sir_unrecognized
    )

    print(
        "Extracted calls without GT:    ",
        sir_no_gt_value
    )

    print()
    print("Not applicable:")

    print(
        "  Neither side has SIR value:  ",
        sir_not_applicable
    )

    print()
    print("Not evaluable:")

    print(
        "  Drug absent from GT:         ",
        sir_no_gt_drug
    )

    print(
        "  Genome not evaluable:        ",
        sir_not_evaluated
    )

    print()

    print(
        "Categorical rows compared:     ",
        sir_compared
    )

    print(
        "GT categorical values avail.:  ",
        sir_gt_available
    )

    if sir_compared:

        print(
            "Accuracy when comparable:       {:.2%}".format(
                sir_correct
                / sir_compared
            )
        )

    if sir_gt_available:

        print(
            "LLM categorical coverage:       {:.2%}".format(
                sir_compared
                / sir_gt_available
            )
        )

        print(
            "Overall correct extraction:     {:.2%}".format(
                sir_correct
                / sir_gt_available
            )
        )

    # ========================================================
    # MIC extraction
    # ========================================================

    mic_correct = (
        results[
            "mic_result"
        ] == "CORRECT"
    ).sum()

    mic_incorrect = (
        results[
            "mic_result"
        ] == "INCORRECT"
    ).sum()

    mic_missing = (
        results[
            "mic_result"
        ] == "MISSING_EXTRACTION"
    ).sum()

    mic_no_gt_value = (
        results[
            "mic_result"
        ] == "NO_GT_VALUE"
    ).sum()

    mic_not_applicable = (
        results[
            "mic_result"
        ] == "NOT_APPLICABLE"
    ).sum()

    mic_no_gt_drug = (
        results[
            "mic_result"
        ] == "NO_GT_DRUG"
    ).sum()

    mic_not_evaluated = (
        results[
            "mic_result"
        ] == "NOT_EVALUATED"
    ).sum()

    mic_compared = (
        mic_correct
        + mic_incorrect
    )

    mic_gt_available = (
        mic_correct
        + mic_incorrect
        + mic_missing
    )

    mic_extracted = (
        mic_correct
        + mic_incorrect
        + mic_no_gt_value
    )

    print()
    print("=" * 60)
    print("MIC EXTRACTION")
    print("=" * 60)

    print(
        "LLM MIC values:                ",
        mic_extracted
    )

    print(
        "Correct MICs:                  ",
        mic_correct
    )

    print(
        "Incorrect MICs:                ",
        mic_incorrect
    )

    print(
        "Missing LLM MICs:              ",
        mic_missing
    )

    print(
        "Extracted MICs without GT:     ",
        mic_no_gt_value
    )

    print()
    print("Not applicable:")

    print(
        "  Neither side has MIC value:  ",
        mic_not_applicable
    )

    print()
    print("Not evaluable:")

    print(
        "  Drug absent from GT:         ",
        mic_no_gt_drug
    )

    print(
        "  Genome not evaluable:        ",
        mic_not_evaluated
    )

    print()

    print(
        "MIC rows compared:             ",
        mic_compared
    )

    print(
        "GT MIC values available:       ",
        mic_gt_available
    )

    if mic_compared:

        print(
            "MIC accuracy when comparable:   {:.2%}".format(
                mic_correct
                / mic_compared
            )
        )

    if mic_gt_available:

        print(
            "LLM MIC coverage:               {:.2%}".format(
                mic_compared
                / mic_gt_available
            )
        )

        print(
            "Overall correct MIC:            {:.2%}".format(
                mic_correct
                / mic_gt_available
            )
        )


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Evaluate LLM-extracted AST data against "
            "BV-BRC ground truth."
        )
    )

    parser.add_argument(
        "extracted",
        help=(
            "LLM-extracted AST table"
        )
    )

    parser.add_argument(
        "ground_truth",
        help=(
            "Merged BV-BRC ground-truth table"
        )
    )

    parser.add_argument(
        "--output",
        default="comparison_results.txt",
        help=(
            "Detailed comparison output "
            "(default: comparison_results.txt)"
        )
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Read files
    # --------------------------------------------------------

    extracted = pd.read_csv(
        args.extracted,
        sep="\t",
        dtype=str,
        keep_default_na=False
    )

    gt = pd.read_csv(
        args.ground_truth,
        sep="\t",
        dtype=str,
        keep_default_na=False
    )

    print(
        "Extracted rows:",
        len(extracted)
    )

    print(
        "Ground-truth rows:",
        len(gt)
    )

    print(
        "Ground-truth genomes:",
        gt["genome_id"].nunique()
    )

    # --------------------------------------------------------
    # Compare
    # --------------------------------------------------------

    results = compare(
        extracted,
        gt
    )

    # --------------------------------------------------------
    # Save detailed results
    # --------------------------------------------------------

    results.to_csv(
        args.output,
        sep="\t",
        index=False
    )

    # --------------------------------------------------------
    # Report metrics
    # --------------------------------------------------------

    calculate_metrics(
        results
    )

    print()

    print(
        "Detailed results written to:",
        args.output
    )


if __name__ == "__main__":
    main()