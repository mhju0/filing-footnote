"""M9: the owner's proofreading sheet for staged summaries.

    python -m app.build.review --out dist/review.html [--staged PATH]
        [--database-url URL] [--as-of DATE]

Writes one self-contained static page (inline CSS, no script, no outside request) with every
staged summary: the Korean and English lines side by side, the guard violations, the N9
warnings, the reviewer's flags, the source link and the command that approves it. Filings with
reviewer flags or warnings come first, then withheld ones, then the rest. With
``--database-url`` the page also shows the company, the filing title and the facts the filing
states; without it only the staged rows are shown. The same input gives the same bytes.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import shlex
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from app.build.export import _company_id, _filing_id
from app.build.model import BuildInput
from app.build.summaries import STAGED_PATH, company_names, read_jsonl

SOURCE_PREFIXES = ("https://dart.fss.or.kr/", "https://www.sec.gov/")
DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
LANG_LABEL = {"ko": "한국어", "en": "English"}


@dataclass(frozen=True)
class FilingInfo:
    company: str
    title: str
    kind: str  # 'event' | 'annual'
    url: str | None
    facts: tuple[tuple[str, str], ...]  # (label, value) as the filing states them


# -- filing details from the build input ---------------------------------------------------------


def _source_url(regulator: str, key: str, url: str | None) -> str | None:
    if url and url.startswith(SOURCE_PREFIXES):
        return url
    return DART_VIEWER + key if regulator == "DART" else None


def _fact_value(fact: Any) -> str:
    if fact.value_decimal is not None:
        return f"{fact.value_decimal.normalize():f} {fact.unit or ''}".strip()
    if fact.value_date is not None:
        return fact.value_date.isoformat()
    return fact.value_text or fact.raw


def build_info(data: BuildInput) -> dict[str, FilingInfo]:
    """Filing id -> company, title, source link and facts, from the build input."""
    names = company_names(data.companies)
    shown = {_company_id(c.regulator, c.key): c.name_en or c.name for c in data.companies}
    shown.update({cid: ns[0] for cid, ns in names.items() if ns})
    info: dict[str, FilingInfo] = {}
    for event in data.events:
        cid = _company_id(event.regulator, event.company_key)
        facts = tuple((f.key, _fact_value(f)) for f in event.facts if f.error is None)
        info[_filing_id(event.regulator, event.filing_key)] = FilingInfo(
            shown.get(cid, ""),
            event.report_nm,
            "event",
            _source_url(event.regulator, event.filing_key, event.url),
            facts,
        )
    figures: dict[str, list[tuple[str, str]]] = {}
    for row in data.financials:
        figures.setdefault(_filing_id(row.regulator, row.filing_key), []).append(
            (f"{row.metric} {row.period}", f"{row.value.normalize():f} {row.unit}".strip())
        )
    for filing in data.annual_filings:
        fid = _filing_id(filing.regulator, filing.filing_key)
        cid = _company_id(filing.regulator, filing.company_key)
        info[fid] = FilingInfo(
            shown.get(cid, ""),
            filing.title,
            "annual",
            _source_url(filing.regulator, filing.filing_key, filing.url),
            tuple(sorted(figures.get(fid, []))),
        )
    return info


# -- page ----------------------------------------------------------------------------------------

CSS = """\
:root { color-scheme: light dark; --ink: #152A31; --muted: #5B6475; --line: #E6E9EE;
  --bg: #F5F6F8; --card: #FFFFFF; --pine: #10645B; --tint: #E7F0EE; --warn: #8A4B00;
  --bad: #A02525; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #E8EEF0; --muted: #A5AEBB; --line: #2C3A40; --bg: #0F1A1E; --card: #16252B;
    --pine: #5CC4B6; --tint: #1E3A38; --warn: #E9B35E; --bad: #FF8F8F; } }
* { box-sizing: border-box; }
body { margin: 0; padding: 16px; background: var(--bg); color: var(--ink);
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Segoe UI",
    sans-serif; word-break: keep-all; overflow-wrap: anywhere; }
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 0; }
p { margin: 4px 0; }
a { color: var(--pine); }
a:focus-visible, summary:focus-visible { outline: 3px solid var(--pine); outline-offset: 2px; }
.muted { color: var(--muted); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  padding: 16px; margin: 16px 0; }
.head { display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline; }
.state { font-weight: 600; }
.langs { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 12px 0; }
@media (max-width: 640px) { .langs { grid-template-columns: 1fr; } }
.lang h3 { font-size: 14px; margin: 0 0 4px; color: var(--muted); }
ol { margin: 0; padding-left: 24px; }
li { margin: 4px 0; }
.problem { color: var(--bad); font-weight: 600; }
.warning { color: var(--warn); font-weight: 600; }
.notes { margin: 8px 0; padding: 0; list-style: none; }
.command { display: block; margin: 8px 0 0; padding: 8px 12px; background: var(--tint);
  border-radius: 4px; user-select: all; white-space: pre-wrap; overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px; }
