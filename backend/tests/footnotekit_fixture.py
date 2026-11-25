"""The fixture bundle FootnoteKit's Swift tests read (development mode, never shipped).

    cd backend && python -m tests.footnotekit_fixture            # rewrite the committed file
    cd backend && python -m tests.footnotekit_fixture OUT.sqlite

It runs the offline build seed (:func:`tests.build_seed.fixture_build_input`) through the real
exporter, :func:`app.build.export.build_bundle` and :func:`app.build.export.write_bundle`, with
``allow_unapproved``. A few summaries keyed to the current source text, prompt version and word
lists are marked approved so the ``filing_summaries`` table has rows; their lines are fixture
text, not owner-approved summaries. The exporter writes no glossary yet, so two entries are added
before the write. Source sentences (D100) come from made-up faithfulness records that cover each
kind of ``summary_sources`` row: the event summary's first line has one sentence, its second two
(partly supported), its third none; the annual one line has one sentence and the business line
is a template line without an excerpt. ``tests/test_footnotekit_fixture.py`` fails when this file's schema drifts
from :mod:`app.build.bundle`.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

from app.build import export, faithfulness
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


# Made-up source sentences by (section, line): (verdict, [(start, text), ...]).
_SPANS = {
    ("summary", 1): ("supported", [(40, "이사회는 자기주식 취득을 결의하였습니다.")]),
    ("summary", 2): ("partly", [(120, "취득 목적 : 임직원 주식보상"),
                                (180, "취득 방법은 유가증권시장을 통한 장내 매수로 합니다.")]),
    ("one_line", 1): ("supported", [(10, "당사는 전자 부품을 만들어 판매하고 있습니다.")]),
    ("business", 1): ("template", []),
}  # fmt: skip


def _records(summaries: tuple[SummaryRow, ...]) -> faithfulness.RecordIndex:
    records = []
    for row in summaries:
        lines = (row.line1, row.line2, row.line3)
        for number, line in enumerate(lines, start=1):
            if line is None or (row.section, number) not in _SPANS:
                continue
            verdict, spans = _SPANS[(row.section, number)]
            records.append({
                "filing_id": row.filing_id, "lang": row.lang, "section": row.section,
                "line_no": number, "line_sha256": faithfulness.line_sha256(line),
                "input_sha256": row.input_sha256, "verdict": verdict,
                "aligner_version": faithfulness.ALIGNER_VERSION,
                "spans": [{"start": a, "end": a + len(t), "text": t} for a, t in spans],
            })  # fmt: skip
    return faithfulness.RecordIndex(records)


def write_fixture(out: Path) -> dict:
    data = _sourced(fixture_build_input())
    options = BuildOptions(AS_OF, SOURCE_REVISION, allow_unapproved=True)
    first = build_bundle(data, options, PINNED_DIRS)
    filings = first.rows["filings"]
    chosen = [next(r[0] for r in filings if r[2] == kind) for kind in ("annual", "event")]
    summaries = _approved(data, chosen)
    bundle = build_bundle(
        dataclasses.replace(data, summaries=summaries), options, PINNED_DIRS, _records(summaries)
    )
    bundle.rows["glossary"] = sorted(_GLOSSARY)
    report = write_bundle(bundle, out)
    export.report_path_for(out).unlink(missing_ok=True)  # the report is not part of the fixture
    return report


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURE
    result = write_fixture(target)
    print(target, result["row_counts"], result["file"]["sha256"])
