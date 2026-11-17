"""M6 summaries against PostgreSQL: ``generate --dry-run`` reads a seeded *_test database."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.clients.sec_document import extract_10k_prose
from app.ingest.chunking import chunk_document
from tests.build_seed import AS_OF, seed
from tests.test_sec_document import _build_10k_html

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL and not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    raise RuntimeError(
        "refusing to drop tables: TEST_DATABASE_URL must name an isolated *_test database"
    )
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is required")

BACKEND = Path(__file__).resolve().parents[1]
SEC_ANNUAL = "sec:0000320193-25-000079"
RISK_TITLE = "Item 1A. Risk Factors"


async def _seed_10k_chunks(url: str, *, with_risks: bool) -> None:
    """The M8 seed, with Apple's 10-K chunks replaced by what the SEC extractor and chunker
    make of a 10-K document: Item 1, Item 7 and, unless left out as ingest does for a
    missing or short Item 1A, Item 1A."""
    await seed(url)
    chunks = [c for c in chunk_document(extract_10k_prose(_build_10k_html()))
              if with_risks or c.section_title != RISK_TITLE]  # fmt: skip
    assert (RISK_TITLE in {c.section_title for c in chunks}) is with_risks
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            filing_id = (await connection.execute(
                text("SELECT id FROM filings WHERE sec_accession_no = '0000320193-25-000079'")
            )).scalar_one()  # fmt: skip
            await connection.execute(
                text("DELETE FROM filing_chunks WHERE filing_id = :f"), {"f": filing_id}
            )
            for index, chunk in enumerate(chunks):
                meta = {"section_title": chunk.section_title,
                        "section_order": chunk.section_order, "part_index": chunk.part_index}  # fmt: skip
                await connection.execute(
                    text("INSERT INTO filing_chunks (filing_id, chunk_index, content, meta)"
                         " VALUES (:f, :i, :c, CAST(:m AS jsonb))"),
                    {"f": filing_id, "i": index, "c": chunk.content, "m": json.dumps(meta)},
                )  # fmt: skip
    finally:
        await engine.dispose()


def _dry_run(tmp_path) -> tuple[list[list[str]], list[list[str]]]:
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "app.build.summaries", "generate", "--dry-run",
         "--as-of", AS_OF.isoformat(), "--database-url", TEST_DATABASE_URL,
         "--max-calls", "1000",
         "--staged", str(out / "staged.jsonl"), "--approved", str(out / "approved.jsonl"),
         "--calls-log", str(out / "calls.jsonl")],
        cwd=BACKEND, capture_output=True, text=True, check=False,
        env={**os.environ, "LLM_API_KEY": ""},
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith("model: ") and "prompt_version: m6-" in lines[0]
    assert lines[-1].startswith("dry run: would generate ") and lines[-1].endswith("calls 0")
    assert not out.exists()
    planned = [line.split()[2:4] for line in lines if line.startswith("would generate ")]
    skipped = [line.split()[1:] for line in lines if line.startswith("no_source_text ")]
    return planned, skipped


def test_dry_run_plans_sec_sections_from_10k_chunks_with_item_1a(tmp_path) -> None:
    asyncio.run(_seed_10k_chunks(TEST_DATABASE_URL, with_risks=True))
    planned, skipped = _dry_run(tmp_path)
    for section in ("one_line", "business", "changes", "risks"):
        assert [SEC_ANNUAL, section] in planned
    assert not any(fid == SEC_ANNUAL for fid, _ in skipped)
    # Event filings with a stored body are planned: Apple's 8-Ks and the DART filing whose
    # document the seed's ingest fetched.
    assert any(fid.startswith("sec:") and s == "summary" for fid, s in planned)
    assert any(fid.startswith("dart:") and s == "summary" for fid, s in planned)
    # The seeded DART report has no risk heading, so it has no risks section at all.
    assert not any(s == "risks" and f.startswith("dart:") for f, s in planned + skipped)


def test_dry_run_has_no_sec_risks_when_ingest_left_item_1a_out(tmp_path) -> None:
    asyncio.run(_seed_10k_chunks(TEST_DATABASE_URL, with_risks=False))
    planned, skipped = _dry_run(tmp_path)
    for section in ("one_line", "business", "changes"):
        assert [SEC_ANNUAL, section] in planned
    assert not any(f == SEC_ANNUAL and s == "risks" for f, s in planned + skipped)
