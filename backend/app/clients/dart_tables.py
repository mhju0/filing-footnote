"""Facts from the tables of DART exchange filings (xforms ``document.xml`` bodies).

Some event filings have no structured OpenDART endpoint but are a fixed form whose content is
a regular table: preliminary results, the 30% change in revenue or profit, monthly unit sales,
cash dividend decisions and results outlooks. :func:`parse_table_facts` reads the table rows
that :func:`app.clients.dart_events.read_event_document` extracts and returns
:class:`~app.clients.dart_events.ExtractedFact` values, following the ``documents`` block of
``contracts/filing-facts.json``.

Rules, the same as for the structured endpoints:

* Amounts, counts and ratios are exact ``Decimal`` values parsed from the cell text; ``-`` and
  the empty string mean "absent" and give no fact. △ before a number is a minus sign.
* The unit is the one the filing states (``백만원``, ``조원``, ``대``, ``원``, ``%``).
* A table that does not have the expected shape, or a cell that should hold a number and holds
  anything else, gives no facts at all: the filing is then summarised by the model.

Ingest and the build's pinned check (:mod:`app.build.verify`) both call this module on the same
document body, so the stored values and the pinned values come from one parser.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Sequence
from decimal import Decimal
from functools import cache
from typing import Any

from app.clients.dart_events import (
    EventValueError,
    ExtractedFact,
    load_facts_contract,
    parse_event_decimal,
)

Rows = Sequence[Sequence[str]]

_ISO_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_KO_DATE_RE = re.compile(r"([0-9]{4})\s*년\s*([0-9]{1,2})\s*월\s*([0-9]{1,2})\s*일")
_UNIT_RE = re.compile(r"단위\s*:\s*([^,)]+)")
_PAREN_UNIT_RE = re.compile(r"\(([^()]+)\)\s*$")
_LEADING_NUMBER_RE = re.compile(r"^[0-9]+\.\s*")
_YEAR_RE = re.compile(r"^[0-9]{4}$")
_ABSENT = frozenset({"", "-"})


class TableShapeError(ValueError):
    """The rows are not the table this parser reads; no fact is taken from them."""


# -- contract ------------------------------------------------------------------------------------


@cache
def _tables() -> dict[str, dict[str, Any]]:
    return {spec["table"]: spec for spec in load_facts_contract()["documents"]}


def table_spec(table: str) -> dict[str, Any]:
    try:
        return _tables()[table]
    except KeyError:
        raise KeyError(f"no filing-facts document table {table!r}") from None


def table_for(category: str | None, base_key: str) -> str | None:
    """The document table read for a filing of ``category`` whose normalised report name is
    ``base_key``, or None. The category decides between tables that share a report name
    (영업(잠정)실적 is results for some companies and unit sales for others)."""
    for spec in _tables().values():
        if category in spec["categories"] and base_key in spec["report_names"]:
            return str(spec["table"])
    return None


def table_of_key(key: str) -> str | None:
    """The document table that defines fact ``key``, or None."""
    for spec in _tables().values():
        if any(field["key"] == key for field in spec["fields"]):
            return str(spec["table"])
    return None


# -- cells ---------------------------------------------------------------------------------------


def _squash(text: str) -> str:
    return "".join(text.split())


def _label(text: str) -> str:
    """``3. 1주당 배당금(원)`` -> ``1주당배당금(원)``: no item number, no spaces."""
    return _squash(_LEADING_NUMBER_RE.sub("", text.strip()))


def _decimal(raw: str) -> Decimal | None:
    """A cell's number; None when absent. △ (the Korean minus sign) is accepted."""
    text = raw.strip()
    if text.startswith("△"):
        value = _decimal(text[1:])
        if value is None:
            raise TableShapeError(f"not a number: {raw!r}")
        return -value
    try:
        return parse_event_decimal(text)
    except EventValueError as exc:
        raise TableShapeError(str(exc)) from None


