'''
python extract_inocrrect.py [comparison result tsv] [output]
'''

#!/usr/bin/env python3

import argparse
import pandas as pd


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Extract rows containing an incorrect SIR or MIC result "
            "from compare_ast.py output."
        )
    )

    parser.add_argument(
        "input",
        help="Comparison TSV produced by compare_ast.py --output"
    )

    parser.add_argument(
        "output",
        help="Output TSV containing incorrect rows"
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Read comparison table
    # --------------------------------------------------------

    df = pd.read_csv(
        args.input,
        sep="\t",
        dtype=str,
        keep_default_na=False
    )

    # --------------------------------------------------------
    # Make sure required columns exist
    # --------------------------------------------------------

    required_columns = {
        "sir_result",
        "mic_result"
    }

    missing_columns = (
        required_columns - set(df.columns)
    )

    if missing_columns:

        raise ValueError(
            "Input file is missing required column(s): {}".format(
                ", ".join(sorted(missing_columns))
            )
        )

    # --------------------------------------------------------
    # Select rows where EITHER result is INCORRECT
    #
    # Examples retained:
    #
    #   SIR = INCORRECT, MIC = CORRECT
    #   SIR = CORRECT,   MIC = INCORRECT
    #   SIR = INCORRECT, MIC = INCORRECT
    #   SIR = INCORRECT, MIC = NOT_APPLICABLE
    #   SIR = NO_GT_VALUE, MIC = INCORRECT
    #
    # The other result does not matter.
    # --------------------------------------------------------

    incorrect = df[
        (df["sir_result"].str.upper() == "INCORRECT")
        |
        (df["mic_result"].str.upper() == "INCORRECT")
    ].copy()

    # --------------------------------------------------------
    # Write complete rows, preserving all diagnostic columns
    # including PMID.
    # --------------------------------------------------------

    incorrect.to_csv(
        args.output,
        sep="\t",
        index=False
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    sir_incorrect = (
        incorrect["sir_result"].str.upper()
        == "INCORRECT"
    ).sum()

    mic_incorrect = (
        incorrect["mic_result"].str.upper()
        == "INCORRECT"
    ).sum()

    both_incorrect = (
        (
            incorrect["sir_result"].str.upper()
            == "INCORRECT"
        )
        &
        (
            incorrect["mic_result"].str.upper()
            == "INCORRECT"
        )
    ).sum()

    print("Total input rows:       ", len(df))
    print("Rows with any error:    ", len(incorrect))
    print("Incorrect SIR calls:    ", sir_incorrect)
    print("Incorrect MIC calls:    ", mic_incorrect)
    print("Both incorrect:         ", both_incorrect)
    print()
    print("Output written to:", args.output)


if __name__ == "__main__":
    main()