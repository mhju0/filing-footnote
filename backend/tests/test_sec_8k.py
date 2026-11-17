"""8-K text extraction, exhibit selection and the SEC request limiter, offline."""

from __future__ import annotations

import asyncio
import gzip
import json
import random

import httpx
import pytest

from app.clients.rate_limit import RequestLimiter, rate_limited_client
from app.clients.sec import SecFilingItem
from app.clients.sec_8k import TEXT_STORE_LIMIT, plain_text, read_8k, store_text, strip_sgml_header
from app.filings.categories import classify_sec, normalise_text
from tests.sec_fakes import CLASSIFIER_SEC, HTML, FakeSecClient

CIK = "0000320193"
APPLE_EARNINGS = "0000320193-26-000024"  # 2.02, 9.01: 8-K plus EX-99.1


def filing(accession: str, form: str = "8-K", items: str = "2.02,9.01", primary: str = "p.htm"):
    return SecFilingItem(accession, form, None, None, primary, items=items)


def run(coro):
    return asyncio.run(coro)


# -- reading a filing ----------------------------------------------------------------------------


def test_earnings_release_is_read_from_primary_and_ex99_and_classifies_as_earnings() -> None:
    client = FakeSecClient()
    docs = run(read_8k(client, CIK, filing(APPLE_EARNINGS, primary="aapl-20261102.htm")))
    assert [t for t, _ in docs.texts] == ["8-K", "EX-99.1"]
    assert docs.skipped == [] and docs.failed == []
    # The index's GRAPHIC row is not an exhibit and is never fetched.
    assert [c[2] for c in client.calls if c[0] == "document"] == [
        "aapl-20261102.htm",
        "a8-kex991q4202609262026.htm",
    ]
    result = classify_sec("8-K", "2.02,9.01", docs.texts)
    assert (result.category, result.matched_rule) == ("earnings", "sec.2.02.results")


def test_html_text_matches_the_classifier_fixture_texts() -> None:
    # The M2 golden texts and this module's HTML reduction give the same classification.
    stored = json.loads(gzip.open(CLASSIFIER_SEC / f"{APPLE_EARNINGS}.json.gz").read())
    golden = classify_sec(stored["form"], stored["items"], [(d["type"], d["text"]) for d in stored["documents"]])
    docs = run(read_8k(FakeSecClient(), CIK, filing(APPLE_EARNINGS, primary="aapl-20261102.htm")))
    assert classify_sec("8-K", "2.02,9.01", docs.texts) == golden


def test_tables_are_removed_so_no_table_figures_reach_the_text() -> None:
    html = HTML.format("Revenue was up.") + "<table><tr><td>Net sales</td><td>$4,000</td></tr></table>"
    text = plain_text(html.encode(), "x.htm")
    assert "Revenue was up." in text
    assert "4,000" not in text and "Net sales" not in text


def test_pdf_and_image_exhibits_are_skipped_and_recorded_not_failed() -> None:
    accession = "0000000000-26-000001"
    client = FakeSecClient(
        indexes={
            accession: [("p.htm", "8-K"), ("a.htm", "EX-99.1"), ("b.pdf", "EX-99.2"),
                        ("c.jpg", "EX-99.3"), ("d.htm", "EX-10.1"), ("e.jpg", "GRAPHIC")]
        },  # fmt: skip
        documents={
            (accession, "p.htm"): HTML.format("primary").encode(),
            (accession, "a.htm"): HTML.format("release").encode(),
        },
    )
    docs = run(read_8k(client, CIK, filing(accession)))
    assert docs.texts == [("8-K", "primary"), ("EX-99.1", "release")]
    assert docs.skipped == ["EX-99.2 b.pdf", "EX-99.3 c.jpg"]
    assert docs.failed == []
    assert not any(c[0] == "document" and c[2] in {"b.pdf", "c.jpg", "d.htm"} for c in client.calls)


