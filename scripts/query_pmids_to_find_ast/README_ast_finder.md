# Finding AST evidence for the Staph PMID list

## What's new in this version

You asked for three things on top of the original script — all added:

1. **BV-BRC genome accessions per PMID.** For each PMID, `fetch_bvbrc_genomes()` queries
   `www.bv-brc.org/api/genome/` for genomes whose `publication` field references that PMID, and
   pulls `genome_id`, `bioproject_accession`, `biosample_accession`, `assembly_accession`,
   `genbank_accessions`, `refseq_accessions` into new output columns. It also cross-checks
   whether any of those accessions actually appear in the paper's own full text
   (`accessions_confirmed_in_text`).
2. **Real AST table extraction, not just a location guess.** `extract_tables_from_xml()` parses
   every `<table-wrap>` out of the PMC JATS XML (label, caption, and every row/cell as text) and
   saves the ones that look like genuine phenotypic AST tables — as opposed to a genotype/AMR-gene
   table that just happens to share the word "resistance" — to `ast_tables/<pmid>/<label>.tsv`.
   I validated this against real papers from your `data/starter/` set (see "Validation" below);
   it correctly pulled a 21-drug MIC table (PMID 40867962) with drug names, MIC values, and S/R
   calls intact.
3. **Input is now PMID-only**, and the script wires directly into the repo's existing
   `amr_extraction.excel_extractor` (LLM-based column mapping) to turn any downloaded `.xlsx`/`.xls`
   supplements into normalized, per-isolate AST records — written to `ast_records_extracted.tsv`.
   This needs `GOOGLE_API_KEY` set, plus the packages in `requirements.txt` installed (see
   "Installing dependencies" below — you do **not** need `pip install -e .`; the script adds
   `../../src` to `sys.path` itself, which I verified resolves correctly from
   `scripts/query_pmids_to_find_ast/find_ast_evidence.py`). PDF/docx/csv supplements are downloaded
   but **not** run through the extractor — that module only handles Excel workbooks — the script
   notes this per-file in the `extraction_notes` column rather than silently skipping.

## New output columns (in `paper_classification_<name>.tsv`)

| column | meaning |
|---|---|
| `bvbrc_genome_ids` | BV-BRC genome IDs linked to this PMID |
| `bioproject_accessions` / `biosample_accessions` / `assembly_accessions` / `genbank_accessions` / `refseq_accessions` | from BV-BRC, semicolon-separated |
| `accessions_confirmed_in_text` | yes/no/unclear — did any of those accessions actually turn up in the paper's own text |
| `ast_table_files` | paths to extracted main-text AST table TSVs (real row/column data, not just a flag) |
| `ast_records_extracted` | count of normalized AST records pulled from this paper's downloaded xlsx/xls supplements |
| `extraction_notes` | per-file notes from the supplement extraction step (extracted N records / skipped format / failed) |
| `ast_location` | now includes a new value: `no_fulltext_restricted` (see below) |

Plus a new file, `ast_records_extracted.tsv`, with one row per extracted isolate-drug AST
measurement across every paper (isolate name, drug, MIC operator/value, S/I/R call, accession,
source file, pmid), when any xlsx/xls supplements were both downloaded and successfully parsed.

## New: a `supplement_paths` column, and rate-limit retries for the LLM extraction step

`paper_classification_<name>.tsv` now has a `supplement_paths` column — the local file path of
every downloaded supplement for that PMID (semicolon-separated, matching the order of
`supplement_files`). It's populated from whatever's actually on disk under
`<outdir>/supplements/<pmid>/` at write time, so it's accurate even on a `--no-download` rerun
against files a previous run already fetched.

