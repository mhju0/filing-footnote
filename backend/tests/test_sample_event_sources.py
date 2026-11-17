import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

from scripts import sample_event_sources as ses
from scripts.sample_event_sources import (
    analyze_exhibit_html,
    document_basename,
    find_leaks,
    parse_index_html_table,
    redact_params,
    strip_prefixes,
    tally_report_names,
    zip_rows_from_submissions,
)


def test_strip_prefixes_removes_all_leading_groups():
    assert strip_prefixes("[기재정정][첨부추가]주요사항보고서(자기주식취득결정) ") == (
        "주요사항보고서(자기주식취득결정)",
        ["[기재정정]", "[첨부추가]"],
    )
    assert strip_prefixes("영업(잠정)실적(공정공시)") == ("영업(잠정)실적(공정공시)", [])
    assert strip_prefixes("기업가치제고계획(자율공시)      (이행현황)") == (
        "기업가치제고계획(자율공시) (이행현황)",
        [],
    )
    assert strip_prefixes("본문[기재정정]") == ("본문[기재정정]", [])


def test_redact_params_drops_key():
    assert redact_params({"crtfc_key": "SECRET", "corp_code": "1"}) == {"corp_code": "1"}


def test_find_leaks_detects_key_value_and_parameter_name(tmp_path: Path):
    (tmp_path / "ok.json").write_text("{}")
    (tmp_path / "bad.json").write_text("xx SECRETVALUE yy")
    (tmp_path / "param.json").write_text("?crtfc_key=***")
    assert find_leaks(tmp_path, "SECRETVALUE") == ["bad.json", "param.json"]


def test_tally_counts_names_across_prefixes():
    rows = {
        "A": [
            {"report_nm": "[기재정정]배당결정", "rcept_no": "1"},
            {"report_nm": "배당결정", "rcept_no": "2"},
        ],
        "B": [{"report_nm": "배당결정", "rcept_no": "3"}],
    }
    entry = tally_report_names(rows)["배당결정"]
    assert entry["total"] == 3
    assert entry["per_company"] == {"A": 2, "B": 1}
    assert entry["prefixes"] == {"[기재정정]": 1}


def test_zip_rows_filters_form_and_window():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["a", "b", "c", "d"],
                "filingDate": ["2026-01-02", "2026-01-03", "2024-01-01", "2026-02-01"],
                "form": ["8-K", "10-Q", "8-K", "8-K/A"],
                "items": ["2.02", "", "5.02", "8.01"],
            },
            "files": [],
        }
    }
    rows, meta = zip_rows_from_submissions(payload, "2025-11-18", "2026-11-17")
    assert [r["accessionNumber"] for r in rows] == ["a", "d"]
    assert rows[0]["primaryDocument"] == ""
    assert meta["recent_oldest_filing_date"] == "2024-01-01"


def test_index_html_table_and_basename():
    html = (
        '<table class="tableFile" summary="Document Format Files">'
        "<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>"
        '<tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1/2/x8k.htm">x8k.htm</a></td>'
        "<td>8-K</td><td>10</td></tr>"
        '<tr><td>2</td><td>PR</td><td><a href="/Archives/edgar/data/1/2/ex991.htm">ex991.htm</a></td>'
        "<td>EX-99.1</td><td>20</td></tr></table>"
    )
    rows = parse_index_html_table(html)
    assert [r["Type"] for r in rows] == ["8-K", "EX-99.1"]
    assert document_basename(rows[0]["href"]) == "x8k.htm"
    assert document_basename(rows[1]["href"]) == "ex991.htm"


def test_exhibit_analysis_separates_prose_and_table_figures():
    html = "<p>Revenue was $5 billion.</p><table><tr><td>Net sales</td><td>$4,000</td></tr></table>"
    result = analyze_exhibit_html(html)
    assert result["table_tag_count"] == 1
    assert result["dollar_figures_outside_tables"] == 1
    assert result["dollar_figures_inside_tables"] == 1


# -- review fixes ---------------------------------------------------------------------------


def test_window_boundaries_inclusive():
    as_of = dt.date(2026, 11, 17)
    start = ses.window_start(as_of)
    assert start == dt.date(2025, 11, 18)
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["a", "b", "c", "d"],
                "filingDate": ["2025-11-17", "2025-11-18", "2026-11-17", "2026-11-18"],
                "form": ["8-K"] * 4,
                "items": [""] * 4,
            }
        }
    }
    rows, _ = zip_rows_from_submissions(payload, start.isoformat(), as_of.isoformat())
    assert [r["accessionNumber"] for r in rows] == ["b", "c"]


def test_non_tablefile_tables_are_skipped():
    html = (
        '<table class="other"><tr><th>Seq</th><th>Type</th></tr><tr><td>1</td><td>EX-1</td></tr>'
        "</table>"
        '<table class="tableFile"><tr><th>Seq</th><th>Document</th><th>Type</th></tr>'
        '<tr><td>1</td><td><a href="/a.htm">a.htm</a></td><td>8-K</td></tr></table>'
    )
    assert [r["Type"] for r in parse_index_html_table(html)] == ["8-K"]
    assert parse_index_html_table('<table class="other"><tr><th>Type</th></tr></table>') == []


