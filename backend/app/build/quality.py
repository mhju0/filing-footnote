"""Quality report for the summary build: what the model wrote, what the guard stopped, what the
owner approved, and what it cost in calls and tokens.

    python -m app.build.quality [--staged P] [--approved P] [--calls P]

It reads ``staged.jsonl``, ``approved.jsonl`` and ``calls.jsonl`` and prints Markdown tables. It
writes nothing. Counts are per filing section (one filing's ``summary`` or one annual-report
section), with Korean and English counted together: a section is withheld when either language
was withheld, and a guard rule counts once per section however many lines it caught.

The call log records each call's purpose. A ``retry`` call happens only after the first answer
failed the guard, so retries count first answers the guard rejected; a retry that ended in an
API error is counted apart. A retry counts as having fixed a section only when it was the
section's last completed writing call and the section now passes; a later run that wrote the
section again from a first call does not count. The log does not record which rule failed a
first answer; the rules listed are the ones on rows that stayed withheld.

An approved section counts as approved even when a newer staged or withheld version exists;
that case is counted apart. Whether an approval still matches its source text, prompt, model
and word lists is checked by the export (``stale_approved_rows_skipped`` in its report), not
here.
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.build.summaries import APPROVED_PATH, CALLS_PATH, STAGED_PATH, read_jsonl

Row = Mapping[str, Any]
TEMPLATE = "template"


@dataclass
class Report:
    sections: int = 0
    by_model: int = 0
    by_template: int = 0
    approved: int = 0
    approved_with_newer_version: int = 0
    awaiting_owner: int = 0
    withheld: int = 0
    withheld_rules: Counter[str] = field(default_factory=Counter)
    owner_edited: int = 0
    soft_warnings: int = 0
    reviewer_flagged: int = 0
    reviewer_clean: int = 0
    reviewer_not_run: int = 0
    first_calls: int = 0
    retries: int = 0
    retry_errors: int = 0
    retried_then_passed: int = 0
    retried_then_withheld: int = 0
    review_calls: int = 0
    cache_hits: int = 0
    template_runs: int = 0
    api_errors: Counter[str] = field(default_factory=Counter)
    tokens_in: list[int] = field(default_factory=list)
    tokens_out: list[int] = field(default_factory=list)
    first_call_at: str | None = None
    last_call_at: str | None = None


def _key(row: Row) -> tuple[str, str]:
    return str(row["filing_id"]), str(row["section"])


def _sections(staged: Iterable[Row], approved: Iterable[Row]) -> dict[tuple[str, str], list[Row]]:
    """Approved rows win over staged ones for the same filing section."""
    out: dict[tuple[str, str], list[Row]] = {}
    for row in approved:
        out.setdefault(_key(row), []).append(row)
    done = set(out)
    for row in staged:
        if _key(row) not in done:
            out.setdefault(_key(row), []).append(row)
    return out


def build(staged: Sequence[Row], approved: Sequence[Row], calls: Sequence[Row]) -> Report:
    report = Report()
    sections = _sections(staged, approved)
    approved_keys = {_key(r) for r in approved}
    report.approved_with_newer_version = len(approved_keys & {_key(r) for r in staged})
    states: dict[tuple[str, str], str] = {}
    for key, rows in sections.items():
        report.sections += 1
        if all(r.get("model") == TEMPLATE for r in rows):
            report.by_template += 1
        else:
            report.by_model += 1
        found = {str(r.get("review_state")) for r in rows}
        if found == {"approved"}:
            state = "approved"
        elif "withheld" in found:
            state = "withheld"
            report.withheld_rules.update(
                {v["rule_id"] for r in rows for v in (r.get("violations") or [])}
            )
        else:
            state = "staged"
        states[key] = state
        report.approved += state == "approved"
        report.withheld += state == "withheld"
        report.awaiting_owner += state == "staged"
        report.owner_edited += any(r.get("owner_edited") for r in rows)
        report.soft_warnings += any(r.get("warnings") for r in rows)
        # A withheld section is never sent to the reviewer, though its rows hold an empty list.
        flags = [r.get("reviewer_flags") for r in rows if r.get("model") != TEMPLATE]
        if flags and state != "withheld":
            if any(f is None for f in flags):
                report.reviewer_not_run += 1
            elif any(flags):
                report.reviewer_flagged += 1
            else:
                report.reviewer_clean += 1

    last_writer: dict[tuple[str, str], str] = {}
    for call in calls:
        purpose, cache = call.get("purpose"), call.get("cache")
        at = call.get("at")
        if at:
            report.first_call_at = min(filter(None, [report.first_call_at, at]))
            report.last_call_at = max(filter(None, [report.last_call_at, at]))
        if call.get("error"):
            report.api_errors[str(call["error"])] += 1
            report.retry_errors += purpose == "retry"
            continue
        if cache == "hit":
            report.cache_hits += 1
            continue
        if cache == TEMPLATE:
            report.template_runs += 1
            continue
        if purpose == "generate":
            report.first_calls += 1
        elif purpose == "retry":
            report.retries += 1
        elif purpose == "review":
            report.review_calls += 1
        if purpose in ("generate", "retry"):
            last_writer[_key(call)] = str(purpose)
            if call.get("tokens_in") is not None:
                report.tokens_in.append(int(call["tokens_in"]))
            if call.get("tokens_out") is not None:
                report.tokens_out.append(int(call["tokens_out"]))
    for key, purpose in last_writer.items():
        if purpose != "retry":
            continue
        state = states.get(key)
        if state in ("approved", "staged"):
            report.retried_then_passed += 1
        elif state == "withheld":
            report.retried_then_withheld += 1
    return report


def _median(values: Sequence[int]) -> str:
    return str(round(statistics.median(values))) if values else "none"


def render(report: Report) -> str:
    r = report
    rules = ", ".join(f"{rule} {n}" for rule, n in sorted(r.withheld_rules.items())) or "none"
    errors = ", ".join(f"{e} ×{n}" for e, n in sorted(r.api_errors.items())) or "none"
    window = f"{r.first_call_at} to {r.last_call_at}" if r.first_call_at else "no calls logged"
    lines = [
        "| Filing sections | Count |",
        "|---|---|",
        f"| In the summary files | {r.sections} |",
        f"| Written by the model | {r.by_model} |",
        f"| Written by a template (no model call) | {r.by_template} |",
        f"| Approved by the owner | {r.approved} |",
        f"| Approved, with a newer version staged or withheld | {r.approved_with_newer_version} |",
        f"| Approved with an owner edit | {r.owner_edited} |",
        f"| Passed the guard, awaiting the owner | {r.awaiting_owner} |",
        f"| Withheld by the guard | {r.withheld} |",
        f"| Withheld, by rule (a section can fail more than one) | {rules} |",
        f"| With a soft-intensity warning (N9, never blocks) | {r.soft_warnings} |",
        "",
        "| Model reviewer (advisory; model-written sections that passed the guard) | Count |",
        "|---|---|",
        f"| No flags | {r.reviewer_clean} |",
        f"| Flagged something | {r.reviewer_flagged} |",
        f"| Did not run | {r.reviewer_not_run} |",
        "",
        "| Calls | Count |",
        "|---|---|",
        f"| First calls | {r.first_calls} |",
        f"| Retries (first answer failed the guard) | {r.retries} |",
        f"| Retries that ended in an API error | {r.retry_errors} |",
        f"| Sections the retry fixed (last writing call, now passing) | {r.retried_then_passed} |",
        f"| Sections whose last writing call was a failed retry (withheld) | "
        f"{r.retried_then_withheld} |",
        f"| Reviewer calls | {r.review_calls} |",
        f"| Cache hits (no call made) | {r.cache_hits} |",
        f"| Template runs (no call made) | {r.template_runs} |",
        f"| API errors | {errors} |",
        f"| Median tokens in / out per writing call | {_median(r.tokens_in)} / "
        f"{_median(r.tokens_out)} |",
        f"| Total tokens in / out | {sum(r.tokens_in)} / {sum(r.tokens_out)} |",
        "",
        f"Call log window: {window}.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.build.quality", description=__doc__)
    parser.add_argument("--staged", type=Path, default=STAGED_PATH)
    parser.add_argument("--approved", type=Path, default=APPROVED_PATH)
    parser.add_argument("--calls", type=Path, default=CALLS_PATH)
    args = parser.parse_args(argv)
    report = build(read_jsonl(args.staged), read_jsonl(args.approved), read_jsonl(args.calls))
    print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
