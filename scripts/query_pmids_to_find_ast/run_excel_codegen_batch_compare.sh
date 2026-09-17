#!/usr/bin/env bash
# Runs extract_excel_codegen.py twice per PMID supplement folder that contains an
# Excel file (.xlsx/.xls), writing outputs to temporary run directories under tmp/
# and comparing the outputs of both runs.
#
# Run from the repo root (needs GOOGLE_API_KEY set and the venv activated first):
#   bash scripts/query_pmids_to_find_ast/run_excel_codegen_batch_compare.sh
#
# Optional overrides (positional):
#   bash scripts/query_pmids_to_find_ast/run_excel_codegen_batch_compare.sh <supplements_dir> <tmp_dir>

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SUPP_BASE="${1:-scripts/query_pmids_to_find_ast/output/supplements}"
TMP_BASE="${2:-${REPO_ROOT}/tmp}"

if [ ! -d "$SUPP_BASE" ]; then
    echo "Supplements directory not found: $SUPP_BASE" >&2
    echo "Run this from the repo root, or pass the supplements dir as the first argument." >&2
    exit 1
fi

if [ -z "${GOOGLE_API_KEY:-}" ]; then
    echo "WARNING: GOOGLE_API_KEY is not set in this shell - extract_excel_codegen.py will fail." >&2
fi

START_TIME="$(date +%s)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${TMP_BASE}/run_compare_${TIMESTAMP}"
OUT_DIR_1="${RUN_DIR}/run1"
OUT_DIR_2="${RUN_DIR}/run2"

mkdir -p "$OUT_DIR_1" "$OUT_DIR_2"

echo "Temporary output directory: $RUN_DIR"
echo "  Run 1: $OUT_DIR_1"
echo "  Run 2: $OUT_DIR_2"

total=0
skipped=0
run1_failed=0
run2_failed=0
matched=0
mismatched=0
failed_pmids=()
mismatched_pmids=()

for pmid_dir in "$SUPP_BASE"/*/; do
    [ -d "$pmid_dir" ] || continue
    pmid="$(basename "$pmid_dir")"

    # Only bother with folders that actually have an Excel file in them.
    if ! find "$pmid_dir" -maxdepth 1 -type f \( -iname '*.xlsx' -o -iname '*.xls' \) -print -quit | grep -q .; then
        skipped=$((skipped + 1))
        continue
    fi

    total=$((total + 1))
    out_tsv_1="$OUT_DIR_1/${pmid}.mic.tsv"
    out_tsv_2="$OUT_DIR_2/${pmid}.mic.tsv"
    echo "=== [$total] PMID $pmid ==="

    echo "  Running pass 1 -> $out_tsv_1"
    if ! python3 src/amr_extraction/extract_excel_codegen.py \
        -o "$out_tsv_1" \
        --num-passes 2 \
        --supp-dir "$pmid_dir"; then
        run1_failed=$((run1_failed + 1))
        failed_pmids+=("${pmid} (run1)")
        echo "  FAILED: PMID $pmid on pass 1" >&2
        continue
    fi

    echo "  Running pass 2 -> $out_tsv_2"
    if ! python3 src/amr_extraction/extract_excel_codegen.py \
        -o "$out_tsv_2" \
        --num-passes 2 \
        --supp-dir "$pmid_dir"; then
        run2_failed=$((run2_failed + 1))
        failed_pmids+=("${pmid} (run2)")
        echo "  FAILED: PMID $pmid on pass 2" >&2
        continue
    fi

    echo "  Comparing outputs..."
    if cmp -s "$out_tsv_1" "$out_tsv_2"; then
        matched=$((matched + 1))
        echo "  MATCH: Outputs are identical."
    else
        mismatched=$((mismatched + 1))
        mismatched_pmids+=("$pmid")
        echo "  MISMATCH: Outputs differ between pass 1 and pass 2." >&2
    fi
done

END_TIME="$(date +%s)"
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

echo
echo "=== Summary ==="
echo "Total PMIDs processed: $total"
echo "Skipped (no Excel files): $skipped"
echo "Matched (identical runs): $matched"
echo "Mismatched: $mismatched"
echo "Run 1 failures: $run1_failed"
echo "Run 2 failures: $run2_failed"
echo "Outputs preserved at: $RUN_DIR"
echo "Total duration: ${MINUTES}m ${SECONDS}s (${DURATION}s)"

if [ "${#failed_pmids[@]}" -gt 0 ]; then
    echo "Failed PMIDs: ${failed_pmids[*]}" >&2
fi

if [ "${#mismatched_pmids[@]}" -gt 0 ]; then
    echo "Mismatched PMIDs: ${mismatched_pmids[*]}" >&2
fi

total_failures=$((run1_failed + run2_failed + mismatched))
[ "$total_failures" -eq 0 ]
