"""Plain text of an 8-K and its EX-99.* exhibits, for classification and summaries.

The filing index (``-index.html``) names each exhibit's type; the primary document comes from
``filings.recent.primaryDocument``. HTML is reduced with ``_html_to_text``, which drops tables,
so figures in tables never reach the text. PDF and image exhibits are not read: they are listed
in ``Sec8KDocuments.skipped`` so the run summary can say so.

Classification reads the full text. Text kept for storage and summaries is cut at
``TEXT_STORE_LIMIT`` characters and the cut is reported.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

import httpx

from app.clients.sec import SecApiError, SecClient, SecFilingItem
from app.clients.sec_document import _decode_html_bytes, _html_to_text

# Longest stored/summarised text per filing. Long earnings releases are cut here; the full
# text is still what ``classify_sec`` sees.
TEXT_STORE_LIMIT = 20_000

_TEXT_SUFFIXES = (".htm", ".html", ".txt")
_FETCH_ERRORS = (SecApiError, httpx.HTTPError, ValueError)


@dataclass
class Sec8KDocuments:
    # (document type, full plain text): the primary document first, typed by its form
    # (``8-K`` / ``8-K/A``), then EX-99.* exhibits typed as the index names them.
    texts: list[tuple[str, str]] = field(default_factory=list)
    # EX-99.* documents that are not text (PDF, images), as "EX-99.1 name.pdf".
    skipped: list[str] = field(default_factory=list)
    # Documents that should have been read and could not be, with the reason.
    failed: list[str] = field(default_factory=list)


_SGML_HEAD_RE = re.compile(r"^\s*<DOCUMENT>.*?<TEXT>\s*", re.S)


def strip_sgml_header(html: str) -> str:
    """Drop the leading ``<DOCUMENT><TYPE>...<TEXT>`` wrapper EDGAR puts on some exhibits."""
    return _SGML_HEAD_RE.sub("", html, count=1)


def plain_text(raw: bytes, name: str) -> str:
    """Visible text of one fetched document; ``.txt`` is taken as is."""
    decoded = _decode_html_bytes(raw)
    if name.lower().endswith(".txt"):
        return "\n".join(line.strip() for line in decoded.splitlines() if line.strip())
    return _html_to_text(strip_sgml_header(decoded))


def store_text(
    texts: list[tuple[str, str]], limit: int = TEXT_STORE_LIMIT
) -> tuple[str, bool]:
    """The text kept for storage and summaries and whether it was cut at ``limit`` characters."""
    joined = "\n\n".join(f"[{doc_type}]\n{text}" for doc_type, text in texts if text)
    if len(joined) <= limit:
        return joined, False
    return joined[:limit], True


async def read_8k(client: SecClient, cik: str, filing: SecFilingItem) -> Sec8KDocuments:
    """Fetch the filing index, the primary document and its text EX-99.* exhibits."""
    result = Sec8KDocuments()
    accession = filing.accession_number
    exhibits: list[tuple[str, str]] = []
    try:
        for doc in await client.fetch_filing_index(cik, accession):
            if doc.doc_type.upper().startswith("EX-99") and doc.document != filing.primary_document:
                exhibits.append((doc.doc_type, doc.document))
    except _FETCH_ERRORS as exc:
        result.failed.append(f"{accession} index: {exc}")

    documents = [(filing.form, filing.primary_document)] if filing.primary_document else []
    if not documents:
        result.failed.append(f"{accession} primary: no primary document listed")
    documents.extend(exhibits)
    for doc_type, name in documents:
        if posixpath.splitext(name)[1].lower() not in _TEXT_SUFFIXES:
            result.skipped.append(f"{doc_type} {name}")
            continue
        try:
            payload = await client.fetch_document(cik, accession, name)
        except _FETCH_ERRORS as exc:
            result.failed.append(f"{accession} {doc_type} {name}: {exc}")
            continue
        result.texts.append((doc_type, plain_text(payload.raw_bytes, name)))
    return result
