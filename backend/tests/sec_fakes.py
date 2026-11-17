"""A fake SecClient serving the saved M1 SEC fixtures, for 8-K ingest tests (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.clients.sec import (
    SecCompanyMatch,
    SecDocumentPayload,
    SecFilingItem,
    SecIndexDocument,
    filing_index_url,
    parse_filing_index_html,
    parse_submissions_payload,
)

SEC = Path(__file__).parent / "fixtures" / "events" / "sec"
CLASSIFIER_SEC = Path(__file__).parent / "fixtures" / "events" / "classifier" / "sec"

HTML = "<html><body><p>{}</p></body></html>"


def submissions_payload(ticker: str, accessions: set[str] | None = None) -> dict:
    """The saved M1 rows of ``ticker`` as a column-oriented ``filings.recent`` payload."""
    rows = json.loads((SEC / "submissions_8k" / f"{ticker}.json").read_text())["rows"]
    rows = [r for r in rows if accessions is None or r["accessionNumber"] in accessions]
    columns = (
        "accessionNumber", "filingDate", "reportDate", "form", "items", "primaryDocument",
        "primaryDocDescription",
    )  # fmt: skip
    return {"filings": {"recent": {c: [r[c] for r in rows] for c in columns}, "files": []}}


class FakeSecClient:
    """Lists from the saved submissions rows; indexes and documents from the saved fixtures.

    ``indexes`` maps an accession to extra index rows (document, type), replacing the saved
    index; ``documents`` maps ``(accession, name)`` to bytes, tried before the saved files;
    ``broken`` holds ``(accession, name)`` pairs whose fetch raises. Anything else with no
    fixture raises a connection error. ``calls`` records what was requested.
    """

    def __init__(
        self,
        ticker: str = "AAPL",
        accessions: set[str] | None = None,
        indexes: dict[str, list[tuple[str, str]]] | None = None,
        documents: dict[tuple[str, str], bytes] | None = None,
        broken: set[tuple[str, str]] | None = None,
        list_problems: list[str] | None = None,
        extras: list[SecFilingItem] | None = None,
    ) -> None:
        self.extras = extras or []
        self.list_problems = list_problems or []
        self.ticker = ticker
        self.accessions = accessions
        self.indexes = indexes or {}
        self.documents = documents or {}
        self.broken = broken or set()
        self.calls: list[tuple[str, ...]] = []

    async def search_company(self, query: str) -> list[SecCompanyMatch]:
        return [SecCompanyMatch("0000320193", self.ticker, "Apple Inc.")]

    async def list_filings(self, cik: str, filing_types: list[str] | None = None) -> list[SecFilingItem]:
        self.calls.append(("list", cik))
        listed = parse_submissions_payload(
            submissions_payload(self.ticker, self.accessions), filing_types
        )
        return listed + [e for e in self.extras if filing_types is None or e.form in filing_types]

    async def list_filings_window(
        self, cik: str, filing_types: list[str], since: object
    ) -> tuple[list[SecFilingItem], list[str]]:
        self.calls.append(("window", cik))
        return await self.list_filings(cik, filing_types), list(self.list_problems)

    async def fetch_filing_index(self, cik: str, accession: str) -> list[SecIndexDocument]:
        self.calls.append(("index", accession))
        if accession in self.indexes:
            return [SecIndexDocument(name, doc_type, "") for name, doc_type in self.indexes[accession]]
        path = SEC / "index" / f"{accession}-index.html"
        if not path.exists():
            raise httpx.ConnectError(f"no index fixture for {accession}")
        return parse_filing_index_html(path.read_text())

    async def fetch_document(self, cik: str, accession: str, name: str) -> SecDocumentPayload:
        self.calls.append(("document", accession, name))
        url = filing_index_url(cik, accession).replace("-index.html", f"/{name}")
        if (accession, name) in self.broken:
            raise httpx.ConnectError(f"{name} unavailable")
        if (accession, name) in self.documents:
            raw = self.documents[(accession, name)]
        else:
            path = SEC / "documents" / f"{accession}_{name}"
            if not path.exists():
                raise httpx.ConnectError(f"no document fixture {accession}/{name}")
            raw = path.read_bytes()
        return SecDocumentPayload(cik, accession, name, url, raw)
