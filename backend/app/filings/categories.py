"""Deterministic category for one event filing, from ``contracts/filing-categories.json``.

Pure functions, no network. A filing gets exactly one category, or is excluded with a reason
key. Nothing is guessed: when the decision needs the filing text and none is given, the
result is excluded as ``needs_body``.
"""

from __future__ import annotations

import datetime
import html
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "filing-categories.json"


SecText = str | tuple[str, str]


@dataclass(frozen=True)
class Classification:
    category: str | None
    excluded_reason: str | None
    subsidiary: bool
    is_correction: bool
    basis: str | None
    matched_rule: str

    def __post_init__(self) -> None:
        if (self.category is None) == (self.excluded_reason is None):
            raise ValueError("exactly one of category and excluded_reason must be set")


@lru_cache(maxsize=1)
def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _priority(category: str) -> int:
    for entry in load_contract()["categories"]:
        if entry["key"] == category:
            return int(entry["priority"])
    raise KeyError(category)


def _hit(
    category: str,
    rule: str,
    *,
    subsidiary: bool = False,
    is_correction: bool = False,
    basis: str | None = None,
) -> Classification:
    return Classification(category, None, subsidiary, is_correction, basis, rule)


def _miss(
    reason: str, rule: str, *, subsidiary: bool = False, is_correction: bool = False
) -> Classification:
    return Classification(None, reason, subsidiary, is_correction, None, rule)


# -- DART --------------------------------------------------------------------------------------


def normalise_dart_name(report_nm: str) -> tuple[str, bool, bool]:
    """Return ``(match_key, subsidiary, is_correction)`` for a DART ``report_nm``."""
    dart = load_contract()["dart"]
    text = report_nm.strip()
    prefix = re.match(dart["correction_prefix_pattern"], text)
    is_correction = prefix is not None
    if prefix:
        text = text[prefix.end() :]
    key = re.sub(r"\s+", "", text)
    subsidiary = False
    for raw_marker in dart["subsidiary_markers"]:
        marker = re.sub(r"\s+", "", raw_marker)
        if marker in key:
            subsidiary = True
            key = key.replace(marker, "")
    wrapper = dart["report_wrapper"]
    if key.startswith(f"{wrapper}(") and key.endswith(")"):
        key = key[len(wrapper) + 1 : -1]
    return key, subsidiary, is_correction


def _longest_match(entries: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    """The entry owning the longest prefix of ``key``; list order never matters."""
    best: tuple[int, dict[str, Any]] | None = None
    for entry in entries:
        for prefix in entry["prefixes"]:
            if key.startswith(prefix) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), entry)
    return best[1] if best else None


def _tag_free(text: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))


def _reports_results(body_text: str) -> bool:
    """True when the first 매출액 당해실적 cell holds a figure rather than ``-``."""
    pattern = load_contract()["dart"]["earnings"]["monthly_results_pattern"]
    match = re.search(pattern, _tag_free(body_text))
    return match is not None and match.group(1) != "-"


def _period_months(body_text: str) -> int | None:
    """Whole calendar months in the body's 당기실적 period, or ``None`` if not aligned."""
    pattern = load_contract()["dart"]["earnings"]["period_pattern"]
    match = re.search(pattern, _tag_free(body_text))
    if match is None:
        return None
    y1, m1, d1, y2, m2, d2 = (int(g) for g in match.groups())
    try:
        start = datetime.date(y1, m1, d1)
        end = datetime.date(y2, m2, d2)
    except ValueError:
        return None
    next_day = end + datetime.timedelta(days=1)
    if start.day != 1 or next_day.day != 1 or end < start:
        return None
    return (end.year - start.year) * 12 + end.month - start.month + 1


def classify_dart(report_nm: str, body_text: str | None = None) -> Classification:
    """Classify a DART filing by report name; plain 영업(잠정)실적 also needs the body."""
    dart = load_contract()["dart"]
    key, subsidiary, is_correction = normalise_dart_name(report_nm)
    flags = {"subsidiary": subsidiary, "is_correction": is_correction}

    excluded = _longest_match(dart["exclusions"], key)
    if excluded is not None:
        return _miss(excluded["reason"], excluded["id"], **flags)

    earnings = dart["earnings"]
    if key.startswith(tuple(earnings["consolidated_prefixes"])):
        return _hit("earnings", earnings["id"], basis="consolidated", **flags)
    if key.startswith(tuple(earnings["plain_prefixes"])):
        if not body_text or not body_text.strip():
            return _miss("needs_body", f"{earnings['id']}.period", **flags)
        months = _period_months(body_text)
        if months in earnings["unit_sales_months"]:
            if _reports_results(body_text):
                return _miss("no_rule", f"{earnings['id']}.monthly_with_results", **flags)
            return _hit("unit_sales", f"{earnings['id']}.monthly", **flags)
        if months is not None and months >= earnings["earnings_min_months"]:
            return _hit("earnings", f"{earnings['id']}.period", basis="separate", **flags)
        return _miss("no_rule", f"{earnings['id']}.period_other", **flags)

    rule = _longest_match(dart["rules"], key)
    if rule is not None:
        return _hit(rule["category"], rule["id"], **flags)
    return _miss("no_rule", "dart.no_rule", **flags)


