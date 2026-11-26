"""Build-time faithfulness check (D97): find the source sentence behind each summary line.

    python -m app.build.faithfulness check --as-of DATE [--database-url URL]
        [--rows PATH ...] [--out PATH]
    python -m app.build.faithfulness eval [--cases PATH] [--sources PATH] [--show]
    python -m app.build.faithfulness accept --filing ID --section S --lang ko|en --line N
        --note TEXT [--rows PATH] [--accepted PATH]

``check`` reads summary rows (by default ``approved.jsonl`` and ``staged.jsonl``), takes each
row's source text from the build database exactly as the summary step sent it to the model
(:func:`app.build.summaries.select_targets`), and writes one record per line to
``data/summaries/faithfulness.jsonl``: the verdict, the overlap, the supporting sentences as
character offsets into the source text with their text, and the reasons. ``eval`` scores the
check against the hand-labelled lines in ``tests/fixtures/faithfulness/``. ``accept`` is the
owner's command to let one flagged line through a release; agents never run it.

The method is deterministic, local and free. The source text is split into sentences. For a
line in the source's language, every content word of the line is looked up in each sentence:
a Korean word by its stem with particles and endings stripped (이천시에 -> 이천시) as a
substring of the sentence with spaces removed, an English word by a shared prefix (disposal,
dispose). Places, products and filing terms in ``contracts/faithfulness-lexicon.json`` resolve
to one id in both languages (파운드리 and Foundry, 중화권 and Greater China), and Latin words and
numbers must appear as written. The best sentence, plus a second one when it adds words, is the
span; the share of the line's words it covers decides the verdict. A place, product, Latin word
or number the line names that the source never names makes the line ``unsupported``, the
region-swap case of the case study; so does a rival term the source does not use (cancel where
the filing disposes, special where it says quarterly). A negation or a direction (rose, fell)
that the span does not share lowers ``supported`` to ``partly``.

A line in the other language (an English line on a DART filing, a Korean line on an SEC
filing) is checked through its parallel line, which the prompt writes to say the same thing in
the same order: it takes that line's verdict and span, and its own places, products, Latin
words and numbers must still be in the source, and its negation and direction must match the
parallel line's.

Template lines (D78) are not aligned: their wording is fixed and their figures and direction
come from the filing's parsed table, which the export re-reads from the pinned response. Their
verdict is ``template``.

What it cannot do: it measures word overlap, not meaning. A line that reuses the filing's words
in a wrong relation passes, and a faithful paraphrase in other words is flagged. The eval
counts both.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from functools import cache
from pathlib import Path
from typing import Any

from app.build.model import LANGS

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent
LEXICON_PATH = REPO_DIR / "contracts" / "faithfulness-lexicon.json"
SUMMARIES_DIR = BACKEND_DIR / "data" / "summaries"
REPORT_PATH = SUMMARIES_DIR / "faithfulness.jsonl"
ACCEPTED_PATH = SUMMARIES_DIR / "faithfulness_accepted.jsonl"
EVAL_DIR = BACKEND_DIR / "tests" / "fixtures" / "faithfulness"
EVAL_CASES_PATH = EVAL_DIR / "cases.jsonl"
EVAL_SOURCES_PATH = EVAL_DIR / "sources.json"

# Part of every record; a release refuses records from another version.
ALIGNER_VERSION = "f3-2026-11-26"
SUPPORTED_AT = Fraction(7, 10)
PARTLY_AT = Fraction(2, 5)
MAX_SPAN_SENTENCES = 2
ENTITY_WEIGHT = 2
WORD_WEIGHT = 1

SUPPORTED, PARTLY, UNSUPPORTED = "supported", "partly", "unsupported"
VERDICTS = (SUPPORTED, PARTLY, UNSUPPORTED)
TEMPLATE = "template"  # a template line (D78), not aligned
NO_SOURCE = "no_source"  # no source text to check against
_RANK = {SUPPORTED: 2, PARTLY: 1, UNSUPPORTED: 0}

TEMPLATE_MODEL = "template"  # app.build.templates.TEMPLATE_MODEL, kept here to avoid the import

# Release policy: the verdicts that block a release, by policy name (D97).
POLICIES: dict[str, frozenset[str]] = {
    "off": frozenset(),
    "warn": frozenset(),
    "unsupported": frozenset({UNSUPPORTED, NO_SOURCE}),
    "partly": frozenset({UNSUPPORTED, PARTLY, NO_SOURCE}),
}
DEFAULT_POLICY = "unsupported"

# -- lexicon -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Lexicon:
    version: int
    hangul: Mapping[str, str | None]  # Hangul form -> entry id; None for an ignored word
    hangul_lengths: tuple[int, ...]  # longest first
    latin_exact: Mapping[tuple[str, ...], str]  # acronym words, case kept -> entry id
    latin_folded: Mapping[tuple[str, ...], str]  # other words, lower case -> entry id
    latin_max: int
    signs: Mapping[str, str]  # currency sign or Hanja abbreviation -> entry id
    strict: frozenset[str]  # ids of strict classes (places, products, currencies)
    ambiguous: frozenset[str]  # forms with a second common meaning (인도: India, delivery)
    rivals: Mapping[str, frozenset[str]]  # term id -> the ids it excludes (cancel: dispose, ...)


_HANGUL_FORM_RE = re.compile(r"[가-힣]+")
# Hangul words joined by one space or a middle dot, so 아시아 태평양 and 아시아·태평양 resolve
# like 아시아태평양.
_HANGUL_RUN_RE = re.compile(r"[가-힣]+(?:[ ·・‧][가-힣]+)*")
_HANGUL_JOINERS = " ·・‧"
_ALNUM_RE = re.compile(r"[A-Za-z0-9]+")
_LATIN_GAP_RE = re.compile(r"[\s.'’&\-]{0,3}")


def _is_acronym(form: str) -> bool:
    letters = [c for c in form if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def build_lexicon(raw: Mapping[str, Any]) -> Lexicon:
    strict_classes = {name for name, kind in raw["classes"].items() if kind == "strict"}
    hangul: dict[str, str | None] = {word: None for word in raw.get("ignore", ())}
    exact: dict[tuple[str, ...], str] = {}
    folded: dict[tuple[str, ...], str] = {}
    strict = set()
    for entry in raw["entries"]:
        if entry["class"] not in raw["classes"]:
            raise ValueError(f"{entry['id']}: unknown class {entry['class']!r}")
        if entry["class"] in strict_classes:
            strict.add(entry["id"])
        for form in entry["ko"]:
            if not _HANGUL_FORM_RE.fullmatch(form):
                raise ValueError(f"{entry['id']}: Korean form {form!r} is not one Hangul word")
            hangul[form] = entry["id"]
        for form in entry["en"]:
            words = tuple(_ALNUM_RE.findall(form))
            if _is_acronym(form):
                exact[words] = entry["id"]
            else:
                folded[tuple(w.lower() for w in words)] = entry["id"]
    rivals: dict[str, frozenset[str]] = {}
    for group in raw.get("rivals", ()):
        for term_id in group:
            rivals[term_id] = frozenset(group) - {term_id}
    lengths = tuple(sorted({len(form) for form in hangul}, reverse=True))
    longest = max(len(words) for words in (*exact, *folded))
    return Lexicon(
        raw["version"], hangul, lengths, exact, folded, longest, dict(raw.get("signs", {})),
        frozenset(strict), frozenset(raw.get("ambiguous", ())), rivals,
    )  # fmt: skip


@cache
def load_lexicon(path: Path = LEXICON_PATH) -> Lexicon:
    return build_lexicon(json.loads(path.read_text(encoding="utf-8")))


_KO_PREFIXES = frozenset("대범전주재")


def _word_start(text: str, where: Sequence[int], i: int) -> bool:
    def starts(k: int) -> bool:
        return where[k] == 0 or not _HANGUL_RE.match(text[where[k] - 1])

    return starts(i) or (i > 0 and starts(i - 1) and where[i - 1] == where[i] - 1
                         and text[where[i - 1]] in _KO_PREFIXES)  # fmt: skip


def _scan_hangul(text: str, lexicon: Lexicon) -> Iterable[tuple[str | None, int, int]]:
    for run in _HANGUL_RUN_RE.finditer(text):
        chars: list[str] = []
        where: list[int] = []
        piece: list[int] = []
        number = 0
        for offset, char in enumerate(run.group(), start=run.start()):
            if char in _HANGUL_JOINERS:
                number += 1
                continue
            chars.append(char)
            where.append(offset)
            piece.append(number)
        word, i, last = "".join(chars), 0, -1
        while i < len(word):
            for length in lexicon.hangul_lengths:
                if i + length > len(word) or word[i : i + length] not in lexicon.hangul:
                    continue
                # Across a space each part must be a word of its own: 아시아 태평양 joins,
                # 이 중 동일 does not become 중동.
                parts = Counter(piece[i : i + length])
                if len(parts) > 1 and min(parts.values()) < 2:
                    continue
                # A two-syllable form starts a word, follows a one-syllable prefix (대중국) or
                # follows another form (특별배당): 유로 is the euro, 사유로 is not.
                if length == 2 and i != last and not _word_start(text, where, i):
                    continue
                yield lexicon.hangul[word[i : i + length]], where[i], where[i + length - 1] + 1
                i += length
                last = i
                break
            else:
                i += 1


def _scan_latin(text: str, lexicon: Lexicon) -> Iterable[tuple[str, int, int]]:
    words = list(_ALNUM_RE.finditer(text))
    j = 0
    while j < len(words):
        for n in range(min(lexicon.latin_max, len(words) - j), 0, -1):
            group = words[j : j + n]
            if any(not _LATIN_GAP_RE.fullmatch(text[a.end() : b.start()])
                   for a, b in zip(group, group[1:], strict=False)):  # fmt: skip
                continue
            key = tuple(w.group() for w in group)
            entry_id = lexicon.latin_exact.get(key) or lexicon.latin_folded.get(
                tuple(w.lower() for w in key)
            )
            if entry_id is not None:
                yield entry_id, group[0].start(), group[-1].end()
                j += n
                break
        else:
            j += 1


def scan_terms(text: str, lexicon: Lexicon) -> list[tuple[str, int, int]]:
    """``(id, start, end)`` of every lexicon form in ``text``, left to right, never overlapping,
    the longest form winning: Greater China, not China; 대한민국, not 한국; US$, not US.
    A Korean form matches inside a longer word (이천시에 names 이천); a Latin form matches whole
    words, in any case unless it is an acronym (US, not us)."""
    found: list[tuple[str | None, int, int]] = [*_scan_hangul(text, lexicon),
                                                *_scan_latin(text, lexicon)]  # fmt: skip
    for sign, entry_id in lexicon.signs.items():
        start = text.find(sign)
        while start >= 0:
            found.append((entry_id, start, start + len(sign)))
            start = text.find(sign, start + len(sign))
    kept: list[tuple[str, int, int]] = []
    end = -1
    for entry_id, start, stop in sorted(found, key=lambda f: (f[1], f[1] - f[2])):
        if start >= end:
            end = stop
            if entry_id is not None:
                kept.append((entry_id, start, stop))
    return kept


# -- words ---------------------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"[가-힣]+|[A-Za-z][A-Za-z0-9&'\-]*[A-Za-z0-9]|[A-Za-z]|[0-9][0-9,.]*[0-9]|[0-9]"
)
_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Particles and endings, stripped from the end of a Korean word, longest first.
_KO_SUFFIXES = tuple(
    sorted(
        {
            "했어요", "밝혔어요", "했다고", "한다고", "된다고", "됐다고", "되었다고", "였다고",
            "이었다고", "이라고", "라고", "다고", "한다는", "된다는", "했다는", "이라는", "라는",
            "하기로", "하기", "되거나", "하거나", "거나", "되면", "하면서", "하는", "하고", "하며",
            "하여", "하면", "해서", "했고", "했으며",
            "되는", "되고", "되어", "되며", "됐고", "된", "될", "한", "할", "함", "됨", "이며",
            "이고", "이다", "입니다", "니다", "있는", "있다", "있고", "있으며", "없는", "없다",
            "에서는", "으로는", "에게서", "에게", "에서", "에는", "에도", "으로", "로는", "부터",
            "까지", "보다", "처럼", "마다", "와의", "과의", "으로서", "로서", "인", "은", "는",
            "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만", "나", "고", "며",
        },
        key=lambda s: (-len(s), s),
    )
)  # fmt: skip
_KO_STOP = frozenset(
    {
        "회사", "당사", "그리고", "또한", "또", "및", "등", "것", "수", "이", "그", "이번", "해당",
        "관련", "대해", "대한", "위해", "위한", "따라", "따른", "통해", "같은", "있다", "있어요",
        "하다", "되다", "한다", "했다", "밝혔", "밝혔어요", "공시", "보고", "적었어요", "예정",
        "계획", "내용", "사항", "경우", "각각", "모두", "함께", "관한", "대하여", "있다고",
        "없다고", "했어요", "말했어요", "보고했어요", "공시했어요", "밝혔다고", "적었다고",
    }
)  # fmt: skip
_EN_STOP = frozenset(
    """a an the of to and or in on for with by at as from that this these those its it is are
    was were be been being company company's said says reported disclosed stated decided filed
    also which who whom whose will would may might can could shall should must has have had
    than other such including include includes about into through under over based plans plan
    intends intend their they them his her he she its our we us any all each both not no
    there here so if when while then than per one more most""".split()
)
_EN_SUFFIXES = ("ies", "es", "s", "ing", "ed", "ly")
_EN_PREFIX = 6

_KO_NEGATION = re.compile(r"않|없|아니|아님|못하")
_EN_NEGATION = re.compile(r"\b(?:not|no(?!\.)|never|none|denied|denies|deny)\b", re.IGNORECASE)
_KO_UP = re.compile(r"증가|늘었|늘어|늘고|늘린|상승|확대|개선")
_KO_DOWN = re.compile(r"감소|줄었|줄어|줄고|줄인|하락|축소|악화")
_EN_UP = re.compile(r"\b(?:increas\w*|rose|rise\w*|grew|grow\w*|higher|expand\w*)\b", re.I)
_EN_DOWN = re.compile(r"\b(?:decreas\w*|declin\w*|fell|fall\w*|lower|drop\w*|reduc\w*)\b", re.I)


def ko_stems(word: str) -> tuple[str, ...]:
    """The word and each shorter stem left after stripping one particle or ending at a time,
    while at least two syllables remain: 이천시에 -> (이천시에, 이천시). A stem of three or
    more syllables also yields itself less its last syllable, for compounds the filing writes
    short (승용차 -> 승용)."""
    stems = [word]
    current = word
    for _ in range(3):
        for suffix in _KO_SUFFIXES:
            if current.endswith(suffix) and len(current) - len(suffix) >= 2:
                current = current[: -len(suffix)]
                stems.append(current)
                break
        else:
            break
    if len(current) >= 3:
        stems.append(current[:-1])
    return tuple(stems)


def en_key(word: str) -> str:
    key = word.lower().removesuffix("'s").removesuffix("’s")
    if len(key) > 4:
        for suffix in _EN_SUFFIXES:
            if key.endswith(suffix) and len(key) - len(suffix) >= 3:
                key = key[: -len(suffix)] + ("y" if suffix == "ies" else "")
                break
    return key


def _en_matches(key: str, keys: Iterable[str]) -> bool:
    for other in keys:
        if other == key:
            return True
        if min(len(key), len(other)) >= _EN_PREFIX and key[:_EN_PREFIX] == other[:_EN_PREFIX]:
            return True
    return False


def _digits(token: str) -> str:
    return token.replace(",", "")


def script_of(text: str) -> str:
    """``ko`` when at least three in ten letters are Hangul, else ``en``."""
    hangul = len(_HANGUL_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    return "ko" if hangul * 10 >= (hangul + latin) * 3 and hangul else "en"


# -- sentences -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sentence:
    start: int
    end: int
    text: str


_ABBREVIATIONS = frozenset(
    "inc co corp ltd llc llp l.p pte plc no mr ms mrs dr jr sr st vs etc u.s u.k e.g i.e "
    "n.a a.m p.m adj ex reg d.c".split()
)
# A boundary before a DART list marker: " - ", "【", "※", "■", "□", "○", "▶", "•", a numbered
# field (" 5. 처분목적") or a lettered item (" 가. ").
_MARKER_RE = re.compile(
    r"(?<=\s)(?=-\s|[【※■□○▶•])|(?<=\s)(?=[0-9]{1,2}\.\s+[가-힣A-Za-z(])|(?<=\s)(?=[가-하]\.\s)"
)
_STOP_RE = re.compile(r"[.!?。](?=\s|[가-힣\-【※(\"'”’])")
# A '.' after a Latin letter and before Hangul ends a name, not a sentence: "Green Holding
# L.P.와 체결한", "Pte. Ltd.(이하 '회사')".
_NAME_DOT_RE = re.compile(r"(?<=[A-Za-z])\.(?=\(?[가-힣])")
# A soft-wrapped line in English filing text: the line runs on into the next one, which starts
# with a lowercase word ("named executive officers\nas disclosed in the proxy statement",
# "6.250%\nnotes due 2066"), or the line ends on a comma or semicolon. Blank lines, headings,
# list items and lines that end a sentence or a label stay cuts.
_WRAP_RE = re.compile(
    r"(?<=[A-Za-z0-9%,;’”)™])[ \t]*\n[ \t]*(?=[a-z])|(?<=[,;])[ \t]*\n[ \t]*(?=[A-Z0-9$])"
)
# A line break inside an open quote or bracket also runs on when the next line starts with a
# Latin word or a number: "(the “2036\nNotes”)", "the “Prior\nTrustee”)".
_RUNS_ON_RE = re.compile(r"[ \t]*[A-Za-z0-9$“]")
# Lines the pipeline adds around the filing's own text (``app.build.model``,
# ``app.clients.sec_8k``): the title and text labels, the report name and section labels such
# as "[Item 1. Business]" or "[EX-99.1]". They are not the filing's sentences, so they are
# neither excerpts nor support.
_HEADER_RE = re.compile(
    r"^[ \t]*(?:Filing title: .*|Filing text:|Report: .*|\[[^\[\]\n]{1,80}\])[ \t]*$", re.M
)
# A list number after a space, an opening quote or bracket, or a word that points back
# ("상기", "위", "아래") is a list marker or a reference to a field, not the end of a sentence:
# "5. 처분목적", "상기 '4. 채무보증내역'은", "상기4. 및 5.와", "'2.금전대여내역'".
_FIELD_NUMBER_RE = re.compile(
    r"(?:^|[\s'‘\"“(\[「『〈<])(?:[0-9]{1,2}|[가-하]|[Ⅰ-Ⅹ])$|(?:상기|위|아래)[0-9]{1,2}$"
    r"|['‘\"“(\[「『〈<][IVX]{1,4}$"
)
# The '.' that ends a date before a particle: "2024.12.31.이 속하는".
_DATE_DOT_RE = re.compile(r"[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}(\.)(?=[가-힣])")
# In English text a sentence starts with a capital, so a '.' after a Latin letter or a digit and
# before a lowercase word ends a reference or an abbreviation: "General Instruction A.2.
# below", "Adj. operating income". An SEC item number is a reference too: "Item 1A. Risk".
_RUNS_ON_DOT_RE = re.compile(r"(?<=[A-Za-z0-9])\.(?=[ \t]+[a-z])")
_ITEM_RE = re.compile(r"\bItem\s+(?:[0-9]{1,2}[A-C]?)?$", re.I)
# A quoted reference in DART text names a numbered field, and the field's own list markers
# stay inside it: "상기 '8. 취득전 자기주식보유현황 - 기타취득'",
# "『Ⅲ. 재무에 관한 사항 중 3. 연결재무제표 주석』".
_QUOTES = (("'", "'"), ("‘", "’"), ("「", "」"), ("『", "』"))
_BULLETS = frozenset("•◦▪●·")


def _soft_breaks(text: str) -> set[int]:
    """Positions of the line breaks that are not cuts: a soft wrap, a break inside a quote or
    bracket that is still open since the last cut, or a break after a bullet alone on its line."""
    wraps = {m.group(0).index("\n") + m.start() for m in _WRAP_RE.finditer(text)}
    segment = 0
    for m in re.finditer(r"\n", text):
        at = m.start()
        if at in wraps:
            continue
        open_text = text[segment:at]
        still_open = (open_text.count("“") > open_text.count("”")
                      or open_text.count("(") > open_text.count(")"))  # fmt: skip
        line = text[text.rfind("\n", 0, at) + 1 : at].strip()
        if (still_open and _RUNS_ON_RE.match(text, at + 1)) or line in _BULLETS:
            wraps.add(at)
        else:
            segment = at + 1
    return wraps


def _in_quote(text: str, start: int, at: int) -> bool:
    """Whether ``at`` sits inside a short quoted reference in Korean text that opened after
    ``start``, the last cut before it, and closes within the next few words."""
    back = text[max(start, at - 80) : at]
    if not re.search(r"[가-힣]", back):
        return False
    end = text.find("\n", at)
    ahead = text[at : min(at + 80, len(text) if end == -1 else end)]
    for opening, closing in _QUOTES:
        if opening == closing:
            still_open = back.count(opening) % 2 == 1
        else:
            still_open = back.count(opening) > back.count(closing)
        if still_open and closing in ahead:
            return True
    return False


def split_sentences(text: str) -> list[Sentence]:
    """The source text cut at line breaks, sentence ends and DART list markers, each piece with
    its offsets into ``text``. A soft-wrapped line break is not a cut, so a sentence can hold a
    line break; its text is still ``text[start:end]``. Lines the pipeline adds around the
    filing's text are left out."""
    cuts = {0, len(text)}
    headers = [(m.start(), m.end()) for m in _HEADER_RE.finditer(text)]
    wraps = _soft_breaks(text)
    breaks = [m.start() for m in re.finditer(r"\n", text) if m.start() not in wraps]
    cuts.update(breaks)
    cuts.update(at + 1 for at in breaks)
    not_ends = {m.start() for m in _NAME_DOT_RE.finditer(text)}
    not_ends.update(m.start(1) for m in _DATE_DOT_RE.finditer(text))
    not_ends.update(m.start() for m in _RUNS_ON_DOT_RE.finditer(text))
    for match in _STOP_RE.finditer(text):
        if match.start() in not_ends:
            continue
        before = text[max(0, match.start() - 4) : match.start()]
        word = re.search(r"([A-Za-z.]+)$", before)
        if word and word.group(1).lower().strip(".") in _ABBREVIATIONS:
            continue
        if re.search(r"(?:^|\s)[A-Z]$", before):  # an initial: "Joseph E. Creed"
            continue
        wide = text[max(0, match.start() - 9) : match.start()]
        if _FIELD_NUMBER_RE.search(wide[-6:]) or _ITEM_RE.search(wide):
            continue  # "5." "가." "'4." "상기4." "'II." "Item 1A."
        after = text[match.end() : match.end() + 2]
        if after[:1] in "\"'”’" and after[1:] in ("", " ", "\n", "\t"):
            cuts.add(match.end() + 1)  # the quote closes with the sentence: Nation." The
        elif after[:1] not in "”’":
            cuts.add(match.end())
    ordered = sorted(cuts)
    for m in _MARKER_RE.finditer(text):
        last = ordered[bisect.bisect_right(ordered, m.start()) - 1]
        if _ITEM_RE.search(text[max(0, m.start() - 9) : m.start()]):
            continue  # "Item 1. Business" is one reference
        if not _in_quote(text, last, m.start()):
            cuts.add(m.start())
    sentences = []
    ordered = sorted(cuts)
    for start, end in zip(ordered, ordered[1:], strict=False):
        piece = text[start:end]
        stripped = piece.strip()
        if len(stripped) < 2:
            continue
        offset = start + (len(piece) - len(piece.lstrip()))
        end_at = offset + len(stripped)
        if any(a <= offset and end_at <= b for a, b in headers):  # a line the pipeline added
            continue
        sentences.append(Sentence(offset, end_at, stripped))
    return sentences


