"""The glossary contract (``contracts/glossary.json``) as bundle rows (D81).

Each entry has a ``term_key``, an ``approved`` flag and a ko and en ``{term, plain, formal}``.
Only the owner sets ``approved``; the exporter ships approved entries, a development build
(``--allow-unapproved``) also ships the rest, and a release build refuses while any entry is
unapproved. Every text passes the neutrality guard (N1 no digits, N2 to N8) like a summary line.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.llm.neutrality_guard import check_line

GLOSSARY_PATH = Path(__file__).resolve().parents[3] / "contracts" / "glossary.json"
LANGS = ("ko", "en")
FIELDS = ("term", "plain", "formal")
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.])\s+")


def load_glossary() -> dict[str, dict[str, Any]]:
    return json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))["entries"]


def glossary_problems(entries: dict[str, dict[str, Any]]) -> list[str]:
    """Structure and neutrality problems; an empty list means every entry may ship."""
    problems = []
    for key, entry in sorted(entries.items()):
        if not isinstance(entry.get("approved"), bool):
            problems.append(f"glossary {key}: approved must be true or false")
        for lang in LANGS:
            texts = entry.get(lang)
            if not isinstance(texts, dict) or set(texts) != set(FIELDS):
                problems.append(f"glossary {key}/{lang}: needs exactly term, plain and formal")
                continue
            for field in ("term", "plain"):
                if not isinstance(texts[field], str) or not texts[field].strip():
                    problems.append(f"glossary {key}/{lang}: {field} is empty")
            if texts["formal"] is not None and not (
                isinstance(texts["formal"], str) and texts["formal"].strip()
            ):
                problems.append(f"glossary {key}/{lang}: formal is empty, use null")
            for field in FIELDS:
                text = texts[field]
                if not isinstance(text, str) or not text.strip():
                    continue
                # Each sentence is checked as one summary line. N4 (attribution to the
                # company) shapes summary sentences, not definitions. A Korean term can be a
                # Latin abbreviation (K-IFRS), so N8 is for sentences only.
                for sentence in _SENTENCE_BREAK_RE.split(text.strip()):
                    for v in check_line(sentence, lang):  # type: ignore[arg-type]
                        if v.rule_id == "N4" or (v.rule_id == "N8" and field == "term"):
                            continue
                        problems.append(f"glossary {key}/{lang}/{field}: {v.rule_id} {v.token!r}")
    return problems


def glossary_rows(entries: dict[str, dict[str, Any]], *, allow_unapproved: bool) -> list[tuple]:
    """(term_key, lang, term, plain, formal) rows, approved entries only unless allowed."""
    return [
        (key, lang, entry[lang]["term"], entry[lang]["plain"], entry[lang]["formal"])
        for key, entry in sorted(entries.items())
        if entry["approved"] or allow_unapproved
        for lang in LANGS
    ]


def release_problems(entries: dict[str, dict[str, Any]]) -> list[str]:
    return [
        f"release build refused: glossary entry {key!r} is not approved"
        for key, entry in sorted(entries.items())
        if not entry["approved"]
    ]
