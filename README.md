# AMR-Evidence Extraction, Integration, and Interoperability

**NIAID-BRCs AI Codeathon 2.0** · September 16–18, 2026 · Argonne National Laboratory

Extract AST data from supplementary data in published articles.

Project page: https://niaid-brc-codeathons.github.io/projects/amr-evidence-extraction/

## Goal (proposed)

Extract antimicrobial susceptibility and genotype–phenotype evidence from literature, harmonize AMR and virulence databases

## Three-Day MVP (proposed)

Use *Staphylococcus aureus* as demonstration organisms. Screen a defined PubMed/PMC corpus, extract AST measurements and genotype associations, normalize drug names and breakpoints, and link the evidence to BV-BRC genomes, AMRFinderPlus entities, CARD, VFDB, and related resources.

## Evaluation (proposed)

Use BV-BRC curated data as the truth set. Report extraction precision/recall, accession-linking accuracy, prediction F1/AUROC, provenance completeness, and disagreement with current AMR annotations.

## Membership

- Marcus Nguyen Co-team-lead
- Arjun Prasad  Co-team-lead
- Andrew Davis
- Liliana Brown

## Setup

Requires Python 3.10+. From the repo root:

```bash
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -e .
```

`pip install -e .` installs this package (`amr_extraction`) in editable mode along with its
dependencies (`pandas`, `openpyxl`, `pydantic`, `google-genai`), as declared in `pyproject.toml`.
It must be run from the repo root — running it from a subdirectory (e.g. `data/`) fails with
*"does not appear to be a Python project"* since that's where `pyproject.toml` lives.

For running the test suite too, install the `dev` extra instead:

```bash
pip install -e ".[dev]"
```

The AST-finder script's supplement downloader (`scripts/query_pmids_to_find_ast/find_ast_evidence.py`)
can fall back to a real headless-Chromium browser (via Playwright) when PMC's anti-bot page blocks
a plain download. That's an optional extra, since it pulls in a ~300MB browser binary:

```bash
pip install -e ".[browser]"
playwright install chromium
```

Skip this if you don't need it — the script works fine without it, just with more supplement
downloads reported as failures (or pass `--no-browser` to suppress the fallback explicitly).

Scripts under `scripts/` (like `scripts/query_pmids_to_find_ast/find_ast_evidence.py`) that
use `amr_extraction` add `src/` to `sys.path` themselves, so no separate install step is needed
for them beyond the one above — just make sure you've run `pip install -e .` from the repo root
at least once in whichever environment you're using.

The supplement-extraction pipeline (`amr_extraction.llm`) also needs a Gemini API key in the
`GOOGLE_API_KEY` environment variable. Get a free key from
[Google AI Studio](https://aistudio.google.com/apikey), then:

```bash
export GOOGLE_API_KEY="your-key-here"          # current terminal session only
# or, to persist it across terminals:
echo 'export GOOGLE_API_KEY="your-key-here"' >> ~/.zshrc && source ~/.zshrc
```

Google's free tier caps requests **per day**, not just per minute (20 requests/day for
`gemini-3.6-flash` at time of writing) — the supplement-extraction step makes 2 Gemini calls per
spreadsheet sheet, so it's easy to exhaust this processing even a handful of files. If you hit
this, `find_ast_evidence.py` stops immediately (see its README for details) rather than retrying
uselessly; re-run later once the quota resets, or set `GEMINI_MODEL` to a different model, which
has its own separate daily quota.

### Alternative: a local model via Ollama (no API key, no daily quota)