# -- line items ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    kind: str  # 'term' | 'latin' | 'number' | 'ko' | 'en'
    value: str  # entry id, latin word, digits, or the word
    stems: tuple[str, ...] = ()
    strict: bool = False
    surface: str = ""  # a term's text in the line
    loose: str = ""  # why a place or product does not block: an ambiguous form or a name

    @property
    def weight(self) -> int:
        return ENTITY_WEIGHT if self.kind in ("term", "latin", "number") else WORD_WEIGHT

    @property
    def label(self) -> str:
        return self.value


_NAME_NEXT_RE = re.compile(r"\s+[A-Z][a-z]")
_NAME_PREV_RE = re.compile(r"([A-Z][a-z]+)\s+$")
_NAME_STARTERS = frozenset({"The", "In", "For", "From", "To", "And", "Its"})


def line_items(line: str, lexicon: Lexicon) -> list[Item]:
    """The words of ``line`` the check looks for: lexicon terms first, then the remaining
    Latin words, numbers and content words. Frame words (회사는, The company said) are left out.

    A place followed by a capitalised word is read as part of a name (Korea Athletics
    Federation), and an ambiguous form (인도) is read as a word; neither blocks on its own."""
    items: list[Item] = []
    seen: set[tuple[str, str]] = set()
    masked = list(line)
    terms = scan_terms(line, lexicon)
    starts = {start for _, start, _ in terms}
    for term_id, start, end in terms:
        masked[start:end] = " " * (end - start)
        surface = line[start:end]
        loose = ""
        if surface in lexicon.ambiguous:
            loose = f"{surface} has another meaning"
        elif _LATIN_RE.match(surface):
            after = _NAME_NEXT_RE.match(line, end)
            before = _NAME_PREV_RE.search(line[:start])
            if (after and after.end() - 1 not in starts) or (
                before and before.start() > 0 and before.group(1) not in _NAME_STARTERS
            ):
                loose = f"{surface} is part of a name"
        if ("term", term_id) not in seen:
            seen.add(("term", term_id))
            strict = term_id in lexicon.strict and not loose
            items.append(Item("term", term_id, strict=strict, surface=surface, loose=loose))
    rest = "".join(masked)
    for match in _TOKEN_RE.finditer(rest):
        token = match.group()
        if token[0].isdigit():
            item = Item("number", _digits(token), strict=True)
        elif _HANGUL_RE.match(token):
            stems = ko_stems(token)
            if any(stem in _KO_STOP for stem in stems) or len(stems[-1]) < 2:
                continue
            # What is left of a word around a term (이천시에 -> 시에) is a particle, not a word.
            lo, hi = match.start(), match.end()
            touches = (lo > 0 and rest[lo - 1] == " " != line[lo - 1]) or (
                hi < len(line) and rest[hi] == " " != line[hi]
            )
            if touches and len(token) <= 2:
                continue
            item = Item("ko", token, stems)
        elif _is_acronym(token) or (token[0].isupper() and match.start() > 0
                                    and not line[: match.start()].rstrip().endswith(".")):
            if token in ("The", "Korean", "English"):
                continue
            item = Item("latin", token, strict=_is_acronym(token))
        else:
            key = en_key(token)
            if token.lower() in _EN_STOP or key in _EN_STOP or len(key) < 3:
                continue
            item = Item("en", key)
        if (item.kind, item.value) not in seen:
            seen.add((item.kind, item.value))
            items.append(item)
    return items


