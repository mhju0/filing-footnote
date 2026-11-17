"""A fake DartClient serving the saved M1/M3 fixtures, for event-ingest tests (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.clients.dart import DartApiError, DocumentPayload, FilingListing, _filing_item_from_row

DART = Path(__file__).parent / "fixtures" / "events" / "dart"
CLASSIFIER_DOCUMENTS = Path(__file__).parent / "fixtures" / "events" / "classifier" / "dart" / "document"


BLANK_BODY = "<html><body><p>본문 없음</p></body></html>".encode()


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeDartClient:
    """Lists from ``dart/list/<stock>_<B|I>.json``, structured rows from ``dart/structured``.

    ``documents`` maps a 접수번호 to a fixture path, then the saved M2 classifier bodies are
    tried; any other document is a blank body, or raises with ``missing='fail'``. Documents in
    ``broken`` raise the given exception. ``calls`` records what was requested.
    """

    def __init__(
        self,
        stock_code: str,
        documents: dict[str, Path] | None = None,
        list_errors: dict[str, list[str]] | None = None,
        use_classifier_documents: bool = True,
        missing: str = "blank",
        broken: dict[str, Exception] | None = None,
    ) -> None:
        self.use_classifier_documents = use_classifier_documents
        self.missing = missing  # 'blank': a body with no correction target; 'fail': status 014
        self.broken = broken or {}  # 접수번호 -> exception fetch_document raises
        self.stock_code = stock_code
        self.documents = documents or {}
        self.list_errors = list_errors or {}
        self.calls: list[tuple[str, str]] = []

    async def resolve_corp_code(self, ticker: str) -> str | None:
        return "00266961" if ticker == self.stock_code else None

    async def list_all_filings(
        self,
        corp_code: str,
        bgn_de: str,
        end_de: str,
        pblntf_ty: str | None = None,
        pblntf_detail_ty: str | None = None,
    ) -> FilingListing:
        self.calls.append(("list", str(pblntf_ty)))
        payload = json.loads((DART / "list" / f"{self.stock_code}_{pblntf_ty}.json").read_text())
        items = [_filing_item_from_row(r) for r in payload["list"]]
        errors = self.list_errors.get(str(pblntf_ty), [])
        return FilingListing(items, len(items), 1, errors, bool(errors))

    async def fetch_document(self, rcept_no: str) -> DocumentPayload:
        self.calls.append(("document", rcept_no))
        path = self.documents.get(rcept_no)
        if path is None and self.use_classifier_documents:
            saved = CLASSIFIER_DOCUMENTS / f"{rcept_no}.xml"
            path = saved if saved.exists() else None
        if rcept_no in self.broken:
            raise self.broken[rcept_no]
        if path is None and self.missing == "blank":
            return DocumentPayload(rcept_no, "blank.xml", BLANK_BODY, ("blank.xml",))
        if path is None:
            raise DartApiError("document.xml returned status 014")
        return DocumentPayload(rcept_no, path.name, path.read_bytes(), (path.name,))

    def _api_key(self) -> str:
        return "FAKE_KEY"

    async def _get(self, endpoint: str, params: dict[str, Any]) -> _Response:
        self.calls.append(("structured", endpoint))
        assert "crtfc_key" in params
        name = endpoint.removesuffix(".json")
        path = DART / "structured" / f"{name}_{self.stock_code}.json"
        if not path.exists():
            return _Response({"status": "013", "message": "조회된 데이타가 없습니다."})
        return _Response(json.loads(path.read_text()))

    async def aclose(self) -> None:
        return None