Instead of Gemini, the supplement-extraction step can run entirely against a local model through
[Ollama](https://ollama.com) — no API key, no network egress for the LLM calls, and no daily
quota to run into. Trade-off: local models in the size that fits on a laptop (7B-8B parameters)
follow a strict JSON schema less reliably than Gemini, so expect more failed/retried extractions.

```bash
# 1. Install the Ollama app (https://ollama.com/download) and make sure it's running
#    (the menu-bar app runs the `ollama serve` daemon for you; or run `ollama serve` yourself).

# 2. Pull a model. Anything Ollama's library has works, e.g.:
ollama pull llama3.1:8b
# ...or any GGUF model from Hugging Face:
ollama pull hf.co/bartowski/Qwen2.5-7B-Instruct-GGUF

# 3. Install the ollama Python client into this project's environment:
pip install -e ".[ollama]"

# 4. Point find_ast_evidence.py at it:
python find_ast_evidence.py Staph.pmid_only.txt --no-download \
    --llm-provider ollama --llm-model llama3.1:8b
```

`--llm-provider`/`--llm-model` can also be set via the `LLM_PROVIDER`/`OLLAMA_MODEL` (or
`GEMINI_MODEL`) environment variables instead of flags. See `find_ast_evidence.py --help` for
details, and its own README for more on how the extraction step uses whichever provider is active.

### Alternative: virtualenvwrapper

If you'd rather manage this project's environment with `mkvirtualenv`/`workon`/`rmvirtualenv`
(conda-`env-list`-style) instead of activating `venv/` by hand, that works fine too and doesn't
touch the plain `venv/` setup above — pick whichever one you actually use.

```bash
# One-time: install virtualenvwrapper (Homebrew avoids Python's "externally managed
# environment" restriction, which a plain `pip install` will otherwise hit on newer macOS):
brew install virtualenv virtualenvwrapper

# Hook it into your shell — add to ~/.zshrc (or ~/.bash_profile):
cat >> ~/.zshrc <<'RCEOF'

# --- virtualenvwrapper ---
export WORKON_HOME=$HOME/.virtualenvs
export VIRTUALENVWRAPPER_PYTHON=$(which python3)
source $(brew --prefix)/bin/virtualenvwrapper.sh
RCEOF
source ~/.zshrc

# Create this project's environment (creates + auto-activates a new env under $WORKON_HOME,
# separate from any venv/ folder already in the repo):
cd path/to/amr-evidence-extraction
mkvirtualenv amr-evidence-extraction
pip install -e ".[browser]"
playwright install chromium

# Optional: make `workon amr-evidence-extraction` also cd here automatically
setvirtualenvproject $WORKON_HOME/amr-evidence-extraction $(pwd)
```

Day to day:

```bash
workon amr-evidence-extraction   # activate (and cd here, if you ran setvirtualenvproject)
workon                            # list every environment, like `micromamba env list`
deactivate                        # leave it
rmvirtualenv amr-evidence-extraction   # delete it entirely
```

## Repository Structure

```
.
|-- data/              # Input literature corpora and benchmark datasets
|   `-- starter/       # Curated evaluation papers organized by PMID
|-- docs/              # Project documentation and developer guides
|   |-- paper_classification.md
|   `-- testing.md
|-- scripts/           # Standalone pipeline scripts (not part of the installable package)
|   |-- accuracy_metrics/
|   |   |-- computeAccuracy1.py
|   |   |-- extractErrors.py
|   |   |-- runAllAcc.sh
|   |   `-- statToTab.py
|   `-- query_pmids_to_find_ast/
|       |-- find_ast_evidence.py
|       `-- README_ast_finder.md
|-- src/               
|   `-- amr_extraction/        # Python source code for extraction package
|       |-- antibiotics.list.txt
|       |-- excel_extractor.py
|       |-- extract_excel_codegen.py
|       |-- llm.py
|       `-- schemas.py
`-- tests/             # Layered unit and integration test suite
    |-- conftest.py
    |-- test_check_one_isolate.py
    |-- test_excel_extractor.py
    `-- test_extract_excel_codegen.py
```

### Directory Details

- **`data/`**: Input literature files and evaluation benchmarks. The `data/starter/` directory contains curated evaluation papers organized by PMID, including raw supplementary files (Excel, XML, PDF), paper metadata, and BV-BRC ground truth TSV files where available.
- **`docs/`**: Project documentation, including corpus categorization and the testing guide ([docs/amr_excel_extraction_testing.md](docs/amr_excel_extraction_testing.md)).
- **`scripts/`**: Standalone scripts that use the `amr_extraction` package but aren't part of it - e.g. `query_pmids_to_find_ast/find_ast_evidence.py`, which takes a PMID list and finds/downloads AST evidence (see its own README for details), and `accuracy_metrics/runAllAcc.sh` for evaluating extraction accuracy against ground truth. Distinct from `src/` (the installable package) and `data/` (pure input/benchmark data).
- **`src/`**: Source code. Contains the `amr_extraction` package and `extract_excel_codegen.py`, implementing LLM-driven code generation extraction, AST table parsing, header detection, and accession mapping.
- **`tests/`**: Contains tests. See [docs/amr_excel_extraction_testing.md](docs/amr_excel_extraction_testing.md) for execution instructions.

## Excel AST Extraction with Code Generation (`extract_excel_codegen.py`)

The script `src/amr_extraction/extract_excel_codegen.py` extracts antimicrobial susceptibility testing (AST) data (MIC values and SIR interpretations) from supplementary Excel files (`.xlsx`, `.xls`).

Instead of sending raw table rows through LLM context windows, it inspects spreadsheet structure, prompts Gemini (`gemini-3.8-flash` by default) to generate Python/pandas transformation code (`transform_sheet(df)`), and executes the code locally.

### Key Capabilities

- **Automated Sheet Discovery**: Detects worksheets that contain AST data or processes a specified sheet.
- **Header Flattening**: Merges multi-level and merged header cells (such as antibiotic names spanning MIC and SIR columns).
- **Stacked Table Detection**: Identifies pathogenic sheets with multiple vertically stacked tables and handles each panel.
- **Local Execution and Self-Correction**: Runs generated transformation code locally with QC checks. If execution or validation fails, error feedback is returned to Gemini for automated repair.
- **Multi-Pass Ensembling**: Supports running multiple code generation passes per sheet (`--num-passes`), retaining consensus records and dropping conflicting values.
- **Metadata and Accession Linking**: Scans other worksheets and supplementary spreadsheets (`--supp-dir`) to map isolate IDs to NCBI BioSample accessions (`SAMN*`, `SAMEA*`, `SAMD*`) and other public accessions (BioProject, Assembly, SRA, GenBank, RefSeq).
- **Drug Standardization**: Normalizes extracted antibiotic names against standard nomenclature (`src/amr_extraction/antibiotics.list.txt`).

### Usage

Requires `GOOGLE_API_KEY` to be set in your environment.

```bash
# Basic usage: process a single Excel file
python src/amr_extraction/extract_excel_codegen.py path/to/supplement.xlsx -o output.mic.tsv

# Process an entire directory of supplements for a PMID
python src/amr_extraction/extract_excel_codegen.py --supp-dir data/starter/31266463/supplements -o 31266463.mic.tsv

# Multi-pass ensembling with saved transformation code
python src/amr_extraction/extract_excel_codegen.py path/to/supplement.xlsx \
    --num-passes 3 \
    --save-code transform.py \
    -o output.mic.tsv
```

### Command-Line Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `excel_file` | Positional | None | Path to Excel file (optional if `--supp-dir` is provided). |
| `-s`, `--sheet` | Option | None | Specific sheet name to process (default: auto-discover). |
| `-o`, `--output` | Option | `gemini_ast_codegen.tsv` | Output TSV file path. |
| `--save-code` | Option | `generated_transform.py` | Path to save generated Python transformation script. |
| `--supp-dir` | Option | None | Directory with supplementary spreadsheets to scan for data or BioSample metadata. |
| `--antibiotics-list` | Option | `antibiotics.list.txt` | Text file of standard antibiotic names for normalization. |
| `--pmid` | Option | None | PubMed ID (inferred from input path if omitted). |
| `--num-passes` | Option | `1` | Number of code generation passes to run and ensemble. |
| `--llm-provider` | Option | `gemini` | LLM backend: `gemini` or `argo` (default: `LLM_PROVIDER` env var, or `gemini`). |
| `--model` | Option | None | LLM model override (default: `GEMINI_MODEL` / `ARGO_MODEL` env var, or provider default). |
| `--argo-user` | Option | None | Argonne username / bearer token for Argo (default: `ARGO_USER` env var). |

### Output Files

1. **TSV Output (`-o`)**: Contains standardized AST records with the following columns:
   - `pmid`: PubMed ID.
   - `file_name`: Name of the source supplementary file.
   - `sheet_name`: Name of the worksheet.
   - `isolate_id`: Local isolate identifier.
   - Accession columns: `bioproject_accession`, `biosample_accession`, `assembly_accession`, `genbank_accessions`, `refseq_accessions`, `sra_accession`, `other_accessions`.
   - AST measurements: `drug`, `mic_sign` (`=`, `>`, `>=`, `<`, `<=`), `mic` (numeric value), `sir_call` (`S`, `I`, `R`, `SDD`, `NS`).
   - `notes`: Extraction notes and provenance details.
2. **Companion Log (`<output>.log`)**: Records execution time, token usage, LLM calls, pass summaries, consensus counts, and conflict details.
3. **Generated Code (`--save-code`)**: Standalone Python script with the generated `transform_sheet` function for inspection and reproducibility.

## Accuracy Metrics Scripts (`scripts/accuracy_metrics`)

The `scripts/accuracy_metrics/` directory contains scripts to evaluate extracted AST data against ground truth datasets.

### `runAllAcc.sh`

The shell script `runAllAcc.sh` will compare a set of paper runs against ground truth data (both aggregated across all papers and individually per paper).

To run the script:

```bash
cd scripts/accuracy_metrics
bash runAllAcc.sh
```

Steps performed by `runAllAcc.sh`:

1. **Aggregate Paper Results**: Concatenates extracted TSVs from individual paper runs (`../../data/andrew_ast/*.tsv`) into `output.all.tsv`.
2. **Compute Aggregate Accuracy**: Runs `computeAccuracy1.py` comparing `output.all.tsv` against ground truth (`../../data/rawTSV/dataset.staph.merged.txt`), generating full match rows in `output.all.comp.tsv` and summary metrics in `output.all.acc.txt`.
3. **Tabulate Metrics**: Runs `statToTab.py` to convert `output.all.acc.txt` into a tabular format in `output.all.acc.tsv`.
4. **Extract Errors**: Runs `extractErrors.py` on `output.all.comp.tsv` to output rows with incorrect SIR or MIC values to `output.all.err.tsv`.
5. **Per-Paper Evaluation**: Iterates over each individual paper TSV in `../../data/andrew_ast/*.tsv`, running `computeAccuracy1.py` and `statToTab.py` to write per-paper comparison tables and statistics into the `accuracies/` directory.

### `check_one_isolate.sh`

The shell script `check_one_isolate.sh` runs end-to-end extraction and accuracy evaluation for a single paper/PMID. It extracts AST data from supplementary Excel files using `extract_excel_codegen.py` and evaluates extraction accuracy against ground truth using `computeAccuracy1.py`, `statToTab.py`, and `extractErrors.py`.

Usage:

```bash
# Can be run from repo root or inside scripts/accuracy_metrics
bash scripts/accuracy_metrics/check_one_isolate.sh <PMID> [SUPP_DIR] [GROUND_TRUTH]
```

Arguments:

- `<PMID>` (required): The PubMed ID to evaluate.
- `[SUPP_DIR]` (optional): Directory containing supplementary Excel files (.xlsx, .xls). If omitted, automatically checks `scripts/query_pmids_to_find_ast/output/supplements/<PMID>` and `data/starter/<PMID>/supplements`.
- `[GROUND_TRUTH]` (optional): Ground truth file. Defaults to `data/rawTSV/dataset.staph.merged.txt`.

Outputs generated under `scripts/accuracy_metrics/output/<PMID>/`:

- `<PMID>.mic.tsv`: Extracted AST table.
- `<PMID>.transform_code.py`: LLM-generated Python transformation script.
- `<PMID>.comp.tsv`: Detailed comparison table against ground truth.
- `<PMID>.stats.txt`: Summary accuracy metrics report.
- `<PMID>.stats.tsv`: Tabulated accuracy metrics.
- `<PMID>.err.tsv`: Rows with erroneous SIR or MIC calls.