# -- source index --------------------------------------------------------------------------------


@dataclass
class _Indexed:
    sentence: Sentence
    flat: str  # lower case, spaces removed: for Korean stems and Latin words
    lower: str
    en_keys: tuple[str, ...]
    terms: frozenset[str]


class SourceIndex:
    def __init__(self, text: str, lexicon: Lexicon) -> None:
        self.text = text
        self.lang = script_of(text)
        self.lexicon = lexicon
        self.sentences = [self._index(s) for s in split_sentences(text)]
        self.terms = frozenset(t for s in self.sentences for t in s.terms)
        self.flat = "".join(s.flat for s in self.sentences)
        self.lower = " ".join(s.lower for s in self.sentences)

    def _index(self, sentence: Sentence) -> _Indexed:
        text = sentence.text
        lower = text.lower()
        keys = tuple(
            en_key(t) for t in _TOKEN_RE.findall(text) if _LATIN_RE.match(t)
        )  # fmt: skip
        terms = frozenset(term_id for term_id, _, _ in scan_terms(text, self.lexicon))
        return _Indexed(sentence, re.sub(r"\s+", "", lower).replace(",", ""), lower, keys, terms)

    def matches(self, item: Item, at: _Indexed) -> bool:
        if item.kind == "term":
            return item.value in at.terms or bool(item.loose and item.surface.lower() in at.flat)
        if item.kind == "number":
            return item.value in at.flat
        if item.kind == "latin":
            return _latin_in(item.value, at.lower) or _spelled_out(item.value, at.sentence.text)
        if item.kind == "ko":
            return any(len(stem) >= 2 and stem in at.flat for stem in item.stems)
        return _en_matches(item.value, at.en_keys)

    def present(self, item: Item) -> bool:
        """Whether the source names ``item`` anywhere."""
        if item.kind == "term" and item.value in self.terms:
            return True
        if item.kind == "number":
            return item.value in self.flat
        if item.kind == "latin":
            return _latin_in(item.value, self.lower) or _spelled_out(item.value, self.text)
        return any(self.matches(item, s) for s in self.sentences)