def test_a_failed_exhibit_is_reported_and_the_other_documents_are_kept() -> None:
    accession = "0000000000-26-000002"
    client = FakeSecClient(
        indexes={accession: [("p.htm", "8-K"), ("a.htm", "EX-99.1")]},
        documents={(accession, "p.htm"): HTML.format("primary").encode()},
        broken={(accession, "a.htm")},
    )
    docs = run(read_8k(client, CIK, filing(accession)))
    assert docs.texts == [("8-K", "primary")]
    assert len(docs.failed) == 1 and docs.failed[0].startswith(f"{accession} EX-99.1 a.htm: ")


def test_a_failed_index_is_reported_and_the_primary_document_is_still_read() -> None:
    accession = "0000000000-26-000003"
    client = FakeSecClient(documents={(accession, "p.htm"): HTML.format("primary").encode()})
    docs = run(read_8k(client, CIK, filing(accession)))
    assert docs.texts == [("8-K", "primary")]
    assert len(docs.failed) == 1 and docs.failed[0].startswith(f"{accession} index: ")


def test_http_errors_from_the_fetch_are_caught() -> None:
    class Failing(FakeSecClient):
        async def fetch_document(self, cik, accession, name):
            raise httpx.HTTPStatusError(
                "503", request=httpx.Request("GET", "https://x"), response=httpx.Response(503)
            )

    accession = "0000000000-26-000004"
    docs = run(read_8k(Failing(indexes={accession: [("p.htm", "8-K")]}), CIK, filing(accession)))
    assert docs.texts == [] and len(docs.failed) == 1


def test_the_primary_document_is_not_read_twice_when_the_index_lists_it_as_an_exhibit() -> None:
    accession = "0000000000-26-000005"
    client = FakeSecClient(
        indexes={accession: [("p.htm", "8-K"), ("p.htm", "EX-99.1")]},
        documents={(accession, "p.htm"): HTML.format("primary").encode()},
    )
    docs = run(read_8k(client, CIK, filing(accession)))
    assert [t for t, _ in docs.texts] == ["8-K"]


# -- stored text ---------------------------------------------------------------------------------


def test_text_under_the_limit_is_kept_whole() -> None:
    text, cut = store_text([("8-K", "short"), ("EX-99.1", "release")])
    assert text == "[8-K]\nshort\n\n[EX-99.1]\nrelease" and cut is False


def test_long_text_is_cut_at_the_constant_and_flagged_but_classification_sees_all() -> None:
    tail = "net sales"
    release = "x " * TEXT_STORE_LIMIT + tail  # the results phrase sits past the cut
    texts = [("8-K", "Item 2.02"), ("EX-99.1", release)]
    text, cut = store_text(texts)
    assert cut is True and len(text) == TEXT_STORE_LIMIT
    assert tail not in text
    assert classify_sec("8-K", "2.02", texts).category == "earnings"
    assert store_text(texts, limit=10**9)[1] is False


def _joined_of(length: int) -> list[tuple[str, str]]:
    """One document whose stored text is exactly ``length`` characters with its ``[8-K]`` header."""
    return [("8-K", "a" * (length - len("[8-K]\n")))]


def test_text_of_exactly_the_limit_is_kept_whole_and_not_flagged() -> None:
    text, cut = store_text(_joined_of(TEXT_STORE_LIMIT))
    assert len(text) == TEXT_STORE_LIMIT and cut is False
    assert text.endswith("a")


def test_text_one_character_over_the_limit_is_cut_to_the_limit_and_flagged() -> None:
    texts = _joined_of(TEXT_STORE_LIMIT + 1)
    text, cut = store_text(texts)
    assert cut is True and len(text) == TEXT_STORE_LIMIT
    assert text == "[8-K]\n" + "a" * (TEXT_STORE_LIMIT - len("[8-K]\n"))  # the last character is gone


# -- request limiter -----------------------------------------------------------------------------


