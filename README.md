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
|   `-- amr_excel_extraction/  # Python source code for extraction package
|       |-- excel_extractor.py
|       |-- llm.py
|       `-- schemas.py
`-- tests/             # Layered unit and integration test suite
    |-- conftest.py
    `-- test_excel_extractor.py
```

### Directory Details

- **`data/`**: Input literature files and evaluation benchmarks. The `data/starter/` directory contains curated evaluation papers organized by PMID, including raw supplementary files (Excel, XML, PDF), paper metadata, and BV-BRC ground truth TSV files where available.
- **`docs/`**: Project documentation, including corpus categorization and the testing guide ([docs/amr_excel_extraction_testing.md](docs/amr_excel_extraction_testing.md)).
- **`scripts/`**: Standalone scripts that use the `amr_extraction` package but aren't part of it - e.g. `query_pmids_to_find_ast/find_ast_evidence.py`, which takes a PMID list and finds/downloads AST evidence (see its own README for details), and `accuracy_metrics/runAllAcc.sh` for evaluating extraction accuracy against ground truth. Distinct from `src/` (the installable package) and `data/` (pure input/benchmark data).
- **`src/`**: Source code. Currently contains only the `amr_extraction` package, implementing the hybrid LLM sheet/column mapping and deterministic table unpivoting pipeline.
- **`tests/`**: Contains tests. See [docs/amr_excel_extraction_testing.md](docs/amr_excel_extraction_testing.md) for execution instructions.

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

