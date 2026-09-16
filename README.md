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