def _latin_in(word: str, lower: str) -> bool:
    """Whether ``word`` is a word of ``lower``, also with dots dropped (JP, J.P.). An acronym
    of three or more letters may sit inside a longer one (RNA in mRNA, HBM in HBM3E)."""
    key = re.escape(word.lower())
    if _is_acronym(word) and len(word) >= 3:
        pattern = key
    elif _is_acronym(word):
        pattern = rf"(?<![a-z0-9]){key}(?![a-z])"
    else:
        pattern = rf"(?<![a-z0-9]){key}(?![a-z0-9])"
    return any(re.search(pattern, text) for text in (lower, lower.replace(".", "")))


def _spelled_out(word: str, text: str) -> bool:
    """Whether ``text`` spells out the acronym ``word``: DTC, The Depository Trust Company."""
    if not _is_acronym(word) or not 2 <= len(word) <= 5 or not word.isalpha():
        return False
    pattern = r"\s+".join(rf"{letter}[a-z]+" for letter in word)
    return re.search(rf"(?<![A-Za-z]){pattern}(?![A-Za-z])", text) is not None


# -- verdicts ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LineResult:
    lang: str
    line_no: int
    text: str
    verdict: str
    coverage: Fraction
    method: str  # 'direct' | 'pivot' | 'terms' | 'template' | 'no_source'
    spans: tuple[Sentence, ...] = ()
    reasons: tuple[str, ...] = ()

    def record(self) -> dict[str, Any]:
        return {
            "lang": self.lang,
            "line_no": self.line_no,
            "line_sha256": line_sha256(self.text),
            "verdict": self.verdict,
            "coverage": _ratio(self.coverage),
            "method": self.method,
            "spans": [{"start": s.start, "end": s.end, "text": s.text} for s in self.spans],
            "reasons": list(self.reasons),
        }


