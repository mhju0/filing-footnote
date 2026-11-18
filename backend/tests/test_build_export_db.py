"""M8 export against PostgreSQL: the CLI reads a fixture-seeded *_test database."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.build.export import BuildOptions, build_bundle, write_bundle
from tests.build_seed import AS_OF, PINNED_DIRS, fixture_build_input, seed

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL and not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    raise RuntimeError(
        "refusing to drop tables: TEST_DATABASE_URL must name an isolated *_test database"
    )
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is required")

BACKEND = Path(__file__).resolve().parents[1]


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", *args], cwd=BACKEND, capture_output=True, text=True, check=False
    )


def _export(out: Path, *extra: str) -> subprocess.CompletedProcess:
    # A file that does not exist: these tests never read the owner's approved.jsonl.
    extra = (*extra, "--approved", str(out.parent / "no-approved.jsonl"))
    pinned = [arg for d in PINNED_DIRS for arg in ("--pinned", str(d))]
    return _cli("app.build.export", "--as-of", AS_OF.isoformat(), "--out", str(out),
                "--database-url", TEST_DATABASE_URL, "--source-revision", "test", *pinned,
                *extra)  # fmt: skip


def _sha(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith("content_sha256="))


def test_two_database_exports_match_each_other_and_the_offline_build(tmp_path) -> None:
    asyncio.run(seed(TEST_DATABASE_URL))
    a = _export(tmp_path / "a.sqlite", "--allow-unapproved")
    b = _export(tmp_path / "b.sqlite", "--allow-unapproved")
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    assert _sha(a.stdout) == _sha(b.stdout)

    offline = tmp_path / "offline.sqlite"
    report = write_bundle(
        build_bundle(
            fixture_build_input(), BuildOptions(AS_OF, "test", allow_unapproved=True), PINNED_DIRS
        ),
        offline,
    )
    assert _sha(a.stdout) == f"content_sha256={report['build_meta']['content_sha256']}"
    # The database rows went through the adapter: SEC 8-K/A chain and DART linked chain.
    with sqlite3.connect(tmp_path / "a.sqlite") as connection:
        corrected = dict(
            connection.execute("SELECT id, form FROM filings WHERE is_corrected = 1").fetchall()
        )
    assert corrected["sec:0001140361-26-035325"] == "8-K/A"
    assert "dart:20261029800099" in corrected

    pinned = [arg for d in PINNED_DIRS for arg in ("--pinned", str(d))]
    checked = _cli("app.build.verify", str(tmp_path / "a.sqlite"), *pinned)
    assert checked.returncode == 0, checked.stderr
    release = _cli("app.build.verify", str(tmp_path / "a.sqlite"), "--release", *pinned)
    assert release.returncode == 1 and "--allow-unapproved" in release.stderr


def test_database_release_build_is_refused_without_summaries(tmp_path) -> None:
    asyncio.run(seed(TEST_DATABASE_URL))
    result = _export(tmp_path / "footnote.sqlite")
    assert result.returncode == 1
    assert "release build refused" in result.stderr
    assert not any(tmp_path.iterdir())
