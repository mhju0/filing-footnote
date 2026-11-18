"""D2: US and Korean figures mean the same thing, and every company has a Korean name."""

import json
import os
import re
from pathlib import Path

import pytest

from app.build.verify import DEFAULT_PINNED_DIR
from app.clients.sec import parse_companyfacts_payload

CONTRACTS = Path(__file__).parents[2] / "contracts"
HANGUL = re.compile(r"[가-힣]")
# The pinned responses are git-ignored; set PINNED_DIR to read them from another checkout.
PINNED_DIR = Path(os.environ.get("PINNED_DIR") or DEFAULT_PINNED_DIR)

# SEC CIK -> ticker for the nine US companies of the corpus.
US_COMPANIES = {
    "0000320193": "AAPL",
    "0000789019": "MSFT",
    "0001045810": "NVDA",
    "0001318605": "TSLA",
    "0001018724": "AMZN",
    "0000909832": "COST",
    "0001652044": "GOOGL",
    "0001326801": "META",
    "0000104169": "WMT",
}


def _glossary_companies() -> dict[str, list[str]]:
    glossary = json.loads((CONTRACTS / "family-glossary.json").read_text(encoding="utf-8"))
    return glossary["companies"]


def test_every_glossary_company_has_a_hangul_korean_name() -> None:
    for ticker, names in _glossary_companies().items():
        assert HANGUL.search(names[0]), f"{ticker}: {names[0]!r} has no Hangul"
        assert names[1].strip(), ticker


def test_every_us_company_has_a_korean_name() -> None:
    companies = _glossary_companies()
    assert set(US_COMPANIES.values()) <= set(companies)
    assert {t: companies[t][0] for t in ("AMZN", "COST", "GOOGL", "META", "WMT")} == {
        "AMZN": "아마존",
        "COST": "코스트코",
        "GOOGL": "알파벳",
        "META": "메타",
        "WMT": "월마트",
    }


def test_exporter_gives_every_us_ticker_a_hangul_name_ko() -> None:
    from app.build.export import _korean_names

    names = _korean_names()
    for ticker in US_COMPANIES.values():
        assert HANGUL.search(names.get(ticker, "")), ticker


@pytest.mark.parametrize("cik10", sorted(US_COMPANIES))
def test_pinned_sec_export_gives_attributable_net_income_and_total_only_with_profit_loss(
    cik10: str,
) -> None:
    path = PINNED_DIR / "sec" / "companyfacts" / f"CIK{cik10}.json"
    if not path.exists():
        pytest.skip(f"no pinned response {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_metric: dict[str, set[str]] = {}
    for item in parse_companyfacts_payload(payload):
        by_metric.setdefault(item.metric, set()).add(item.tag)
    assert by_metric["net_income_attributable"] == {"NetIncomeLoss"}
    profit_loss = payload["facts"]["us-gaap"].get("ProfitLoss", {}).get("units", {}).get("USD", [])
    if any(e.get("form") == "10-K" for e in profit_loss):
        assert by_metric["net_income"] == {"ProfitLoss"}
    else:
        assert "net_income" not in by_metric
