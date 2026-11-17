"""DART event data: structured major-matters endpoints and event document text.

Two jobs, both pure apart from the fetchers:

* ``fetch_structured_events`` reads one DS005 endpoint (for example ``tsstkAqDecsn``) and
  turns each row into :class:`ExtractedFact` values, following ``contracts/filing-facts.json``.
  Amounts, counts and ratios become ``Decimal``, dates become ``date``; ``-`` and the empty
  string mean "absent" and produce no fact; anything else that does not parse is kept as a fact
  carrying an error and no value. Nothing is guessed and no float is involved.
* ``read_event_document`` turns a ``document.xml`` body into flat text (for classification and
  correction links), DSD prose sections and xforms table rows.
"""

from __future__ import annotations

import datetime
import html
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError

from app.clients.dart import (
    DartApiError,
    DartClient,
    ProseSection,
    decode_dart_bytes,
    detect_document_format,
    extract_dsd_prose,
    parse_dart_decimal,
)

logger = logging.getLogger(__name__)

FACTS_CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "filing-facts.json"

_STATUS_OK = "000"
_STATUS_NO_DATA = "013"
_ABSENT = frozenset({"", "-"})


class EventValueError(ValueError):
    """A source value that is present but is not a valid amount, count, ratio or date."""


@lru_cache(maxsize=1)
def load_facts_contract() -> dict[str, Any]:
    return json.loads(FACTS_CONTRACT_PATH.read_text(encoding="utf-8"))


def endpoint_spec(endpoint: str) -> dict[str, Any]:
    for spec in load_facts_contract()["endpoints"]:
        if spec["endpoint"] == endpoint:
            return spec
    raise KeyError(f"no filing-facts entry for endpoint {endpoint!r}")


def endpoint_for_report_key(report_key: str) -> str | None:
    """Endpoint whose ``report_names`` contain the normalised DART report name, if any."""
    for spec in load_facts_contract()["endpoints"]:
        if report_key in spec["report_names"]:
            return str(spec["endpoint"])
    return None


# -- value parsing ------------------------------------------------------------------------------

# ASCII digits only; thousands groups, when present, must be well formed (1,234 not 1,23 or 0,123).
_NUMBER_RE = re.compile(r"-?(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?")
_KO_DATE_RE = re.compile(r"([0-9]{4})\s*년\s*([0-9]{1,2})\s*월\s*([0-9]{1,2})\s*일")
_COMPACT_DATE_RE = re.compile(r"([0-9]{4})([0-9]{2})([0-9]{2})")


def parse_event_decimal(raw: str | None) -> Decimal | None:
    """``None`` for an absent value (``-`` or empty); ``EventValueError`` if not a plain number."""
    text = (raw or "").strip()
    if text in _ABSENT:
        return None
    if not _NUMBER_RE.fullmatch(text):
        raise EventValueError(f"not a number: {raw!r}")
    value = parse_dart_decimal(text)
    if value is None:
        raise EventValueError(f"not a number: {raw!r}")
    return value


def parse_event_count(raw: str | None) -> Decimal | None:
    """A whole, non-negative number of shares as an integral ``Decimal``."""
    value = parse_event_decimal(raw)
    if value is None:
        return None
    if value < 0 or value != value.to_integral_value():
        raise EventValueError(f"not a whole non-negative count: {raw!r}")
    return value


def parse_event_date(raw: str | None) -> datetime.date | None:
    """``2026년 01월 30일`` or ``20260830`` to a date; ``None`` when absent."""
    text = (raw or "").strip()
    if text in _ABSENT:
        return None
    match = _KO_DATE_RE.fullmatch(text) or _COMPACT_DATE_RE.fullmatch(text)
    if match is None:
        raise EventValueError(f"not a date: {raw!r}")
    year, month, day = (int(g) for g in match.groups())
    try:
        return datetime.date(year, month, day)
    except ValueError:
        raise EventValueError(f"not a calendar date: {raw!r}") from None


# -- facts ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractedFact:
    key: str
    kind: str
    unit: str | None
    source_field: str
    raw: str
    value_decimal: Decimal | None = None
    value_date: datetime.date | None = None
    value_text: str | None = None
    error: str | None = None