def line_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ratio(value: Fraction) -> str:
    return str((Decimal(value.numerator) / Decimal(value.denominator)).quantize(Decimal("0.01")))


def _lower(verdict: str, cap: str) -> str:
    return verdict if _RANK[verdict] <= _RANK[cap] else cap


def _polarity(text: str, lang: str) -> tuple[bool, bool, bool]:
    """(negated, up, down) for a line or span in ``lang``."""
    if lang == "ko":
        return (bool(_KO_NEGATION.search(text)), bool(_KO_UP.search(text)),
                bool(_KO_DOWN.search(text)))  # fmt: skip
    return (bool(_EN_NEGATION.search(text)), bool(_EN_UP.search(text)),
            bool(_EN_DOWN.search(text)))  # fmt: skip


def _polarity_reasons(line: tuple[bool, bool, bool], other: tuple[bool, bool, bool]) -> list[str]:
    reasons = []
    if line[0] != other[0]:
        reasons.append("negation differs")
    if (line[1] and not line[2] and other[2] and not other[1]) or (
        line[2] and not line[1] and other[1] and not other[2]
    ):
        reasons.append("direction differs")
    return reasons


def _best_span(items: Sequence[Item], index: SourceIndex) -> tuple[list[_Indexed], set[int]]:
    hits = [
        {n for n, item in enumerate(items) if index.matches(item, s)} for s in index.sentences
    ]

    def weight(found: set[int]) -> int:
        return sum(items[n].weight for n in found)

    chosen: list[int] = []
    covered: set[int] = set()
    for _ in range(MAX_SPAN_SENTENCES):
        best, gain = None, 0
        for number, found in enumerate(hits):
            extra = weight(found - covered)
            if number not in chosen and extra > gain:
                best, gain = number, extra
        if best is None:
            break
        chosen.append(best)
        covered |= hits[best]
    # The first sentence chosen carries the claim; the second only adds words.
    return [index.sentences[n] for n in chosen], covered


