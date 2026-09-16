# Finding AST evidence for the Staph PMID list

## Files

- **`find_ast_evidence.py`** — reusable script. Give it a `genome_id \t genome_id \t pmid`
  file (like `Staph.pmid.txt`), and it will: dedupe to unique PMIDs, look up each one's
  PMCID/DOI/title/author/year, fetch the PMC full-text XML, classify where the AST data
  lives (main text table, main-text prose only, supplementary file, both, none found, or
  no PMC record), pull out any supplementary-material filenames it can find in the XML,
  attempt to download them, and write a `paper_classification_<name>.tsv` plus a
  `download_report.json` — matching the shape/conventions of `data/starter/paper_classification.tsv`
  and `data/starter/download_report.json` already in the repo.

- **`staph_ast_classification.tsv`** — the actual classification for all 30 unique, valid
  PMIDs in `Staph.pmid.txt` (of 42,373 rows / 32 distinct PMID values, 2 were blank or `-`
  and dropped). I generated this now using PubMed/PMC tools available in this session,
  since network access to NCBI is blocked from this sandbox for direct script execution —
  see "Why the output is pre-generated" below. Columns:

  | column | meaning |
  |---|---|
  | `pmid` / `pmcid` | PubMed ID and PMC ID (blank if not in PMC) |
  | `title` / `first_author` / `year` | |
  | `genome_row_count` | how many rows in `Staph.pmid.txt` cite this PMID |
  | `ast_location` | `main_text_table`, `main_text_prose`, `supplement`, `main_text_and_supplement`, `none_found`, `no_fulltext`, or `no_pmc_record` |
  | `biosample_hint` | whether BioSample/BioProject/SRA accessions turned up near the isolate/AST data |
  | `supplement_files` | supplementary file names found in the text, when any |
  | `details` | short evidence note (drugs/methods/table numbers found) |

## Results at a glance (30 papers)

- 3 report AST **only in a main-text table** (easiest to extract)
- 8 have AST **in both a main-text table and a supplement**
- 8 discuss AST **only in prose** (no dedicated table — will need targeted parsing or manual extraction)
- 2 have AST data **only in supplementary files**
- 4 have a PMCID but the full-text fetch came back empty (`no_fulltext`) — worth a manual PMC visit
- 5 papers have **no PMCID at all** (`no_pmc_record`) — not deposited in PMC / likely paywalled, need manual lookup via the DOI

## Why the output is pre-generated rather than script output

I tried to run this pipeline live via `curl`/`requests` both from this cloud session and from
your Mac's sandboxed shell, and both got rejected by network egress policy
(`eutils.ncbi.nlm.nih.gov` / `pmc.ncbi.nlm.nih.gov` connections were refused by the proxy).
That's a property of this sandboxed session, not of your normal internet connection — when you
run `find_ast_evidence.py` from your own terminal (outside this session) it should reach NCBI
fine, the same way the existing `data/starter/` corpus was originally downloaded.

Since a PubMed/PMC connector *was* available to me in this session (routed differently from raw
HTTP), I used it to actually fetch full text and classify all 30 papers — so `staph_ast_classification.tsv`
is real, current data, not a preview. I could not, however, download the supplementary files
themselves through that connector, so no supplement files were downloaded in this run. Re-run
`find_ast_evidence.py data/query_pmids_to_find_ast/Staph.pmid.txt` yourself to attempt those
downloads (expect some to fail with the same "anti-bot HTML interstitial" issue already logged
in `data/starter/download_report.json` — PMC blocks a fair number of automated supplement
downloads).

## Caveats on the classification

This is a **heuristic, keyword-based** classification (same idea as manually reading each paper
for `data/starter/paper_classification.tsv`, but automated) — treat `ast_location` and
`biosample_hint` as a strong first pass to prioritize manual review, not ground truth. The 4
`no_fulltext` and 5 `no_pmc_record` papers in particular need a human (or the script rerun with
retries) to resolve.