def _date(raw: str) -> datetime.date | None:
    text = raw.strip()
    if text in _ABSENT:
        return None
    match = _ISO_DATE_RE.fullmatch(text) or _KO_DATE_RE.fullmatch(text)
    if match is None:
        raise TableShapeError(f"not a date: {raw!r}")
    try:
        return datetime.date(*(int(g) for g in match.groups()))
    except ValueError:
        raise TableShapeError(f"not a calendar date: {raw!r}") from None


def _cell(row: Sequence[str], index: int) -> str:
    if index >= len(row):
        raise TableShapeError(f"row {list(row)!r} has no column {index}")
    return row[index]


class _Facts:
    """Collects facts in contract order; values are typed by the contract's kind."""

    def __init__(self, table: str) -> None:
        self.fields = {f["key"]: f for f in table_spec(table)["fields"]}
        self.found: dict[str, ExtractedFact] = {}

    def add(self, key: str, raw: str, unit: str | None = None) -> None:
        field = self.fields[key]
        kind = field["kind"]
        base = {"key": key, "kind": kind, "source_field": field["source_field"], "raw": raw}
        if kind in ("amount", "count", "ratio"):
            value = _decimal(raw)
            if value is None:
                return
            if unit is None:
                raise TableShapeError(f"{key}: the filing states no unit")
            self.found[key] = ExtractedFact(**base, unit=unit, value_decimal=value)
        elif kind == "date":
            day = _date(raw)
            if day is not None:
                self.found[key] = ExtractedFact(**base, unit=None, value_date=day)
        else:
            text = " ".join(raw.split())
            if text not in _ABSENT:
                self.found[key] = ExtractedFact(**base, unit=None, value_text=text)

    def result(self) -> list[ExtractedFact]:
        order = list(self.fields)
        return sorted(self.found.values(), key=lambda f: order.index(f.key))


def _index_of(rows: Rows, test: Callable[[Sequence[str]], bool], start: int = 0) -> int:
    for index in range(start, len(rows)):
        if rows[index] and test(rows[index]):
            return index
    raise TableShapeError("expected row not found")


def _stated_unit(text: str) -> str:
    match = _UNIT_RE.search(text)
    if match is None:
        raise TableShapeError(f"no unit in {text!r}")
    return match.group(1).strip()


def _period(rows: Rows, label: str) -> tuple[str, str] | None:
    """``당기실적 | 2026-07-01 | ~ | 2026-09-30`` -> the two date cells."""
    for row in rows:
        if row and _squash(row[0]) == label and len(row) >= 4 and row[2].strip() == "~":
            return row[1], row[3]
    return None


# -- preliminary results (잠정실적) ----------------------------------------------------------------

_METRICS = {
    "매출액": "revenue",
    "영업이익": "operating_income",
    "법인세비용차감전계속사업이익": "pretax_income",
    "법인세비용차감전순이익": "pretax_income",
    "당기순이익": "net_income",
    "지배기업소유주지분순이익": "net_income_attributable",
}