Also fixed: the LLM extraction step (`extract_ast_from_supplements`) was failing outright on
`429 RESOURCE_EXHAUSTED` (Gemini's per-minute rate limit on the free tier) and occasional
`503 UNAVAILABLE` (transient overload) errors, with no retry. `query_structured()` in
`src/amr_extraction/llm.py` now retries those two specific errors with backoff (10s, 20s, 45s,
90s — 4 attempts before giving up), and `find_ast_evidence.py` adds a short pause between files
so a multi-sheet workbook (which makes 2 Gemini calls per sheet) is less likely to trigger the
per-minute cap in the first place. Everything else (a real 400, a parsing failure, etc.) still
fails immediately and shows up in `extraction_notes` as before — retrying those wouldn't help.

**Correction, found on a real run:** not every `429` is the per-minute limit the retry logic
above was built for. Google's free tier also enforces a **daily** cap per model (as of writing,
20 requests/day for `gemini-3.6-flash`) — a 429 for that reason looks identical at first glance
(same status code, same-shaped "retry in Ns" hint), but no amount of backoff fixes it until the
quota resets, so the retry logic was burning ~165s (10+20+45+90s) on every single file, only to
fail every time, for the rest of the run. Google's error response does distinguish the two
internally via a `quotaId` field (`...PerDayPerProjectPerModel-FreeTier` vs.
`...PerMinutePerProjectPerModel...`), so `query_structured()` now checks that specifically and,
for a daily-quota 429, raises a distinct `DailyQuotaExhausted` immediately with **zero** retries.
`extract_ast_from_supplements()` catches that and stops the whole extraction step right there —
marking every remaining file with a short "skipped (daily Gemini quota exhausted this run)" note
instead of attempting (and failing) each one — rather than ever getting to a hundreds-of-seconds
death-by-a-thousand-retries. Files already downloaded aren't lost: re-run with `--no-download`
once the quota resets (or with `GEMINI_MODEL` set to a different model — each has its own
separate daily allowance) to pick up extraction where it left off.

## New: `--llm-provider` — swap Gemini for a local Ollama model

The extraction step (step 6, `extract_ast_from_supplements`) no longer hardcodes Gemini.
`amr_extraction.llm.query_structured()` now dispatches to one of two backends based on
`--llm-provider` (or the `LLM_PROVIDER` env var, same effect):

- `gemini` (default) — unchanged behavior, including the retry/daily-quota logic described above.
  Needs `GOOGLE_API_KEY`.
- `ollama` — sends the same prompt + JSON schema to a locally-running
  [Ollama](https://ollama.com) daemon via the `ollama` Python package's `chat(..., format=<json
  schema>)`, which constrains the model's output to that schema, then parses the result the same
  way as the Gemini path (`response_schema.model_validate_json(...)`). No API key, no per-minute
  or daily quota — it's just calling `localhost:11434`. Needs `pip install -e ".[ollama]"` and
  `ollama pull <model>` done ahead of time, and the daemon actually running (`ollama serve`, or
  just have the Ollama app open).

`--llm-model` overrides the model name for whichever provider is active (`GEMINI_MODEL` /
`OLLAMA_MODEL` env vars do the same). Example:

```bash
python find_ast_evidence.py Staph.pmid_only.txt --no-download \
    --llm-provider ollama --llm-model llama3.1:8b
