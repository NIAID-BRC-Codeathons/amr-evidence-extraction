'''
python metrics_to_table.py metrics.txt metrics.tsv
'''

#!/usr/bin/env python3

import argparse
import csv


def parse_metrics(filename):
    """
    Parse compare_ast.py stdout into:

        Section | Metric | Value
    """

    rows = []
    current_section = None

    with open(filename, "r") as handle:
        lines = handle.readlines()

    i = 0

    while i < len(lines):

        line = lines[i].strip()

        # ----------------------------------------------------
        # Section header:
        #
        # ============================================================
        # GENOME MATCHING
        # ============================================================
        # ----------------------------------------------------

        if (
            line
            and set(line) == {"="}
            and i + 2 < len(lines)
        ):

            header = lines[i + 1].strip()
            next_line = lines[i + 2].strip()

            if (
                header
                and next_line
                and set(next_line) == {"="}
            ):
                current_section = header
                i += 3
                continue

        # ----------------------------------------------------
        # Metric line
        #
        # Example:
        #
        # Correct calls:                 123
        # Accuracy when comparable:      95.31%
        # ----------------------------------------------------

        if current_section and ":" in line:

            metric, value = line.split(":", 1)

            metric = metric.strip()
            value = value.strip()

            # Only keep actual metric/value lines.
            if metric and value:

                rows.append({
                    "Section": current_section,
                    "Metric": metric,
                    "Value": value
                })

        i += 1

    return rows


def write_table(rows, output_file):

    with open(
        output_file,
        "w",
        newline=""
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Section",
                "Metric",
                "Value"
            ],
            delimiter="\t"
        )

        writer.writeheader()
        writer.writerows(rows)


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Convert compare_ast.py stdout into "
            "a long-form summary table."
        )
    )

    parser.add_argument(
        "input",
        help="Text file containing compare_ast.py stdout"
    )

    parser.add_argument(
        "output",
        help="Output TSV file"
    )

    args = parser.parse_args()

    rows = parse_metrics(
        args.input
    )

    if not rows:
        raise RuntimeError(
            "No metrics found in {}".format(
                args.input
            )
        )

    write_table(
        rows,
        args.output
    )

    print(
        "Wrote {} metrics to {}".format(
            len(rows),
            args.output
        )
    )


if __name__ == "__main__":
    main()