def check_direct(lang: str, line_no: int, line: str, index: SourceIndex) -> LineResult:
    """A line in the source's own language."""
    items = line_items(line, index.lexicon)
    if not items:
        return LineResult(lang, line_no, line, PARTLY, Fraction(0), "direct",
                          reasons=("no content words",))  # fmt: skip
    span, covered = _best_span(items, index)
    total = sum(item.weight for item in items)
    coverage = Fraction(sum(items[n].weight for n in covered), total)
    reasons = []
    missing = [item for n, item in enumerate(items) if n not in covered]
    absent = [item for item in missing if item.strict and not index.present(item)]
    if absent:
        verdict = UNSUPPORTED
        reasons.append("not in source: " + ", ".join(item.label for item in absent))
    elif coverage >= SUPPORTED_AT:
        verdict = SUPPORTED
    elif coverage >= PARTLY_AT:
        verdict = PARTLY
    else:
        verdict = UNSUPPORTED
    if missing and not absent:
        reasons.append("not in span: " + ", ".join(item.label for item in missing))
    main = span[0] if span else None
    clash = _rival_clash(items, main, index.lexicon)
    if clash:
        verdict = UNSUPPORTED
        reasons.append(clash)
    polarity = _negation_clash(line, lang, items, span, index)
    if polarity:
        reasons.append(polarity)
        verdict = _lower(verdict, PARTLY)
    if main is not None:
        direction = _polarity_reasons(_polarity(line, lang), _polarity(main.sentence.text, lang))
        direction = [r for r in direction if r == "direction differs"]
        if direction:
            reasons += direction
            verdict = _lower(verdict, PARTLY)
    return LineResult(lang, line_no, line, verdict, coverage, "direct",
                      tuple(s.sentence for s in span), tuple(reasons))  # fmt: skip


def _rival_clash(items: Sequence[Item], main: _Indexed | None, lexicon: Lexicon) -> str:
    """A term the line names that its main sentence lacks while naming a rival of it: the line
    says cancel, the sentence says dispose."""
    if main is None:
        return ""
    for item in items:
        if item.kind != "term" or item.value in main.terms:
            continue
        rivals = lexicon.rivals.get(item.value, frozenset()) & main.terms
        if rivals:
            return f"source sentence says {', '.join(sorted(rivals))}, not {item.value}"
    return ""


def _negation_clash(
    line: str, lang: str, items: Sequence[Item], span: Sequence[_Indexed], index: SourceIndex
) -> str:
    """Whether a span sentence that carries at least half of the line's words is negated where
    the line is not, or the reverse."""
    negated = _polarity(line, lang)[0]
    total = sum(item.weight for item in items)
    for at in span:
        weight = sum(item.weight for item in items if index.matches(item, at))
        if weight * 2 >= total and _polarity(at.sentence.text, lang)[0] != negated:
            return "negation differs"
    return ""


def check_crossed(
    lang: str, line_no: int, line: str, index: SourceIndex, twin: LineResult | None
) -> LineResult:
    """A line in the other language, checked through its parallel line ``twin``.

    Its own places, products, currencies and numbers must be in the source, and against an
    English source so must its Latin words. Against a Korean source a Latin name cannot be
    checked (NVIDIA is 엔비디아 there) and is only noted."""
    items = line_items(line, index.lexicon)
    checkable = [item for item in items if item.kind in ("term", "latin", "number")]
    reasons = []
    missing = [item for item in checkable if not index.present(item)]
    strict_absent = [
        item for item in missing
        if item.strict and (item.kind != "latin" or index.lang == "en")
        or (item.kind == "latin" and index.lang == "en")
    ]  # fmt: skip
    soft_absent = [item for item in missing if item.kind == "term" and not item.strict
                   and not item.loose]  # fmt: skip
    unchecked = [item for item in missing if item not in strict_absent and item not in soft_absent]
    if twin is None:
        found = [item for item in checkable if item not in missing]
        total = sum(item.weight for item in checkable)
        coverage = Fraction(sum(i.weight for i in found), total) if total else Fraction(0)
        verdict = PARTLY if coverage >= PARTLY_AT else UNSUPPORTED
        reasons.append("no parallel line; checked by terms only")
        method, spans = "terms", ()
    else:
        verdict, coverage, method, spans = twin.verdict, twin.coverage, "pivot", twin.spans
        if twin.verdict != SUPPORTED:
            reasons.append(f"parallel line is {twin.verdict}")
        polarity = _polarity_reasons(_polarity(line, lang), _polarity(twin.text, twin.lang))
        if polarity:
            reasons += polarity
            verdict = _lower(verdict, PARTLY)
    if strict_absent:
        verdict = UNSUPPORTED
        reasons.append("not in source: " + ", ".join(item.label for item in strict_absent))
    if soft_absent:
        verdict = _lower(verdict, PARTLY)
        reasons.append("term not in source: " + ", ".join(item.label for item in soft_absent))
    if unchecked:
        reasons.append("not checked: " + ", ".join(item.loose or item.label for item in unchecked))
    return LineResult(lang, line_no, line, verdict, coverage, method, spans, tuple(reasons))


def check_section(
    lines: Mapping[str, Sequence[str]], source: str, lexicon: Lexicon | None = None
) -> dict[str, list[LineResult]]:
    """Every line of one summary section, both languages, against its source text."""
    index = SourceIndex(source, lexicon or load_lexicon())
    results: dict[str, list[LineResult]] = {}
    own = index.lang
    results[own] = [
        check_direct(own, n, line, index) for n, line in enumerate(lines.get(own, ()), start=1)
    ]
    for lang in lines:
        if lang == own:
            continue
        twins = results[own]
        results[lang] = [
            check_crossed(lang, n, line, index, twins[n - 1] if n <= len(twins) else None)
            for n, line in enumerate(lines[lang], start=1)
        ]
    return results


# -- summary rows --------------------------------------------------------------------------------


def row_lines(row: Mapping[str, Any]) -> list[str]:
    return [line for line in (row.get("line1"), row.get("line2"), row.get("line3")) if line]


@dataclass(frozen=True)
class Source:
    text: str | None
    template: bool = False