def _results(rows: Rows) -> list[ExtractedFact]:
    facts = _Facts("results")
    header = _index_of(
        rows, lambda r: _squash(r[0]) == "구분" and "당기실적" in r and "전년동기실적" in r
    )
    unit = _stated_unit(" ".join(rows[header - 1]))
    for label, prefix in (("당기실적", "results_period"), ("전년동기실적", "results_year_ago")):
        period = _period(rows[:header], label)
        if period is not None:
            facts.add(f"{prefix}_start", period[0])
            facts.add(f"{prefix}_end", period[1])
    index = header + 2  # the header's second row holds the period labels
    metric = None
    while index < len(rows):
        row = rows[index]
        first = _squash(row[0])
        if first.startswith("구분") or _LEADING_NUMBER_RE.match(row[0].strip()):
            break  # the unit-sales table, or the next numbered section
        if all(cell.strip() in _ABSENT for cell in row):
            index += 1
            continue
        if len(row) >= 2 and _squash(row[1]) == "당해실적":
            if first not in _METRICS:
                raise TableShapeError(f"unknown results row {row[0]!r}")
            metric = _METRICS[first]
            cells = row[2:]
            facts.add(f"results_{metric}_current", _cell(cells, 0), unit)
            facts.add(f"results_{metric}_prior_period", _cell(cells, 1), unit)
            facts.add(f"results_{metric}_year_ago", _cell(cells, 4), unit)
        elif first == "누계실적" and metric is not None:
            cells = row[1:]
            facts.add(f"results_{metric}_cumulative", _cell(cells, 0), unit)
            facts.add(f"results_{metric}_cumulative_year_ago", _cell(cells, 4), unit)
            metric = None
        else:
            raise TableShapeError(f"unexpected results row {row[0]!r}")
        index += 1
    return facts.result()


# -- 매출액또는손익구조30%(대규모법인은15%)이상변경 ----------------------------------

_CHANGE_METRICS = {k: v for k, v in _METRICS.items() if v != "net_income_attributable"}


def _change(rows: Rows) -> list[ExtractedFact]:
    facts = _Facts("change")
    kind_row = _index_of(rows, lambda r: _label(r[0]) == "재무제표의종류")
    facts.add("change_statement", _cell(rows[kind_row], 1))
    period = _index_of(rows, lambda r: _label(r[0]) == "결산기간", kind_row)
    for offset, prefix in ((1, "start"), (2, "end")):
        row = rows[period + offset]
        if _squash(row[0]) != f"-{'시작일' if prefix == 'start' else '종료일'}":
            raise TableShapeError(f"unexpected period row {row[0]!r}")
        facts.add(f"change_period_{prefix}", _cell(row, 1))
        facts.add(f"change_prior_{prefix}", _cell(row, 2))
    header = _index_of(rows, lambda r: "매출액또는손익구조변동내용" in _squash(r[0]), period)
    if _squash(_cell(rows[header], 1)) != "당해사업연도" or _squash(
        _cell(rows[header], 2)
    ) != "직전사업연도":
        raise TableShapeError("unexpected change header")
    unit = _stated_unit(rows[header][0])
    for row in rows[header + 1 :]:
        label = _squash(row[0]).removeprefix("-")
        if label not in _CHANGE_METRICS:
            break
        metric = _CHANGE_METRICS[label]
        facts.add(f"change_{metric}_current", _cell(row, 1), unit)
        facts.add(f"change_{metric}_prior", _cell(row, 2), unit)
    return facts.result()


# -- unit sales (영업(잠정)실적, sales table) -----------------------------------------------------

_SEGMENTS = {
    "국내": "domestic",
    "내수": "domestic",
    "판매대수(내수)": "domestic",
    "해외": "overseas",
    "판매대수(해외)": "overseas",
    "특수": "special",
    "판매대수(특수)": "special",
    "계": "total",
    "합계": "total",
    "총계": "total",
}


def _units(rows: Rows) -> list[ExtractedFact]:
    facts = _Facts("units")

    def is_header(row: Sequence[str]) -> bool:
        first = _squash(row[0])
        return first.startswith("구분") and "단위" in first and "대" in _stated_unit(first)

    monthly = _index_of(rows, is_header)
    cumulative = _index_of(rows, is_header, monthly + 1)
    if "누적" not in _squash(_cell(rows[cumulative], 1)):
        raise TableShapeError("the second sales table is not cumulative")
    period = _period(rows[:monthly], "당기실적")
    if period is not None:
        facts.add("units_period_start", period[0])
        facts.add("units_period_end", period[1])
    for header, columns in (
        (monthly, (("current", 1), ("prior_period", 2), ("year_ago", 5))),
        (cumulative, (("cumulative", 1), ("cumulative_year_ago", 5))),
    ):
        unit = _stated_unit(_squash(rows[header][0]))
        seen = set()
        for row in rows[header + 1 :]:
            label = _squash(row[0])
            if label not in _SEGMENTS:
                break
            segment = _SEGMENTS[label]
            if segment in seen:
                raise TableShapeError(f"segment {label!r} listed twice")
            seen.add(segment)
            for name, column in columns:
                facts.add(f"units_{segment}_{name}", _cell(row, column), unit)
        if "total" not in seen:
            raise TableShapeError("no total row")
    return facts.result()