class FakeClock:
    """A clock only ``sleep`` advances; ``idle`` stands in for the caller doing other work."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        assert seconds > 0
        wake = self.now + seconds
        await asyncio.sleep(0)  # yield, so concurrent callers interleave as with a real sleep
        self.now = max(self.now, wake)  # time is shared: sleepers wake together, not one by one


def _stamps(count: int, idle_after: dict[int, float], per_second: float = 5) -> list[float]:
    clock = FakeClock()
    limiter = RequestLimiter(per_second, clock=clock, sleep=clock.sleep)
    stamps: list[float] = []

    async def go() -> None:
        for i in range(count):
            await limiter.wait()
            stamps.append(clock.now)
            clock.now += idle_after.get(i, 0.0)

    run(go())
    return stamps


def test_back_to_back_requests_never_exceed_the_window_cap_or_the_average() -> None:
    stamps = _stamps(200, {})
    for start in stamps:
        in_window = [s for s in stamps if start <= s < start + 1.0]
        assert len(in_window) <= 10
        assert len(in_window) <= 6  # spacing gives at most 5 per second plus the window's edge
    average = (len(stamps) - 1) / (stamps[-1] - stamps[0])
    assert average <= 5.0 + 1e-9
    assert average == pytest.approx(5.0)  # and it does not idle: no slower than needed


def test_bursts_after_idle_periods_stay_under_the_caps() -> None:
    rng = random.Random(7)
    idle = {i: rng.choice([0.0, 0.0, 0.05, 1.5, 3.0]) for i in range(300)}
    stamps = _stamps(300, idle)
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert min(gaps) >= 0.2 - 1e-9
    for start in stamps:
        assert sum(1 for s in stamps if start <= s < start + 1.0) <= 10
    assert (len(stamps) - 1) / (stamps[-1] - stamps[0]) <= 5.0 + 1e-9


def test_concurrent_callers_are_serialised_by_the_limiter() -> None:
    clock = FakeClock()
    limiter = RequestLimiter(5, clock=clock, sleep=clock.sleep)
    stamps: list[float] = []

    async def one() -> None:
        await limiter.wait()
        stamps.append(clock.now)

    async def go() -> None:
        await asyncio.gather(*(one() for _ in range(40)))

    run(go())
    assert len(stamps) == 40
    assert all(b - a >= 0.2 - 1e-9 for a, b in zip(stamps, stamps[1:], strict=False))
    for start in stamps:
        assert sum(1 for s in stamps if start <= s < start + 1.0) <= 10


def test_limiter_rejects_a_non_positive_rate() -> None:
    with pytest.raises(ValueError):
        RequestLimiter(0)


def test_the_http_client_waits_on_the_limiter_before_every_request() -> None:
    clock = FakeClock()
    limiter = RequestLimiter(5, clock=clock, sleep=clock.sleep)
    sent: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(clock.now)
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "https://x.test/b"})
        return httpx.Response(200)

    async def go() -> None:
        async with rate_limited_client(limiter, transport=httpx.MockTransport(handler)) as http:
            await http.get("https://x.test/a")  # redirect: two requests
            await http.get("https://x.test/c")

    run(go())
    assert len(sent) == 3
    assert all(b - a >= 0.2 - 1e-9 for a, b in zip(sent, sent[1:], strict=False))


# -- SGML wrapper (item 3) -------------------------------------------------------------------------


def test_ex99_text_equals_the_m2_golden_text_exactly() -> None:
    stored = json.loads(gzip.open(CLASSIFIER_SEC / f"{APPLE_EARNINGS}.json.gz").read())
    golden = {d["type"]: d["text"] for d in stored["documents"]}
    docs = dict(run(read_8k(FakeSecClient(), CIK, filing(APPLE_EARNINGS, primary="aapl-20261102.htm"))).texts)
    assert docs["EX-99.1"] == golden["EX-99.1"]
    assert docs["8-K"] == golden["8-K"]
    assert normalise_text(docs["EX-99.1"]) == normalise_text(golden["EX-99.1"])


def test_the_sgml_document_wrapper_is_removed_before_the_html_is_read() -> None:
    wrapped = "<DOCUMENT>\n<TYPE>EX-99.1\n<SEQUENCE>2\n<TEXT>\n<html><body><p>Release.</p></body></html>"
    assert plain_text(wrapped.encode(), "ex.htm") == "Release."
    assert strip_sgml_header(wrapped).lstrip().startswith("<html>")
