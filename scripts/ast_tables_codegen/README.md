# ast_tables_codegen

`extract_ast_tables_codegen.py` runs the same LLM code-gen approach as
`extract_excel_codegen.py` (ask Gemini to write a `transform_sheet(df)` pandas function,
execute it locally, QC-validate the result, retry once with the QC errors fed back if
anything fails), but against the already-extracted **main-text** AST tables under
`ast_tables/<pmid>/*.tsv` instead of downloaded Excel supplements.

Those TSVs come from `find_ast_evidence.py`'s step 4, which pulls any main-text tables that
look AST-related out of each paper's PMC full-text XML.

## Usage

Batch mode (default) processes every PMID folder under `ast_tables/`, writing one output TSV
per PMID into `andrew_ast/`. Just running it with no arguments uses the same
`ast_tables/` -> `andrew_ast/` pair already used elsewhere in this repo:

```bash
python scripts/ast_tables_codegen/extract_ast_tables_codegen.py
```

Single PMID's table folder only (mirrors `extract_excel_codegen.py`'s `--supp-dir`):

```bash
python scripts/ast_tables_codegen/extract_ast_tables_codegen.py \
    --tables-dir scripts/query_pmids_to_find_ast/output/ast_tables/29729180 \
    -o data/andrew_ast/29729180.ast_tables.tsv
```

See `python scripts/ast_tables_codegen/extract_ast_tables_codegen.py --help` for the rest
(`--tables-root`, `--outdir`, a single-table positional argument, `--antibiotics-list`,
`--pmid`).

Output uses the same `EXPECTED_OUTPUT_COLUMNS` schema as `extract_excel_codegen.py`'s
`andrew_ast/<pmid>.mic.tsv` files, so the two are safe to concatenate. Batch mode also writes
`<outdir>/<pmid>.transform_code.py` per PMID with the LLM-generated pandas code, for
inspection/debugging.

Requires `GOOGLE_API_KEY` -- this reuses `extract_excel_codegen.py`'s Gemini client and
prompt/QC logic directly, not `amr_extraction.llm`'s provider dispatch, so
`--llm-provider`/Ollama support from `find_ast_evidence.py` does not apply here.

## Known limitations

**Most main-text tables are aggregate summaries, not per-isolate data.** Unlike the raw
per-isolate spreadsheets `extract_excel_codegen.py` usually sees, many main-text AST tables
are already-aggregated (accuracy/concordance stats per drug, resistant-vs-susceptible counts
per species, etc.) with no per-isolate ID or accession at all. The QC rules require every
record to have an `isolate_id` or `accession`, so a purely aggregate table legitimately
produces zero valid records -- an accurate reflection of the source table, not a bug. In
practice, expect a majority of PMIDs to produce no output at all.

**Accession columns are empty right out of this script, but can be filled in afterward.**
`bioproject_accession`, `biosample_accession`, `assembly_accession`, `genbank_accessions`,
`refseq_accessions`, `sra_accession`, and `other_accessions` will be blank in every row this
script produces -- journal main-text tables report strain names and clinical data, not
deposited-database identifiers (checked directly: none of the main-text `ast_tables/*/*.tsv`
files in this repo contain anything that looks like a BioSample/SRA/BioProject/GenBank
accession). Those live in the paper's Data Availability statement / supplementary files
instead. There are now two ways to recover them after the fact, rather than from
`ast_tables/` alone:
  - `extract_excel_codegen.py`, run against downloaded supplements, if the paper has one with
    accessions in it.
  - `scripts/query_pmids_to_find_ast/match_isolates_to_biosample.py`, which takes the
    BioProject accession `find_ast_evidence.py` already found for a PMID, resolves its linked
    BioSamples from NCBI, and matches their `strain` attribute against this script's
    `isolate_id` values -- filling in `bioproject_accession`/`biosample_accession`/
    `sra_accession` for any isolate whose real strain name is recoverable this way. See that
    script's own docstring/README entry for usage; it requires network access this repo's
    sandboxed tooling doesn't have, so it's meant to be run from a normal terminal.

**Some `ast_tables/*.tsv` files have a merged/spanning sub-header line, or are otherwise
malformed.** A number of these tables have a second header-ish line before the real
per-column header row -- a leftover from a merged/spanned cell in the original HTML/XML table
(e.g. a single `MIC (µg/mL)` label spanning many drug columns). `read_ast_table()` detects and
skips exactly one such line when it's clearly narrower than the real header and data rows that
follow it (this was the root cause of a real bug: the isolate/strain-name column was getting
silently absorbed into pandas' index instead of becoming a real column, so extraction fell back
to generic `isolate_1`, `isolate_2`, ... labels instead of the paper's actual strain names). A
few tables have a genuine two-row header instead (two differently-shaped label rows that would
need to be merged, not discarded) -- those are deliberately left alone rather than risking a
wrong guess, and a few others have ragged rows pandas can't parse at all
(`Error tokenizing data. C error: Expected N fields...`). Both cases are caught per-file and
skipped rather than crashing the whole PMID or batch -- they show up as part of the "no valid
records" bucket in the batch summary, not a separate error count.
