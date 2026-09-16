#!/usr/bin/env python3
"""Find AST (antimicrobial susceptibility testing) evidence for a list of PMIDs.

Reads a genome_id/genome_id/PMID mapping file (e.g. data/query_pmids_to_find_ast/Staph.pmid.txt),
looks up each unique PMID in PubMed Central, and classifies whether the paper's antimicrobial
susceptibility data (MIC values, disk-diffusion zones, S/I/R calls, breakpoints, etc.) lives in
the main text, in a supplementary file, or wasn't found — mirroring the manual classification in
data/starter/paper_classification.tsv.

Where possible, it also downloads any supplementary files it finds and records the outcome in a
download report, following the same conventions as data/starter/download_report.json.

USAGE
    python find_ast_evidence.py data/query_pmids_to_find_ast/Staph.pmid.txt \\
        --outdir data/query_pmids_to_find_ast/output

NETWORK
    This script calls the NCBI E-utilities directly over HTTPS (eutils.ncbi.nlm.nih.gov) plus
    pmc.ncbi.nlm.nih.gov for supplementary file downloads. Run it somewhere with normal outbound
    internet access to those hosts — it will not work behind a proxy/allowlist that blocks NCBI.
    Get a free NCBI API key
    (https://www.ncbi.nlm.nih.gov/account/) and set NCBI_API_KEY to raise the rate limit from
    3 req/s to 10 req/s; set NCBI_EMAIL / NCBI_TOOL as good E-utilities citizenship.

OUTPUT (written under --outdir)
    paper_classification_<basename>.tsv   one row per unique PMID, same shape as
                                           data/starter/paper_classification.tsv plus extra columns
    download_report.json                  per-paper supplement download summary + failure log
    supplements/<pmid>/...                downloaded supplementary files, where retrievable
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
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PMC_BIN = "https://pmc.ncbi.nlm.nih.gov/articles/instance/{numeric}/bin/{fname}"

USER_AGENT = "amr-evidence-extraction-ast-finder/1.0 (+https://github.com/NIAID-BRC-Codeathons)"

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

ACCESSION_RE = re.compile(
    r"\b(SAMN\d+|SAMEA\d+|SAMD\d+|PRJNA\d+|PRJEB\d+|PRJDB\d+|SRR\d+|ERR\d+|DRR\d+|BioSample|BioProject)\b"
)


@dataclass
class PaperRecord:
    pmid: str
    genome_ids: list[str] = field(default_factory=list)
    pmcid: str | None = None
    doi: str | None = None
    title: str | None = None
    first_author: str | None = None
    year: str | None = None
    ast_location: str = "unclassified"
    biosample_hint: str = "unclear"
    supplement_files: list[str] = field(default_factory=list)
    supplement_downloaded: int = 0
    details: str = ""
    failures: list[str] = field(default_factory=list)


def http_get(url: str, params: dict | None = None, timeout: int = 30, binary: bool = False):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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


def rate_sleep():
    time.sleep(0.11 if os.environ.get("NCBI_API_KEY") else 0.34)


def parse_input(path: Path) -> dict[str, PaperRecord]:
    """Parse a genome_id \\t genome_id \\t pmid file into one record per unique, valid PMID."""
    records: dict[str, PaperRecord] = {}
    with path.open() as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            genome_id, _, pmid = parts[0], parts[1], parts[2]
            pmid = pmid.strip()
            if not pmid or pmid == "-" or not pmid.isdigit():
                continue
            rec = records.setdefault(pmid, PaperRecord(pmid=pmid))
            if genome_id not in rec.genome_ids:
                rec.genome_ids.append(genome_id)
    return records


def fetch_summaries(records: dict[str, PaperRecord]) -> None:
    """Batch title/author/year/PMCID/DOI lookup via ESummary (single eutils host — this is
    the same call, same host, that reliably returns title/author/year, so PMCID/DOI are
    pulled from its `articleids` field instead of a separate idconv call. NCBI's web-facing
    idconv endpoint (www.ncbi.nlm.nih.gov) has been observed silently returning zero matches
    for scripted/automated clients even for PMIDs that do have a PMCID — eutils.ncbi.nlm.nih.gov
    is the actual API host and is far more reliable for this."""
    pmids = list(records.keys())
    resolved = 0
    for i in range(0, len(pmids), 200):
        chunk = pmids[i : i + 200]
        data, ctype = http_get(
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
            print(f"  WARNING: esummary returned no 'result' for {len(chunk)} PMIDs — response: {str(payload)[:300]}", file=sys.stderr)
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
                idtype = aid.get("idtype", "")
                value = aid.get("value", "")
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


def classify_fulltext(xml_bytes: bytes) -> tuple[str, list[str], str, str]:
    """Return (ast_location, supplement_filenames, biosample_hint, details_snippet)."""
    try:
        text = xml_bytes.decode("utf-8", errors="ignore")
    except Exception:
        text = str(xml_bytes)

    ast_hits = AST_RE.findall(text)
    if not ast_hits:
        return "none_found", [], "unclear", "No AST-related keywords found in full text."

    # Pull supplementary-material filenames out of the JATS XML if present.
    supp_files: list[str] = []
    try:
        root = ET.fromstring(text)
        ns = {"xlink": "http://www.w3.org/1999/xlink"}
        for supp in root.iter("supplementary-material"):
            for media in supp.iter():
                href = media.attrib.get("{http://www.w3.org/1999/xlink}href") or media.attrib.get("href")
                if href:
                    supp_files.append(href)
    except ET.ParseError:
        pass

    has_supp_ref = bool(SUPPLEMENT_REF_RE.search(text)) or bool(supp_files)
    has_main_table_ref = bool(MAIN_TABLE_RE.search(text))
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
    details = f"AST keyword hits: {top}."
    return location, supp_files, biosample_hint, details


def fetch_and_classify(records: dict[str, PaperRecord]) -> None:
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

        location, supp_files, biosample_hint, details = classify_fulltext(data)
        rec.ast_location = location
        rec.supplement_files = supp_files
        rec.biosample_hint = biosample_hint
        rec.details = details
        rate_sleep()


def download_supplements(records: dict[str, PaperRecord], outdir: Path) -> list[dict]:
    """Best-effort download of any supplementary files found in the full text."""
    failures: list[dict] = []
    for pmid, rec in records.items():
        if not rec.pmcid or not rec.supplement_files:
            continue
        numeric = rec.pmcid.lstrip("PMC")
        dest_dir = outdir / "supplements" / pmid
        for fname in rec.supplement_files:
            base = fname.rsplit("/", 1)[-1]
            url = PMC_BIN.format(numeric=numeric, fname=base)
            try:
                data, ctype = http_get(url, timeout=60)
            except (urllib.error.URLError, urllib.error.HTTPError) as e:
                failures.append({"pmid": pmid, "pmcid": rec.pmcid, "url": url, "error": str(e)})
                continue
            if "text/html" in ctype.lower() or data[:15].lstrip().lower().startswith(b"<!doctype html"):
                failures.append(
                    {
                        "pmid": pmid,
                        "pmcid": rec.pmcid,
                        "url": url,
                        "error": "not downloaded; PMC returned an anti-bot/HTML interstitial instead of the file",
                    }
                )
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / base).write_bytes(data)
            rec.supplement_downloaded += 1
            rate_sleep()
    return failures


def write_outputs(records: dict[str, PaperRecord], outdir: Path, basename: str, failures: list[dict]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    tsv_path = outdir / f"paper_classification_{basename}.tsv"
    cols = [
        "pmid", "pmcid", "doi", "title", "first_author", "year", "genome_id_count",
        "ast_location", "biosample_hint", "supplement_files", "supplement_downloaded", "details",
    ]
    with tsv_path.open("w") as f:
        f.write("\t".join(cols) + "\n")
        for pmid in sorted(records, key=lambda p: -len(records[p].genome_ids)):
            r = records[pmid]
            row = [
                r.pmid, r.pmcid or "", r.doi or "", r.title or "", r.first_author or "", r.year or "",
                str(len(r.genome_ids)), r.ast_location, r.biosample_hint,
                ";".join(r.supplement_files), str(r.supplement_downloaded), r.details,
            ]
            f.write("\t".join(x.replace("\t", " ").replace("\n", " ") for x in row) + "\n")

    report = {
        "summary": [
            {
                "pmid": r.pmid,
                "pmcid": r.pmcid,
                "ast_location": r.ast_location,
                "supplement_files": len(r.supplement_files),
                "supplement_downloaded": r.supplement_downloaded,
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
    ap.add_argument("input", type=Path, help="genome_id\\tgenome_id\\tpmid file, e.g. Staph.pmid.txt")
    ap.add_argument("--outdir", type=Path, default=Path("output"), help="Directory for outputs")
    ap.add_argument("--no-download", action="store_true", help="Skip downloading supplementary files")
    args = ap.parse_args()

    records = parse_input(args.input)
    print(f"Found {len(records)} unique valid PMIDs in {args.input}")

    print("Fetching titles/authors/years/PMCIDs/DOIs ...")
    fetch_summaries(records)
    print("Fetching full text and classifying AST location ...")
    fetch_and_classify(records)

    failures: list[dict] = []
    if not args.no_download:
        print("Attempting to download supplementary files ...")
        failures = download_supplements(records, args.outdir)

    write_outputs(records, args.outdir, args.input.stem, failures)


if __name__ == "__main__":
    main()
