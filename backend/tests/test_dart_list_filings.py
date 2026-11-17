"""Tests for DART list.json parsing (filing list -> FilingItem).

All tests here are offline: they drive ``DartClient._parse_list_payload`` with
inline JSON fixtures modeled on measured DART responses, so field cleaning and
status branching (000 / 013 / error) are checked without any network call.

A separate live test (skipped unless DART_API_KEY is set) resolves 삼성전자 and
asserts structural/type invariants only -- no hardcoded rcept_no, which drifts
over time.
"""

import asyncio
import datetime
import logging
import os

import httpx
import pytest

from app.clients.dart import DartApiError, DartClient, FilingItem
from app.config import Settings

logger = logging.getLogger(__name__)

# One 정상(000) response with two rows. report_nm carries trailing space padding
# (as DART sends it) so we can assert .strip() removes it. Fields mirror §2.
_OK_PAYLOAD = {
    "status": "000",
    "message": "정상",
    "page_no": 1,
    "page_count": 10,
    "total_count": 114,
    "total_page": 12,
    "list": [
        {
            "corp_code": "00126380",
            "corp_name": "삼성전자",
            "stock_code": "005930",
            "corp_cls": "Y",
            "report_nm": "지속가능경영보고서등관련사항(자율공시)              ",
            "rcept_no": "20240628800773",
            "flr_nm": "삼성전자",
            "rcept_dt": "20240628",
            "rm": "유",
        },
        {
            "corp_code": "00126380",
            "corp_name": "삼성전자",
            "stock_code": "005930",
            "corp_cls": "Y",
            "report_nm": "사업보고서 (2023.12)",
            "rcept_no": "20240312000736",
            "flr_nm": "삼성전자",
            "rcept_dt": "20240312",
            "rm": "",
        },
    ],
}

_NO_DATA_PAYLOAD = {"status": "013", "message": "조회된 데이타가 없습니다."}
_RATE_LIMIT_PAYLOAD = {"status": "020", "message": "요청 제한을 초과하였습니다."}
_BAD_KEY_PAYLOAD = {"status": "010", "message": "등록되지 않은 키입니다."}


def test_parse_list_payload_ok_cleans_fields() -> None:
    items = DartClient._parse_list_payload(_OK_PAYLOAD)
    assert len(items) == 2
    first = items[0]
    assert isinstance(first, FilingItem)
    # report_nm right-padding stripped (docs §2 [Verified]).
    assert first.report_nm == "지속가능경영보고서등관련사항(자율공시)"
    assert not first.report_nm.endswith(" ")
    # rcept_dt parsed YYYYMMDD -> date.
    assert first.rcept_dt == datetime.date(2024, 6, 28)
    # join keys preserved.
    assert first.rcept_no == "20240628800773"
    assert first.corp_code == "00126380"
    assert first.corp_cls == "Y"
    # viewer_url (filings.url source) derives from rcept_no.
    assert first.viewer_url.endswith("rcpNo=20240628800773")


def test_parse_list_payload_no_data_returns_empty() -> None:
    # status 013 is a valid "nothing in range" answer, not an error.
    assert DartClient._parse_list_payload(_NO_DATA_PAYLOAD) == []


def test_parse_list_payload_rate_limit_raises() -> None:
    with pytest.raises(DartApiError) as exc:
        DartClient._parse_list_payload(_RATE_LIMIT_PAYLOAD)
    assert "020" in str(exc.value)


def test_parse_list_payload_bad_key_raises_without_key_leak() -> None:
    with pytest.raises(DartApiError) as exc:
        DartClient._parse_list_payload(_BAD_KEY_PAYLOAD)
    msg = str(exc.value)
    assert "010" in msg
    # The error surfaces status/message but never the API key value.
    assert "crtfc_key" not in msg


def test_parse_list_payload_bad_date_is_defensive() -> None:
    payload = {
        "status": "000",
        "list": [{"rcept_no": "X", "report_nm": "T", "rcept_dt": "notadate"}],
    }
    items = DartClient._parse_list_payload(payload)
    assert len(items) == 1
    assert items[0].rcept_dt is None  # unparseable date -> None, no raise


def test_parse_list_payload_missing_list_returns_empty() -> None:
    # status 000 but no 'list' array -> defensive empty result.
    assert DartClient._parse_list_payload({"status": "000"}) == []


# -- pblntf_detail_ty and pagination (offline, httpx.MockTransport) ----------------------------

_KEY = "SYNTHETIC_LIST_PAGING_KEY"


def _row(n: int) -> dict:
    return {
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "stock_code": "005930",
        "corp_cls": "Y",
        "report_nm": f"주요사항보고서(자기주식취득결정) {n}",
        "rcept_no": f"2026010100{n:04d}",
        "flr_nm": "삼성전자",
        "rcept_dt": "20260101",
        "rm": "",
    }


def _page(page_no: int, total_page: int, total_count: int, rows: list[dict]) -> dict:
    return {
        "status": "000",
        "message": "정상",
        "page_no": page_no,
        "page_count": 2,
        "total_count": total_count,
        "total_page": total_page,
        "list": rows,
    }