# -- cash dividend decision (현금ㆍ현물배당결정) ---------------------------------------------------


def _dividend(rows: Rows) -> list[ExtractedFact]:
    facts = _Facts("dividend")
    # A correction lists the changed items first; the form itself starts at 배당구분.
    start = _index_of(rows, lambda r: _label(r[0]) == "배당구분")
    form = rows[start:]
    pending: str | None = None  # the item whose 종류주식 row follows
    for row in form:
        label = _label(row[0])
        if label == "배당구분":
            facts.add("dividend_kind", _cell(row, 1))
        elif label == "배당종류":
            facts.add("dividend_type", _cell(row, 1))
        elif label.startswith("1주당배당금") or label.startswith("시가배당률"):
            item = "per_share" if label.startswith("1주당") else "yield"
            if _squash(_cell(row, 1)) != "보통주식":
                raise TableShapeError(f"unexpected {label} row")
            unit = _PAREN_UNIT_RE.search(label)
            if unit is None:
                raise TableShapeError(f"no unit in {label!r}")
            facts.add(f"dividend_{item}_common", _cell(row, 2), unit.group(1))
            pending = f"{item}:{unit.group(1)}"
        elif label == "종류주식" and pending is not None:
            item, unit_text = pending.split(":")
            facts.add(f"dividend_{item}_preferred", _cell(row, 1), unit_text)
            pending = None
        elif label.startswith("배당금총액"):
            unit = _PAREN_UNIT_RE.search(label)
            if unit is None:
                raise TableShapeError(f"no unit in {label!r}")
            facts.add("dividend_total", _cell(row, 1), unit.group(1))
        elif label == "배당기준일":
            facts.add("dividend_record_date", _cell(row, 1))
        elif label == "배당금지급예정일자":
            facts.add("dividend_payment_date", _cell(row, 1))
        elif label.startswith("이사회결의일"):
            facts.add("dividend_decision_date", _cell(row, 1))
        elif label.startswith("기타투자판단"):
            break
    if "dividend_kind" not in facts.found or "dividend_type" not in facts.found:
        raise TableShapeError("no dividend kind or type")
    return facts.result()


# -- results outlook (영업실적등에대한전망) --------------------------------------------------------

_OUTLOOK_METRICS = {k: v for k, v in _METRICS.items() if v != "net_income_attributable"}
OUTLOOK_YEARS = 3
OUTLOOK_ITEMS = 6
OUTLOOK_CHANGES = 6