def extract_facts(endpoint: str, row: dict[str, Any]) -> list[ExtractedFact]:
    """One fact per contract field that is present in ``row``; absent values give no fact."""
    facts: list[ExtractedFact] = []
    for field in endpoint_spec(endpoint)["fields"]:
        raw = row.get(field["source_field"])
        if raw is None:
            continue
        base = {
            "key": field["key"],
            "kind": field["kind"],
            "unit": field["unit"],
            "source_field": field["source_field"],
        }
        if not isinstance(raw, str):
            facts.append(
                ExtractedFact(**base, raw=repr(raw), error=f"non-string value {raw!r}")
            )
            continue
        try:
            value = _parse_value(field["kind"], raw)
        except EventValueError as exc:
            facts.append(ExtractedFact(**base, raw=raw, error=str(exc)))
            continue
        if value is None:
            continue
        if isinstance(value, Decimal):
            facts.append(ExtractedFact(**base, raw=raw, value_decimal=value))
        elif isinstance(value, datetime.date):
            facts.append(ExtractedFact(**base, raw=raw, value_date=value))
        else:
            facts.append(ExtractedFact(**base, raw=raw, value_text=value))
    return facts


def _parse_value(kind: str, raw: str) -> Decimal | datetime.date | str | None:
    if kind == "count":
        return parse_event_count(raw)
    if kind in ("amount", "ratio"):
        return parse_event_decimal(raw)
    if kind == "date":
        return parse_event_date(raw)
    if kind == "text":
        text = " ".join(raw.split())
        return None if text in _ABSENT else text
    raise EventValueError(f"unknown fact kind {kind!r}")


# -- structured endpoints ------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuredEvent:
    endpoint: str
    rcept_no: str
    corp_code: str
    facts: list[ExtractedFact]


@dataclass(frozen=True)
class StructuredResult:
    events: list[StructuredEvent]
    errors: list[str]


async def fetch_structured_events(
    client: DartClient,
    endpoint: str,
    corp_code: str,
    bgn_de: str,
    end_de: str,
    on_body: Callable[[bytes], None] | None = None,
) -> StructuredResult:
    """Fetch one structured endpoint for a company and extract the contract's facts.

    Status ``013`` (no data) is an empty result. Any other non-``000`` status raises
    ``DartApiError``. ``on_body`` receives the response body as received once it has parsed.
    A row without ``rcept_no`` cannot be joined to a filing and is reported
    in ``errors`` instead of being dropped.
    """
    endpoint_spec(endpoint)  # unknown endpoints fail before any request
    logger.info(
        "fetching %s.json (crtfc_key=***, corp_code=%s, bgn_de=%s, end_de=%s)",
        endpoint,
        corp_code,
        bgn_de,
        end_de,
    )
    resp = await client._get(
        f"{endpoint}.json",
        {
            "crtfc_key": client._api_key(),
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
        },
    )
    result = parse_structured_payload(endpoint, resp.json())
    if on_body is not None:
        on_body(resp.content)
    return result


def parse_structured_payload(endpoint: str, payload: Any) -> StructuredResult:
    if not isinstance(payload, dict):
        raise DartApiError(f"{endpoint}.json: unexpected response (not a JSON object)")
    status = str(payload.get("status", "")).strip()
    if status == _STATUS_NO_DATA:
        return StructuredResult([], [])
    if status != _STATUS_OK:
        raise DartApiError(
            f"{endpoint}.json returned status {status}: {str(payload.get('message', '')).strip()}"
        )
    rows = payload.get("list")
    if not isinstance(rows, list):
        return StructuredResult([], [f"{endpoint}: status 000 but 'list' is not an array"])
    events: list[StructuredEvent] = []
    errors: list[str] = []
    for index, row in enumerate(rows):
        rcept_no = str(row.get("rcept_no", "")).strip() if isinstance(row, dict) else ""
        if not rcept_no:
            errors.append(f"{endpoint}: row {index} has no rcept_no")
            continue
        events.append(
            StructuredEvent(
                endpoint=endpoint,
                rcept_no=rcept_no,
                corp_code=str(row.get("corp_code", "")).strip(),
                facts=extract_facts(endpoint, row),
            )
        )
    return StructuredResult(events, errors)


async def fetch_buyback_acquisitions(
    client: DartClient, corp_code: str, bgn_de: str, end_de: str
) -> StructuredResult:
    return await fetch_structured_events(client, "tsstkAqDecsn", corp_code, bgn_de, end_de)


