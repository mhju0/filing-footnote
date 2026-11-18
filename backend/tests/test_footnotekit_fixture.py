"""The committed FootnoteKit fixture bundle keeps the exporter's current schema.

When this fails after a change to ``app/build/bundle.py``, rewrite the fixture with
``python -m tests.footnotekit_fixture`` and run ``swift test --package-path ios/FootnoteKit``.
"""

from __future__ import annotations

import sqlite3

from app.build.bundle import SCHEMA, SCHEMA_VERSION, TABLES, content_sha256
from tests.footnotekit_fixture import FIXTURE, write_fixture


def _schema(connection: sqlite3.Connection) -> list[tuple]:
    return connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
    ).fetchall()


def _expected_schema() -> list[tuple]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(SCHEMA)
        return _schema(connection)
    finally:
        connection.close()


def _open(path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def test_committed_fixture_has_the_current_schema() -> None:
    with _open(FIXTURE) as connection:
        assert _schema(connection) == _expected_schema()
        meta = connection.execute(
            "SELECT schema_version, allow_unapproved, content_sha256 FROM build_meta"
        ).fetchall()
        assert len(meta) == 1
        schema_version, allow_unapproved, fingerprint = meta[0]
        assert schema_version == SCHEMA_VERSION
        assert allow_unapproved == 1  # a development bundle, never shipped
        assert fingerprint == content_sha256(connection)


def test_committed_fixture_has_rows_in_every_table() -> None:
    with _open(FIXTURE) as connection:
        for table in [*TABLES, "build_meta"]:
            count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count > 0, table


def test_generator_writes_the_same_schema(tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    write_fixture(out)
    with _open(out) as connection:
        assert _schema(connection) == _expected_schema()
    assert not (tmp_path / "footnote.report.json").exists()