details { margin-top: 8px; }
summary { cursor: pointer; min-height: 44px; display: flex; align-items: center; }
dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; }
dd { margin: 0; font-variant-numeric: tabular-nums; }
"""


def _group(rows: Sequence[Mapping[str, Any]]) -> int:
    if any(r.get("reviewer_flags") or r.get("warnings") for r in rows):
        return 0
    if any(r["review_state"] == "withheld" for r in rows):
        return 1
    return 2


def _lines(row: Mapping[str, Any]) -> list[str]:
    return [line for line in (row["line1"], row["line2"], row["line3"]) if line is not None]


def _problem(item: Mapping[str, Any]) -> str:
    where = f"line {item['line_no']}" if item.get("line_no") else "whole summary"
    token = f" {item['token']!r}" if item.get("token") else ""
    return f"{item['rule_id']} {where}{token}"


def _flag(item: Mapping[str, Any]) -> str:
    quote = f": {item['quote_from_summary']}" if item.get("quote_from_summary") else ""
    return f"{item.get('type', 'flag')} line {item.get('line', '?')}{quote}"


def _notes(rows: Sequence[Mapping[str, Any]]) -> str:
    out = []
    for row in rows:
        label = LANG_LABEL.get(row["lang"], row["lang"])
        for item in row.get("violations") or []:
            out.append(
                f'<li class="problem">{escape(label)} guard violation: '
                f"{escape(_problem(item))}</li>"
            )
        for item in row.get("warnings") or []:
            out.append(
                f'<li class="warning">{escape(label)} N9 warning: {escape(_problem(item))}</li>'
            )
        flags = row.get("reviewer_flags")
        if flags is None:
            out.append(f'<li class="muted">{escape(label)}: the reviewer did not run</li>')
        for item in flags or []:
            out.append(
                f'<li class="warning">{escape(label)} reviewer flag: {escape(_flag(item))}</li>'
            )
    return f'<ul class="notes">{"".join(out)}</ul>' if out else ""


def _command(filing_id: str, section: str) -> str:
    return (
        "python -m app.build.approve --filing "
        + shlex.quote(filing_id)
        + " --section "
        + shlex.quote(section)
    )


def _card(
    filing_id: str, section: str, rows: Sequence[Mapping[str, Any]], info: FilingInfo | None
) -> str:
    anchor = escape(f"{filing_id}-{section}", quote=True)
    head = [f"<h2>{escape(info.company if info and info.company else filing_id)}</h2>"]
    if info:
        head.append(f"<span>{escape(info.title)} ({escape(info.kind)})</span>")
    head.append(f"<span>section: {escape(section)}</span>")
    states = ", ".join(f"{r['lang']} {r['review_state']}" for r in rows)
    head.append(f'<span class="state">{escape(states)}</span>')
    if info and info.url and info.url.startswith(SOURCE_PREFIXES):
        head.append(
            f'<a href="{escape(info.url, quote=True)}" rel="noopener noreferrer">Source filing</a>'
        )
    langs = []
    for row in rows:
        items = "".join(f"<li>{escape(line)}</li>" for line in _lines(row))
        langs.append(
            f'<div class="lang"><h3>{escape(LANG_LABEL.get(row["lang"], row["lang"]))}'
            f'</h3><ol lang="{escape(row["lang"], quote=True)}">{items}</ol></div>'
        )
    parts = [
        f'<section class="card" id="{anchor}">',
        f'<div class="head">{"".join(head)}</div>',
        f'<p class="muted">{escape(filing_id)}</p>',
        f'<div class="langs">{"".join(langs)}</div>',
        _notes(rows),
    ]
    if info and info.facts:
        facts = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in info.facts)
        parts.append(
            f"<details><summary>Facts the filing states</summary><dl>{facts}</dl></details>"
        )
    if all(r["review_state"] == "staged" and not r.get("violations") for r in rows):
        parts.append(
            '<p class="muted">Approve both languages:</p>'
            f'<code class="command">{escape(_command(filing_id, section))}</code>'
        )
    else:
        parts.append('<p class="muted">Not approvable: a withheld row is never approved.</p>')
    parts.append("</section>")
    return "\n".join(parts)


def render(
    rows: Sequence[Mapping[str, Any]],
    info: Mapping[str, FilingInfo],
    as_of: datetime.date | None = None,
) -> str:
    """The whole page as text; deterministic for the same rows, details and date."""
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in sorted(
        rows, key=lambda r: (r["filing_id"], r["section"], r["lang"] != "ko", r["lang"])
    ):
        grouped.setdefault((row["filing_id"], row["section"]), []).append(row)
    order = sorted(grouped, key=lambda k: (_group(grouped[k]), k))
    cards = "\n".join(
        _card(fid, section, grouped[(fid, section)], info.get(fid)) for fid, section in order
    )
    counts = f"{len(order)} summaries, {len(rows)} rows"
    when = f" as of {as_of.isoformat()}" if as_of else ""
    note = (
        ""
        if info
        else (
            '<p class="muted">Company, title and facts are not shown: no '
            "--database-url was given.</p>"
        )
    )
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Summary review</title>\n"
        f"<style>\n{CSS}</style>\n</head>\n<body>\n<main>\n"
        f'<h1>Summary review</h1>\n<p class="muted">{escape(counts + when)}. Flagged or '
        "warned summaries first, then withheld, then the rest. To change a line, add "
        "--lang, --edit-line and --text to the command.</p>\n"
        f"{note}\n{cards}\n</main>\n</body>\n</html>\n"
    )


# -- command line --------------------------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix=f".{path.name}."
    ) as handle:
        handle.write(text)
    Path(handle.name).replace(path)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.build.review",
        description="Write the owner's proofreading sheet for staged summaries.",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--staged", type=Path, default=STAGED_PATH)
    parser.add_argument("--database-url", help="adds company, title, link and facts")
    parser.add_argument("--as-of", type=datetime.date.fromisoformat)
    args = parser.parse_args(argv)
    info: dict[str, FilingInfo] = {}
    if args.database_url:
        from app.build.source import load_build_input

        info = build_info(asyncio.run(load_build_input(args.database_url)))
    rows = read_jsonl(args.staged)
    _write(args.out, render(rows, info, args.as_of))
    print(f"wrote {args.out}: {len(rows)} rows from {args.staged}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
