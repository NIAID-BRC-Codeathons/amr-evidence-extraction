# AMR-Evidence Extraction, Integration, and Interoperability

**NIAID-BRCs AI Codeathon 2.0** · September 16–18, 2026 · Argonne National Laboratory

Extracting antimicrobial susceptibility and genotype–phenotype evidence from literature, harmonizing AMR and virulence databases, and combining that evidence with genome-based predictive models.

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

The AST-finder script's supplement downloader (`data/query_pmids_to_find_ast/find_ast_evidence.py`)
can fall back to a real headless-Chromium browser (via Playwright) when PMC's anti-bot page blocks
a plain download. That's an optional extra, since it pulls in a ~300MB browser binary:

```bash
pip install -e ".[browser]"
playwright install chromium
```

Skip this if you don't need it — the script works fine without it, just with more supplement
downloads reported as failures (or pass `--no-browser` to suppress the fallback explicitly).

Scripts under `data/` (like `data/query_pmids_to_find_ast/find_ast_evidence.py`) that use
`amr_extraction` add `src/` to `sys.path` themselves, so no separate install step is needed for
them beyond the one above — just make sure you've run `pip install -e .` from the repo root at
least once in whichever environment you're using.

The supplement-extraction pipeline (`amr_extraction.llm`) also needs a Gemini API key in the
`GOOGLE_API_KEY` environment variable. Get a free key from
[Google AI Studio](https://aistudio.google.com/apikey), then:

```bash
export GOOGLE_API_KEY="your-key-here"          # current terminal session only
# or, to persist it across terminals:
echo 'export GOOGLE_API_KEY="your-key-here"' >> ~/.zshrc && source ~/.zshrc
```

## Repository Structure

```
.
|-- data/              # Input literature corpora and benchmark datasets
|   `-- starter/       # Curated evaluation papers organized by PMID
|-- docs/              # Project documentation and developer guides
|   |-- paper_classification.md
|   `-- testing.md
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
- **`src/`**: Source code. Currently contains only the `amr_extraction` package, implementing the hybrid LLM sheet/column mapping and deterministic table unpivoting pipeline.
- **`tests/`**: Contains tests. See [docs/amr_excel_extraction_testing.md](docs/amr_excel_extraction_testing.md) for execution instructions.