# -- SEC ---------------------------------------------------------------------------------------


def _split_items(items: str | Sequence[str]) -> list[str]:
    parts = items.split(",") if isinstance(items, str) else items
    return [p.strip() for p in parts if p.strip()]


_SGML_HEAD_RE = re.compile(r"^\s*<DOCUMENT>.*?<TEXT>\s*", re.S)
_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_DASHES = re.compile("[\u2010-\u2015\u2212]")


def normalise_text(text: str) -> str:
    """Matching form of filing text: no markup, NFKC, ASCII hyphens, ``&`` as 'and', lowercase."""
    text = _SGML_HEAD_RE.sub("", text, count=1)
    text = html.unescape(_TAG_RE.sub(" ", text))
    text = unicodedata.normalize("NFKC", text)
    text = _DASHES.sub("-", text).replace("&", " and ")
    return re.sub(r"\s+", " ", text).strip().lower()


def _readable_text(texts: Sequence[SecText] | None, form: str, source: str) -> str:
    """Join the texts the contract allows for ``source`` (``keyword_sources``/``earnings_sources``).

    A bare string counts as the primary document. A ``(document_type, text)`` pair is primary
    when its type is ``primary`` or equals the form, and an exhibit when its type starts with an
    allowed prefix (only the lead of it when the contract sets ``exhibit_lead_chars``).
    """
    sources = load_contract()["sec"][source]
    prefixes = tuple(p.upper() for p in sources["exhibit_type_prefixes"])
    lead = sources["exhibit_lead_chars"]
    kept = []
    for entry in texts or ():
        doc_type, text = ("primary", entry) if isinstance(entry, str) else entry
        doc_type = doc_type.strip().upper()
        if doc_type in ("PRIMARY", form):
            kept.append(normalise_text(text))
        elif doc_type.startswith(prefixes):
            clean = normalise_text(text)
            kept.append(clean[:lead] if lead else clean)
    return " ".join(kept)


def classify_sec(
    form: str, items: str | Sequence[str], texts: Sequence[SecText] | None = None
) -> Classification:
    """Classify an 8-K / 8-K/A by its item numbers and, for 2.02/7.01/8.01, its text."""
    sec = load_contract()["sec"]
    form = form.strip().upper()
    item_list = _split_items(items)
    is_correction = form in sec["correction_forms"]
    flags = {"is_correction": is_correction}
    keyword_text = _readable_text(texts, form, "keyword_sources")
    results_text = _readable_text(texts, form, "earnings_sources")
    needs_text = any(i in sec["body_items"] for i in item_list)
    if needs_text and not results_text.strip():
        return _miss("needs_body", "sec.needs_body", **flags)

    candidates: list[tuple[str, str]] = []
    reasons: list[tuple[str, str]] = []

    earnings = sec["earnings_item"]
    if earnings["item"] in item_list:
        has_results = any(p in results_text for p in earnings["results_phrases"])
        has_units = any(p in results_text for p in earnings["unit_sales_phrases"])
        if has_units and not has_results:
            candidates.append(("unit_sales", earnings["unit_sales_id"]))
        else:
            candidates.append(("earnings", earnings["earnings_id"]))

    keyword_items = [i for i in item_list if i in sec["keyword_items"]]
    if keyword_items:
        before = len(candidates)
        for rule in sec["keyword_rules"]:
            if any(p in keyword_text for p in rule["phrases"]):
                candidates.append((rule["category"], rule["id"]))
        if len(candidates) == before:
            for extra in sec["no_keyword_reasons"]:
                if any(p in keyword_text for p in extra["phrases"]):
                    reasons.append((extra["reason"], extra["id"]))
                    break
            else:
                reasons.append(("no_keyword_match", f"sec.item.{keyword_items[0]}.no_keyword"))

    for item in item_list:
        if item in sec["items"]:
            entry = sec["items"][item]
            candidates.append((entry["category"], entry["id"]))
        elif item in sec["item_exclusions"]:
            reasons.append((sec["item_exclusions"][item], f"sec.item.{item}.excluded"))
        elif item != earnings["item"] and item not in sec["keyword_items"]:
            reasons.append(("no_rule", f"sec.item.{item}.no_rule"))

    if candidates:
        category, rule_id = min(candidates, key=lambda c: _priority(c[0]))
        return _hit(category, rule_id, **flags)
    if reasons:
        order = sec["exclusion_order"]
        reason, rule_id = min(reasons, key=lambda r: order.index(r[0]))
        return _miss(reason, rule_id, **flags)
    return _miss("no_rule", "sec.no_items", **flags)
