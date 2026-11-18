"""M9: the owner's approval step for build-time summaries.

    python -m app.build.approve --filing ID [--section S] [--lang ko|en]
        [--edit-line N --text "..."] [--database-url URL]
    python -m app.build.approve --all-reviewed

Approving moves rows from ``staged.jsonl`` to ``approved.jsonl`` with ``review_state`` set to
``approved``; ``input_sha256`` and the provenance fields are kept, because the exporter checks
that key against the current source text, prompt, model and word lists. Nothing is approved
unless the owner runs this command. A ``withheld`` row is never approved, and a row that holds
guard violations is refused.

The exporter ships a filing only when both languages of every required section are approved
(``app.build.export._summaries``), and it reports a duplicate (filing, language, section) as a
problem, so approving again replaces the approved row. Without ``--lang`` both languages of the
filing and section move together.

An edit replaces one line of one language and runs the language's lines through the same guard
the exporter runs (``summaries.guard_lines``) with the company's names; on a violation nothing is
written. ``--all-reviewed`` approves a filing section only when both languages are staged,
hold no violations and have a reviewer result with no flags; a row whose reviewer did not run is
left for the owner. It lists what it approved.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.build.export import _company_id, _filing_id
from app.build.model import LANGS, BuildInput
from app.build.summaries import (
    APPROVED_PATH,
    LINE_COUNT,
    STAGED_PATH,
    company_names,
    guard_lines,
    read_jsonl,
    write_staged,
)
from app.llm.neutrality_guard import summary_warnings

Row = dict[str, Any]
Key = tuple[str, str, str]  # (filing_id, lang, section)
NamesFor = Callable[[str], Sequence[str]]


class ApproveError(Exception):
    """The request is refused; no file was changed."""


@dataclass
class ApproveResult:
    approved: list[Key] = field(default_factory=list)


def _key(row: Mapping[str, Any]) -> Key:
    return (row["filing_id"], row["lang"], row["section"])


def _lines(row: Mapping[str, Any]) -> list[str]:
    count = LINE_COUNT[row["section"]]
    return [line for line in (row["line1"], row["line2"], row["line3"])[:count] if line is not None]


def _refusal(row: Mapping[str, Any]) -> str | None:
    key = " ".join(_key(row))
    if row["review_state"] == "withheld":
        return f"{key} is withheld and is never approved"
    if row["review_state"] != "staged":
        return f"{key} is {row['review_state']}, not staged"
    if row.get("violations"):
        return f"{key} holds guard violations"
    return None


def _commit(
    staged_path: Path, approved_path: Path, staged: Iterable[Row], moved: Sequence[Row]
) -> ApproveResult:
    moving = {_key(row) for row in moved}
    kept_approved = [r for r in read_jsonl(approved_path) if _key(r) not in moving]
    # Approved first: a failure between the two writes leaves a row in both files, never in
    # neither.
    write_staged(approved_path, kept_approved + list(moved))
    write_staged(staged_path, [r for r in staged if _key(r) not in moving])
    return ApproveResult(sorted(moving))


def _approved_row(row: Row) -> Row:
    return {**row, "review_state": "approved"}


def _violation_text(found: Sequence[Any]) -> str:
    return "; ".join(f"{v.rule_id} line {v.line_no} {v.token!r}" for v in found)


def _edited(row: Row, number: int, text: str, names: Sequence[str]) -> Row:
    lines = _lines(row)
    if not 1 <= number <= len(lines):
        raise ApproveError(f"line {number} does not exist; {' '.join(_key(row))} has {len(lines)}")
    lines[number - 1] = text.strip()
    found = guard_lines(row["section"], row["lang"], lines, names)
    if found:
        raise ApproveError(f"edit refused, the guard found: {_violation_text(found)}")
    padded = lines + [None] * (3 - len(lines))
    return {
        **row,
        "line1": padded[0],
        "line2": padded[1],
        "line3": padded[2],
        "violations": [],
        "warnings": [
            {"rule_id": v.rule_id, "line_no": v.line_no, "token": v.token, "span": list(v.span)}
            for v in summary_warnings(lines, row["lang"])
        ],  # type: ignore[arg-type]
        "owner_edited": True,
    }


def approve_filing(
    staged_path: Path,
    approved_path: Path,
    filing_id: str,
    section: str | None = None,
    lang: str | None = None,
    edit: tuple[int, str] | None = None,
    names: NamesFor | None = None,
) -> ApproveResult:
    staged = read_jsonl(staged_path)
    picked = [
        r
        for r in staged
        if r["filing_id"] == filing_id
        and section in (None, r["section"])
        and lang in (None, r["lang"])
    ]
    if not picked:
        raise ApproveError(
            f"no staged summary for {filing_id}"
            + (f" {section}" if section else "")
            + (f" {lang}" if lang else "")
        )
    sections = sorted({r["section"] for r in picked})
    if len(sections) > 1:
        raise ApproveError(
            f"{filing_id} has several sections ({', '.join(sections)}); pass --section"
        )
    for row in picked:
        reason = _refusal(row)
        if reason:
            raise ApproveError(reason)
    if edit is not None:
        if lang is None:
            raise ApproveError("an edit needs --lang")
        if names is None:
            raise ApproveError("an edit needs the company names to run the guard")
        picked = [_edited(picked[0], edit[0], edit[1], names(filing_id))]
    return _commit(staged_path, approved_path, staged, [_approved_row(r) for r in picked])


def _clean_and_reviewed(row: Mapping[str, Any]) -> bool:
    return (
        row["review_state"] == "staged"
        and not row.get("violations")
        and row.get("reviewer_flags") == []
    )


def approve_all_reviewed(staged_path: Path, approved_path: Path) -> ApproveResult:
    staged = read_jsonl(staged_path)
    pairs: dict[tuple[str, str], list[Row]] = {}
    for row in staged:
        pairs.setdefault((row["filing_id"], row["section"]), []).append(row)
    picked = [
        _approved_row(r)
        for rows in pairs.values()
        if {r["lang"] for r in rows} == set(LANGS) and all(map(_clean_and_reviewed, rows))
        for r in rows
    ]
    return _commit(staged_path, approved_path, staged, picked)


def filing_names(data: BuildInput) -> dict[str, tuple[str, ...]]:
    """Filing id -> the company names the exporter passes to the guard."""
    by_company = company_names(data.companies)
    names = {}
    for event in data.events:
        names[_filing_id(event.regulator, event.filing_key)] = by_company.get(
            _company_id(event.regulator, event.company_key), ()
        )
    for filing in data.annual_filings:
        names[_filing_id(filing.regulator, filing.filing_key)] = by_company.get(
            _company_id(filing.regulator, filing.company_key), ()
        )
    return names


def _database_names(database_url: str | None) -> NamesFor:
    from app.build.source import load_build_input

    if database_url is None:
        from app.config import get_settings

        database_url = get_settings().database_url
    names = filing_names(asyncio.run(load_build_input(database_url)))

    def names_for(filing_id: str) -> Sequence[str]:
        if filing_id not in names:
            raise ApproveError(f"{filing_id} is not in the build database; cannot run the guard")
        return names[filing_id]

    return names_for


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.build.approve",
        description="Approve staged summaries: move them to approved.jsonl.",
    )
    parser.add_argument("--filing", metavar="ID", help="filing id, such as dart:2025...")
    parser.add_argument("--section", help="needed when the filing has several staged sections")
    parser.add_argument("--lang", choices=LANGS, help="only this language")
    parser.add_argument("--edit-line", type=int, metavar="N", help="replace line N (needs --lang)")
    parser.add_argument("--text", help="the replacement line for --edit-line")
    parser.add_argument(
        "--all-reviewed",
        action="store_true",
        help="approve each filing section whose two languages are clean and reviewed",
    )
    parser.add_argument("--database-url", help="for --edit-line; default: DATABASE_URL")
    parser.add_argument("--staged", type=Path, default=STAGED_PATH)
    parser.add_argument("--approved", type=Path, default=APPROVED_PATH)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.all_reviewed == bool(args.filing):
        parser.error("give --filing ID or --all-reviewed, not both or neither")
    if (args.edit_line is None) != (args.text is None):
        parser.error("--edit-line and --text go together")
    if args.all_reviewed and (args.edit_line is not None or args.section or args.lang):
        parser.error("--all-reviewed takes no --section, --lang or --edit-line")
    try:
        if args.all_reviewed:
            result = approve_all_reviewed(args.staged, args.approved)
        else:
            edit = None if args.edit_line is None else (args.edit_line, args.text)
            names = _database_names(args.database_url) if edit else None
            result = approve_filing(
                args.staged, args.approved, args.filing, args.section, args.lang, edit, names
            )
    except ApproveError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    for filing_id, lang, section in result.approved:
        print(f"approved {filing_id} {lang} {section}")
    print(f"approved {len(result.approved)} rows -> {args.approved}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