def check_pair(rows: Sequence[Mapping[str, Any]], source: Source | None) -> list[dict[str, Any]]:
    """Records for the rows of one filing section (one row per language)."""
    lines = {row["lang"]: row_lines(row) for row in rows}
    by_lang: dict[str, list[LineResult]]
    if any(row.get("model") == TEMPLATE_MODEL for row in rows):
        by_lang = {lang: [LineResult(lang, n, line, TEMPLATE, Fraction(0), TEMPLATE)
                          for n, line in enumerate(ls, start=1)]
                   for lang, ls in lines.items()}  # fmt: skip
    elif source is None or not source.text:
        by_lang = {lang: [LineResult(lang, n, line, NO_SOURCE, Fraction(0), NO_SOURCE,
                                     reasons=("no source text for this section",))
                          for n, line in enumerate(ls, start=1)]
                   for lang, ls in lines.items()}  # fmt: skip
    else:
        by_lang = check_section(lines, source.text)
    records = []
    for row in rows:
        for result in by_lang.get(row["lang"], ()):
            records.append(
                {
                    "filing_id": row["filing_id"],
                    "section": row["section"],
                    "input_sha256": row["input_sha256"],
                    "review_state": row.get("review_state"),
                    "model": row.get("model"),
                    "source_sha256": None if not source or not source.text
                    else line_sha256(source.text),
                    "aligner_version": ALIGNER_VERSION,
                    "lexicon_version": load_lexicon().version,
                    **result.record(),
                }
            )
    return records


def check_rows(
    rows: Iterable[Mapping[str, Any]], sources: Mapping[tuple[str, str], Source]
) -> list[dict[str, Any]]:
    """Records for every line of ``rows``, grouped by (filing, section, input key, state)."""
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["filing_id"], row["section"], row.get("review_state") or "",
               row.get("model") or "")  # fmt: skip
        groups[key].append(row)
    records = []
    for (filing_id, section, _, _), members in sorted(groups.items()):
        records += check_pair(members, sources.get((filing_id, section)))
    return records


def record_key(record: Mapping[str, Any]) -> tuple[str, str, str, int]:
    return (record["filing_id"], record["lang"], record["section"], record["line_no"])


