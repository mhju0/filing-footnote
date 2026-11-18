"""The fixture bundle FootnoteKit's Swift tests read (development mode, never shipped).

    cd backend && python -m tests.footnotekit_fixture            # rewrite the committed file
    cd backend && python -m tests.footnotekit_fixture OUT.sqlite

It runs the offline build seed (:func:`tests.build_seed.fixture_build_input`) through the real
exporter, :func:`app.build.export.build_bundle` and :func:`app.build.export.write_bundle`, with
``allow_unapproved``. A few summaries keyed to the current source text, prompt version and word
lists are marked approved so the ``filing_summaries`` table has rows; their lines are fixture
text, not owner-approved summaries. The exporter writes no glossary yet, so two entries are added
before the write. ``tests/test_footnotekit_fixture.py`` fails when this file's schema drifts
from :mod:`app.build.bundle`.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

from app.build import export
from app.build.export import BuildOptions, build_bundle, write_bundle
from app.build.model import (
    BuildInput,
    ChunkRow,
    SummaryRow,
    annual_source_text,
    event_source_text,
    summary_input_sha256,
)
from app.llm.neutrality_guard import load_lexicon
from tests.build_seed import AS_OF, PINNED_DIRS, fixture_build_input

REPO = Path(__file__).resolve().parents[2]
FIXTURE = (
    REPO / "ios" / "FootnoteKit" / "Tests" / "FootnoteKitTests" / "Fixtures" / "footnote.sqlite"
)
SOURCE_REVISION = "footnotekit-fixture"

_CHUNKS = {
    "DART": (ChunkRow(10, "1. 사업의 개요", "사업 본문"),),
    "SEC": (ChunkRow(10, "Item 1. Business", "Business text"),),
}
_LINES = {
    "ko": ("회사는 이 공시를 제출했다고 밝혔어요", "회사는 공시에 세부 내용을 적었어요",
           "회사는 공시 원문에 근거를 남겼다고 밝혔어요"),
    "en": ("The company said it filed this report.",
           "The company said the filing lists the details.",
           "The company said the source filing has the full text."),
}  # fmt: skip
_GLOSSARY = [
    ("operating_margin", "en", "Operating margin", "Operating income as a share of revenue.",
     "Operating income divided by revenue"),
    ("operating_margin", "ko", "영업이익률", "매출 가운데 영업이익이 차지하는 비율이에요.", None),
    ("revenue", "en", "Revenue", "Money the company took in from its business.", None),
    ("revenue", "ko", "매출액", "회사가 사업으로 벌어들인 돈이에요.", "수익(매출액)"),
]  # fmt: skip


def _sourced(data: BuildInput) -> BuildInput:
    annual = tuple(dataclasses.replace(f, chunks=f.chunks + _CHUNKS[f.regulator])
                   for f in data.annual_filings)  # fmt: skip
    return dataclasses.replace(data, annual_filings=annual)


def _approved(data: BuildInput, filing_ids: list[str]) -> tuple[SummaryRow, ...]:
    """Fixture summaries keyed exactly as the exporter checks them, so they are written."""
    events = {f"{e.regulator.lower()}:{e.filing_key}": e for e in data.events}
    annual = {f"{f.regulator.lower()}:{f.filing_key}": f for f in data.annual_filings}
    rows = []
    for fid in filing_ids:
        sections = ("summary",) if fid in events else ("one_line", "business")
        for section in sections:
            if fid in events:
                source = event_source_text(events[fid])
            else:
                source = annual_source_text(annual[fid], section)
            assert source is not None, (fid, section)
            key = summary_input_sha256(source, export.DEFAULT_LLM_MODEL, section,
                                       export.DEFAULT_PROMPT_VERSION, load_lexicon().version)  # fmt: skip
            for lang in ("ko", "en"):
                lines = _LINES[lang] if section == "summary" else (_LINES[lang][0], None, None)
                rows.append(SummaryRow(fid, lang, section, *lines, "approved", key))
    return tuple(rows)


def write_fixture(out: Path) -> dict:
    data = _sourced(fixture_build_input())
    options = BuildOptions(AS_OF, SOURCE_REVISION, allow_unapproved=True)
    first = build_bundle(data, options, PINNED_DIRS)
    filings = first.rows["filings"]
    chosen = [next(r[0] for r in filings if r[2] == kind) for kind in ("annual", "event")]
    bundle = build_bundle(
        dataclasses.replace(data, summaries=_approved(data, chosen)), options, PINNED_DIRS
    )
    bundle.rows["glossary"] = sorted(_GLOSSARY)
    report = write_bundle(bundle, out)
    export.report_path_for(out).unlink(missing_ok=True)  # the report is not part of the fixture
    return report


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURE
    result = write_fixture(target)
    print(target, result["row_counts"], result["file"]["sha256"])
