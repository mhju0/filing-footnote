"""Quality report: counts per filing section from the staged, approved and call files."""

from __future__ import annotations

import json

from app.build import quality


def _row(fid, lang, state, model="m", violations=(), warnings=(), flags=(), edited=False):
    row = {
        "filing_id": fid, "section": "summary", "lang": lang, "review_state": state,
        "model": model, "violations": [{"rule_id": r} for r in violations],
        "warnings": [{"rule_id": w} for w in warnings],
        "reviewer_flags": None if flags is None else list(flags),
    }  # fmt: skip
    if edited:
        row["owner_edited"] = True
    return row


def _call(fid, purpose, cache="miss", error=None, tin=None, tout=None, at="2026-11-18T00:00:00"):
    call = {"filing_id": fid, "section": "summary", "purpose": purpose, "cache": cache,
            "tokens_in": tin, "tokens_out": tout, "at": at}  # fmt: skip
    if error:
        call["error"] = error
    return call


STAGED = [
    _row("a", "ko", "staged"), _row("a", "en", "staged"),
    _row("b", "ko", "withheld", violations=["N1", "N1"]),
    _row("b", "en", "withheld", violations=["N1", "N6"]),
    _row("c", "ko", "staged", model="template", flags=None),
    _row("c", "en", "staged", model="template", flags=None),
    # Also approved below: the approved rows win.
    _row("d", "ko", "staged"), _row("d", "en", "staged"),
]  # fmt: skip
APPROVED = [
    _row("d", "ko", "approved", warnings=["N9"], flags=["unsupported"], edited=True),
    _row("d", "en", "approved"),
]  # fmt: skip
CALLS = [
    _call("a", "generate", tin=100, tout=10, at="2026-11-17T00:00:00"),
    _call("b", "generate", tin=300, tout=30),
    _call("b", "retry", tin=400, tout=40),
    _call("d", "generate", tin=200, tout=20),
    _call("d", "retry", tin=500, tout=50),
    _call("d", "review", tin=50, tout=5),
    _call("a", "generate", cache="hit"),
    _call("c", "generate", cache="template"),
    _call("a", "generate", error="LLMApiError 429", at="2026-11-19T00:00:00"),
]  # fmt: skip


def test_sections_are_counted_once_with_approved_rows_winning():
    r = quality.build(STAGED, APPROVED, CALLS)
    assert (r.sections, r.by_model, r.by_template) == (4, 3, 1)
    assert (r.approved, r.awaiting_owner, r.withheld) == (1, 2, 1)
    assert r.owner_edited == 1
    assert r.soft_warnings == 1


def test_a_withheld_rule_counts_once_per_section():
    assert quality.build(STAGED, APPROVED, CALLS).withheld_rules == {"N1": 1, "N6": 1}


def test_reviewer_results_skip_template_and_withheld_sections():
    r = quality.build(STAGED, APPROVED, CALLS)
    assert (r.reviewer_clean, r.reviewer_flagged, r.reviewer_not_run) == (1, 1, 0)


def test_calls_by_purpose_and_retry_outcomes():
    r = quality.build(STAGED, APPROVED, CALLS)
    assert (r.first_calls, r.retries, r.review_calls) == (3, 2, 1)
    assert (r.cache_hits, r.template_runs) == (1, 1)
    assert (r.retried_then_passed, r.retried_then_withheld) == (1, 1)
    assert r.api_errors == {"LLMApiError 429": 1}
    assert r.tokens_in == [100, 300, 400, 200, 500]
    assert (r.first_call_at, r.last_call_at) == ("2026-11-17T00:00:00", "2026-11-19T00:00:00")


def test_render_and_cli_read_the_files(tmp_path, capsys):
    paths = {}
    for name, rows in (("staged", STAGED), ("approved", APPROVED), ("calls", CALLS)):
        paths[name] = tmp_path / f"{name}.jsonl"
        paths[name].write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    argv = [f"--{k}={v}" for k, v in paths.items()]
    assert quality.main(argv) == 0
    out = capsys.readouterr().out
    assert "| Withheld, by rule (a section can fail more than one) | N1 1, N6 1 |" in out
    assert "| Median tokens in / out per writing call | 300 / 30 |" in out
    assert "| Total tokens in / out | 1500 / 150 |" in out


def test_empty_files_render():
    out = quality.render(quality.build([], [], []))
    assert "| In the summary files | 0 |" in out
    assert "no calls logged" in out