def _run_with_handler(handler, call):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            client = DartClient(Settings(_env_file=None, dart_api_key=_KEY), client=transport)
            return await call(client)

    return asyncio.run(run())


def test_list_filings_sends_detail_code_alone() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=_page(1, 1, 1, [_row(1)]))

    items = _run_with_handler(
        handler,
        lambda c: c.list_filings("00126380", "20260101", "20261231", pblntf_detail_ty="B001"),
    )
    assert len(items) == 1
    assert seen[0]["pblntf_detail_ty"] == "B001"
    assert "pblntf_ty" not in seen[0]


def test_list_filings_refuses_type_and_detail_together() -> None:
    # DART ignores the detail code when the coarse type is present, so a call sending both
    # would silently return the wider list.
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be sent")

    for method in ("list_filings", "list_all_filings"):
        with pytest.raises(ValueError, match="not both"):
            _run_with_handler(
                handler,
                lambda c, m=method: getattr(c, m)(
                    "00126380", "20260101", "20261231", pblntf_ty="B", pblntf_detail_ty="B001"
                ),
            )


def test_list_all_filings_follows_total_page() -> None:
    pages = {
        "1": _page(1, 3, 5, [_row(1), _row(2)]),
        "2": _page(2, 3, 5, [_row(3), _row(4)]),
        "3": _page(3, 3, 5, [_row(5)]),
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.params["page_no"])
        assert request.url.params["pblntf_ty"] == "B"
        return httpx.Response(200, json=pages[request.url.params["page_no"]])

    listing = _run_with_handler(
        handler,
        lambda c: c.list_all_filings("00126380", "20260101", "20261231", pblntf_ty="B", page_count=2),
    )
    assert requested == ["1", "2", "3"]
    assert [i.rcept_no for i in listing.items] == [f"2026010100{n:04d}" for n in range(1, 6)]
    assert (listing.total_count, listing.total_page) == (5, 3)
    assert listing.page_errors == [] and listing.partial is False


def test_list_all_filings_records_failed_page_and_keeps_the_rest(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page_no"]
        if page == "2":
            return httpx.Response(200, json={"status": "020", "message": "요청 제한"})
        if page == "3":
            return httpx.Response(500, text="boom")
        rows = [_row(1), _row(2)]
        return httpx.Response(200, json=_page(1, 3, 5, rows))

    listing = _run_with_handler(
        handler, lambda c: c.list_all_filings("00126380", "20260101", "20261231", page_count=2)
    )
    assert [i.rcept_no for i in listing.items] == ["20260101000001", "20260101000002"]
    assert listing.partial is True
    assert len(listing.page_errors) == 2
    assert "page 2" in listing.page_errors[0] and "020" in listing.page_errors[0]
    assert "page 3" in listing.page_errors[1] and "500" in listing.page_errors[1]
    assert _KEY not in "".join(listing.page_errors)
    assert _KEY not in caplog.text


def test_list_all_filings_flags_a_row_count_that_disagrees_with_total_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_page(1, 1, 4, [_row(1), _row(2)]))

    listing = _run_with_handler(
        handler, lambda c: c.list_all_filings("00126380", "20260101", "20261231")
    )
    assert listing.partial is True
    assert listing.page_errors == ["expected 4 rows, got 2"]


def test_list_all_filings_no_data_is_empty_not_partial() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_NO_DATA_PAYLOAD)

    listing = _run_with_handler(
        handler, lambda c: c.list_all_filings("00126380", "20260101", "20261231")
    )
    assert listing.items == [] and listing.partial is False and listing.page_errors == []


@pytest.mark.skipif(
    not os.environ.get("DART_API_KEY"),
    reason="DART_API_KEY not set; skipping live list.json fetch",
)
def test_list_filings_live_samsung() -> None:
    # Live: resolve 삼성전자 -> corp_code, then list ~1y of 정기공시 (pblntf_ty=A).
    # Structural/type asserts only -- specific rcept_no values change over time.
    async def _run() -> list[FilingItem]:
        client = DartClient(settings=Settings())
        try:
            corp_code = await client.resolve_corp_code("005930")
            assert corp_code == "00126380"
            # bgn_de = one year before end_de; avoid Date.now(): derive from today.
            today = datetime.date.today()
            bgn = today.replace(year=today.year - 1)
            return await client.list_filings(
                corp_code,
                bgn_de=bgn.strftime("%Y%m%d"),
                end_de=today.strftime("%Y%m%d"),
                pblntf_ty="A",
            )
        finally:
            await client.aclose()

    items = asyncio.run(_run())
    assert len(items) >= 1
    for it in items:
        # no leading/trailing whitespace on report_nm.
        assert it.report_nm == it.report_nm.strip()
        assert it.report_nm != ""
        # rcept_dt parsed to a real date.
        assert isinstance(it.rcept_dt, datetime.date)
