#!/usr/bin/env bash
# check_one_isolate.sh
# Runs extract_excel_codegen.py on supplementary Excel files for a single PMID,
# then evaluates extraction accuracy against ground truth using computeAccuracy1.py,
# statToTab.py, and extractErrors.py.
#
# Usage:
#   bash check_one_isolate.sh <PMID> [SUPP_DIR] [GROUND_TRUTH]
#
# Example:
#   bash check_one_isolate.sh 35756053

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <PMID> [SUPP_DIR] [GROUND_TRUTH]" >&2
    echo "Example: $0 35756053" >&2
    exit 1
fi

PMID="$1"
SUPP_DIR="${2:-}"
GROUND_TRUTH="${3:-${REPO_ROOT}/data/rawTSV/dataset.staph.merged.txt}"

if [ -z "${GOOGLE_API_KEY:-}" ] && [ -f "${REPO_ROOT}/.env" ]; then
    set -a
    source "${REPO_ROOT}/.env"
    set +a
fi

if [ -z "${GOOGLE_API_KEY:-}" ]; then
    echo "WARNING: GOOGLE_API_KEY is not set in this shell - extract_excel_codegen.py will fail." >&2
fi

# Auto-discover supplement folder if not explicitly provided
if [ -z "$SUPP_DIR" ]; then
    if [ -d "${REPO_ROOT}/scripts/query_pmids_to_find_ast/output/supplements/${PMID}" ]; then
        SUPP_DIR="${REPO_ROOT}/scripts/query_pmids_to_find_ast/output/supplements/${PMID}"
    elif [ -d "${REPO_ROOT}/data/starter/${PMID}/supplements" ]; then
        SUPP_DIR="${REPO_ROOT}/data/starter/${PMID}/supplements"
    else
        echo "Supplements directory not found for PMID ${PMID}." >&2
        echo "Checked:" >&2
        echo "  - ${REPO_ROOT}/scripts/query_pmids_to_find_ast/output/supplements/${PMID}" >&2
        echo "  - ${REPO_ROOT}/data/starter/${PMID}/supplements" >&2
        echo "Please pass SUPP_DIR explicitly as the second argument." >&2
        exit 1
    fi
fi

if [ ! -d "$SUPP_DIR" ]; then
    echo "Supplements directory not found: $SUPP_DIR" >&2
    exit 1
fi

# Check that at least one Excel file exists in the directory
if ! find "$SUPP_DIR" -maxdepth 1 -type f \( -iname '*.xlsx' -o -iname '*.xls' \) -print -quit | grep -q .; then
    echo "No Excel file (.xlsx or .xls) found in supplements directory: $SUPP_DIR" >&2
    exit 1
fi

if [ ! -f "$GROUND_TRUTH" ]; then
    echo "Ground truth file not found: $GROUND_TRUTH" >&2
    exit 1
fi

OUT_BASE="${OUTPUT_BASE_DIR:-${REPO_ROOT}/scripts/accuracy_metrics/output}"
OUT_DIR="${OUT_BASE}/${PMID}"
mkdir -p "$OUT_DIR"

AST_DIR="${REPO_ROOT}/data/andrew_ast"
mkdir -p "$AST_DIR"

EXTRACTED_TSV="${AST_DIR}/${PMID}.mic.tsv"
TRANSFORM_CODE="${AST_DIR}/${PMID}.transform_code.py"
COMP_TSV="${OUT_DIR}/${PMID}.comp.tsv"
STATS_TXT="${OUT_DIR}/${PMID}.stats.txt"
STATS_TSV="${OUT_DIR}/${PMID}.stats.tsv"
ERR_TSV="${OUT_DIR}/${PMID}.err.tsv"

rm -f "$EXTRACTED_TSV" "$TRANSFORM_CODE" "$COMP_TSV" "$STATS_TXT" "$STATS_TSV" "$ERR_TSV"

echo "=== Step 1: Extracting AST data from supplements with extract_excel_codegen.py ==="
python3 "${REPO_ROOT}/src/amr_extraction/extract_excel_codegen.py" \
    -o "$EXTRACTED_TSV" \
    --save-code "$TRANSFORM_CODE" \
    --supp-dir "$SUPP_DIR" \
    --pmid "$PMID"

if [ ! -f "$EXTRACTED_TSV" ]; then
    echo "[!] Notice: No AST data extracted for PMID ${PMID} (sheet(s) may have been skipped or contained no AST data)." >&2
    echo "=== Summary Statistics for PMID ${PMID} ==="
    echo "No AST records extracted."
    exit 0
fi

echo "=== Step 2: Computing accuracy metrics against ground truth ==="
python3 "${REPO_ROOT}/scripts/accuracy_metrics/computeAccuracy1.py" \
    "$EXTRACTED_TSV" \
    "$GROUND_TRUTH" \
    --output "$COMP_TSV" > "$STATS_TXT"

echo "=== Step 3: Tabulating accuracy statistics ==="
python3 "${REPO_ROOT}/scripts/accuracy_metrics/statToTab.py" \
    "$STATS_TXT" \
    "$STATS_TSV"

echo "=== Step 4: Extracting erroneous calls ==="
python3 "${REPO_ROOT}/scripts/accuracy_metrics/extractErrors.py" \
    "$COMP_TSV" \
    "$ERR_TSV"

echo
echo "=== Summary Statistics for PMID ${PMID} ==="
cat "$STATS_TXT"
echo
echo "=== Output files generated ==="
echo "  Extracted AST TSV:    $EXTRACTED_TSV"
echo "  Transform Code:       $TRANSFORM_CODE"
echo "  Detailed Comparison:  $COMP_TSV"
echo "  Summary Stats (Text): $STATS_TXT"
echo "  Summary Stats (TSV):  $STATS_TSV"
echo "  Error Calls TSV:      $ERR_TSV"
