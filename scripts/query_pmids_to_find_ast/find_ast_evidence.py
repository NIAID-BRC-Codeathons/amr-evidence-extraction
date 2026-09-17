#!/usr/bin/env python3
"""Find AST (antimicrobial susceptibility testing) evidence for a list of PMIDs.

Given either a plain list of PMIDs (one per line, e.g. Staph.pmid_only.txt) or the older
genome_id \\t genome_id \\t pmid mapping (e.g. Staph.pmid.txt), this script:

  1. Looks up each unique, valid PMID's title/author/year/PMCID/DOI via NCBI ESummary.
  2. Queries the BV-BRC Data API for genomes whose `publication` field references that PMID,
     pulling genome_id, bioproject_accession, biosample_accession, assembly_accession,
     genbank_accessions, and refseq_accessions for each matching genome.
  3. Fetches the PMC full-text XML and classifies where the paper's AST data (MIC values,
     disk-diffusion zones, S/I/R calls, breakpoints, etc.) lives: a main-text table, prose only,
     a supplementary file, both, or not found — mirroring data/starter/paper_classification.tsv.
  4. Extracts actual table content (rows/columns) from any main-text tables that look
     AST-related, and saves each as its own TSV under <outdir>/ast_tables/<pmid>/.
  5. Downloads any supplementary files it finds referenced in the XML. Plain HTTP first; if PMC's
     anti-bot interstitial blocks that (it runs a client-side JS proof-of-work challenge), falls
     back to a real headless-Chromium download via Playwright, which can execute that JS
     (--no-browser to disable this and just report those as failures).
  6. For downloaded .xlsx/.xls supplements, runs the repo's existing LLM-based extractor
     (amr_extraction.excel_extractor) to pull out normalized, per-isolate AST records
     (isolate, drug, MIC, S/I/R) — requires the amr_extraction package importable (run this from
     within the repo, or `pip install -e .` first) and an LLM backend: Gemini (default; needs
     GOOGLE_API_KEY) or a local Ollama daemon (--llm-provider ollama; needs `ollama serve` running
     and the model pulled). See --llm-provider / --llm-model below.

USAGE
    python find_ast_evidence.py data/query_pmids_to_find_ast/Staph.pmid_only.txt \\
        --outdir data/query_pmids_to_find_ast/output

    # Skip slower/optional steps:
    python find_ast_evidence.py Staph.pmid_only.txt --no-bvbrc --no-download --no-extract

    # Use a local Ollama model instead of Gemini for the extraction step:
    python find_ast_evidence.py Staph.pmid_only.txt --no-download --llm-provider ollama --llm-model llama3.1:8b

NETWORK
    Talks to eutils.ncbi.nlm.nih.gov (paper metadata + full text), www.bv-brc.org (genome
    accessions), and pmc.ncbi.nlm.nih.gov (supplementary file downloads). Run it somewhere with
    normal outbound internet access — it will not work behind a proxy/allowlist that blocks
    these hosts. Get a free NCBI API key (https://www.ncbi.nlm.nih.gov/account/) and set
    NCBI_API_KEY to raise the eutils rate limit from 3 req/s to 10 req/s.

    A NOTE ON THE BV-BRC QUERY: I could not test the BV-BRC Data API live from the sandbox this
    script was written in (network egress was blocked there too), so `fetch_bvbrc_genomes()`
    below is best-effort based on BV-BRC's documented RQL query syntax and genome field names
    (https://www.bv-brc.org/api/doc/). If it comes back empty for PMIDs you know have linked
    genomes, print the raw response (the WARNING lines below will show a snippet) and adjust the
    query — most likely culprit is the exact match vs. substring/keyword semantics of the
    `publication` field.

OUTPUT (written under --outdir)
    paper_classification_<basename>.tsv   one row per unique PMID (includes supplement_paths:
                                           local file paths of every downloaded supplement, and
                                           data_availability_accessions: any BioSample/SRA/
                                           BioProject/GenBank/RefSeq accessions found in the
                                           paper's own Data Availability statement -- see NOTE
                                           ON DATA AVAILABILITY ACCESSIONS below)
    ast_tables/<pmid>/<table_label>.tsv   extracted main-text AST table contents
    ast_records_extracted.tsv             normalized per-isolate AST records pulled from
                                           downloaded .xlsx/.xls supplements (if any + GOOGLE_API_KEY)
    download_report.json                  per-paper supplement download summary + failure log
    supplements/<pmid>/...                downloaded supplementary files, where retrievable

NOTE ON DATA AVAILABILITY ACCESSIONS: `extract_data_availability_accessions()` looks for a Data
    Availability statement in the paper's full-text XML (tagged explicitly by some publishers,
    or matched by heading text like "Data Availability" / "Accession Numbers" for the rest) and
    scrapes any accession-looking tokens out of it. This is a PAPER-LEVEL list, not tied to any
    specific isolate/strain -- a paper that says "all reads deposited under BioProject
    PRJNA123456" gives you that one accession with no indication of which isolate_id in
    ast_tables/ or the supplement extraction it belongs to. Getting a real per-isolate mapping
    would need a separate LLM-based pass (out of scope here); this is the cheap first step to see
    how much the paper-level list is worth before building that.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PMC_BIN = "https://pmc.ncbi.nlm.nih.gov/articles/instance/{numeric}/bin/{fname}"
BVBRC_GENOME = "https://www.bv-brc.org/api/genome/"

USER_AGENT = "amr-evidence-extraction-ast-finder/1.1 (+https://github.com/NIAID-BRC-Codeathons)"

# Make the repo's amr_extraction package importable when this script lives at
# data/query_pmids_to_find_ast/find_ast_evidence.py (repo_root/src/amr_extraction).
_REPO_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

# Keyword families used to decide whether a stretch of text is talking about AST results.
AST_KEYWORDS = [
    r"\bMICs?\b", r"minimum inhibitory concentration",
    r"\bsusceptib\w*", r"\bresistan\w*", r"\bintermediate\b",
    r"disk diffusion", r"disc diffusion", r"zone diameter",
    r"\bCLSI\b", r"\bEUCAST\b", r"breakpoint",
    r"Sensititre", r"broth microdilution", r"agar dilution",
    r"\bE-?test\b", r"\bVITEK\b", r"\bPhoenix\b", r"antibiogram",
]
AST_RE = re.compile("|".join(AST_KEYWORDS), re.IGNORECASE)

SUPPLEMENT_REF_RE = re.compile(
    r"(Table\s*S\d+[A-Za-z]?|Supplementary\s+(Table|Data|File|Material)s?\s*\d*|"
    r"Additional\s+file\s*\d*|Dataset\s*S\d+)",
    re.IGNORECASE,
)
MAIN_TABLE_RE = re.compile(r"\bTable\s*\d+[A-Za-z]?\b(?!\s*S)", re.IGNORECASE)
SUPP_LABEL_RE = re.compile(r"^\s*(Table\s*S|Supplementary|Additional\s+file|Dataset\s*S)", re.IGNORECASE)
# A caption mentioning "gene(s)" without any phenotypic-testing keyword usually means a
# genotype/resistance-gene table (AMR gene presence/absence), not an actual AST results table —
# both loosely match AST_RE via the shared word "resistance", so this filters that false positive.
GENE_TABLE_RE = re.compile(r"\bgenes?\b", re.IGNORECASE)
STRONG_AST_RE = re.compile(
    r"\bMICs?\b|susceptib\w*|resistan\w*\s*(test|phenotyp)\w*|\bCLSI\b|\bEUCAST\b|breakpoint|"
    r"disk diffusion|disc diffusion|broth microdilution|Sensititre|\bE-?test\b|\bVITEK\b",
    re.IGNORECASE,
)

ACCESSION_RE = re.compile(
    r"\b(SAMN\d+|SAMEA\d+|SAMD\d+|PRJNA\d+|PRJEB\d+|PRJDB\d+|SRR\d+|ERR\d+|DRR\d+|BioSample|BioProject)\b"
)

# Broader than ACCESSION_RE above (which is only used as a yes/no "does this paper mention
# accessions at all" hint): this one actually collects real accession tokens, so it also covers
# assembly (GCA_/GCF_) and RefSeq (NZ_/NC_) accessions, and SRA/ENA/DDBJ experiment IDs
# (SRX/ERX/DRX), which papers' Data Availability statements commonly use.
DATA_AVAIL_ACCESSION_RE = re.compile(
    r"\b(SAMN\d+|SAMEA\d+|SAMD\d+|PRJNA\d+|PRJEB\d+|PRJDB\d+|"
    r"SRR\d+|ERR\d+|DRR\d+|SRX\d+|ERX\d+|DRX\d+|"
    r"GCA_\d+(?:\.\d+)?|GCF_\d+(?:\.\d+)?|"
    r"(?:NZ_|NC_)[A-Z]{2,4}\d+(?:\.\d+)?)\b"
)

# Matches common heading phrasing for a paper's data-deposition statement, used as a fallback
# when the JATS XML doesn't tag the section explicitly via sec-type="data-availability" (many
# publishers just use a plain <title> instead).
DATA_AVAILABILITY_HEADING_RE = re.compile(
    r"data\s+availab|availability\s+of\s+data|accession\s+number|data\s+deposition|"
    r"sequence\s+data\s+availab",
    re.IGNORECASE,
)


@dataclass
class PaperRecord:
    pmid: str
    genome_ids: list[str] = field(default_factory=list)  # from the input file, if it had them
    pmcid: str | None = None
    doi: str | None = None
    title: str | None = None
    first_author: str | None = None
    year: str | None = None
    ast_location: str = "unclassified"
    biosample_hint: str = "unclear"
    supplement_files: list[str] = field(default_factory=list)
    supplement_downloaded: int = 0
    supplement_paths: list[str] = field(default_factory=list)  # local paths of downloaded files
    ast_table_files: list[str] = field(default_factory=list)
    details: str = ""
    failures: list[str] = field(default_factory=list)
    # BV-BRC genome accessions linked to this PMID
    bvbrc_genome_ids: list[str] = field(default_factory=list)
    bioproject_accessions: list[str] = field(default_factory=list)
    biosample_accessions: list[str] = field(default_factory=list)
    assembly_accessions: list[str] = field(default_factory=list)
    genbank_accessions: list[str] = field(default_factory=list)
    refseq_accessions: list[str] = field(default_factory=list)
    accessions_confirmed_in_text: str = "unclear"
    # Accessions scraped from the paper's own Data Availability statement (paper-level, not
    # tied to a specific isolate -- see scripts/ast_tables_codegen/README.md for why per-isolate
    # accession joining is a separate, harder problem).
    data_availability_accessions: list[str] = field(default_factory=list)
    data_availability_section_found: bool = False
    # LLM-based extraction from downloaded xlsx/xls supplements
    ast_records_extracted: int = 0
    extraction_notes: list[str] = field(default_factory=list)


def http_get(url: str, params: dict | None = None, timeout: int = 30, headers: dict | None = None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type", "")
    return data, ctype


def eutils_params(extra: dict) -> dict:
    p = dict(extra)
    if os.environ.get("NCBI_API_KEY"):
        p["api_key"] = os.environ["NCBI_API_KEY"]
    if os.environ.get("NCBI_EMAIL"):
        p["email"] = os.environ["NCBI_EMAIL"]
    p["tool"] = os.environ.get("NCBI_TOOL", "amr-evidence-extraction")
    return p


def rate_sleep(seconds: float | None = None):
    if seconds is not None:
        time.sleep(seconds)
    else:
        time.sleep(0.11 if os.environ.get("NCBI_API_KEY") else 0.34)


def parse_input(path: Path) -> dict[str, PaperRecord]:
    """Parse either a plain PMID-per-line file or the older genome_id\\tgenome_id\\tpmid file."""
    records: dict[str, PaperRecord] = {}
    with path.open() as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                genome_id, pmid = parts[0].strip(), parts[2].strip()
            elif len(parts) == 1:
                genome_id, pmid = None, parts[0].strip()
            else:
                genome_id, pmid = parts[0].strip(), parts[-1].strip()
            if not pmid or pmid == "-" or not pmid.isdigit():
                continue
            rec = records.setdefault(pmid, PaperRecord(pmid=pmid))
            if genome_id and genome_id not in rec.genome_ids:
                rec.genome_ids.append(genome_id)
    return records


def fetch_summaries(records: dict[str, PaperRecord]) -> None:
    """Batch title/author/year/PMCID/DOI lookup via ESummary (single eutils host — PMCID/DOI
    are pulled from its `articleids` field rather than a separate idconv call, which has been
    observed silently returning zero matches for scripted clients)."""
    pmids = list(records.keys())
    resolved = 0
    for i in range(0, len(pmids), 200):
        chunk = pmids[i : i + 200]
        data, _ = http_get(
            f"{EUTILS}/esummary.fcgi",
            eutils_params({"db": "pubmed", "id": ",".join(chunk), "retmode": "json"}),
        )
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            snippet = data[:200].decode("utf-8", errors="replace")
            print(f"  WARNING: esummary did not return JSON for this batch (got: {snippet!r})", file=sys.stderr)
            continue
        result = payload.get("result", {})
        if not result:
            print(f"  WARNING: esummary returned no 'result' — response: {str(payload)[:300]}", file=sys.stderr)
        for pmid in chunk:
            doc = result.get(pmid)
            if not doc:
                continue
            rec = records[pmid]
            rec.title = doc.get("title", "").rstrip(".")
            authors = doc.get("authors") or []
            if authors:
                rec.first_author = authors[0].get("name")
            pubdate = doc.get("pubdate", "")
            m = re.search(r"\d{4}", pubdate)
            rec.year = m.group(0) if m else ""
            for aid in doc.get("articleids", []):
                idtype, value = aid.get("idtype", ""), aid.get("value", "")
                if idtype == "pmc" and value:
                    rec.pmcid = value if value.upper().startswith("PMC") else f"PMC{value}"
                    resolved += 1
                elif idtype == "doi" and value:
                    rec.doi = value
        rate_sleep()
    print(f"  Resolved PMCIDs for {resolved}/{len(records)} PMIDs.")
    if resolved == 0 and records:
        print(
            "  WARNING: zero PMCIDs resolved for the whole batch — this usually means NCBI "
            "blocked/throttled the request rather than none of these papers being in PMC. "
            "Check the WARNING lines above, set NCBI_API_KEY/NCBI_EMAIL, and try again.",
            file=sys.stderr,
        )


# --- BV-BRC genome accession lookup -----------------------------------------------------

BVBRC_SELECT_FIELDS = (
    "genome_id,genome_name,publication,bioproject_accession,biosample_accession,"
    "assembly_accession,genbank_accessions,refseq_accessions"
)


def _bvbrc_query(rql: str) -> list[dict]:
    url = BVBRC_GENOME + "?" + rql + f"&select({BVBRC_SELECT_FIELDS})&limit(1000)&http_accept=application/json"
    try:
        data, ctype = http_get(url, headers={"Accept": "application/json"}, timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"  WARNING: BV-BRC request failed ({e}) for query: {rql}", file=sys.stderr)
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        snippet = data[:200].decode("utf-8", errors="replace")
        print(f"  WARNING: BV-BRC did not return JSON for {rql!r} (got: {snippet!r})", file=sys.stderr)
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        # Some BV-BRC responses wrap results in a "response"/"docs" envelope.
        return payload.get("response", {}).get("docs", []) or payload.get("docs", [])
    return []


def fetch_bvbrc_genomes(records: dict[str, PaperRecord]) -> None:
    """For each PMID, find BV-BRC genomes whose `publication` field references it, and pull
    genome_id + accession fields. Tries an exact-match query first, falling back to a keyword
    search if that comes back empty (the `publication` field's exact format varies)."""
    matched = 0
    for pmid, rec in records.items():
        docs = _bvbrc_query(f"eq(publication,{pmid})")
        if not docs:
            docs = _bvbrc_query(f"keyword({pmid})")
        if docs:
            matched += 1
        for doc in docs:
            gid = doc.get("genome_id")
            if gid and gid not in rec.bvbrc_genome_ids:
                rec.bvbrc_genome_ids.append(str(gid))
            for field_name, bucket in (
                ("bioproject_accession", rec.bioproject_accessions),
                ("biosample_accession", rec.biosample_accessions),
                ("assembly_accession", rec.assembly_accessions),
            ):
                val = doc.get(field_name)
                if val and val not in bucket:
                    bucket.append(str(val))
            for field_name, bucket in (
                ("genbank_accessions", rec.genbank_accessions),
                ("refseq_accessions", rec.refseq_accessions),
            ):
                val = doc.get(field_name)
                if not val:
                    continue
                # These fields can be comma-separated lists of accessions.
                for v in re.split(r"[,;]\s*", str(val)):
                    v = v.strip()
                    if v and v not in bucket:
                        bucket.append(v)
        rate_sleep(0.3)
    print(f"  BV-BRC: found genome records for {matched}/{len(records)} PMIDs.")
    if matched == 0 and records:
        print(
            "  WARNING: zero PMIDs matched any BV-BRC genome — this could mean none of these "
            "papers are linked to BV-BRC genomes, or the query syntax needs adjusting for this "
            "API version. See the module docstring's NETWORK section.",
            file=sys.stderr,
        )


# --- PMC full text: AST-location classification + real table extraction ----------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def extract_tables_from_xml(xml_bytes: bytes) -> list[dict]:
    """Pull every <table-wrap> out of the JATS XML as {label, caption, rows}."""
    tables: list[dict] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return tables
    for tw in root.iter():
        if _local(tw.tag) != "table-wrap":
            continue
        label = caption = None
        for child in tw.iter():
            tag = _local(child.tag)
            if tag == "label" and label is None:
                label = "".join(child.itertext()).strip()
            elif tag == "caption" and caption is None:
                caption = " ".join("".join(child.itertext()).split())
        rows: list[list[str]] = []
        for tr in tw.iter():
            if _local(tr.tag) != "tr":
                continue
            cells = [
                " ".join("".join(cell.itertext()).split())
                for cell in tr
                if _local(cell.tag) in ("td", "th")
            ]
            if cells:
                rows.append(cells)
        if rows:
            tables.append({"label": label or "", "caption": caption or "", "rows": rows})
    return tables


def extract_data_availability_accessions(xml_bytes: bytes) -> tuple[list[str], bool]:
    """Looks for a Data Availability statement in the JATS full-text XML -- tagged explicitly
    via sec-type/notes-type/fn-type="data-availability" by some publishers, or (far more common)
    just a plain <sec>/<notes>/<fn> whose <title> matches DATA_AVAILABILITY_HEADING_RE -- and
    pulls any accession-looking tokens out of it with DATA_AVAIL_ACCESSION_RE.

    This is a paper-level scrape: it tells you which accessions the paper says it deposited
    somewhere, not which isolate/strain each one belongs to. Papers vary a lot in how (or
    whether) they spell that mapping out in prose; a real per-isolate join would need a separate,
    smarter pass (see the "LLM-based per-isolate join" discussion in this repo's history) -- this
    is the cheaper first step to see how much the paper-level list alone is worth on its own.

    Returns (accessions, section_found) so callers can tell "no such section in this paper" (both
    empty / False) apart from "section exists but didn't contain anything accession-shaped"
    (empty list, True).
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return [], False

    section_texts: list[str] = []
    for el in root.iter():
        tag = _local(el.tag)
        if tag not in ("sec", "notes", "fn"):
            continue
        type_attr = (
            el.attrib.get("sec-type") or el.attrib.get("notes-type") or el.attrib.get("fn-type") or ""
        )
        title_text = ""
        for child in el:
            if _local(child.tag) == "title":
                title_text = "".join(child.itertext())
                break
        if "data-availability" in type_attr.lower() or DATA_AVAILABILITY_HEADING_RE.search(title_text):
            section_texts.append("".join(el.itertext()))

    if not section_texts:
        return [], False

    combined = " ".join(section_texts)
    accessions = sorted(set(DATA_AVAIL_ACCESSION_RE.findall(combined)))
    return accessions, True


def classify_fulltext(xml_bytes: bytes) -> tuple[str, list[str], str, str, list[dict]]:
    """Return (ast_location, supplement_filenames, biosample_hint, details, ast_tables)."""
    try:
        text = xml_bytes.decode("utf-8", errors="ignore")
    except Exception:
        text = str(xml_bytes)

    # Some publishers (e.g. several ASM journals) let PMC host the paper for reading but block
    # bulk/API XML redistribution — efetch then returns only <front> (title/abstract/metadata),
    # no <body>, no tables, no supplementary-material refs, even though the article + supplements
    # are perfectly readable on the PMC website. Detect that explicitly instead of silently
    # falling back to a low-confidence "prose" guess based on abstract keywords alone.
    if "does not allow downloading of the full text" in text or "<body" not in text.lower():
        return (
            "no_fulltext_restricted",
            [],
            "unclear",
            "Publisher restricts full-text XML via the PMC API (efetch returned only front "
            "matter/abstract, no <body>). View this paper's tables/supplements manually at its "
            "PMC article page or PDF.",
            [],
        )

    ast_hits = AST_RE.findall(text)
    if not ast_hits:
        return "none_found", [], "unclear", "No AST-related keywords found in full text.", []

    supp_files: list[str] = []
    try:
        root = ET.fromstring(text)
        for supp in root.iter():
            if _local(supp.tag) != "supplementary-material":
                continue
            # The actual file reference lives on the <supplementary-material> tag itself, or on
            # a <media>/<graphic> child. Do NOT walk every descendant — a supplementary-material
            # block also contains a <license>/<ext-link> pointing at e.g. the CC-BY license URL,
            # which has its own xlink:href and would otherwise get mistaken for a supplement file
            # (and then fail with a 404 to ".../bin/" once its trailing "/" leaves an empty
            # filename after rsplit).
            candidates = [supp] + [c for c in supp.iter() if _local(c.tag) in ("media", "graphic")]
            for el in candidates:
                href = el.attrib.get("{http://www.w3.org/1999/xlink}href") or el.attrib.get("href")
                if href and not href.startswith(("http://", "https://")) and href not in supp_files:
                    supp_files.append(href)
    except ET.ParseError:
        pass

    tables = extract_tables_from_xml(xml_bytes)
    ast_tables = []
    for t in tables:
        if SUPP_LABEL_RE.match(t["label"]):
            continue
        cap = t["caption"]
        body_preview = " ".join(" ".join(r) for r in t["rows"][:6])
        if GENE_TABLE_RE.search(cap) and not STRONG_AST_RE.search(cap) and not STRONG_AST_RE.search(body_preview):
            continue  # looks like a genotype/AMR-gene table, not phenotypic AST results
        if AST_RE.search(cap) or AST_RE.search(body_preview):
            ast_tables.append(t)

    has_supp_ref = bool(SUPPLEMENT_REF_RE.search(text)) or bool(supp_files)
    has_main_table_ref = bool(ast_tables) or bool(MAIN_TABLE_RE.search(text))
    biosample_hint = "yes" if ACCESSION_RE.search(text) else "no"

    if has_main_table_ref and has_supp_ref:
        location = "main_text_and_supplement"
    elif has_main_table_ref:
        location = "main_text_table"
    elif has_supp_ref:
        location = "supplement"
    else:
        location = "main_text_prose"

    counts = Counter(h.lower() for h in ast_hits)
    top = ", ".join(f"{k}×{v}" for k, v in counts.most_common(4))
    details = f"AST keyword hits: {top}. {len(ast_tables)} candidate AST table(s) in main text."
    return location, supp_files, biosample_hint, details, ast_tables


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "table"


def fetch_and_classify(records: dict[str, PaperRecord], outdir: Path) -> None:
    for pmid, rec in records.items():
        if not rec.pmcid:
            rec.ast_location = "no_pmc_record"
            rec.details = "No PMCID — not deposited in PMC (or paywalled). Needs manual lookup."
            continue
        numeric_pmcid = rec.pmcid.lstrip("PMC")
        try:
            data, _ = http_get(
                f"{EUTILS}/efetch.fcgi",
                eutils_params({"db": "pmc", "id": numeric_pmcid, "rettype": "xml", "retmode": "xml"}),
                timeout=60,
            )
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            rec.ast_location = "no_fulltext"
            rec.failures.append(f"efetch pmc {rec.pmcid}: {e}")
            rate_sleep()
            continue

        location, supp_files, biosample_hint, details, ast_tables = classify_fulltext(data)
        rec.ast_location = location
        rec.supplement_files = supp_files
        rec.biosample_hint = biosample_hint
        rec.details = details

        da_accessions, da_section_found = extract_data_availability_accessions(data)
        rec.data_availability_accessions = da_accessions
        rec.data_availability_section_found = da_section_found

        # Cross-check BV-BRC accessions against the full text.
        all_accessions = (
            rec.bioproject_accessions + rec.biosample_accessions + rec.assembly_accessions
        )
        if all_accessions:
            text_str = data.decode("utf-8", errors="ignore")
            rec.accessions_confirmed_in_text = (
                "yes" if any(a and a in text_str for a in all_accessions) else "no"
            )

        # Save extracted AST-looking main-text tables to disk.
        if ast_tables:
            table_dir = outdir / "ast_tables" / pmid
            table_dir.mkdir(parents=True, exist_ok=True)
            for idx, t in enumerate(ast_tables, start=1):
                fname = _sanitize(t["label"] or f"table{idx}") + ".tsv"
                fpath = table_dir / fname
                with fpath.open("w") as f:
                    if t["caption"]:
                        f.write(f"# {t['label']}: {t['caption']}\n")
                    for row in t["rows"]:
                        f.write("\t".join(c.replace("\t", " ") for c in row) + "\n")
                rec.ast_table_files.append(str(fpath))
        rate_sleep()


# PMC's bot-protection front end (pmc.ncbi.nlm.nih.gov) is much more likely to serve the real
# file to something that looks like an ordinary browser tab than to a request announcing itself
# as a script — the custom USER_AGENT above is fine for the eutils API (which wants a tool/email
# identifier) but gets blocked more often here. Only used for supplement downloads.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_supplement(url: str, referer: str) -> tuple[bytes | None, str | None, str | None, bytes | None]:
    """One GET attempt for a supplement file. Returns (data, content_type, error, blocked_body)
    — data is None on any failure (network error, or PMC serving an HTML interstitial instead);
    blocked_body carries the raw bytes PMC sent back when it was an interstitial, so the caller
    can save a sample to inspect what the block actually looks like (status code, page text,
    whether it's a JS/Cloudflare challenge, a captcha, a plain 403, etc.) — that's needed to
    figure out whether there's anything a script can do about it at all."""
    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = referer
    try:
        data, ctype = http_get(url, timeout=60, headers=headers)
    except urllib.error.HTTPError as e:
        body = e.read()
        ctype_hdr = (e.headers.get("Content-Type", "") if e.headers else "").lower()
        if "text/html" in ctype_hdr or body[:15].lstrip().lower().startswith(b"<!doctype html"):
            return None, None, f"not downloaded; PMC returned an anti-bot/HTML interstitial instead of the file (HTTP {e.code})", body
        return None, None, f"HTTP Error {e.code}: {e.reason}", None
    except urllib.error.URLError as e:
        return None, None, str(e), None
    if "text/html" in ctype.lower() or data[:15].lstrip().lower().startswith(b"<!doctype html"):
        return None, None, "not downloaded; PMC returned an anti-bot/HTML interstitial instead of the file (HTTP 200)", data
    return data, ctype, None, None


class _BrowserDownloader:
    """Lazily launches one headless Chromium instance (via Playwright) and reuses it across every
    supplement file that plain HTTP couldn't get past PMC's anti-bot interstitial for. PMC's
    interstitial (see the module docstring / README) runs a genuine client-side JS proof-of-work
    challenge — `window.ncbi.pmc.pow.init(...)` — that sets a `cloudpmc-viewer-pow` cookie once
    solved. A real browser executing that JS is the only way to clear it; no plain HTTP client
    (this script's normal urllib path included) can. Degrades to "unavailable" (never raises) if
    the `playwright` package isn't installed or the browser can't launch, so callers can fall back
    to reporting the plain-HTTP failure as-is."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self._unavailable_reason: str | None = None
        self._tried_launch = False

    def _ensure_launched(self) -> bool:
        if self._context is not None:
            return True
        if self._tried_launch:
            return False
        self._tried_launch = True
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._unavailable_reason = (
                "the `playwright` package isn't installed (pip install -e \".[browser]\" from the "
                "repo root, then `playwright install chromium`) — falling back to plain-HTTP "
                "results only for downloads PMC's anti-bot page blocked"
            )
            return False
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._context = self._browser.new_context(user_agent=BROWSER_HEADERS["User-Agent"])
        except Exception as e:  # noqa: BLE001 - browser launch can fail many ways (missing binary, sandbox, etc.)
            self._unavailable_reason = (
                f"could not launch headless Chromium ({e}) — if this is the first time, run "
                "`playwright install chromium` (or `playwright install-deps chromium` for missing "
                "OS libraries) — falling back to plain-HTTP results only"
            )
            self._pw = self._browser = self._context = None
            return False
        return True

    def fetch(self, url: str, referer: str) -> tuple[bytes | None, str | None]:
        """Try to solve PMC's anti-bot page and download `url` with a real browser. Returns
        (data, error) — data is None on any failure, with `error` explaining why."""
        if not self._ensure_launched():
            return None, self._unavailable_reason
        page = self._context.new_page()
        try:
            # First load the article page itself so the PoW cookie gets set in a normal-looking
            # navigation context (matches what a real user's browser does) before requesting the
            # actual file.
            try:
                page.goto(referer, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)  # let the PoW script finish + set its cookie
            except Exception:
                pass  # if this fails we still try the direct download below

            try:
                with page.expect_download(timeout=45000) as download_info:
                    try:
                        page.goto(url, timeout=45000)
                    except Exception:
                        # A successful file download often manifests as a cancelled/aborted
                        # navigation in Playwright (the browser starts a download instead of
                        # rendering a page) — that's expected, not necessarily a failure; the
                        # `with` block below is what tells us whether a real download happened.
                        pass
                download = download_info.value
                tmp_path = download.path()
                if tmp_path is None:
                    return None, "browser reported a download but no file was saved"
                data = Path(tmp_path).read_bytes()
                if data[:15].lstrip().lower().startswith(b"<!doctype html") or data[:6].lstrip().lower().startswith(b"<html"):
                    return None, "browser download still returned an HTML page, not the file (PoW likely unsolved)"
                return data, None
            except Exception as e:  # noqa: BLE001 - no download materialized in time
                return None, f"browser did not receive a file download ({e})"
        finally:
            try:
                page.close()
            except Exception:
                pass

    def close(self) -> None:
        for obj in (self._context, self._browser):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._pw = self._browser = self._context = None


def download_supplements(records: dict[str, PaperRecord], outdir: Path, use_browser: bool = True) -> list[dict]:
    """Best-effort download of any supplementary files found in the full text.

    Two-stage strategy per file:
      1. Plain HTTP (fast). Retries once after a longer pause on an anti-bot interstitial, in
         case it was a rate-based challenge rather than a hard block.
      2. If that still hit PMC's anti-bot interstitial specifically (not some other error), and
         `use_browser` is True, fall back to a real headless-Chromium download via Playwright,
         which can execute the client-side proof-of-work JS that interstitial requires. This is
         slower (a real page load per file) and only kicks in for files that actually needed it.

    PMC does hard-block a real fraction of automated supplement downloads regardless of method
    (this repo's own data/starter/download_report.json shows the same pattern from manual
    downloads), so some failures here are expected, not a bug."""
    failures: list[dict] = []
    samples_saved = 0
    samples_dir = outdir / "anti_bot_samples"
    browser = _BrowserDownloader() if use_browser else None
    browser_attempts = browser_successes = 0
    try:
        for pmid, rec in records.items():
            if not rec.pmcid or not rec.supplement_files:
                continue
            numeric = rec.pmcid.lstrip("PMC")
            dest_dir = outdir / "supplements" / pmid
            referer = f"https://pmc.ncbi.nlm.nih.gov/articles/{rec.pmcid}/"
            for fname in rec.supplement_files:
                base = fname.rsplit("/", 1)[-1]
                if not base:
                    failures.append(
                        {"pmid": pmid, "pmcid": rec.pmcid, "url": fname, "error": "empty filename after parsing href, skipped"}
                    )
                    continue
                url = PMC_BIN.format(numeric=numeric, fname=base)

                data, ctype, error, blocked_body = _fetch_supplement(url, referer)
                if data is None and error and "anti-bot" in error:
                    rate_sleep(2.0)  # give a rate-based challenge a moment to clear, then try once more
                    data, ctype, error, blocked_body = _fetch_supplement(url, referer)

                if data is None and error and "anti-bot" in error and browser is not None:
                    browser_attempts += 1
                    b_data, b_error = browser.fetch(url, referer)
                    if b_data is not None:
                        data, error, blocked_body = b_data, None, None
                        browser_successes += 1
                    else:
                        error = f"{error}; browser fallback also failed: {b_error}"

                if data is None:
                    failures.append({"pmid": pmid, "pmcid": rec.pmcid, "url": url, "error": error})
                    # Save a few real samples of what PMC actually sends back on a block, so it's
                    # possible to tell a JS/Cloudflare challenge apart from a plain "no" — printing
                    # the error string alone doesn't show that.
                    if blocked_body and samples_saved < 3:
                        samples_dir.mkdir(parents=True, exist_ok=True)
                        (samples_dir / f"{pmid}_{base}.html").write_bytes(blocked_body)
                        samples_saved += 1
                    continue
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / base
                dest_path.write_bytes(data)
                rec.supplement_downloaded += 1
                rec.supplement_paths.append(str(dest_path))
                rate_sleep(0.5)
    finally:
        if browser is not None:
            browser.close()
    if browser_attempts:
        print(f"  Browser fallback: solved PMC's anti-bot challenge for {browser_successes}/{browser_attempts} files.")
    return failures


def scan_downloaded_supplements(records: dict[str, PaperRecord], outdir: Path) -> None:
    """Populate rec.supplement_paths from whatever's actually on disk under
    <outdir>/supplements/<pmid>/, rather than only from files downloaded in this run — so the
    `supplement_paths` output column is accurate even on a --no-download rerun (e.g. just to
    redo LLM extraction) against files a previous run already fetched."""
    for pmid, rec in records.items():
        supp_dir = outdir / "supplements" / pmid
        if not supp_dir.is_dir():
            continue
        paths = sorted(str(p) for p in supp_dir.iterdir() if p.is_file())
        if paths:
            rec.supplement_paths = paths


# --- Wire into the repo's existing LLM-based Excel extractor ---------------------------


def extract_ast_from_supplements(records: dict[str, PaperRecord], outdir: Path) -> list[dict]:
    """Run amr_extraction.excel_extractor over any downloaded .xlsx/.xls supplements to get
    normalized, per-isolate AST records. Requires GOOGLE_API_KEY and the amr_extraction package
    (this script adds ../../src to sys.path automatically when run from inside the repo)."""
    try:
        from amr_extraction.excel_extractor import extract_from_excel
        from amr_extraction.llm import DailyQuotaExhausted, query_structured
    except ImportError as e:
        print(
            f"  WARNING: could not import amr_extraction ({e}). This usually means a dependency "
            "is missing from your environment, not that the package can't be found — run "
            "`pip install -e .` from the repo root (with your venv active; see the Setup section "
            "in the repo's README.md) and try again. Skipping supplement extraction for now.",
            file=sys.stderr,
        )
        return []
    if not os.environ.get("GOOGLE_API_KEY"):
        print(
            "  WARNING: GOOGLE_API_KEY not set; skipping LLM-based AST extraction from supplements.",
            file=sys.stderr,
        )
        return []

    all_rows: list[dict] = []
    quota_exhausted = False
    for pmid, rec in records.items():
        if quota_exhausted:
            break
        supp_dir = outdir / "supplements" / pmid
        if not supp_dir.is_dir():
            continue
        for fpath in sorted(supp_dir.iterdir()):
            if quota_exhausted:
                rec.extraction_notes.append(f"{fpath.name}: skipped (daily Gemini quota exhausted this run)")
                continue
            if fpath.suffix.lower() not in (".xlsx", ".xls"):
                rec.extraction_notes.append(
                    f"{fpath.name}: skipped (only .xlsx/.xls are supported by excel_extractor; "
                    f"{fpath.suffix or 'this format'} needs separate/manual handling)"
                )
                continue
            print(f"  Extracting AST records from {fpath.name} (pmid {pmid}) via LLM column mapping ...")
            try:
                extracted = extract_from_excel(excel_path=fpath, pubmed_id=pmid, query_fn=query_structured)
            except DailyQuotaExhausted as e:
                # Retrying this (query_structured already tried, correctly, exactly zero times
                # for this specific error) or moving on to the next file won't help — the quota is
                # shared across every call this script makes for the rest of the day, so stop
                # immediately instead of burning through every remaining file just to fail the
                # same way each time.
                print(
                    f"  STOPPING extraction: {e}\n"
                    "  Files already downloaded aren't lost — re-run with --no-download once the "
                    "quota resets (or with GEMINI_MODEL set to a different model, which has its "
                    "own separate daily quota) to pick up where this left off.",
                    file=sys.stderr,
                )
                rec.extraction_notes.append(f"{fpath.name}: extraction failed (daily Gemini quota exhausted)")
                quota_exhausted = True
                continue
            except Exception as e:  # noqa: BLE001 - surface any extractor failure per-file, keep going
                rec.extraction_notes.append(f"{fpath.name}: extraction failed ({e})")
                continue
            finally:
                # extract_from_excel makes 2 Gemini calls per sheet (classify + column-map), so a
                # multi-sheet workbook can burst well past the free tier's per-minute request cap
                # on its own; query_structured() now retries 429/503 with backoff, but a small
                # pause between *files* keeps that from being the common case in the first place.
                rate_sleep(1.5)
            rec.ast_records_extracted += len(extracted)
            rec.extraction_notes.append(f"{fpath.name}: extracted {len(extracted)} AST record(s)")
            for r in extracted:
                row = r.model_dump()
                row["source_file"] = fpath.name
                all_rows.append(row)
    return all_rows


# --- Output ------------------------------------------------------------------------------


def write_outputs(records: dict[str, PaperRecord], outdir: Path, basename: str, failures: list[dict], extracted_rows: list[dict]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    tsv_path = outdir / f"paper_classification_{basename}.tsv"
    cols = [
        "pmid", "pmcid", "doi", "title", "first_author", "year", "genome_id_count",
        "ast_location", "biosample_hint", "supplement_files", "supplement_downloaded",
        "supplement_paths", "ast_table_files", "bvbrc_genome_ids", "bioproject_accessions",
        "biosample_accessions", "assembly_accessions", "genbank_accessions", "refseq_accessions",
        "accessions_confirmed_in_text", "data_availability_section_found",
        "data_availability_accessions", "ast_records_extracted", "extraction_notes", "details",
    ]

    def sort_key(pmid: str) -> int:
        r = records[pmid]
        return -(len(r.genome_ids) or len(r.bvbrc_genome_ids))

    with tsv_path.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for pmid in sorted(records, key=sort_key):
            r = records[pmid]
            row = [
                r.pmid, r.pmcid or "", r.doi or "", r.title or "", r.first_author or "", r.year or "",
                str(len(r.genome_ids)), r.ast_location, r.biosample_hint,
                ";".join(r.supplement_files), str(r.supplement_downloaded),
                ";".join(r.supplement_paths),
                ";".join(r.ast_table_files), ";".join(r.bvbrc_genome_ids),
                ";".join(r.bioproject_accessions), ";".join(r.biosample_accessions),
                ";".join(r.assembly_accessions), ";".join(r.genbank_accessions),
                ";".join(r.refseq_accessions), r.accessions_confirmed_in_text,
                "yes" if r.data_availability_section_found else "no",
                ";".join(r.data_availability_accessions),
                str(r.ast_records_extracted), " | ".join(r.extraction_notes), r.details,
            ]
            f.write("\t".join(x.replace("\t", " ").replace("\n", " ") for x in row) + "\n")

    if extracted_rows:
        ext_path = outdir / "ast_records_extracted.tsv"
        ext_cols = list(extracted_rows[0].keys())
        with ext_path.open("w") as f:
            f.write("\t".join(ext_cols) + "\n")
            for row in extracted_rows:
                f.write("\t".join(str(row.get(c, "") or "").replace("\t", " ") for c in ext_cols) + "\n")
        print(f"Wrote {ext_path} ({len(extracted_rows)} normalized AST records)")

    report = {
        "summary": [
            {
                "pmid": r.pmid,
                "pmcid": r.pmcid,
                "ast_location": r.ast_location,
                "supplement_files": len(r.supplement_files),
                "supplement_downloaded": r.supplement_downloaded,
                "ast_tables_extracted": len(r.ast_table_files),
                "bvbrc_genomes": len(r.bvbrc_genome_ids),
                "ast_records_extracted": r.ast_records_extracted,
                "failures": len(r.failures),
            }
            for r in records.values()
        ],
        "failures": failures + [{"pmid": r.pmid, "error": f} for r in records.values() for f in r.failures],
    }
    (outdir / "download_report.json").write_text(json.dumps(report, indent=2))
    print(f"Wrote {tsv_path} ({len(records)} papers) and {outdir / 'download_report.json'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="PMID-per-line file, or the older genome_id\\tgenome_id\\tpmid file")
    ap.add_argument("--outdir", type=Path, default=Path("output"), help="Directory for outputs")
    ap.add_argument("--no-bvbrc", action="store_true", help="Skip BV-BRC genome/accession lookup")
    ap.add_argument("--no-download", action="store_true", help="Skip downloading supplementary files")
    ap.add_argument(
        "--no-browser", action="store_true",
        help=(
            "Don't fall back to a headless-Chromium (Playwright) download when PMC's anti-bot "
            "interstitial blocks a plain-HTTP download — just report those as failures. Use this "
            "if Playwright/Chromium isn't installed, or to keep runs fast when you don't need the "
            "last few percent of supplement files."
        ),
    )
    ap.add_argument(
        "--no-extract", action="store_true",
        help="Skip LLM-based AST record extraction from downloaded xlsx/xls supplements",
    )
    ap.add_argument("--ncbi-api-key", default=None, metavar="KEY", help="Equivalent to NCBI_API_KEY (raises the eutils rate limit).")
    ap.add_argument("--ncbi-email", default=None, metavar="EMAIL", help="Equivalent to NCBI_EMAIL (good E-utilities citizenship).")
    ap.add_argument(
        "--llm-provider",
        choices=["gemini", "ollama"],
        default=os.environ.get("LLM_PROVIDER", "gemini"),
        help=(
            "Which LLM backend to use for supplement extraction (step 6). 'gemini' (default) "
            "needs GOOGLE_API_KEY and hits Google's API (subject to its free-tier daily quota). "
            "'ollama' runs fully locally against a running `ollama serve` daemon - no API key or "
            "internet needed for the LLM step itself, but you must `pip install ollama` and "
            "`ollama pull <model>` first. Defaults to $LLM_PROVIDER if set, else gemini."
        ),
    )
    ap.add_argument(
        "--llm-model",
        default=None,
        metavar="MODEL",
        help=(
            "Model name override for whichever --llm-provider is selected (e.g. gemini-3.6-flash "
            "for gemini, or llama3.1:8b / qwen2.5:7b for ollama). Defaults to the GEMINI_MODEL or "
            "OLLAMA_MODEL env var (matching the active provider), or that provider's built-in default."
        ),
    )
    args = ap.parse_args()

    if args.ncbi_api_key:
        os.environ["NCBI_API_KEY"] = args.ncbi_api_key
    if args.ncbi_email:
        os.environ["NCBI_EMAIL"] = args.ncbi_email

    # Picked up by amr_extraction.llm.query_structured() via LLM_PROVIDER / GEMINI_MODEL /
    # OLLAMA_MODEL env vars, since extract_ast_from_supplements() passes query_structured itself
    # (not a per-call wrapper) as excel_extractor's query_fn.
    os.environ["LLM_PROVIDER"] = args.llm_provider
    if args.llm_model:
        if args.llm_provider == "ollama":
            os.environ["OLLAMA_MODEL"] = args.llm_model
        else:
            os.environ["GEMINI_MODEL"] = args.llm_model
    if not args.no_extract:
        print(f"LLM provider for supplement extraction: {args.llm_provider}"
              + (f" (model: {args.llm_model})" if args.llm_model else ""))

    records = parse_input(args.input)
    print(f"Found {len(records)} unique valid PMIDs in {args.input}")

    print("Fetching titles/authors/years/PMCIDs/DOIs ...")
    fetch_summaries(records)

    if not args.no_bvbrc:
        print("Looking up BV-BRC genomes/accessions per PMID ...")
        fetch_bvbrc_genomes(records)

    print("Fetching full text, classifying AST location, extracting main-text AST tables ...")
    fetch_and_classify(records, args.outdir)

    failures: list[dict] = []
    if not args.no_download:
        print("Attempting to download supplementary files ...")
        failures = download_supplements(records, args.outdir, use_browser=not args.no_browser)

    # Always refresh from disk (cheap), whether or not a download happened this run, so the
    # supplement_paths output column reflects whatever files actually exist right now.
    scan_downloaded_supplements(records, args.outdir)

    extracted_rows: list[dict] = []
    if not args.no_extract:
        # Reads whatever's already on disk under <outdir>/supplements/ — doesn't require having
        # just downloaded anything this run, so re-running with --no-download (e.g. after fixing
        # GOOGLE_API_KEY or the Gemini model) re-extracts from previously downloaded files without
        # hitting PMC again.
        print("Extracting normalized AST records from downloaded xlsx/xls supplements ...")
        extracted_rows = extract_ast_from_supplements(records, args.outdir)

    write_outputs(records, args.outdir, args.input.stem, failures, extracted_rows)


if __name__ == "__main__":
    main()
