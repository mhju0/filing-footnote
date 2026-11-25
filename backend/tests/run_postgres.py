"""Run database tests on a fresh disposable database, never the local corpus.

Uses DATABASE_URL's server/role by default. Set TEST_DATABASE_ADMIN_URL when
the application role cannot create databases (for example, postgresql:///postgres
with a local Homebrew superuser). Each run owns a unique *_test database.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.config import get_settings

BACKEND = Path(__file__).resolve().parents[1]


def main() -> None:
    admin_url = make_url(
        os.environ.get("TEST_DATABASE_ADMIN_URL") or get_settings().database_url
    ).set(drivername="postgresql")
    database = f"filing_footnote_{uuid.uuid4().hex}_test"
    test_url = admin_url.set(database=database)
    with psycopg.connect(
        admin_url.render_as_string(hide_password=False), autocommit=True
    ) as admin:
        # Keep creation outside the try: never drop a database we did not create.
        try:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        except psycopg.errors.InsufficientPrivilege:
            raise SystemExit(
                "Database tests need a role with CREATEDB. Set TEST_DATABASE_ADMIN_URL "
                "to a test PostgreSQL server with pgvector installed."
            ) from None
        try:
            print(f"Database tests: {database} (removed on exit)", flush=True)
            with psycopg.connect(
                test_url.render_as_string(hide_password=False), autocommit=True
            ) as connection:
                connection.execute((BACKEND / "db/init.sql").read_text())

            environment = os.environ.copy()
            environment.pop("DART_API_KEY", None)
            environment.update(
                DATABASE_URL=test_url.set(drivername="postgresql+psycopg").render_as_string(
                    hide_password=False
                ),
            )
            environment["TEST_DATABASE_URL"] = environment["DATABASE_URL"]
            # Each suite sets up its own rows on the actual SQL schema with
            # real transactions.
            for suite in (
                "test_normalized_filing_persistence.py",
                "test_event_ingest_db.py",
                "test_legacy_migration.py",
                "test_event_migration.py",
                "test_build_export_db.py",
                "test_build_summaries_db.py",
            ):
                subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", f"tests/{suite}"],
                    cwd=BACKEND,
                    env=environment,
                    check=True,
                )
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
