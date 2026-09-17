#!/usr/bin/env bash
# Runs extract_excel_codegen.py once per PMID supplement folder that actually contains an
# Excel file (.xlsx/.xls), writing one output TSV per PMID under data/andrew_ast/.
#
# Run from the repo root (needs GOOGLE_API_KEY set and the venv activated first):
#   bash scripts/query_pmids_to_find_ast/run_excel_codegen_batch.sh
#
# Optional overrides (positional):
#   bash scripts/query_pmids_to_find_ast/run_excel_codegen_batch.sh <supplements_dir> <output_dir>

set -uo pipefail

SUPP_BASE="${1:-scripts/query_pmids_to_find_ast/output/supplements}"
OUT_DIR="${2:-data/andrew_ast}"

if [ ! -d "$SUPP_BASE" ]; then
    echo "Supplements directory not found: $SUPP_BASE" >&2
    echo "Run this from the repo root, or pass the supplements dir as the first argument." >&2
    exit 1
fi

if [ -z "${GOOGLE_API_KEY:-}" ]; then
    echo "WARNING: GOOGLE_API_KEY is not set in this shell — extract_excel_codegen.py will fail." >&2
fi

mkdir -p "$OUT_DIR"

total=0
succeeded=0
failed=0
skipped=0
failed_pmids=()

for pmid_dir in "$SUPP_BASE"/*/; do
    [ -d "$pmid_dir" ] || continue
    pmid="$(basename "$pmid_dir")"

    # Only bother with folders that actually have an Excel file in them.
    if ! find "$pmid_dir" -maxdepth 1 -type f \( -iname '*.xlsx' -o -iname '*.xls' \) -print -quit | grep -q .; then
        skipped=$((skipped + 1))
        continue
    fi

    total=$((total + 1))
    out_tsv="$OUT_DIR/${pmid}.mic.tsv"
    echo "=== [$total] PMID $pmid -> $out_tsv ==="

    if python3 src/amr_extraction/extract_excel_codegen.py \
        -o "$out_tsv" \
        --supp-dir "$pmid_dir"; then
        succeeded=$((succeeded + 1))
    else
        failed=$((failed + 1))
        failed_pmids+=("$pmid")
        echo "  FAILED: PMID $pmid (see output above)" >&2
    fi
done

echo
echo "Done. $succeeded/$total succeeded, $failed failed, $skipped supplement folder(s) skipped (no Excel files)."
if [ "$failed" -gt 0 ]; then
    echo "Failed PMIDs: ${failed_pmids[*]}" >&2
fi
[ "$failed" -eq 0 ]
