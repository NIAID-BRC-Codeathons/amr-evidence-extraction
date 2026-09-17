#!/usr/bin/env python3
"""Match isolate_id values already extracted into data/andrew_ast/<pmid>.*.tsv against real
NCBI BioSample records, using the BioProject accession(s) find_ast_evidence.py already found
for that PMID (paper_classification_<basename>.tsv's bioproject_accessions column, falling
back to any PRJNA*/PRJDB*/PRJEB* tokens in data_availability_accessions).

BACKGROUND
    A paper's Data Availability statement usually names a BioProject accession (e.g. PRJDB8056)
    covering the isolates it sequenced, but the per-isolate extraction (extract_excel_codegen.py
    / extract_ast_tables_codegen.py) has no way to know which BioSample under that BioProject
    corresponds to which extracted isolate_id -- it only sees the paper's own tables, not NCBI.
    This script closes that gap with a straightforward, verified chain:

        esearch (db=bioproject, term=<ACCESSION>)         -> BioProject's internal UID
        elink   (dbfrom=bioproject, db=biosample, id=UID)  -> linked BioSample UIDs
        esummary(db=biosample, id=<UIDs>)                  -> each BioSample's 'strain' attribute
                                                               (parsed from 'infraspecies', e.g.
                                                               "strain: KG-03") plus its SRA
                                                               accession (parsed from
                                                               'identifiers', e.g. "SRA: DRS091762")

    ...then matches each BioSample's strain name against the isolate_id values already sitting
    in data/andrew_ast/<pmid>.mic.tsv and/or <pmid>.ast_tables.tsv.

    Verified by hand for PMID 31474962 / BioProject PRJDB8056: all 13 BioSamples' strain
    attributes (KG-03, KG-06, KG-18, ...) matched exactly against that PMID's Table 1 isolate
    IDs. See conversation history for the full curl-by-curl trace this script automates.

IMPORTANT -- NETWORK ACCESS
    This talks to eutils.ncbi.nlm.nih.gov. That domain is blocked from Claude's own sandboxes
    (both the cloud container and the local device_bash VM refuse the connection), so THIS
    SCRIPT MUST BE RUN FROM YOUR OWN TERMINAL, not through Claude's tools. It only needs
    standard library (urllib), no extra pip installs.

USAGE
    # Report-only (default): prints matches, writes a report TSV, does not touch andrew_ast/.
    python scripts/query_pmids_to_find_ast/match_isolates_to_biosample.py --pmid 31474962

    # Same, but also fill in blank bioproject_accession/biosample_accession/sra_accession
    # columns in data/andrew_ast/<pmid>.*.tsv for exact-match rows. Never overwrites a
    # non-blank accession value already present, and writes a <file>.bak backup first.
    python scripts/query_pmids_to_find_ast/match_isolates_to_biosample.py --pmid 31474962 --apply

    # Use a specific BioProject accession instead of reading one from the classification TSV
    # (useful for testing, or a PMID whose classification row doesn't have one):
    python scripts/query_pmids_to_find_ast/match_isolates_to_biosample.py --pmid 31474962 \\
        --bioproject PRJDB8056

    # Optional: an NCBI API key raises the rate limit from 3 req/s to 10 req/s
    # (https://www.ncbi.nlm.nih.gov/account/settings/ -> API Key Management).
    export NCBI_API_KEY=xxxxxxxx

OUTPUT
    scripts/query_pmids_to_find_ast/output/biosample_matches/<pmid>.isolate_biosample_matches.tsv
    Columns: pmid, source_file, isolate_id, match_type, matched_strain, bioproject_accession,
    biosample_accession, sra_accession
    match_type is 'exact' (case-insensitive, whitespace-normalized equality) or 'fuzzy'
    (one string contains the other) -- only 'exact' matches are ever written back with --apply;
    'fuzzy' matches are reported for manual review only.

CAVEATS
    - Only as good as the BioProject accession found in the paper: if the Data Availability
      statement names the wrong accession, or covers a different/larger sample set than the
      table in question, matches will be wrong or spurious. Always sanity-check the report TSV
      before trusting --apply's results.
    - isolate_id extraction quality matters. If the source extraction produced generic
      placeholders (e.g. "isolate_1") instead of real strain names, there is nothing to match
      against -- fix the extraction first (see extract_ast_tables_codegen.py's read_ast_table
      for one real example of this).
    - A BioProject can have far more (or fewer) BioSamples than the paper's own table -- e.g. a
      lab's umbrella BioProject accumulated across several papers. Unmatched BioSamples and
      unmatched isolate_ids are both normal and are reported as such, not treated as errors.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_CLASSIFICATION_GLOB = "scripts/query_pmids_to_find_ast/output/paper_classification_*.tsv"
DEFAULT_ANDREW_AST_DIR = "data/andrew_ast"
DEFAULT_OUTDIR = "scripts/query_pmids_to_find_ast/output/biosample_matches"
ACCESSION_COLUMNS_TO_FILL = ["bioproject_accession", "biosample_accession", "sra_accession"]

BIOPROJECT_TOKEN_RE = re.compile(r"^PRJ(?:NA|EB|DB)\d+$")


def _eutils_get(endpoint: str, params: dict, api_key: Optional[str], email: Optional[str]) -> dict:
    """GETs one eutils endpoint with retmode=json, a small delay for NCBI's rate limit, and
    basic retry-on-failure. Returns the parsed JSON dict."""
    query = dict(params)
    query["retmode"] = "json"
    if api_key:
        query["api_key"] = api_key
    if email:
        query["email"] = email
        query["tool"] = "amr-evidence-extraction"
    url = f"{EUTILS_BASE}/{endpoint}?{urllib.parse.urlencode(query)}"

    delay = 0.11 if api_key else 0.35  # ~10/s with a key, ~3/s (NCBI's public limit) without
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            time.sleep(delay)
            return data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"eutils request to '{endpoint}' failed after retries: {last_err}") from last_err


def bioproject_accession_to_uid(accession: str, api_key: Optional[str], email: Optional[str]) -> Optional[str]:
    data = _eutils_get("esearch.fcgi", {"db": "bioproject", "term": accession}, api_key, email)
    idlist = data.get("esearchresult", {}).get("idlist", [])
    return idlist[0] if idlist else None


def bioproject_uid_to_biosample_uids(uid: str, api_key: Optional[str], email: Optional[str]) -> list[str]:
    data = _eutils_get(
        "elink.fcgi",
        {"dbfrom": "bioproject", "db": "biosample", "id": uid},
        api_key, email,
    )
    linksets = data.get("linksets", [])
    if not linksets:
        return []
    for linksetdb in linksets[0].get("linksetdbs", []):
        if linksetdb.get("dbto") == "biosample":
            return list(linksetdb.get("links", []))
    return []


_STRAIN_FROM_INFRASPECIES_RE = re.compile(r"strain:\s*(.+)$", re.IGNORECASE)
_SRA_FROM_IDENTIFIERS_RE = re.compile(r"\bSRA:\s*([A-Z]{3}\d+)", re.IGNORECASE)


def biosample_uids_to_records(uids: list[str], api_key: Optional[str], email: Optional[str]) -> list[dict]:
    """Batches esummary calls (NCBI is fine with large id lists in one call, but this chunks
    defensively at 200 to stay well under any URL-length limits) and extracts strain name +
    accession + SRA id from each BioSample summary."""
    records = []
    for i in range(0, len(uids), 200):
        chunk = uids[i:i + 200]
        data = _eutils_get(
            "esummary.fcgi", {"db": "biosample", "id": ",".join(chunk)}, api_key, email,
        )
        result = data.get("result", {})
        for uid in result.get("uids", []):
            doc = result.get(uid, {})
            strain = None
            m = _STRAIN_FROM_INFRASPECIES_RE.search(doc.get("infraspecies", "") or "")
            if m:
                strain = m.group(1).strip()
            if not strain:
                # fall back to the sample title, which is often "... str. <strain>" or just
                # "<strain>" outright
                title = (doc.get("title", "") or "").strip()
                tm = re.search(r"str\.\s*(\S+)\s*$", title)
                strain = tm.group(1) if tm else (title or None)
            sra = None
            sm = _SRA_FROM_IDENTIFIERS_RE.search(doc.get("identifiers", "") or "")
            if sm:
                sra = sm.group(1)
            records.append({
                "biosample_uid": uid,
                "biosample_accession": doc.get("accession", ""),
                "strain": strain or "",
                "sra_accession": sra or "",
            })
    return records


def resolve_biosamples_for_bioproject(
    bioproject_accession: str, api_key: Optional[str], email: Optional[str]
) -> list[dict]:
    print(f"[*] esearch bioproject '{bioproject_accession}'...", file=sys.stderr)
    uid = bioproject_accession_to_uid(bioproject_accession, api_key, email)
    if not uid:
        print(f"[!] No BioProject UID found for '{bioproject_accession}'.", file=sys.stderr)
        return []
    print(f"[*] elink bioproject UID {uid} -> biosample...", file=sys.stderr)
    biosample_uids = bioproject_uid_to_biosample_uids(uid, api_key, email)
    if not biosample_uids:
        print(f"[!] No linked BioSamples found for BioProject '{bioproject_accession}' (UID {uid}).", file=sys.stderr)
        return []
    print(f"[*] esummary for {len(biosample_uids)} BioSample UID(s)...", file=sys.stderr)
    records = biosample_uids_to_records(biosample_uids, api_key, email)
    for r in records:
        r["bioproject_accession"] = bioproject_accession
    print(f"[OK] Resolved {len(records)} BioSample record(s) for '{bioproject_accession}'.", file=sys.stderr)
    return records


def find_classification_row(pmid: str, classification_glob: str) -> Optional[dict]:
    import glob
    for path in sorted(glob.glob(classification_glob)):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if row.get("pmid") == pmid:
                    return row
    return None


def bioproject_accessions_for_pmid(pmid: str, classification_glob: str) -> list[str]:
    row = find_classification_row(pmid, classification_glob)
    if row is None:
        print(f"[!] PMID '{pmid}' not found in any file matching '{classification_glob}'.", file=sys.stderr)
        return []
    accs = [a for a in (row.get("bioproject_accessions") or "").split(";") if a.strip()]
    if not accs:
        # fall back to PRJ* tokens scraped from the paper's Data Availability statement
        da_tokens = (row.get("data_availability_accessions") or "").split(";")
        accs = [t for t in da_tokens if BIOPROJECT_TOKEN_RE.match(t.strip())]
    return sorted(set(a.strip() for a in accs if a.strip()))


def _normalize_id(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).casefold()


def load_isolate_ids(andrew_ast_dir: str, pmid: str) -> list[tuple[str, str]]:
    """Returns [(source_filename, isolate_id), ...] for every non-blank isolate_id across
    <pmid>.mic.tsv and <pmid>.ast_tables.tsv in andrew_ast_dir (whichever exist)."""
    out = []
    for suffix in (".mic.tsv", ".ast_tables.tsv"):
        path = os.path.join(andrew_ast_dir, f"{pmid}{suffix}")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                val = (row.get("isolate_id") or "").strip()
                if val:
                    out.append((os.path.basename(path), val))
    # de-dupe while preserving first-seen order
    seen = set()
    deduped = []
    for src, iid in out:
        key = (src, iid)
        if key not in seen:
            seen.add(key)
            deduped.append((src, iid))
    return deduped


def match_isolates(
    isolate_rows: list[tuple[str, str]], biosample_records: list[dict]
) -> list[dict]:
    by_norm_strain: dict[str, dict] = {}
    for rec in biosample_records:
        if rec["strain"]:
            by_norm_strain.setdefault(_normalize_id(rec["strain"]), rec)

    matches = []
    for source_file, isolate_id in isolate_rows:
        norm_iid = _normalize_id(isolate_id)
        exact = by_norm_strain.get(norm_iid)
        if exact:
            matches.append({
                "source_file": source_file, "isolate_id": isolate_id, "match_type": "exact",
                "matched_strain": exact["strain"],
                "bioproject_accession": exact["bioproject_accession"],
                "biosample_accession": exact["biosample_accession"],
                "sra_accession": exact["sra_accession"],
            })
            continue
        # fuzzy fallback: substring match either direction, only if reasonably specific
        # (skip anything under 3 chars to avoid nonsense matches like "1" matching everything)
        fuzzy_hit = None
        if len(norm_iid) >= 3:
            for norm_strain, rec in by_norm_strain.items():
                if len(norm_strain) >= 3 and (norm_iid in norm_strain or norm_strain in norm_iid):
                    fuzzy_hit = rec
                    break
        if fuzzy_hit:
            matches.append({
                "source_file": source_file, "isolate_id": isolate_id, "match_type": "fuzzy",
                "matched_strain": fuzzy_hit["strain"],
                "bioproject_accession": fuzzy_hit["bioproject_accession"],
                "biosample_accession": fuzzy_hit["biosample_accession"],
                "sra_accession": fuzzy_hit["sra_accession"],
            })
        else:
            matches.append({
                "source_file": source_file, "isolate_id": isolate_id, "match_type": "no_match",
                "matched_strain": "", "bioproject_accession": "", "biosample_accession": "", "sra_accession": "",
            })
    return matches


def write_report(pmid: str, matches: list[dict], outdir: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"{pmid}.isolate_biosample_matches.tsv")
    cols = ["pmid", "source_file", "isolate_id", "match_type", "matched_strain",
            "bioproject_accession", "biosample_accession", "sra_accession"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(cols)
        for m in matches:
            writer.writerow([pmid] + [m.get(c, "") for c in cols[1:]])
    return out_path


def apply_matches_to_andrew_ast(andrew_ast_dir: str, pmid: str, matches: list[dict]) -> None:
    """Fills blank bioproject_accession/biosample_accession/sra_accession cells in
    data/andrew_ast/<pmid>.*.tsv for 'exact' matches only, never overwriting a non-blank value
    already present. Writes a .bak of each file it touches before modifying it."""
    exact_by_file: dict[str, dict[str, dict]] = {}
    for m in matches:
        if m["match_type"] != "exact":
            continue
        exact_by_file.setdefault(m["source_file"], {})[_normalize_id(m["isolate_id"])] = m

    for fname, by_iid in exact_by_file.items():
        path = os.path.join(andrew_ast_dir, fname)
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            fieldnames = reader.fieldnames
            rows = list(reader)

        if not fieldnames or not all(c in fieldnames for c in ACCESSION_COLUMNS_TO_FILL):
            print(f"[!] '{fname}' is missing expected accession columns; skipping --apply for it.", file=sys.stderr)
            continue

        changed = 0
        for row in rows:
            m = by_iid.get(_normalize_id((row.get("isolate_id") or "").strip()))
            if not m:
                continue
            for col in ACCESSION_COLUMNS_TO_FILL:
                if not (row.get(col) or "").strip() and (m.get(col) or "").strip():
                    row[col] = m[col]
                    changed += 1

        if changed == 0:
            continue

        backup_path = path + ".bak"
        if not os.path.exists(backup_path):
            with open(path, "r", encoding="utf-8") as src, open(backup_path, "w", encoding="utf-8") as dst:
                dst.write(src.read())

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
        print(f"[OK] Filled {changed} accession cell(s) in '{path}' (backup at '{backup_path}').")


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pmid", required=True, help="PMID to match isolates for.")
    parser.add_argument("--bioproject", default=None,
                         help="Explicit BioProject accession(s), comma-separated, overriding the "
                              "classification TSV lookup.")
    parser.add_argument("--classification-glob", default=DEFAULT_CLASSIFICATION_GLOB,
                         help=f"Glob for paper_classification_*.tsv file(s) (default: {DEFAULT_CLASSIFICATION_GLOB})")
    parser.add_argument("--andrew-ast-dir", default=DEFAULT_ANDREW_AST_DIR,
                         help=f"Directory containing <pmid>.mic.tsv / <pmid>.ast_tables.tsv (default: {DEFAULT_ANDREW_AST_DIR})")
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR, help=f"Where to write the match report TSV (default: {DEFAULT_OUTDIR})")
    parser.add_argument("--apply", action="store_true",
                         help="Also fill blank accession columns in the andrew_ast TSVs for exact matches (writes .bak backups).")
    parser.add_argument("--api-key", default=None, help="NCBI API key (default: $NCBI_API_KEY env var, if set).")
    parser.add_argument("--email", default=None, help="Contact email to send with eutils requests (recommended by NCBI, optional).")
    return parser


def main() -> None:
    args = build_cli_parser().parse_args()
    api_key = args.api_key or os.environ.get("NCBI_API_KEY")

    if args.bioproject:
        bioproject_accessions = [a.strip() for a in args.bioproject.split(",") if a.strip()]
    else:
        bioproject_accessions = bioproject_accessions_for_pmid(args.pmid, args.classification_glob)

    if not bioproject_accessions:
        print(f"[!] No BioProject accession found for PMID '{args.pmid}' (and none given via --bioproject). Nothing to do.", file=sys.stderr)
        sys.exit(1)
    print(f"[*] BioProject accession(s) for PMID {args.pmid}: {', '.join(bioproject_accessions)}", flush=True)

    biosample_records: list[dict] = []
    for acc in bioproject_accessions:
        biosample_records.extend(resolve_biosamples_for_bioproject(acc, api_key, args.email))

    if not biosample_records:
        print(f"[!] No BioSamples resolved for PMID '{args.pmid}'. Nothing to match against.", file=sys.stderr)
        sys.exit(1)

    isolate_rows = load_isolate_ids(args.andrew_ast_dir, args.pmid)
    if not isolate_rows:
        print(f"[!] No isolate_id values found in '{args.andrew_ast_dir}' for PMID '{args.pmid}'.", file=sys.stderr)
        sys.exit(1)
    print(f"[*] Loaded {len(isolate_rows)} isolate_id value(s) from andrew_ast/ for PMID {args.pmid}.", flush=True)

    matches = match_isolates(isolate_rows, biosample_records)
    exact = sum(1 for m in matches if m["match_type"] == "exact")
    fuzzy = sum(1 for m in matches if m["match_type"] == "fuzzy")
    no_match = sum(1 for m in matches if m["match_type"] == "no_match")
    print(f"[*] Matches: {exact} exact, {fuzzy} fuzzy, {no_match} unmatched (of {len(matches)} isolate_id values).", flush=True)

    report_path = write_report(args.pmid, matches, args.outdir)
    print(f"[OK] Wrote match report to '{report_path}'", flush=True)

    if args.apply:
        apply_matches_to_andrew_ast(args.andrew_ast_dir, args.pmid, matches)
    elif exact:
        print("[*] Re-run with --apply to fill blank accession columns in andrew_ast/ for the exact matches above.", flush=True)


if __name__ == "__main__":
    main()
