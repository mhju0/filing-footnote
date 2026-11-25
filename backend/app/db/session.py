"""Lazy SQLAlchemy async engine/session factories.

IMPORTANT: importing this module must NOT connect to the database. Engines are
created on first get_*_engine() call only (and SQLAlchemy itself connects lazily
on first use). Tests import app code without any DB running.

The ``postgresql+psycopg://`` URL drives psycopg3's async dialect. The async
stack is shared by ingestion and the build.
"""

import logging
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_async_engine() -> AsyncEngine:
    """Create (once) and return the async SQLAlchemy engine.

    The ``postgresql+psycopg://`` URL uses psycopg3's async dialect here. No
    connection is opened until first use.
    Requires the ``greenlet`` runtime (declared in requirements.txt).
    """
    settings = get_settings()
    logger.info("creating async SQLAlchemy engine (lazy connect)")
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a cached async_sessionmaker bound to the lazy async engine.

    ``expire_on_commit=False`` so values read before a commit stay usable after
    it without an implicit (and, on an AsyncSession, illegal) lazy reload.
    """
    return async_sessionmaker(bind=get_async_engine(), expire_on_commit=False)


def get_async_session() -> AsyncSession:
    """Create a new AsyncSession. Caller is responsible for closing it.

    Intended to be used as an async context manager, e.g.:

        result = await ingest_filing(adapter, get_async_session)
    """
    return get_async_session_factory()()
