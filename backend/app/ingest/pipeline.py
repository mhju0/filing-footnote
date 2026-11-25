"""Shared persistence lifecycle for regulatory filing adapters."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.filings.model import NormalizedFiling
from app.filings.persistence import persist_normalized_filing

logger = logging.getLogger(__name__)


class RegulatoryFilingAdapter(Protocol):
    """Fetch and normalize one complete Corporate Filing snapshot."""

    async def fetch(self) -> NormalizedFiling: ...


@dataclass(frozen=True)
class IngestResult:
    """Identity and work completed by one persisted snapshot."""

    company_id: uuid.UUID
    filing_id: uuid.UUID
    source_filing_id: str
    financials_written: int
    chunks_written: int


async def ingest_filing(
    adapter: RegulatoryFilingAdapter,
    session_factory: Callable[[], AsyncSession],
) -> IngestResult:
    """Fetch, then atomically persist, one Normalized Filing."""
    normalized = await adapter.fetch()

    async with session_factory() as session:
        persisted = await persist_normalized_filing(session, normalized)

    result = IngestResult(
        company_id=persisted.company_id,
        filing_id=persisted.filing_id,
        source_filing_id=normalized.identity.source_filing_id,
        financials_written=persisted.financial_facts_written,
        chunks_written=persisted.filing_chunks_written,
    )
    logger.info(
        "ingested source_filing_id=%s -> company=%s filing=%s financials=%d chunks=%d",
        result.source_filing_id,
        result.company_id,
        result.filing_id,
        result.financials_written,
        result.chunks_written,
    )
    return result
