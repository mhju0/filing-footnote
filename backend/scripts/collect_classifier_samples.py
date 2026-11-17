"""Collect text samples the M2 category rules are written against (read-only, live).

Run from ``backend/`` so ``app.config`` finds ``.env``::

    cd backend && ../.venv/bin/python scripts/collect_classifier_samples.py

Reads the M1 list fixtures under ``tests/fixtures/events/`` and fetches:

* DART ``document.xml`` for every plain ``영업(잠정)실적`` row;
* for every SEC 8-K / 8-K/A with Item 2.02, 7.01 or 8.01, the filing index, the full primary
  document and every ``EX-99.*`` exhibit, saved as one gzip JSON per accession
  (``sec/<accession>.json.gz``). Document types are the index types (``8-K``, ``EX-99.1``).

``--sec-only`` skips the DART bodies. The gzip files cannot be grepped for the DART key, so
each SEC record is checked for it before it is compressed.

Output goes to ``tests/fixtures/events/classifier/``. The DART key is never recorded and the
output is scanned for it (and the literal ``crtfc_key``) before the script ends.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import datetime as dt  # noqa: E402

from sample_event_sources import (  # noqa: E402
    DART_COMPANIES,
    DEFAULT_OUT,
    SEC_COMPANIES,
    Sampler,
    _html_to_text,
    document_basename,
    parse_index_html_table,
    strip_prefixes,
    strip_sgml_header,
)

from app.clients.sec import _archive_url, format_cik  # noqa: E402

OUT_DIR = DEFAULT_OUT / "classifier"
SEC_WANTED_ITEMS = {"2.02", "7.01", "8.01"}
SKIP_SUFFIXES = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".xlsx", ".xls")


def plain_earnings_rows(list_dir: Path) -> list[dict[str, str]]:
    """Every plain ``영업(잠정)실적`` row (not the consolidated name)."""
    picked: list[dict[str, str]] = []
    for code in DART_COMPANIES:
        path = list_dir / f"{code}_I.json"
        if not path.exists():
            continue
        rows = []
        for row in json.loads(path.read_text(encoding="utf-8"))["list"]:
            name, _ = strip_prefixes(str(row.get("report_nm", "")))
            if name.startswith("영업(잠정)실적"):
                rows.append({"code": code, "rcept_no": str(row["rcept_no"]), "name": name})
        rows.sort(key=lambda r: r["rcept_no"])
        picked.extend(rows)
    return picked


def sec_rows(sub_dir: Path) -> list[dict[str, str]]:
    rows = []
    for ticker in SEC_COMPANIES:
        path = sub_dir / f"{ticker}.json"
        if not path.exists():
            continue
        for row in json.loads(path.read_text(encoding="utf-8"))["rows"]:
            items = {i.strip() for i in str(row["items"]).split(",")}
            if items & SEC_WANTED_ITEMS:
                rows.append({"ticker": ticker, **row})
    return rows


async def collect_dart(sampler: Sampler, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        rec = await sampler.fetch_document_record(row["rcept_no"])
        out.append(
            {
                "rcept_no": row["rcept_no"],
                "code": row["code"],
                "http": rec.get("http_status"),
                "zip": rec.get("zip"),
                "decoded_chars": rec.get("decoded_chars"),
            }
        )
    return out


async def collect_sec(sampler: Sampler, rows: list[dict[str, str]]) -> dict[str, Any]:
    skipped: list[dict[str, str]] = []
    failures: list[str] = []
    for row in rows:
        cik = SEC_COMPANIES[row["ticker"]]
        acc = row["accessionNumber"]
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
        http, body = await sampler.sec_get(f"{base}/{acc}-index.html")
        table = parse_index_html_table(body.decode("utf-8", "replace")) if http == 200 else []
        if not table:
            failures.append(f"{acc}: index http={http}")
        primary_type = row["form"]
        for r in table:
            if document_basename(r.get("href")) == row["primaryDocument"] and r.get("Type"):
                primary_type = str(r["Type"])
        wanted: list[tuple[str, str]] = [(primary_type, row["primaryDocument"])]
        for r in table:
            name = document_basename(r.get("href"))
            if name and str(r.get("Type", "")).upper().startswith("EX-99"):
                if (str(r["Type"]), name) not in wanted:
                    wanted.append((str(r["Type"]), name))
        documents = []
        for doc_type, name in wanted:
            if name.lower().endswith(SKIP_SUFFIXES):
                skipped.append({"accession": acc, "type": doc_type, "filename": name})
                continue
            http, raw = await sampler.sec_get(_archive_url(format_cik(cik), acc, name))
            if http != 200:
                failures.append(f"{acc}: {name} http={http}")
                continue
            text = _html_to_text(strip_sgml_header(raw.decode("utf-8", "replace")))
            documents.append({"type": doc_type, "filename": name, "text": text})
        record = json.dumps(
            {
                "ticker": row["ticker"],
                "accession": acc,
                "form": row["form"],
                "items": row["items"],
                "filingDate": row["filingDate"],
                "documents": documents,
            },
            ensure_ascii=False,
        )
        if "crtfc_key" in record or (sampler.secret and sampler.secret in record):
            raise SystemExit(f"DART key text found in SEC record {acc}; nothing written for it")
        sampler.save_bytes(f"sec/{acc}.json.gz", gzip.compress(record.encode("utf-8"), mtime=0))
    return {"skipped": skipped, "failures": failures}


async def main_async(sec_only: bool) -> int:
    sampler = Sampler(OUT_DIR, dt.date(2026, 11, 17))
    dart_rows = plain_earnings_rows(DEFAULT_OUT / "dart" / "list")
    sec_targets = sec_rows(DEFAULT_OUT / "sec" / "submissions_8k")
    leak_ok = False
    sec_dir = OUT_DIR / "sec"
    if sec_dir.is_dir():
        for old in sec_dir.iterdir():
            old.unlink()
    try:
        dart_result = [] if sec_only else await collect_dart(sampler, dart_rows)
        sec_result = await collect_sec(sampler, sec_targets)
    finally:
        await sampler.http.aclose()
        leak_ok = sampler.leak_scan()
    print(f"requests: dart={sampler.dart_calls} sec={sampler.sec_calls}")
    print(f"dart bodies: {len(dart_result)} {dict(Counter(r['code'] for r in dart_result))}")
    print(f"sec accessions: {len(sec_targets)}; skipped docs: {sec_result['skipped']}")
    print(f"sec failures: {sec_result['failures']}")
    print(f"files written: {len(sampler.written)}")
    return 0 if leak_ok else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sec-only", action="store_true", help="skip the DART bodies")
    raise SystemExit(asyncio.run(main_async(parser.parse_args().sec_only)))
