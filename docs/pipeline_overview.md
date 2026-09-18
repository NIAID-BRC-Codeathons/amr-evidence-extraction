# Pipeline Overview

This diagram traces one PMID from the initial literature search through per-isolate AST
extraction, NCBI accession cross-referencing, and evaluation against BV-BRC ground truth.

```mermaid
flowchart TD
    A["PMID list"] --> B["Fetch PubMed metadata<br/>and PMC identifiers"]
    B --> C["Optional BV-BRC lookup<br/>paper-associated genomes and accessions"]
    C --> D{"PMC full-text XML available?"}
    D -->|No| M["Flag for manual lookup"]
    D -->|Yes| E["Screen for AST evidence<br/>and identify tables / supplements"]

    E --> F["Download supplementary files"]
    E --> T["Save main-text AST tables"]
    E --> DA["Scrape Data Availability statement<br/>for BioProject / BioSample / SRA accessions<br/>(paper-level, not per-isolate)"]

    subgraph Extraction["Extract per-isolate measurements"]
        F --> X["Inspect Excel sheets<br/>prefer MIC sheets; otherwise SIR"]
        X --> G["Gemini generates<br/>table-transformation code"]
        G --> H["Run code on full sheet"]
        H --> Q["Validate records<br/>one repair attempt if needed"]
        Q --> J["Optional multiple-pass consensus"]
        J --> K["Join isolate records to accession<br/>metadata across supplementary spreadsheets"]

        T --> L["Main-text codegen extractor<br/>generate → execute → validate"]

        X -. Alternative route .-> O["LLM maps column roles<br/>deterministic extraction"]
        O --> P["Separate AST-record TSV"]
    end

    K --> N["Standardized per-paper TSV<br/>isolate, accessions, drug, MIC and SIR"]
    L --> N

    subgraph AccessionMatch["Cross-reference isolates to NCBI accessions"]
        N --> Y{"BioProject accession known for this PMID?<br/>(from BV-BRC lookup or Data Availability scrape)"}
        C -.-> Y
        DA -.-> Y
        Y -->|No| N2["Leave accession columns as extracted"]
        Y -->|Yes| Z["Resolve BioProject → linked BioSamples<br/>(NCBI esearch / elink / esummary)"]
        Z --> AA["Match BioSample strain name<br/>to isolate_id"]
        AA --> AB["Fill bioproject / biosample / sra<br/>accession columns (exact matches only)"]
    end

    N2 --> R
    AB --> R

    subgraph Evaluation["Evaluate extraction"]
        R["Match accession → genome<br/>then genome + antibiotic"]
        GT["BV-BRC curated ground truth"] --> R
        R --> S["Compare SIR and MIC independently"]
        S --> U["Detailed comparison TSV"]
        S --> V["Per-paper and aggregate metrics"]
        U --> W["Extract rows with incorrect SIR or MIC"]
    end
```

## Notes on the accession cross-referencing step

- Implemented in `scripts/query_pmids_to_find_ast/match_isolates_to_biosample.py`.
- The BioProject accession going into node `Y` can come from either the BV-BRC genome lookup
  (`C`, usually the more reliable of the two since it's tied to an actual matched genome) or the
  Data Availability scrape (`DA`, paper-level text mining -- see
  `scripts/query_pmids_to_find_ast/README_ast_finder.md`'s note on
  `data_availability_accessions` for why that one needs a sanity check before trusting it blindly).
- Matching is strain-name based (NCBI BioSample's `strain`/`isolate` attribute vs. this
  pipeline's `isolate_id`), not accession-based -- there's no accession to match against until
  after this step runs. Only exact (case-insensitive, whitespace-normalized) matches get written
  back by default; `--apply` never overwrites an accession column that's already non-blank, which
  is why a supplement sheet that already had its own accessions (e.g. from a BV-BRC/PATRIC
  metadata sheet) is left untouched even when this step independently finds the same answer.
- This depends on live network access to `eutils.ncbi.nlm.nih.gov`, which isn't reachable from
  this repo's own sandboxed tooling -- it's meant to be run from a normal terminal, per PMID, as
  a follow-up pass after extraction rather than as part of the automated pipeline above.
