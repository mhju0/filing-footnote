"""Read-only sampling of Korean DART event filings and US SEC 8-Ks (milestone M1).

Run from ``backend/`` so ``app.config`` finds ``.env``::

    cd backend && ../.venv/bin/python scripts/sample_event_sources.py --report

It makes live GET requests, saves raw samples under ``tests/fixtures/events/`` and writes
``sample_summary.json``. The DART key is sent only as a query parameter, never recorded, and
every written file is scanned for the key before the script finishes.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import shutil
import sys
import time
import zipfile
from collections import Counter
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from defusedxml.ElementTree import fromstring as _xml_fromstring

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.clients.dart import (  # noqa: E402
    DartClient,
    _extract_document_member,
    decode_dart_bytes,
    detect_document_format,
    extract_dsd_prose,
    parse_dart_decimal,
)
from app.clients.sec import _archive_url, format_cik  # noqa: E402
from app.clients.sec_document import _html_to_text  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402

DART_COMPANIES = {
    "005930": "Samsung Electronics",
    "000660": "SK Hynix",
    "035420": "NAVER",
    "005380": "Hyundai Motor",
    "000270": "Kia",
    "006400": "Samsung SDI",
    "051910": "LG Chem",
    "066570": "LG Electronics",
    "207940": "Samsung Biologics",
}
SEC_COMPANIES = {
    "AAPL": 320193,
    "MSFT": 789019,
    "NVDA": 1045810,
    "TSLA": 1318605,
    "AMZN": 1018724,
    "COST": 909832,
    "GOOGL": 1652044,
    "META": 1326801,
    "WMT": 104169,
}
DEFAULT_OUT = _BACKEND_DIR / "tests" / "fixtures" / "events"
DART_INTERVAL = 0.35
SEC_INTERVAL = 0.25
DOC_SAVE_LIMIT = 400_000
SEC_8K_FORMS = {"8-K", "8-K/A"}
SEC_COLUMNS = (
    "accessionNumber",
    "filingDate",
    "reportDate",
    "form",
    "items",
    "primaryDocument",
    "primaryDocDescription",
)
_PREFIX_RE = re.compile(r"^\s*((?:\[[^\]]*\]\s*)+)")


# -- pure helpers (offline-tested) ---------------------------------------------------------


def strip_prefixes(report_nm: str) -> tuple[str, list[str]]:
    """Split leading bracketed groups such as ``[기재정정]`` from a report name."""
    text = (report_nm or "").strip()
    match = _PREFIX_RE.match(text)
    prefixes = re.findall(r"\[[^\]]*\]", match.group(1)) if match else []
    body = text[match.end() :] if match else text
    return " ".join(body.split()), prefixes  # DART pads some names with runs of spaces


def redact_params(params: dict[str, Any]) -> dict[str, Any]:
    """Copy of request params that is safe to record (the DART key is dropped)."""
    return {k: v for k, v in params.items() if k != "crtfc_key"}


def find_leaks(out_dir: Path, secret: str) -> list[str]:
    """Names of files under ``out_dir`` holding the key value or a ``crtfc_key`` parameter."""
    needles = [b"crtfc_key"]
    if secret:
        needles.append(secret.encode("utf-8"))
    bad = []
    for path in sorted(out_dir.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            if any(n in data for n in needles):
                bad.append(str(path.relative_to(out_dir)))
    return bad


def tally_report_names(rows_by_company: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Per stripped report_nm: total, per-company counts, example rcept_no, prefixes seen."""
    result: dict[str, Any] = {}
    for stock_code, rows in rows_by_company.items():
        for row in rows:
            name, prefixes = strip_prefixes(str(row.get("report_nm", "")))
            entry = result.setdefault(
                name,
                {
                    "total": 0,
                    "per_company": Counter(),
                    "example_rcept_no": str(row.get("rcept_no", "")),
                    "prefixes": Counter(),
                },
            )
            entry["total"] += 1
            entry["per_company"][stock_code] += 1
            entry["prefixes"].update(prefixes)
    ordered = sorted(result.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
    return {
        name: {
            "total": e["total"],
            "per_company": dict(e["per_company"]),
            "example_rcept_no": e["example_rcept_no"],
            "prefixes": dict(e["prefixes"]),
        }
        for name, e in ordered
    }


def zip_rows_from_submissions(
    payload: dict[str, Any], start: str, end: str
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Zip the column-oriented ``filings.recent`` block into 8-K / 8-K/A rows in the window."""
    recent = payload["filings"]["recent"]
    n = len(recent["accessionNumber"])
    rows = []
    for i in range(n):
        row = {c: (recent.get(c) or [""] * n)[i] for c in SEC_COLUMNS}
        if row["form"] in SEC_8K_FORMS and start <= row["filingDate"] <= end:
            rows.append(row)
    dates = recent.get("filingDate") or []
    meta = {
        "recent_count": n,
        "recent_oldest_filing_date": min(dates) if dates else None,
        "older_files_listed": len(payload["filings"].get("files") or []),
    }
    return rows, meta


class _IndexTableParser(HTMLParser):
    """Collect rows (cell text plus hrefs) from the document table of a filing index page."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[dict[str, Any]]]] = []
        self.table_classes: list[str] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table":
            self.tables.append([])
            self.table_classes.append(a.get("class") or "")
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"text": "", "href": None}
        elif tag == "a" and self._cell is not None and a.get("href"):
            self._cell["href"] = a["href"]

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._cell["text"] = " ".join(self._cell["text"].split())
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None and self.tables:
            if self._row:
                self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"] += data


def parse_index_html_table(html: str) -> list[dict[str, str | None]]:
    """Rows of the ``Document Format Files`` table: Seq, Description, Document, Type, Size."""
    parser = _IndexTableParser()
    parser.feed(html)
    parser.close()
    for rows, cls in zip(parser.tables, parser.table_classes, strict=True):
        if "tableFile" not in cls or not rows:
            continue
        header = [c["text"] for c in rows[0]]
        if "Type" not in header:
            continue
        out: list[dict[str, str | None]] = []
        for row in rows[1:]:
            record: dict[str, str | None] = {}
            for name, cell in zip(header, row, strict=False):
                record[name] = cell["text"]
                if name == "Document":
                    record["href"] = cell["href"]
            out.append(record)
        return out
    return []


def document_basename(href: str | None) -> str | None:
    """File name of an index-table link, unwrapping the ``/ix?doc=`` inline-XBRL viewer form."""
    if not href:
        return None
    if "doc=" in href:
        href = href.split("doc=", 1)[1]
    return href.rsplit("/", 1)[-1] or None


def window_start(as_of: dt.date) -> dt.date:
    """First day of the 365-day window that ends on (and includes) ``as_of``."""
    return as_of - dt.timedelta(days=364)


def check_sec_user_agent(user_agent: str) -> str:
    """Refuse a placeholder User-Agent; never echo it. Returns ``"contact-style"``."""
    default = Settings.model_fields["sec_user_agent"].default
    ua = (user_agent or "").strip()
    if ua == default or "example.com" in ua or "@" not in ua:
        raise SystemExit(
            "SEC_USER_AGENT is a placeholder or lacks a contact address; "
            "set a real 'name contact@host' value in backend/.env (value not shown)"
        )
    return "contact-style"


def clear_fixture_dir(out: Path, root: Path = DEFAULT_OUT) -> bool:
    """Empty ``out`` if it is ``root`` or inside it; otherwise leave it alone (False)."""
    out_r, root_r = out.resolve(), root.resolve()
    if out_r != root_r and root_r not in out_r.parents:
        return False
    if out_r.exists():
        for child in out_r.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    return True


def scan_and_purge(out_dir: Path, secret: str) -> list[str]:
    """Delete any fixture holding the key and return the offending relative names."""
    leaks = find_leaks(out_dir, secret)
    for rel in leaks:
        (out_dir / rel).unlink()
    return leaks


_DECIMAL_ID_FIELDS = frozenset({"rcept_no", "corp_code", "corp_cls"})


def decimal_parse_check(row: dict[str, Any]) -> dict[str, str]:
    """Parse numeric-looking string fields with ``parse_dart_decimal``; mark ``-`` as absent."""
    out: dict[str, str] = {}
    for key, value in row.items():
        if key in _DECIMAL_ID_FIELDS or not isinstance(value, str):
            continue
        text = value.strip()
        if text in ("-", ""):
            out[key] = "absent"
        elif re.fullmatch(r"-?[\d,]+(\.\d+)?", text):
            out[key] = str(parse_dart_decimal(text))
    return out


_SGML_HEAD_RE = re.compile(r"^\s*<DOCUMENT>.*?<TEXT>\s*", re.S)


def strip_sgml_header(html: str) -> str:
    """Drop the leading ``<DOCUMENT><TYPE>…<TEXT>`` wrapper EDGAR puts on some exhibits."""
    return _SGML_HEAD_RE.sub("", html, count=1)


class _TableSplitter(HTMLParser):
    """Separate visible text inside ``<table>`` from text outside, counting tables."""

    def __init__(self) -> None:
        super().__init__()
        self.table_tags = 0
        self.outside: list[str] = []
        self.inside: list[str] = []
        self._depth = 0
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.table_tags += 1
            self._depth += 1
        elif tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._depth:
            self._depth -= 1
        elif tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip or not data.strip():
            return
        (self.inside if self._depth else self.outside).append(" ".join(data.split()))


def analyze_exhibit_html(html: str) -> dict[str, Any]:
    """Count tables and show where dollar figures sit (prose versus table cells)."""
    parser = _TableSplitter()
    html = strip_sgml_header(html)
    parser.feed(html)
    parser.close()
    outside = " ".join(parser.outside)
    inside = " | ".join(parser.inside)
    dollar = re.compile(r"\$\s?\d[\d,.]*(?:\s(?:billion|million))?")
    numeric = re.compile(r"\(?-?[\d,]+(?:\.\d+)?\)?%?")
    cells = parser.inside
    # a "$" cell followed by a numeric cell is one figure; "$12" in one cell is one too
    table_dollars = sum(
        1
        for i, c in enumerate(cells)
        if dollar.search(c) or (c == "$" and i + 1 < len(cells) and numeric.fullmatch(cells[i + 1]))
    )
    sentences = re.split(r"(?<=[.!?])\s+", outside)
    revenue_prose = [
        s for s in sentences if re.search(r"revenue|net sales", s, re.I) and re.search(r"\d", s)
    ]
    return {
        "table_tag_count": parser.table_tags,
        "dollar_figures_outside_tables": len(dollar.findall(outside)),
        "dollar_figures_inside_tables": table_dollars,
        "numeric_cells_inside_tables": sum(1 for c in cells if numeric.fullmatch(c)),
        "revenue_sentences_outside_tables": len(revenue_prose),
        "revenue_sentence_example": revenue_prose[0][:300] if revenue_prose else None,
        "inside_tables_has_net_sales_label": bool(re.search(r"net sales|revenue", inside, re.I)),
        "outside_text_chars": len(outside),
        "inside_text_chars": len(inside),
    }


# -- runtime ---------------------------------------------------------------------------------


class Sampler:
    def __init__(self, out_dir: Path, as_of: dt.date) -> None:
        self.settings = get_settings()
        key = self.settings.dart_api_key
        self.secret = key.get_secret_value() if key is not None else ""
        if not self.secret:
            raise SystemExit("DART_API_KEY is not configured")
        self.out = out_dir
        self.as_of = as_of
        self.start = window_start(as_of)  # 365 days inclusive of as_of
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True
        )
        self.dart = DartClient(self.settings, client=self.http)
        self.dart_calls = 0
        self.sec_calls = 0
        self._last_dart = 0.0
        self._last_sec = 0.0
        self.statuses: list[dict[str, Any]] = []
        self.written: list[Path] = []
        self.summary: dict[str, Any] = {}
        self.sec_status_log: list[dict[str, Any]] = []
        self.sec_ua_check = check_sec_user_agent(self.settings.sec_user_agent)

    # --- io
    def save_bytes(self, rel: str, data: bytes) -> None:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.written.append(path)

    def save_json(self, rel: str, obj: Any) -> None:
        text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        self.save_bytes(rel, text.encode("utf-8"))

    # --- DART
    async def dart_get(self, endpoint: str, params: dict[str, Any]) -> tuple[int | None, bytes]:
        wait = DART_INTERVAL - (time.monotonic() - self._last_dart)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_dart = time.monotonic()
        self.dart_calls += 1
        full = {"crtfc_key": self.secret, **params}
        try:
            resp = await self.dart._get(endpoint, full)
        except httpx.HTTPStatusError as exc:
            self.statuses.append(
                {
                    "source": "dart",
                    "endpoint": endpoint,
                    "http": exc.response.status_code,
                    "params": redact_params(params),
                }
            )
            return exc.response.status_code, b""
        except httpx.RequestError as exc:
            self.statuses.append(
                {
                    "source": "dart",
                    "endpoint": endpoint,
                    "error": type(exc).__name__,
                    "params": redact_params(params),
                }
            )
            return None, b""
        return resp.status_code, resp.content

    def note_dart_status(
        self, endpoint: str, params: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        status = str(payload.get("status", ""))
        if status != "000":
            self.statuses.append(
                {
                    "source": "dart",
                    "endpoint": endpoint,
                    "status": status,
                    "message": str(payload.get("message", "")),
                    "params": redact_params(params),
                }
            )

    async def dart_json(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        http, body = await self.dart_get(endpoint, params)
        if http is None or not body:
            return {"status": f"http-{http}", "message": "no body"}
        try:
            payload = json.loads(body)
        except ValueError:
            return {"status": "non-json", "message": body[:200].decode("utf-8", "replace")}
        self.note_dart_status(endpoint, params, payload)
        return payload

    async def dart_list_all(
        self, corp_code: str, ty: str | None, extra: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """All pages of list.json; a failure on page 2+ keeps page 1's status, marks partial."""
        params: dict[str, Any] = {
            "corp_code": corp_code,
            "bgn_de": self.start.strftime("%Y%m%d"),
            "end_de": self.as_of.strftime("%Y%m%d"),
            "page_count": 100,
            "page_no": 1,
            **(extra or {}),
        }
        if ty:
            params["pblntf_ty"] = ty
        rows: list[dict[str, Any]] = []
        total_count = 0
        total_page = 1
        status = ""
        message = ""
        partial = False
        page_errors: list[dict[str, Any]] = []
        page = 1
        while True:
            params["page_no"] = page
            payload = await self.dart_json("list.json", params)
            pstatus = str(payload.get("status", ""))
            pmessage = str(payload.get("message", ""))
            if page == 1:
                status, message = pstatus, pmessage
            if pstatus != "000":
                if page >= 2:
                    partial = True
                    page_errors.append({"page": page, "status": pstatus, "message": pmessage})
                    print(
                        f"WARNING: list.json page {page} for corp_code {corp_code} "
                        f"returned status {pstatus}; result is partial"
                    )
                break
            if page == 1:
                total_count = int(payload.get("total_count", 0))
                total_page = int(payload.get("total_page", 1))
            rows.extend(r for r in payload.get("list", []) if isinstance(r, dict))
            if page >= total_page:
                break
            page += 1
        result: dict[str, Any] = {
            "status": status,
            "message": message,
            "total_count": total_count,
            "total_page": total_page,
            "rows": rows,
            "partial": partial,
        }
        if page_errors:
            result["page_errors"] = page_errors
        return result

    async def run_dart(self) -> None:
        corp: dict[str, str] = {}
        from app.clients.dart import DEFAULT_CACHE_PATH

        cache_existed = DEFAULT_CACHE_PATH.exists()
        for code in DART_COMPANIES:
            cc = await self.dart.resolve_corp_code(code)
            if not cc:
                raise SystemExit(f"cannot resolve corp_code for {code}")
            corp[code] = cc
        if not cache_existed:
            self.dart_calls += 1  # corpCode.xml fetched inside resolve_corp_code
        lists: dict[str, dict[str, list[dict[str, Any]]]] = {"B": {}, "I": {}}
        list_meta: dict[str, dict[str, Any]] = {}
        for code, cc in corp.items():
            for ty in ("B", "I"):
                res = await self.dart_list_all(cc, ty)
                lists[ty][code] = res["rows"]
                list_meta[f"{code}_{ty}"] = {k: v for k, v in res.items() if k != "rows"} | {
                    "rows": len(res["rows"])
                }
                self.save_json(
                    f"dart/list/{code}_{ty}.json",
                    {
                        "stock_code": code,
                        "corp_code": cc,
                        "pblntf_ty": ty,
                        "bgn_de": self.start.strftime("%Y%m%d"),
                        "end_de": self.as_of.strftime("%Y%m%d"),
                        "status": res["status"],
                        "message": res["message"],
                        "total_count": res["total_count"],
                        "partial": res["partial"],
                        "page_errors": res.get("page_errors", []),
                        "list": res["rows"],
                    },
                )
        # tallies
        tally: dict[str, Any] = {}
        rm_tally: dict[str, Any] = {}
        meta_tally: dict[str, Any] = {}
        for ty in ("B", "I"):
            tally[ty] = tally_report_names(lists[ty])
            all_rows = [r for rows in lists[ty].values() for r in rows]
            rm_tally[ty] = dict(Counter(str(r.get("rm", "")).strip() for r in all_rows))
            meta_tally[ty] = {
                "corp_cls": dict(Counter(str(r.get("corp_cls", "")) for r in all_rows)),
                "flr_nm": dict(Counter(str(r.get("flr_nm", "")).strip() for r in all_rows)),
            }
        self.save_json(
            "dart/report_nm_tally.json",
            {"tally": tally, "rm_tally": rm_tally, "meta_tally": meta_tally},
        )
        # pblntf_detail_ty, Samsung only: detail-only queries plus one combined query.
        samsung = corp["005930"]
        detail: dict[str, Any] = {}
        for dty in ("I001", "I002", "I003", "I004", "I005", "B001", "E001"):
            res = await self.dart_list_all(samsung, None, {"pblntf_detail_ty": dty})
            detail[dty] = self.save_detail(f"005930_{dty}", dty, None, res)
        res = await self.dart_list_all(samsung, "I", {"pblntf_detail_ty": "I002"})
        combined = self.save_detail("005930_I_plus_I002", "I002", "I", res)
        i_total = list_meta["005930_I"]["total_count"]
        i_sum = sum(detail[c]["total_count"] for c in ("I001", "I002", "I003", "I004", "I005"))
        detail_summary = {
            "detail_only": detail,
            "combined_I_plus_I002": combined,
            "plain_I_total": i_total,
            "plain_B_total": list_meta["005930_B"]["total_count"],
            "detail_only_I001_to_I005_sum": i_sum,
            "I_detail_sum_equals_plain_I": i_sum == i_total,
            "combined_equals_plain_I": combined["total_count"] == i_total,
            "finding": (
                "pblntf_detail_ty filters only when sent without pblntf_ty"
                if combined["total_count"] == i_total and detail["I002"]["total_count"] != i_total
                else "see counts"
            ),
        }
        # documents
        documents = await self.sample_documents(lists)
        # structured endpoints
        structured = await self.sample_structured(corp, lists)
        self.summary["dart"] = {
            "corp_codes_resolved": len(corp),
            "corpcode_snapshot_already_cached": cache_existed,
            "list_meta": list_meta,
            "counts": {code: {ty: len(lists[ty][code]) for ty in ("B", "I")} for code in corp},
            "pblntf_detail_ty": detail_summary,
            "documents": documents,
            "structured": structured,
        }

    def save_detail(
        self, name: str, dty: str, ty: str | None, res: dict[str, Any]
    ) -> dict[str, Any]:
        self.save_json(
            f"dart/detail_ty/{name}.json",
            {
                "stock_code": "005930",
                "pblntf_ty": ty,
                "pblntf_detail_ty": dty,
                "status": res["status"],
                "message": res["message"],
                "total_count": res["total_count"],
                "partial": res["partial"],
                "list": res["rows"],
            },
        )
        names = Counter(strip_prefixes(str(r.get("report_nm", "")))[0] for r in res["rows"])
        return {
            "status": res["status"],
            "message": res["message"],
            "total_count": res["total_count"],
            "rows": len(res["rows"]),
            "partial": res["partial"],
            "report_nm": dict(names),
        }

    def pick(
        self, lists: dict[str, dict[str, list[dict[str, Any]]]], tys: tuple[str, ...], test: Any
    ) -> tuple[str, str, dict[str, Any]] | None:
        """First matching row, preferring un-prefixed (original) filings."""
        found = []
        for ty in tys:
            for code, rows in lists[ty].items():
                for row in rows:
                    name, prefixes = strip_prefixes(str(row.get("report_nm", "")))
                    if test(name):
                        found.append((bool(prefixes), ty, code, row))
        if not found:
            return None
        found.sort(key=lambda t: t[0])
        _, ty, code, row = found[0]
        return ty, code, row

    async def sample_documents(
        self, lists: dict[str, dict[str, list[dict[str, Any]]]]
    ) -> list[dict[str, Any]]:
        wanted: list[tuple[str, Any, tuple[str, ...]]] = [
            ("b001_buyback", lambda n: "자기주식취득결정" in n.replace(" ", ""), ("B",)),
            ("b001_any", lambda n: n.startswith("주요사항보고서"), ("B",)),
            ("earnings_prelim", lambda n: "잠정" in n and "실적" in n, ("I", "B")),
            ("dividend", lambda n: "배당" in n, ("I", "B")),
            ("share_retirement", lambda n: "소각" in n, ("I", "B")),
            ("supply_contract", lambda n: "단일판매" in n, ("I", "B")),
            ("ceo_change", lambda n: "대표이사" in n and "변경" in n, ("I", "B")),
        ]
        results = []
        seen: set[str] = set()
        for label, test, tys in wanted:
            hit = self.pick(lists, tys, test)
            if hit is None:
                results.append({"label": label, "found": False})
                continue
            ty, code, row = hit
            rcept = str(row["rcept_no"])
            if rcept in seen:
                results.append({"label": label, "found": True, "same_as_earlier_sample": rcept})
                continue
            seen.add(rcept)
            rec = await self.fetch_document_record(rcept)
            rec |= {
                "label": label,
                "found": True,
                "stock_code": code,
                "pblntf_ty": ty,
                "report_nm": str(row.get("report_nm", "")).strip(),
                "rm": str(row.get("rm", "")).strip(),
            }
            results.append(rec)
        return results

    async def fetch_document_record(self, rcept_no: str) -> dict[str, Any]:
        http, body = await self.dart_get("document.xml", {"rcept_no": rcept_no})
        rec: dict[str, Any] = {"rcept_no": rcept_no, "http_status": http, "bytes": len(body)}
        if http is None or http >= 400 or not body:
            return rec | {"zip": False}
        if body[:2] != b"PK":
            try:
                root = _xml_fromstring(body)
                status = (root.findtext("status") or "").strip()
                message = (root.findtext("message") or "").strip()
            except Exception:  # noqa: BLE001
                status, message = "unparseable", body[:200].decode("utf-8", "replace")
            self.statuses.append(
                {
                    "source": "dart",
                    "endpoint": "document.xml",
                    "status": status,
                    "message": message,
                    "rcept_no": rcept_no,
                }
            )
            return rec | {"zip": False, "error_status": status, "error_message": message}
        try:
            with zipfile.ZipFile(BytesIO(body)) as zf:
                infos = [(i.filename, i.file_size) for i in zf.infolist()]
            member, raw, _ = _extract_document_member(body, rcept_no)
        except Exception as exc:  # noqa: BLE001
            return rec | {"zip": True, "zip_error": type(exc).__name__}
        text = decode_dart_bytes(raw)
        fmt = detect_document_format(text)
        rec |= {
            "zip": True,
            "members": infos,
            "main_member": member,
            "main_member_bytes": len(raw),
            "format": fmt,
            "head_600": text[:600],
        }
        if fmt == "dsd":
            try:
                sections = extract_dsd_prose(text)
                rec["dsd_prose"] = {
                    "sections": len(sections),
                    "titles": [s.section_title for s in sections[:20]],
                }
            except Exception as exc:  # noqa: BLE001
                rec["dsd_prose"] = {"error": f"{type(exc).__name__}: {str(exc)[:150]}"}
        else:
            rec["dsd_prose"] = None
        truncated = len(text) > DOC_SAVE_LIMIT
        self.save_bytes(
            f"dart/document/{rcept_no}.xml",
            (text[:DOC_SAVE_LIMIT] if truncated else text).encode("utf-8"),
        )
        rec["saved_truncated"] = truncated
        rec["decoded_chars"] = len(text)
        return rec

    async def sample_structured(
        self, corp: dict[str, str], lists: dict[str, dict[str, list[dict[str, Any]]]]
    ) -> dict[str, Any]:
        b_rcepts = {
            str(r["rcept_no"]): (c, str(r.get("report_nm", "")).strip())
            for c, rows in lists["B"].items()
            for r in rows
        }
        out: dict[str, Any] = {}
        for endpoint in ("tsstkAqDecsn", "tsstkDpDecsn"):
            per: dict[str, Any] = {}
            example_done = False
            seen_rcepts: set[str] = set()
            for code, cc in corp.items():
                params = {
                    "corp_code": cc,
                    "bgn_de": self.start.strftime("%Y%m%d"),
                    "end_de": self.as_of.strftime("%Y%m%d"),
                }
                payload = await self.dart_json(f"{endpoint}.json", params)
                rows = payload.get("list") if isinstance(payload.get("list"), list) else []
                per[code] = {
                    "status": payload.get("status"),
                    "message": payload.get("message"),
                    "rows": len(rows),
                }
                seen_rcepts.update(str(r.get("rcept_no", "")) for r in rows)
                if rows:
                    self.save_json(f"dart/structured/{endpoint}_{code}.json", payload)
                    if not example_done:
                        example_done = True
                        first = rows[0]
                        rcept = str(first.get("rcept_no", ""))
                        per["_example"] = {
                            "stock_code": code,
                            "fields": list(first.keys()),
                            "values": first,
                            "rcept_no_in_B_list": rcept in b_rcepts,
                            "list_row_report_nm": b_rcepts.get(rcept, (None, None))[1],
                            "cross_link_matches_all_rows": all(
                                str(r.get("rcept_no")) in b_rcepts for r in rows
                            ),
                        }
                        per["_example"]["decimal_parse_check"] = decimal_parse_check(first)
            keyword = "자기주식취득결정" if endpoint == "tsstkAqDecsn" else "자기주식처분결정"
            wanted = {
                rc: (c, nm)
                for rc, (c, nm) in b_rcepts.items()
                if keyword in strip_prefixes(nm)[0].replace(" ", "")
            }
            unmatched = sorted(rc for rc in wanted if rc not in seen_rcepts)
            per["_b_list_cross_match"] = {
                "b_list_rows_named": len(wanted),
                "found_in_structured_rows": len(wanted) - len(unmatched),
                "structured_rows_total": len(seen_rcepts),
                "unmatched_b_rcept_nos": [
                    {"rcept_no": rc, "stock_code": wanted[rc][0], "report_nm": wanted[rc][1]}
                    for rc in unmatched
                ],
            }
            out[endpoint] = per
        return out

    # --- SEC
    async def sec_get(self, url: str) -> tuple[int | None, bytes]:
        wait = SEC_INTERVAL - (time.monotonic() - self._last_sec)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_sec = time.monotonic()
        self.sec_calls += 1
        try:
            resp = await self.http.get(url, headers={"User-Agent": self.settings.sec_user_agent})
        except httpx.RequestError as exc:
            self.statuses.append({"source": "sec", "url": url, "error": type(exc).__name__})
            return None, b""
        host = url.split("/")[2]
        self.sec_status_log.append({"host": host, "url": url, "http": resp.status_code})
        if resp.status_code >= 400:
            self.statuses.append({"source": "sec", "url": url, "http": resp.status_code})
        return resp.status_code, resp.content

    async def run_sec(self) -> None:
        start, end = self.start.isoformat(), self.as_of.isoformat()
        per_company: dict[str, Any] = {}
        all_rows: dict[str, list[dict[str, str]]] = {}
        for ticker, cik in SEC_COMPANIES.items():
            cik10 = format_cik(cik)
            http, body = await self.sec_get(
                f"{self.settings.sec_base_url.rstrip('/')}/submissions/CIK{cik10}.json"
            )
            if http != 200:
                per_company[ticker] = {"http": http}
                continue
            rows, meta = zip_rows_from_submissions(json.loads(body), start, end)
            all_rows[ticker] = rows
            items = Counter(
                i.strip() for r in rows for i in str(r["items"]).split(",") if i.strip()
            )
            per_company[ticker] = {
                "http": http,
                "cik": cik,
                "rows_8k_8ka": len(rows),
                "forms": dict(Counter(r["form"] for r in rows)),
                "items": dict(sorted(items.items())),
                **meta,
            }
            self.save_json(
                f"sec/submissions_8k/{ticker}.json",
                {"ticker": ticker, "cik": cik, "window": [start, end], "rows": rows},
            )
        total_items: Counter[str] = Counter()
        for p in per_company.values():
            total_items.update(p.get("items", {}))
        filings = await self.sample_sec_filings(all_rows)
        self.summary["sec"] = {
            "per_company": per_company,
            "total_items": dict(sorted(total_items.items(), key=lambda kv: -kv[1])),
            "total_8k_8ka_rows": sum(p.get("rows_8k_8ka", 0) for p in per_company.values()),
            "total_8ka": sum(p.get("forms", {}).get("8-K/A", 0) for p in per_company.values()),
            "filings": filings,
            "status_by_host": {
                h: dict(Counter(str(s["http"]) for s in self.sec_status_log if s["host"] == h))
                for h in sorted({s["host"] for s in self.sec_status_log})
            },
        }

    def choose(
        self,
        all_rows: dict[str, list[dict[str, str]]],
        item: str,
        tickers: list[str] | None = None,
        avoid: str | None = None,
    ) -> tuple[str, dict[str, str]] | None:
        for pass_avoid in (avoid, None):
            for ticker in tickers or list(all_rows):
                if ticker == pass_avoid:
                    continue
                cands = [
                    r
                    for r in all_rows.get(ticker, [])
                    if r["form"] == "8-K"
                    and item in [i.strip() for i in str(r["items"]).split(",")]
                    and r["primaryDocument"]
                ]
                if cands:
                    return ticker, max(cands, key=lambda r: r["filingDate"])
        return None

    async def sample_sec_filings(
        self, all_rows: dict[str, list[dict[str, str]]]
    ) -> list[dict[str, Any]]:
        picks = [("apple_2.02", self.choose(all_rows, "2.02", ["AAPL"]))]
        pick_502 = self.choose(all_rows, "5.02")
        picks.append(("item_5.02", pick_502))
        picks.append(
            ("item_8.01", self.choose(all_rows, "8.01", avoid=pick_502[0] if pick_502 else None))
        )
        results = []
        for label, pick in picks:
            if pick is None:
                results.append({"label": label, "found": False})
                continue
            ticker, row = pick
            results.append(
                await self.fetch_sec_filing(label, ticker, row, with_exhibit=label == "apple_2.02")
            )
        return results

    async def fetch_sec_filing(
        self, label: str, ticker: str, row: dict[str, str], with_exhibit: bool
    ) -> dict[str, Any]:
        cik = SEC_COMPANIES[ticker]
        acc = row["accessionNumber"]
        nodash = acc.replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}"
        rec: dict[str, Any] = {
            "label": label,
            "found": True,
            "ticker": ticker,
            "accession": acc,
            "filingDate": row["filingDate"],
            "items": row["items"],
            "primaryDocument": row["primaryDocument"],
        }
        # index.json
        http, body = await self.sec_get(f"{base}/index.json")
        rec["index_json"] = {"http": http, "bytes": len(body)}
        if http == 200:
            self.save_bytes(f"sec/index/{acc}_index.json", body)
            try:
                d = json.loads(body)
                directory = d.get("directory", {})
                items = directory.get("item", [])
                rec["index_json"] |= {
                    "top_keys": list(d.keys()),
                    "directory_keys": list(directory.keys()),
                    "item_count": len(items),
                    "item_keys": list(items[0].keys()) if items else [],
                    "first_items": items[:4],
                    "type_values": sorted({str(i.get("type")) for i in items}),
                    "exhibit_type_present": any(
                        str(i.get("type", "")).upper().startswith("EX-") for i in items
                    ),
                }
            except ValueError:
                rec["index_json"]["parse_error"] = True
        # -index.html (fall back to .htm)
        html_body = b""
        for suffix in ("-index.html", "-index.htm"):
            http, body = await self.sec_get(f"{base}/{acc}{suffix}")
            rec[f"index_page{suffix}"] = {"http": http, "bytes": len(body)}
            if http == 200:
                html_body = body
                self.save_bytes(f"sec/index/{acc}{suffix}", body)
                break
        table = parse_index_html_table(html_body.decode("utf-8", "replace")) if html_body else []
        rec["index_table_rows"] = table
        rec["exhibit_types_in_index_html"] = [
            r.get("Type") for r in table if str(r.get("Type", "")).upper().startswith("EX-")
        ]
        # primary document
        primary = row["primaryDocument"]
        rec["primary_fetch"] = await self.fetch_sec_doc(cik, acc, primary, analyze=False)
        if with_exhibit:
            ex = next((r for r in table if str(r.get("Type", "")).upper() == "EX-99.1"), None)
            name = document_basename(ex.get("href")) if ex else None
            rec["ex99_1_document"] = name
            if name:
                rec["ex99_1_fetch"] = await self.fetch_sec_doc(cik, acc, name, analyze=True)
        return rec

    async def fetch_sec_doc(self, cik: int, acc: str, name: str, analyze: bool) -> dict[str, Any]:
        url = _archive_url(format_cik(cik), acc, name)
        http, body = await self.sec_get(url)
        rec: dict[str, Any] = {
            "url_path": url.split("sec.gov", 1)[1],
            "http": http,
            "bytes": len(body),
        }
        if http != 200:
            return rec
        self.save_bytes(f"sec/documents/{acc}_{name}", body)
        html = body.decode("utf-8", "replace")
        text = _html_to_text(html)
        rec |= {"text_chars": len(text), "text_head_600": text[:600]}
        if analyze:
            rec["analysis"] = analyze_exhibit_html(html)
        else:
            rec["table_tag_count"] = len(re.findall(r"<table", html, re.I))
        return rec

    # --- finish
    def write_summary(self) -> None:
        partial = [
            k for k, v in self.summary.get("dart", {}).get("list_meta", {}).items() if v["partial"]
        ]
        self.summary = {
            "as_of": self.as_of.isoformat(),
            "window": [self.start.isoformat(), self.as_of.isoformat()],
            "window_note": "365 days inclusive of as_of",
            "sec_user_agent_check": self.sec_ua_check,
            "request_counts": {"dart": self.dart_calls, "sec": self.sec_calls},
            "partial_list_results": partial,
            "non_ok_statuses": self.statuses,
            **self.summary,
        }
        self.save_json("sample_summary.json", self.summary)

    def leak_scan(self) -> bool:
        leaks = scan_and_purge(self.out, self.secret)
        if leaks:
            print(f"KEY LEAK in: {', '.join(leaks)} (files deleted)")
            return False
        print("key leak check: clean")
        return True

    def finish(self, report: bool) -> None:
        if report:
            self.print_report()
        print(f"fixtures written: {len(self.written)}")

    def print_report(self) -> None:
        d, s = self.summary["dart"], self.summary["sec"]
        print(
            f"\nwindow {self.start} .. {self.as_of}  "
            f"requests: dart={self.dart_calls} sec={self.sec_calls}"
        )
        print("\nDART  stock  name                 B    I")
        for code, name in DART_COMPANIES.items():
            c = d["counts"][code]
            print(f"      {code}  {name:<20} {c['B']:>3}  {c['I']:>3}")
        print("\nSEC   ticker  8-K/8-K/A  items")
        for t, p in s["per_company"].items():
            print(f"      {t:<6} {p.get('rows_8k_8ka', '-'):>5}     {p.get('items', {})}")
        print(
            f"\nSEC total rows {s['total_8k_8ka_rows']}, 8-K/A {s['total_8ka']}, "
            f"items {s['total_items']}"
        )
        if self.statuses:
            print("\nnon-OK statuses:")
            for st in self.statuses:
                print("  ", st)


async def main_async(args: argparse.Namespace) -> int:
    sampler = Sampler(Path(args.out), dt.date.fromisoformat(args.as_of))
    try:
        if not clear_fixture_dir(sampler.out):
            print("note: --out is outside backend/tests/fixtures/events; not cleared")
        await sampler.run_dart()
        await sampler.run_sec()
        sampler.write_summary()
    finally:
        await sampler.http.aclose()
        if not sampler.leak_scan():  # runs on success and on a crash
            raise SystemExit(2)
    sampler.finish(args.report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print a per-company summary")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="fixture output directory")
    parser.add_argument("--as-of", default="2026-11-17", help="window end date, YYYY-MM-DD")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
