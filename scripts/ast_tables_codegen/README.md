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

**Accession columns are always empty.** `bioproject_accession`, `biosample_accession`,
`assembly_accession`, `genbank_accessions`, `refseq_accessions`, `sra_accession`, and
`other_accessions` will be blank in every row this script produces, even for tables that do
extract real per-isolate records. Checked directly: none of the main-text `ast_tables/*/*.tsv`
files in this repo contain anything that looks like a BioSample/SRA/BioProject/GenBank
accession (`SAMN*`, `SRR*`, `PRJNA*`, `GCA_*`, etc.) -- journal main-text tables report strain
names and clinical data, not deposited-database identifiers. Those almost always live in a
separate supplementary data-availability file instead, which is what
`extract_excel_codegen.py` (run against downloaded supplements) is for. This isn't a bug or a
prompt-tuning issue -- there's nothing for the LLM to find in these particular source tables.
Attaching accessions to main-text isolate records would require a deliberate cross-file join
against a paper's supplement/accession table, not just extraction from `ast_tables/` alone.

**Some `ast_tables/*.tsv` files are malformed and unreadable.** A few tables written by
`find_ast_evidence.py`'s table extraction have ragged rows (a stray tab inside a cell value)
that pandas can't parse (`Error tokenizing data. C error: Expected N fields...`). This script
catches that per-file and skips it rather than crashing the whole PMID or batch -- it shows up
as part of the "no valid records" bucket in the batch summary, not a separate error count.