```

Both providers are called through the exact same `query_fn` signature
(`query_fn(prompt=..., response_schema=...)`) that `excel_extractor.py` already used, so nothing
else in the extraction pipeline (sheet classification, column mapping, MIC parsing) changed — only
which backend answers the prompt. `DailyQuotaExhausted` (see above) is Gemini-specific and is
never raised on the Ollama path; a failed Ollama call (daemon not running, model not pulled, bad
JSON back) raises a plain `RuntimeError`/`ValueError` with a message telling you what to check,
and is caught per-file by the existing `except Exception` in `extract_ast_from_supplements()`
(so one bad file doesn't stop the whole run the way a Gemini daily-quota exhaustion does).

Worth knowing before you reach for this: a 7B-8B local model is noticeably less reliable at
strictly following a JSON schema than Gemini is, so expect a higher rate of "extraction failed"
notes on the Ollama path, especially on messier spreadsheets. It's a good option when you're
blocked on Gemini's daily quota and want to keep moving, less good as a wholesale replacement if
accuracy matters more than availability.

## Supplement downloads: PMC's anti-bot challenge, and the browser fallback

If `supplement_downloaded` kept coming back 0 for you, here's why, and what's now fixed.

PMC's supplement-download endpoint (`pmc.ncbi.nlm.nih.gov/.../bin/...`) sits behind an anti-bot
front end ("cloudpmc-viewer") that runs a genuine **client-side JavaScript proof-of-work
challenge** before it'll serve the file — it returns an HTML page titled "Preparing to
download ..." containing a `window.ncbi.pmc.pow.init(...)` call instead of the actual file. No
plain HTTP client (this script's normal `urllib`-based path included) can execute that JS, so it
was failing every single file, 100% of the time, regardless of headers/User-Agent/retries — that
was a real, unfixable-at-the-HTTP-level block, not a bug in the earlier rounds of fixes.

The fix: `download_supplements()` now falls back to a real headless-Chromium browser (via
[Playwright](https://playwright.dev/python/)) for exactly the files that hit this specific
interstitial. It loads the article page first (so the PoW cookie gets set the way a real
browser visit sets it), then requests the file and captures the resulting download. Plain HTTP
is still tried first for every file — the browser only launches (once, reused across files) if
something actually needs it, so runs with no anti-bot blocks pay no extra cost.

This needs the optional `browser` dependency group and a one-time browser install — see
"Installing dependencies" below. Without it, or with `--no-browser`, the script behaves exactly
as before: plain-HTTP-only, with anti-bot blocks reported as failures in `download_report.json`.

**Also fixed: the LLM extraction step was silently failing on every xlsx file** with a 404 —
`src/amr_extraction/llm.py`'s `DEFAULT_MODEL` was hardcoded to `gemini-2.5-flash`, which Google
retired for new API keys; the error message itself named `gemini-3.6-flash` as the replacement,
so that's the new default (override with the `GEMINI_MODEL` env var if it needs to change again).
Also, `extract_ast_from_supplements()` now runs whenever `--no-extract` isn't passed, instead of
also requiring that downloads happened in the same run — it only ever read from files already on
disk under `<outdir>/supplements/`, so there was no reason it couldn't re-run against files
downloaded in an earlier run. That means after a model/API-key fix like this one, you can re-run
with `--no-download` to re-extract from what's already downloaded, without going through PMC (and
its anti-bot challenge) again.

**I could not test the actual PoW-solving behavior myself** — my sandbox's network proxy blocks
`pmc.ncbi.nlm.nih.gov` outright for Chromium too (confirmed via a live Playwright test:
`net::ERR_TUNNEL_CONNECTION_FAILED`), the same restriction that blocked plain `curl`/`urllib`
earlier. I did verify the fallback *wiring* is correct — with the browser call mocked out, a file
that fails plain HTTP with an anti-bot error correctly triggers the browser fallback, gets
written to disk on a simulated success, and reports a combined error message on a simulated
failure; `--no-browser` correctly skips constructing the browser at all. Please run a real
download on your Mac (which has normal PMC access) and let me know the new
`supplement_downloaded` numbers / any browser-related warnings — if PMC's challenge has changed
shape since I inspected it, or the download event isn't captured the way I expect for some file
types, that'll only show up on a real run.

## A real limitation this surfaced: some publishers block full-text XML entirely

While validating against your `data/starter/` papers, I found PMID 27381390 (an ASM journal
article) returns **only front matter** from `efetch` — literally an XML comment saying *"The
publisher of this article does not allow downloading of the full text in XML form"* — even
though the article and its supplements are readable on the PMC website. The script now detects
this (`<body>` missing) and reports it honestly as `ast_location = no_fulltext_restricted`
instead of silently falling back to a low-confidence guess from the abstract alone. Papers with
this status need a manual look at their PMC article page.

## Validation

I don't have live network access to NCBI/BV-BRC from this session (same sandbox restriction as
before), so I couldn't run the script end-to-end here. I did validate the classification and
table-extraction logic against four of your **existing** `data/starter/*/fulltext.xml` files,
whose correct classification you already know from `docs/paper_classification.md`:

- **PMID 40867962** (known: `xml_text`, main-text Table 1 has 21-drug MIC data) →
  script correctly extracted Table 1 with real drug names/MIC values/S-R calls, classified
  `main_text_table`. ✅
- **PMID 27381390** (publisher blocks full-text XML) → correctly flagged
  `no_fulltext_restricted` after I added that check. ✅
- **PMID 34515028 / 35651495** (known: AST mainly in supplement, main text has aggregate/genotype
  tables) → the script's table filter now correctly excludes a genotype "AMR profiles"/"resistance
  genes" table that superficially shares AST vocabulary, but it can still call a main-text
  *aggregate* resistance-percentage table "AST" alongside the real supplement — which isn't
  wrong exactly (it is AST data, just not the per-isolate data), but treat `ast_table_files` as a
  starting point to skim, not ground truth.

I could not test `fetch_bvbrc_genomes()` or the excel_extractor wiring against live data at all
(no network here) — I did confirm the `sys.path` fix makes `amr_extraction` importable from the
script's location, and that it degrades cleanly (clear warning, empty result, no crash) when
`GOOGLE_API_KEY` isn't set. Please run it for real and send me the console output / any WARNING
lines if BV-BRC comes back empty — the query syntax there is my best guess at BV-BRC's RQL
(`https://www.bv-brc.org/api/doc/`), not something I could verify.

## How the main-text AST tables are found and pulled

For each PMID with a PMCID, the script fetches the paper's full-text XML from PMC (the JATS
format PMC's API serves, not the PDF layout) and does two things with it:

1. **Finds every table.** PMC's XML marks each table as a `<table-wrap>` block, with a `<label>`
   (e.g. "Table 2"), a `<caption>`, and the actual `<table><tr><td>...` grid. `extract_tables_from_xml()`
   walks every `<table-wrap>` in the document and pulls out the label, caption, and every row's
   cell text — this is real extracted content, not just "the paper has a table" — so a table like
   a 21-drug MIC susceptibility table comes out with every drug name, MIC value, and S/I/R call
   intact, one row per line.

2. **Decides which tables are actually AST results**, as opposed to, say, a strain-metadata table,
   a phylogenetics table, or a genotype/AMR-gene table that just happens to share vocabulary with
   real susceptibility-testing tables. It does this with two keyword checks against each table's
   caption and first few rows: a broad AST-keyword set (MIC, susceptible/resistant/intermediate,
   CLSI, EUCAST, disk/disc diffusion, zone diameter, breakpoint, Sensititre, broth microdilution,
   E-test, VITEK, Phoenix, antibiogram) and a narrower "strong AST" set used specifically to
   override false positives — a table whose caption mentions "gene(s)" without any of that
   stronger phenotypic-testing vocabulary is treated as a genotype/resistance-gene table (AMR
   gene presence/absence), not real AST data, even though the word "resistance" alone would
   otherwise match. Tables labeled as supplementary ("Table S1", "Supplementary Table...") are
   skipped here since those live in the supplement, not the main text — see the downloads section
   below for those.

Tables that pass both checks are written to `ast_tables/<pmid>/<table_label>.tsv`, with the
caption as a leading `#`-comment line and one row per line after that. This is separate from (and
usually more reliable than) the `ast_location` classification column, which is a coarser
main-text/supplement/both/none guess based on keyword density across the whole paper — the actual
`ast_table_files` are the real data to look at.

## Output folder reference

Everything below is written under `--outdir` (default `output/`, i.e. `scripts/query_pmids_to_find_ast/output/`):

| path | what it is |
|---|---|
| `paper_classification_<name>.tsv` | The main result: one row per unique PMID, with every column described above and in the original script docstring. Start here. |
| `ast_tables/<pmid>/<label>.tsv` | Real AST table content pulled straight out of the paper's own main text (see "How the main-text AST tables are found and pulled" above) — drug names, MIC values, S/I/R calls, etc., as actually printed in the paper. |
| `supplements/<pmid>/<filename>` | Supplementary files downloaded from PMC as-is (xlsx, pdf, docx, zip, whatever the paper attached) — see `supplement_paths` in the main TSV for the exact local path per file. |
| `ast_records_extracted.tsv` | Normalized, per-isolate AST records (isolate, drug, MIC, S/I/R) pulled out of the downloaded `.xlsx`/`.xls` supplements by the repo's LLM-based column-mapping extractor. Only written if at least one supplement was both downloaded and successfully parsed. |
| `download_report.json` | Machine-readable summary of the whole run: per-paper counts (supplement files found/downloaded, AST tables extracted, BV-BRC genomes matched, extraction failures) plus the full list of download failures with their error messages. Handy for scripting a "what still needs attention" check without re-parsing the main TSV. |
| `anti_bot_samples/<pmid>_<filename>.html` | **Debugging output, not data.** When PMC refuses to serve a supplement file — even after the Playwright browser fallback — the script saves up to 3 examples of exactly what PMC sent back instead (almost always its "Preparing to download..." anti-bot interstitial page). This exists so you can *see* what a block actually looks like (a JS challenge vs. a captcha vs. a plain 403) rather than just getting an error string. Once you've confirmed why a handful of downloads failed, this folder is safe to delete — it doesn't feed into anything else the script does. |

## Usage

```
python find_ast_evidence.py Staph.pmid_only.txt --outdir output

# Skip slower/optional steps:
python find_ast_evidence.py Staph.pmid_only.txt --no-bvbrc --no-download --no-extract

# Skip just the Playwright browser fallback for anti-bot-blocked supplement downloads
# (plain-HTTP downloads still happen; use this if you haven't installed the `browser` extra):
python find_ast_evidence.py Staph.pmid_only.txt --no-browser
```

### Installing dependencies

Everything in the script except the supplement-extraction step (`--no-extract` to skip it) is
Python standard library only. That one step needs `pandas`, `openpyxl`, `pydantic`, and
`google-genai` — already declared in the repo's `pyproject.toml`. See the **Setup** section in
the repo root's `README.md` for the install command (`pip install -e .`, run from the repo root
with your venv active). This script doesn't need its own separate install step: it adds the
repo's `src/` directory to `sys.path` itself, so once `amr_extraction`'s dependencies are
installed anywhere in your environment, it just works from wherever you run the script.

If a dependency is still missing, the script won't crash — it prints a `WARNING: could not import
amr_extraction (...)` line and skips just the extraction step, so you still get the rest of the
output (AST-location classification, main-text tables, BV-BRC accessions, downloaded files).

**For the Playwright browser fallback** (solves PMC's anti-bot challenge for supplement
downloads — see the section above), install the optional `browser` extra and its browser binary:

```bash
pip install -e ".[browser]"
playwright install chromium
```

This is entirely optional — without it the script still runs, it just reports anti-bot-blocked
supplement downloads as failures instead of retrying them with a real browser. `--no-browser`
skips this fallback explicitly (e.g. if you haven't installed it, to avoid a per-file wait for a
browser launch that will only fail).

### Setting GOOGLE_API_KEY

The supplement-extraction step (`extract_ast_from_supplements`, step 6 above) needs a Gemini API
key in the `GOOGLE_API_KEY` environment variable — it's read via `os.environ.get("GOOGLE_API_KEY")`
in `src/amr_extraction/llm.py`, the same variable the rest of this repo already uses. Get a free
key from [Google AI Studio](https://aistudio.google.com/apikey), then set it one of these ways:

**For just the current terminal session** (simplest, but you'll need to re-run this each time you
open a new terminal):
```bash
export GOOGLE_API_KEY="your-key-here"
python find_ast_evidence.py Staph.pmid_only.txt
```

**Inline, for a single run** (doesn't persist, doesn't touch your shell config):
```bash
GOOGLE_API_KEY="your-key-here" python find_ast_evidence.py Staph.pmid_only.txt
```

**Permanently, for every new terminal** — add the `export` line to your shell's startup file
(`~/.zshrc` on modern macOS, `~/.bash_profile` or `~/.bashrc` if you're on bash), then restart
your terminal or run `source ~/.zshrc`:
```bash
echo 'export GOOGLE_API_KEY="your-key-here"' >> ~/.zshrc
source ~/.zshrc
```

**Via a `.env` file** — if you'd rather keep it out of your shell config, put `GOOGLE_API_KEY=your-key-here`
in a `.env` file in the repo root (it's already covered by `.gitignore`, so it won't get
committed) and load it before running, e.g. with `export $(cat .env | xargs)` or a tool like
[`direnv`](https://direnv.net/) if you use one.

Whichever way you set it, `echo $GOOGLE_API_KEY` should print your key back before you run the
script — if it prints nothing, the extraction step will just skip itself with a warning rather
than fail, so it's easy to miss.

Also set `NCBI_API_KEY` (free from your [NCBI account](https://www.ncbi.nlm.nih.gov/account/),
raises the eutils rate limit from 3 to 10 requests/sec) the same way, or pass it with
`--ncbi-api-key` on the command line instead.