async def fetch_buyback_disposals(
    client: DartClient, corp_code: str, bgn_de: str, end_de: str
) -> StructuredResult:
    return await fetch_structured_events(client, "tsstkDpDecsn", corp_code, bgn_de, end_de)


async def fetch_rights_issues(
    client: DartClient, corp_code: str, bgn_de: str, end_de: str
) -> StructuredResult:
    return await fetch_structured_events(client, "piicDecsn", corp_code, bgn_de, end_de)


# -- document text -------------------------------------------------------------------------------


@dataclass(frozen=True)
class EventDocument:
    format: str  # "dsd", "xforms" or "unknown"
    text: str  # every text node, whitespace collapsed (tables included)
    prose: list[ProseSection]  # DSD only; tables are dropped by the DSD parser
    rows: list[list[str]]  # xforms table rows as cell texts


class _RowReader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._cells: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "tr":
            self._cells = []
        elif tag in ("td", "th") and self._cells is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None and self._cells is not None:
            self._cells.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._cells is not None:
            if any(self._cells):
                self.rows.append(self._cells)
            self._cells = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def flatten_markup(text: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def extract_xforms_rows(text: str) -> list[list[str]]:
    reader = _RowReader()
    reader.feed(text)
    reader.close()
    return reader.rows


def read_event_document(raw: bytes) -> EventDocument:
    """Decode a ``document.xml`` body (UTF-8 even when it declares euc-kr) and extract text."""
    text = decode_dart_bytes(raw)
    doc_format = detect_document_format(text)
    prose: list[ProseSection] = []
    rows: list[list[str]] = []
    if doc_format == "dsd":
        try:
            prose = extract_dsd_prose(text)
        except (ParseError, ValueError) as exc:
            logger.warning("event document: DSD prose parse failed (%s)", type(exc).__name__)
    elif doc_format == "xforms":
        rows = extract_xforms_rows(text)
    return EventDocument(doc_format, flatten_markup(text), prose, rows)


# -- correction target ---------------------------------------------------------------------------

# One date, as DART writes it in correction bodies: "2026년 07월 27일" (B) or "2026-08-19" (I).
_DATE = r"([0-9]{4})(?:\s*년\s*([0-9]{1,2})\s*월\s*([0-9]{1,2})\s*일|-([0-9]{2})-([0-9]{2}))"
# Observed formats [Verified on saved bodies]:
#   B (DSD):    "1. 정정대상 공시서류 : <name> 2. 정정대상 공시서류의 최초제출일 : <date>"
#   I (xforms): "1. 정정관련 공시서류 <name> 2. 정정관련 공시서류제출일 <date>"
_TARGET_FORMATS = (
    re.compile(
        r"정정대상\s*공시서류\s*:\s*(.+?)\s*[0-9]\.\s*정정대상\s*공시서류의\s*최초제출일\s*:\s*"
        + _DATE
    ),
    re.compile(
        r"정정관련\s*공시서류\s+(.+?)\s+[0-9]\.\s*정정관련\s*공시서류제출일\s*" + _DATE
    ),
)
_MIDDLE_DOT = str.maketrans({"\u00b7": "\u318d"})  # I bodies write 단일판매·공급계약, lists use ㆍ


@dataclass(frozen=True)
class CorrectionTarget:
    name: str | None
    first_filed: datetime.date | None
    error: str | None = None  # set when a date was present but is not a calendar date


def parse_correction_target(text: str) -> CorrectionTarget | None:
    """The report a correction names and the date that report was first filed, or ``None``.

    The body does not state the original's 접수번호, so name and date are what link a
    correction to its original. ``None`` means neither format matched. A date that matches but
    is not a calendar date gives ``first_filed=None`` and an ``error`` naming it.
    """
    flat = flatten_markup(text)
    for pattern in _TARGET_FORMATS:
        match = pattern.search(flat)
        if match is None:
            continue
        name = match.group(1).strip().translate(_MIDDLE_DOT)
        raw_date = flat[match.start(2) : match.end()]
        try:
            if match.group(3):
                parts = (match.group(2), match.group(3), match.group(4))
            else:
                parts = (match.group(2), match.group(5), match.group(6))
            first = datetime.date(*(int(g) for g in parts))
        except ValueError:
            error = f"impossible first-filing date {raw_date!r}"
            return CorrectionTarget(name or None, None, error)
        return CorrectionTarget(name or None, first)
    return None