def _outlook(rows: Rows) -> list[ExtractedFact]:
    facts = _Facts("outlook")
    header = _index_of(
        rows,
        lambda r: _squash(r[0]).startswith("구분(단위") and any(_YEAR_RE.match(c) for c in r[1:]),
    )
    unit = _stated_unit(rows[header][0])
    years = [c.strip() for c in rows[header][1:] if _YEAR_RE.match(c.strip())]
    if not 1 <= len(years) <= OUTLOOK_YEARS:
        raise TableShapeError(f"unexpected outlook years {years!r}")
    # Every forecast cell: (value text, unit), to give a correction row its unit.
    cells: list[tuple[Decimal, str]] = []
    items = 0
    parent: tuple[str, str] | None = None  # (label, unit) of the item a "-국내" row belongs to
    index = header + 1
    while index < len(rows):
        row = rows[index]
        first = row[0].strip()
        label = _squash(first)
        if _LEADING_NUMBER_RE.match(first):
            break  # 2. 전망 또는 예측의 근거
        if label == "대상기간" and len(row) >= 3 and _squash(row[1]) == "시작일":
            values = row[2:]
            for year in range(len(years)):
                facts.add(f"outlook_start_y{year + 1}", _cell(values, year))
        elif label == "종료일":
            for year in range(len(years)):
                facts.add(f"outlook_end_y{year + 1}", _cell(row[1:], year))
        elif all(cell.strip() in _ABSENT for cell in row):
            pass
        elif label in _OUTLOOK_METRICS:
            metric = _OUTLOOK_METRICS[label]
            for year in range(len(years)):
                raw = _cell(row[1:], year)
                facts.add(f"outlook_{metric}_y{year + 1}", raw, unit)
                if (value := _decimal(raw)) is not None:
                    cells.append((value, unit))
        else:
            if label.startswith("-") and parent is not None:
                item_label, item_unit = f"{parent[0]}{first}", parent[1]
            else:
                stated = _PAREN_UNIT_RE.search(first)
                item_label, item_unit = first, stated.group(1) if stated else unit
                parent = (first, item_unit)
            values = [_decimal(_cell(row[1:], year)) for year in range(len(years))]
            if any(v is not None for v in values):
                items += 1
                if items > OUTLOOK_ITEMS:
                    raise TableShapeError("more outlook items than the contract lists")
                facts.add(f"outlook_item{items}_label", item_label)
                for year, raw in enumerate(row[1 : len(years) + 1]):
                    facts.add(f"outlook_item{items}_y{year + 1}", raw, item_unit)
                cells.extend((v, item_unit) for v in values if v is not None)
        index += 1
    for year, text in enumerate(years):
        if any(k.endswith(f"_y{year + 1}") and not k.startswith(("outlook_start", "outlook_end"))
               for k in facts.found):  # fmt: skip
            facts.add(f"outlook_year_y{year + 1}", text)
    _outlook_changes(rows[:header], cells, facts)
    return facts.result()


def _outlook_changes(rows: Rows, cells: list[tuple[Decimal, str]], facts: _Facts) -> None:
    """A correction's 정정전/정정후 rows whose two cells are numbers. A row is kept only when its
    corrected value is a value of the forecast table with one unit, which gives it that unit."""
    try:
        start = _index_of(rows, lambda r: [_squash(c) for c in r[:3]] == ["정정항목", "정정전",
                                                                         "정정후"])  # fmt: skip
    except TableShapeError:
        return
    changes = 0
    for row in rows[start + 1 :]:
        if len(row) != 3 or row[0].strip().startswith("※"):
            break
        try:
            before, after = _decimal(row[1]), _decimal(row[2])
        except TableShapeError:
            continue  # a text item (기타 투자판단 사항), not a figure
        if before is None or after is None:
            continue
        units = {u for value, u in cells if value == after}
        if len(units) != 1:
            continue
        changes += 1
        if changes > OUTLOOK_CHANGES:
            raise TableShapeError("more outlook changes than the contract lists")
        (unit,) = units
        facts.add(f"outlook_change{changes}_label", row[0])
        facts.add(f"outlook_change{changes}_before", row[1], unit)
        facts.add(f"outlook_change{changes}_after", row[2], unit)


# -- entry point ---------------------------------------------------------------------------------

_PARSERS: dict[str, Callable[[Rows], list[ExtractedFact]]] = {
    "results": _results,
    "change": _change,
    "units": _units,
    "dividend": _dividend,
    "outlook": _outlook,
}


def parse_table_facts(table: str, rows: Rows) -> list[ExtractedFact]:
    """The facts of ``table`` in the document's rows, in contract order; an empty list when
    the rows are not that table."""
    table_spec(table)
    try:
        return _PARSERS[table](rows)
    except (TableShapeError, IndexError):
        return []