def test_split_dollar_cells_count_as_figures_and_sgml_header_is_stripped():
    html = (
        "<DOCUMENT>\n<TYPE>EX-99.1\n<SEQUENCE>2\n<FILENAME>x.htm\n<TEXT>\n"
        "<html><body><p>Revenue was $5 billion.</p><table>"
        "<tr><td>Net sales</td><td>$</td><td>1,234</td><td>$</td><td>2,345</td>"
        "<td>(12)</td><td>$7,000</td></tr></table></body></html>"
    )
    result = analyze_exhibit_html(html)
    assert result["dollar_figures_inside_tables"] == 3
    assert result["numeric_cells_inside_tables"] == 3
    assert result["dollar_figures_outside_tables"] == 1
    assert "TYPE" not in result["revenue_sentence_example"]
    assert ses.strip_sgml_header(html).lstrip().startswith("<html>")


class _Resp:
    def __init__(self, payload):
        self.content = json.dumps(payload).encode()
        self.status_code = 200


class _FakeDart:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def _get(self, endpoint, params):
        self.calls.append(params["page_no"])
        return _Resp(self.pages[params["page_no"] - 1])


def _sampler(pages):
    s = ses.Sampler.__new__(ses.Sampler)
    s.secret = "K"
    s.dart = _FakeDart(pages)
    s.dart_calls = 0
    s._last_dart = 0.0
    s.statuses = []
    s.start = dt.date(2025, 11, 18)
    s.as_of = dt.date(2026, 11, 17)
    return s


def _page(n, total, rows):
    return {"status": "000", "total_page": total, "total_count": 5, "page_no": n, "list": rows}


def test_dart_list_all_paginates_over_pages(monkeypatch):
    monkeypatch.setattr(ses, "DART_INTERVAL", 0)
    s = _sampler(
        [_page(1, 2, [{"rcept_no": "1"}, {"rcept_no": "2"}]), _page(2, 2, [{"rcept_no": "3"}])]
    )
    res = asyncio.run(s.dart_list_all("c", "B"))
    assert [r["rcept_no"] for r in res["rows"]] == ["1", "2", "3"]
    assert s.dart.calls == [1, 2]
    assert res["partial"] is False and res["status"] == "000"


def test_dart_list_all_marks_partial_when_later_page_fails(monkeypatch, capsys):
    monkeypatch.setattr(ses, "DART_INTERVAL", 0)
    bad = {"status": "020", "message": "limit"}
    s = _sampler([_page(1, 3, [{"rcept_no": "1"}]), bad])
    res = asyncio.run(s.dart_list_all("c", "B"))
    assert res["partial"] is True
    assert res["status"] == "000"  # page 1's status is kept
    assert res["page_errors"] == [{"page": 2, "status": "020", "message": "limit"}]
    assert len(res["rows"]) == 1
    assert "WARNING" in capsys.readouterr().out
    assert s.statuses[0]["status"] == "020"


def test_dart_list_all_omits_ty_for_detail_only(monkeypatch):
    monkeypatch.setattr(ses, "DART_INTERVAL", 0)
    seen = {}

    class Fake(_FakeDart):
        async def _get(self, endpoint, params):
            seen.update(params)
            return await super()._get(endpoint, params)

    s = _sampler([_page(1, 1, [])])
    s.dart = Fake([_page(1, 1, [])])
    asyncio.run(s.dart_list_all("c", None, {"pblntf_detail_ty": "I002"}))
    assert "pblntf_ty" not in seen and seen["pblntf_detail_ty"] == "I002"


def test_sec_user_agent_check():
    assert ses.check_sec_user_agent("Jane Doe jane@mail.org") == "contact-style"
    for bad in (
        ses.Settings.model_fields["sec_user_agent"].default,
        "x y@example.com",
        "no contact here",
        "",
    ):
        with pytest.raises(SystemExit):
            ses.check_sec_user_agent(bad)


def test_decimal_parse_check_skips_ids_and_marks_absent():
    row = {
        "rcept_no": "20260101000001",
        "corp_code": "00126380",
        "corp_cls": "Y",
        "a": "1,000",
        "b": "-",
        "c": "1.8",
        "d": "2026년 01월 30일",
    }
    assert ses.decimal_parse_check(row) == {"a": "1000", "b": "absent", "c": "1.8"}


def test_clear_fixture_dir_guard(tmp_path: Path):
    root = tmp_path / "events"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "f.json").write_text("x")
    (root / "g.json").write_text("x")
    assert ses.clear_fixture_dir(root, root) is True
    assert list(root.iterdir()) == []
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    assert ses.clear_fixture_dir(outside, root) is False
    assert (outside / "keep.txt").exists()


def test_leak_scan_runs_when_run_crashes(tmp_path: Path, monkeypatch, capsys):
    class Crashing:
        def __init__(self, out, as_of):
            self.out = out
            self.http = self

        async def aclose(self):
            pass

        async def run_dart(self):
            (self.out / "x.json").write_text("has SECRETVALUE inside")
            raise RuntimeError("boom")

        def leak_scan(self):
            return not ses.scan_and_purge(self.out, "SECRETVALUE")

    monkeypatch.setattr(ses, "Sampler", Crashing)
    monkeypatch.setattr(ses, "clear_fixture_dir", lambda out: True)
    args = type("A", (), {"out": str(tmp_path), "as_of": "2026-11-17", "report": False})()
    with pytest.raises(SystemExit) as exc:
        asyncio.run(ses.main_async(args))
    assert exc.value.code == 2
    assert not (tmp_path / "x.json").exists()