def write_records(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    ordered = sorted(records, key=lambda r: (record_key(r), r.get("review_state") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        for r in ordered
    )
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# -- release gate --------------------------------------------------------------------------------


@dataclass
class ReleaseGate:
    """What ``app.build.verify --release`` checks for every summary line in a bundle: a record
    from this aligner version for exactly that line and approval, whose verdict the policy does
    not block, unless the owner accepted that line (``accept``)."""

    records: Sequence[Mapping[str, Any]]
    policy: str = DEFAULT_POLICY
    accepted: Sequence[Mapping[str, Any]] = ()
    notes: list[str] = field(default_factory=list)
    missing: Path | None = None  # the report file, when it does not exist

    def problems(self, summaries: Sequence[Mapping[str, Any]]) -> list[str]:
        if self.policy not in POLICIES:
            return [f"faithfulness policy {self.policy!r} is not one of {sorted(POLICIES)}"]
        if self.policy == "off":
            self.notes.append("faithfulness: not checked (policy off)")
            return []
        if self.missing is not None:
            problem = (f"no faithfulness report at {self.missing}; "
                       "run python -m app.build.faithfulness check")  # fmt: skip
            if self.policy == "warn":
                self.notes.append(f"faithfulness: {problem}")
                return []
            return [problem]
        blocking = POLICIES[self.policy]
        by_key: dict[tuple[str, str, str, int], list[Mapping[str, Any]]] = defaultdict(list)
        for record in self.records:
            by_key[record_key(record)].append(record)
        accepted = {
            (record_key(a), a["line_sha256"], a["input_sha256"]) for a in self.accepted
        }
        counts: Counter[str] = Counter()
        problems = []
        for summary in summaries:
            for number, line in enumerate(row_lines(summary), start=1):
                key = (summary["filing_id"], summary["lang"], summary["section"], number)
                where = f"{key[0]} {key[1]}/{key[2]} line {number}"
                digest = line_sha256(line)
                match = [
                    r for r in by_key.get(key, ())
                    if r["line_sha256"] == digest and r["input_sha256"] == summary["input_sha256"]
                    and r.get("aligner_version") == ALIGNER_VERSION
                ]  # fmt: skip
                if (key, digest, summary["input_sha256"]) in accepted:
                    counts["accepted"] += 1
                    continue
                if not match:
                    counts["unchecked"] += 1
                    problems.append(f"{where}: no faithfulness record from {ALIGNER_VERSION} "
                                    "for this line; rerun the check")  # fmt: skip
                    continue
                verdict = match[0]["verdict"]
                counts[verdict] += 1
                if verdict in blocking:
                    reasons = "; ".join(match[0].get("reasons") or ())
                    problems.append(f"{where}: faithfulness {verdict}"
                                    + (f" ({reasons})" if reasons else ""))  # fmt: skip
        self.notes.append(
            f"faithfulness (policy {self.policy}, {ALIGNER_VERSION}): "
            + ", ".join(f"{name} {counts[name]}" for name in
                        (*VERDICTS, TEMPLATE, NO_SOURCE, "accepted", "unchecked"))
        )  # fmt: skip
        return problems if self.policy != "warn" else []


def load_gate(
    policy: str, report: Path = REPORT_PATH, accepted: Path = ACCEPTED_PATH
) -> ReleaseGate:
    missing = None if report.exists() else report
    return ReleaseGate(read_records(report), policy, read_records(accepted), missing=missing)


# -- eval ----------------------------------------------------------------------------------------


@dataclass
class EvalResult:
    pairs: list[tuple[dict[str, Any], str, LineResult]]  # (case, gold, result)

    def subset(self, **where: str) -> EvalResult:
        return EvalResult([p for p in self.pairs if all(_case_field(p, k) == v
                                                         for k, v in where.items())])  # fmt: skip

    def confusion(self) -> dict[str, dict[str, int]]:
        table = {gold: {got: 0 for got in VERDICTS} for gold in VERDICTS}
        for _, gold, result in self.pairs:
            table[gold][result.verdict] += 1
        return table

    def precision_recall(self, positive: frozenset[str]) -> tuple[int, int, int]:
        """(true positives, predicted positives, gold positives) for ``positive`` verdicts."""
        tp = sum(1 for _, g, r in self.pairs if g in positive and r.verdict in positive)
        predicted = sum(1 for _, _, r in self.pairs if r.verdict in positive)
        gold = sum(1 for _, g, _ in self.pairs if g in positive)
        return tp, predicted, gold


def _case_field(pair: tuple[dict[str, Any], str, LineResult], name: str) -> str:
    case, _, result = pair
    return result.lang if name == "lang" else str(case.get(name))


def run_eval(
    cases_path: Path = EVAL_CASES_PATH, sources_path: Path = EVAL_SOURCES_PATH
) -> EvalResult:
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    pairs = []
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        results = check_section(case["lines"], sources[case["source"]])
        for lang, golds in case["gold"].items():
            for number, gold in enumerate(golds, start=1):
                if gold is None:
                    continue
                if gold not in VERDICTS:
                    raise ValueError(f"{case['id']}: gold {gold!r} is not a verdict")
                pairs.append((case, gold, results[lang][number - 1]))
    return EvalResult(pairs)


def _pr_text(name: str, tp: int, predicted: int, gold: int) -> str:
    def pct(part: int, whole: int) -> str:
        if whole == 0:
            return "n/a"
        return f"{(Decimal(part) * 100 / Decimal(whole)).quantize(Decimal('0.1'))}%"

    return (f"{name}: precision {tp}/{predicted} ({pct(tp, predicted)}), "
            f"recall {tp}/{gold} ({pct(tp, gold)})")  # fmt: skip


def eval_report(result: EvalResult, show: bool = False) -> list[str]:
    out = [f"aligner {ALIGNER_VERSION}, lexicon {load_lexicon().version}: {len(result.pairs)} "
           "labelled lines"]  # fmt: skip
    for title, part in (("all", result), ("dev", result.subset(split="dev")),
                        ("test", result.subset(split="test")), ("ko", result.subset(lang="ko")),
                        ("en", result.subset(lang="en"))):  # fmt: skip
        if not part.pairs:
            continue
        out.append(f"[{title}] {len(part.pairs)} lines")
        out.append("  " + _pr_text("unsupported", *part.precision_recall(frozenset({UNSUPPORTED}))))
        flagged = part.precision_recall(frozenset({PARTLY, UNSUPPORTED}))
        out.append("  " + _pr_text("flagged (partly or unsupported)", *flagged))
    out.append("confusion (rows gold, columns predicted: supported partly unsupported)")
    for gold, row in result.confusion().items():
        out.append(f"  {gold:<11} " + " ".join(f"{row[v]:>3}" for v in VERDICTS))
    if show:
        for case, gold, line in result.pairs:
            if gold != line.verdict:
                out.append(f"  MISS {case['id']} {line.lang}{line.line_no} gold {gold} got "
                           f"{line.verdict} {_ratio(line.coverage)} "
                           + "; ".join(line.reasons))  # fmt: skip
    return out


# -- command line --------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.build.faithfulness",
        description="Find the source sentence behind each summary line (D97).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="check summary rows against their source text")
    check.add_argument("--as-of", required=True, help="the summary run's --as-of (YYYY-MM-DD)")
    check.add_argument("--database-url", help="default: DATABASE_URL from the settings")
    check.add_argument("--rows", type=Path, action="append",
                       help="summary rows to check, repeatable (default: approved.jsonl and "
                            "staged.jsonl)")  # fmt: skip
    check.add_argument("--out", type=Path, default=REPORT_PATH)
    check.add_argument("--list", action="store_true", help="print every flagged line")
    evaluate = commands.add_parser("eval", help="score the check on the labelled lines")
    evaluate.add_argument("--cases", type=Path, default=EVAL_CASES_PATH)
    evaluate.add_argument("--sources", type=Path, default=EVAL_SOURCES_PATH)
    evaluate.add_argument("--show", action="store_true", help="print every miss")
    accept = commands.add_parser("accept", help="owner only: let one flagged line through")
    accept.add_argument("--filing", required=True)
    accept.add_argument("--section", required=True)
    accept.add_argument("--lang", required=True, choices=LANGS)
    accept.add_argument("--line", required=True, type=int)
    accept.add_argument("--note", required=True, help="why the line is faithful")
    accept.add_argument("--rows", type=Path, default=SUMMARIES_DIR / "approved.jsonl")
    accept.add_argument("--accepted", type=Path, default=ACCEPTED_PATH)
    return parser


def _load_sources(database_url: str, as_of: str) -> dict[tuple[str, str], Source]:
    import asyncio
    import datetime

    from app.build.source import load_build_input
    from app.build.summaries import select_targets

    data = asyncio.run(load_build_input(database_url))
    return {
        (t.filing_id, t.section): Source(t.source_text, t.template is not None)
        for t in select_targets(data, datetime.date.fromisoformat(as_of))
    }


def _run_check(args: argparse.Namespace) -> int:
    from app.build.summaries import APPROVED_PATH, STAGED_PATH, read_jsonl

    database_url = args.database_url
    if database_url is None:
        from app.config import get_settings

        database_url = get_settings().database_url
    sources = _load_sources(database_url, args.as_of)
    paths = args.rows or [APPROVED_PATH, STAGED_PATH]
    rows = [row for path in paths for row in read_jsonl(path)]
    records = check_rows(rows, sources)
    write_records(args.out, records)
    counts: Counter[tuple[str, str]] = Counter(
        (r["review_state"] or "", r["verdict"]) for r in records
    )
    print(f"aligner {ALIGNER_VERSION}: {len(records)} lines from {len(rows)} rows -> {args.out}")
    for state in sorted({s for s, _ in counts}):
        print(f"  {state}: " + ", ".join(f"{v} {counts[(state, v)]}"
                                         for v in (*VERDICTS, TEMPLATE, NO_SOURCE)))  # fmt: skip
    if args.list:
        for r in records:
            if r["verdict"] in (PARTLY, UNSUPPORTED, NO_SOURCE):
                print(f"{r['verdict']:<11} {r['review_state']} {r['filing_id']} {r['lang']}/"
                      f"{r['section']} line {r['line_no']} ({r['coverage']}): "
                      + "; ".join(r["reasons"]))  # fmt: skip
    return 0


def _run_accept(args: argparse.Namespace) -> int:
    from app.build.summaries import read_jsonl

    found = [
        r for r in read_jsonl(args.rows)
        if (r["filing_id"], r["section"], r["lang"]) == (args.filing, args.section, args.lang)
    ]  # fmt: skip
    if len(found) != 1:
        print(f"refused: {len(found)} rows for {args.filing} {args.lang}/{args.section}",
              file=sys.stderr)  # fmt: skip
        return 1
    lines = row_lines(found[0])
    if not 1 <= args.line <= len(lines):
        print(f"refused: line {args.line} does not exist", file=sys.stderr)
        return 1
    entry = {
        "filing_id": args.filing, "lang": args.lang, "section": args.section,
        "line_no": args.line, "line_sha256": line_sha256(lines[args.line - 1]),
        "input_sha256": found[0]["input_sha256"], "note": args.note,
    }  # fmt: skip
    kept = [a for a in read_records(args.accepted) if record_key(a) != record_key(entry)]
    write_records(args.accepted, [*kept, entry])
    print(f"accepted {args.filing} {args.lang}/{args.section} line {args.line} -> {args.accepted}")
    return 0


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "eval":
        for line in eval_report(run_eval(args.cases, args.sources), args.show):
            print(line)
        return 0
    if args.command == "accept":
        return _run_accept(args)
    return _run_check(args)


if __name__ == "__main__":
    sys.exit(run())
