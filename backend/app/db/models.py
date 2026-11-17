"""SQLAlchemy 2.0 ORM models (Mapped[] style).

Must stay in exact sync with backend/db/init.sql (DB SCHEMA v0.3).
Schema is applied via init.sql (docker-entrypoint-initdb.d) -- no Alembic.

Notes:
- filing_chunks column is named "meta" because 'metadata' is a reserved
  attribute name on SQLAlchemy Declarative models.
- embedding vector(1024) is [Verified]: KURE-v1 (nlpai-lab/KURE-v1) dense
  dimension (HuggingFace config.json hidden_size=1024).
- filing_chunks.embedding carries an hnsw index over cosine distance
  (vector_cosine_ops), mirroring init.sql (decision D8 resolved).
"""

import datetime
import decimal
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Matches vector(1024) in init.sql. [Verified] -- see module docstring.
EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint("source IN ('dart', 'sec')", name="companies_source_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(Text)
    market: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    dart_corp_code: Mapped[str | None] = mapped_column(Text, unique=True)
    sec_cik: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (Index("idx_filings_company", "company_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    # DART 접수번호: DART filing의 자연키 / financials/document 조인키.
    # SEC filing은 없으므로 nullable. UNIQUE는 ON CONFLICT (rcept_no) 멱등 upsert의
    # inference target; NULL은 서로 distinct라 SEC row끼리는 충돌하지 않는다.
    rcept_no: Mapped[str | None] = mapped_column(Text, unique=True)
    # SEC accession number: SEC filing의 자연키. DART filing은 없으므로 nullable.
    # UNIQUE는 ON CONFLICT (sec_accession_no) 멱등 upsert의 inference target;
    # NULL은 서로 distinct라 DART row끼리는 충돌하지 않는다.
    sec_accession_no: Mapped[str | None] = mapped_column(Text, unique=True)
    filing_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[str | None] = mapped_column(Text)
    filed_at: Mapped[datetime.date | None] = mapped_column(Date)
    url: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class FilingChunk(Base):
    __tablename__ = "filing_chunks"
    __table_args__ = (
        UniqueConstraint(
            "filing_id", "chunk_index", name="filing_chunks_filing_id_chunk_index_key"
        ),
        # Mirrors init.sql: hnsw over cosine (<=>), vector_cosine_ops (D8).
        Index(
            "idx_filing_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("filings.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # [Verified] 1024 dims -- KURE-v1 dense dimension (see module docstring).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    # Named "meta": 'metadata' is reserved on Declarative models.
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Financial(Base):
    __tablename__ = "financials"
    __table_args__ = (
        UniqueConstraint(
            "filing_id",
            "period",
            "metric",
            name="financials_filing_id_period_metric_key",
        ),
        CheckConstraint(
            "period_kind IN ('instant', 'duration')",
            name="financials_period_kind_check",
        ),
        CheckConstraint("scale > 0", name="financials_scale_positive_check"),
        CheckConstraint(
            "period_start IS NULL OR period_end IS NULL OR period_start <= period_end",
            name="financials_period_range_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("filings.id", ondelete="CASCADE"),
        nullable=False,
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(Text, nullable=False)
    period_kind: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'duration'")
    )
    period_start: Mapped[datetime.date | None] = mapped_column(Date)
    period_end: Mapped[datetime.date | None] = mapped_column(Date)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[decimal.Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str | None] = mapped_column(Text)
    scale: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class EventFiling(Base):
    """One DART or SEC event filing in the ingest window (M3/M4 staging); migrations 0002, 0003.

    For source 'sec', rcept_no is 'sec:<accession>', corp_code the 10-digit CIK, stock_code the
    ticker and report_nm the form.
    """

    __tablename__ = "event_filings"
    __table_args__ = (
        CheckConstraint(
            "(category IS NULL) <> (excluded_reason IS NULL)",
            name="event_filings_category_xor_reason_check",
        ),
        CheckConstraint(
            "correction_link IN ('none', 'linked', 'unlinked', 'not_resolved_excluded')",
            name="event_filings_correction_link_check",
        ),
        CheckConstraint("source IN ('dart', 'sec')", name="event_filings_source_check"),
        CheckConstraint(
            "(correction_link = 'none' AND original_rcept_no IS NULL AND NOT is_correction) "
            "OR (correction_link = 'linked' AND original_rcept_no IS NOT NULL "
            "AND is_correction) "
            "OR (correction_link IN ('unlinked', 'not_resolved_excluded') "
            "AND original_rcept_no IS NULL AND is_correction)",
            name="event_filings_link_shape_check",
        ),
        Index("idx_event_filings_corp_filed", "corp_code", text("filed_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    rcept_no: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    corp_code: Mapped[str] = mapped_column(Text, nullable=False)
    stock_code: Mapped[str | None] = mapped_column(Text)
    corp_name: Mapped[str] = mapped_column(Text, nullable=False)
    report_nm: Mapped[str] = mapped_column(Text, nullable=False)
    filed_at: Mapped[datetime.date | None] = mapped_column(Date)
    rm: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    url: Mapped[str | None] = mapped_column(Text)
    # Exactly one of category / excluded_reason is set (classifier contract).
    category: Mapped[str | None] = mapped_column(Text)
    excluded_reason: Mapped[str | None] = mapped_column(Text)
    subsidiary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_correction: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    matched_rule: Mapped[str] = mapped_column(Text, nullable=False)
    basis: Mapped[str | None] = mapped_column(Text)
    # 'none' (an original), 'linked' (original_rcept_no set), 'unlinked' (an in-scope correction
    # whose original could not be determined; correction_note says why), 'not_resolved_excluded'
    # (a correction the classifier excluded; its chain is not resolved).
    correction_link: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'none'")
    )
    original_rcept_no: Mapped[str | None] = mapped_column(Text)
    correction_first_filed_at: Mapped[datetime.date | None] = mapped_column(Date)
    correction_note: Mapped[str | None] = mapped_column(Text)
    # The newest version of a correction chain is the one shown; older versions are kept.
    is_latest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'dart'"))
    # Plain text kept for summaries, cut at a fixed limit; body_truncated says it was cut.
    body_text: Mapped[str | None] = mapped_column(Text)
    body_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class FilingFact(Base):
    """One structured figure/date from an event filing (M3 staging); see migration 0002."""

    __tablename__ = "filing_facts"
    __table_args__ = (
        UniqueConstraint(
            "event_filing_id", "key", name="filing_facts_event_filing_id_key_key"
        ),
        CheckConstraint(
            "kind IN ('amount', 'date', 'count', 'ratio', 'text')",
            name="filing_facts_kind_check",
        ),
        CheckConstraint(
            "(error IS NOT NULL AND value_decimal IS NULL AND value_date IS NULL "
            "AND value_text IS NULL) "
            "OR (error IS NULL AND ("
            "(kind IN ('amount', 'count', 'ratio') AND value_decimal IS NOT NULL "
            "AND value_date IS NULL AND value_text IS NULL) "
            "OR (kind = 'date' AND value_date IS NOT NULL AND value_decimal IS NULL "
            "AND value_text IS NULL) "
            "OR (kind = 'text' AND value_text IS NOT NULL AND value_decimal IS NULL "
            "AND value_date IS NULL)))",
            name="filing_facts_value_shape_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_filings.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)
    source_field: Mapped[str] = mapped_column(Text, nullable=False)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    # Unconstrained numeric: exact decimals, never rounded to a column scale.
    value_decimal: Mapped[decimal.Decimal | None] = mapped_column(Numeric)
    value_date: Mapped[datetime.date | None] = mapped_column(Date)
    value_text: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
