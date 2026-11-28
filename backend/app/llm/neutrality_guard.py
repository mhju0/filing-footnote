"""Neutrality guard for generated filing summaries: rules N1 to N9.

Pure validation, no network, no repair. It decides whether a generated summary line
may ship. Word lists and patterns live in ``contracts/neutrality-lexicon.json`` so the
owner can review them; this module only compiles and applies them.

Every check runs on the line after NFKC normalisation with format characters removed,
and every ``Violation.span`` indexes into that normalised text. N9 is a warning rule:
its hits come only from :func:`line_warnings` / :func:`summary_warnings` and never
from the ``check_*`` functions.

A caller that has the filing passes it as a :class:`Source`. Two narrow allowances (D111)
need it and stay closed without it: an N1 label (a year, quarter, round, numbered plant or
SEC form name) passes only when the source holds the same label, and a Korean line one may
end in a report-type ending only when the filing's title is that report type. A line where a
year, quarter, round or plant label passed (plants since D112) puts the whole summary under N3
`dated_future` (future, plan, target and outlook forms), so a source-held label cannot carry
a dated forecast. On every line, an attributed prediction (`attributed_prediction`:
-ㄹ 거라고, "said ... would") fails N3.
"""

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.llm.number_guard import (
    _KOREAN_SPELLED_RE,
    _SPELLED_FINANCIAL_RE,
    _SPELLED_NUMBER,
    _SPELLED_PREFIX_RE,
)

Lang = Literal["ko", "en"]

LEXICON_PATH = Path(__file__).resolve().parents[3] / "contracts" / "neutrality-lexicon.json"

_EN_SUFFIXES = "s|es|ed|d|ing|ly|ness|en|ened|ening|less"
_EN_E_SUFFIXES = "e|es|ed|ing|ely|ly|y"
_EN_Y_SUFFIXES = "y|ies|ied|ying"
_EN_COMPARATIVE = "er|est"

# number_guard's Korean pattern needs the unit and 원 joined; these add the spaced
# forms (천억 원, 삼조 원), share counts and a bare magnitude used as an amount (일조 규모).
_KO_NUMERAL = "일이삼사오육칠팔구"
_KO_UNIT = "십백천만억조"
_KO_SPACED_AMOUNT_RE = re.compile(
    rf"(?<![가-힣])[{_KO_NUMERAL}{_KO_UNIT}]*[{_KO_UNIT}]\s?"
    r"(?:원(?![칙가본료화래인격자천])|달러|퍼센트|%)"
)
# At least two syllables ending in a unit, so 사주, 구주, 이주 and 천주교 stay clear.
_KO_SHARE_COUNT_RE = re.compile(
    rf"(?<![가-힣])[{_KO_NUMERAL}{_KO_UNIT}]*[{_KO_NUMERAL}{_KO_UNIT}][{_KO_UNIT}]\s?주"
)
# Leading markdown is N6's business; N4 looks at the words after it.
_LEADING_MARKUP_RE = re.compile(r"^[\s#>*+\-]*")
_KO_BARE_MAGNITUDE_RE = re.compile(
    rf"(?<![가-힣])[{_KO_NUMERAL}{_KO_UNIT}]*[{_KO_NUMERAL}][천만억조]+"
    r"(?=\s?(?:규모|어치|명|건|개|주|원|달러))"
)
_SPELLED_SYMBOL_RE = re.compile(rf"[$€£₩]\s*{_SPELLED_NUMBER}", re.IGNORECASE)
_ANY_DIGIT_RE = re.compile(r"\d")
_N1_RES = (
    _ANY_DIGIT_RE,
    _SPELLED_FINANCIAL_RE,
    _SPELLED_PREFIX_RE,
    _KOREAN_SPELLED_RE,
    _KO_SPACED_AMOUNT_RE,
    _KO_SHARE_COUNT_RE,
    _KO_BARE_MAGNITUDE_RE,
    _SPELLED_SYMBOL_RE,
)
# Hangul syllables are laid out as 0xAC00 + (initial*21 + medial)*28 + final; final 8 is ㄹ.
_RIEUL_FINAL = "".join(chr(0xAC00 + block * 28 + 8) for block in range(19 * 21))
_NIEUN_FINAL = "".join(chr(0xAC00 + block * 28 + 4) for block in range(19 * 21))
# Placeholders the N3 form-class lists use for a syllable ending in ㄹ or ㄴ (D111).
_FINAL_CLASSES = {"<ㄹ>": f"[{_RIEUL_FINAL}]", "<ㄴ>": f"[{_NIEUN_FINAL}]"}
# Label kinds that put a whole summary under N3 dated_future (D111; plants since D112).
_DATED_KINDS = frozenset({"year", "quarter", "round", "plant"})


# Spelled ordinals an N1 label may use, so "third quarter" matches the source's 3분기.
_ORDINAL_WORDS = {"first": "1", "second": "2", "third": "3", "fourth": "4"}


@dataclass(frozen=True)
class Source:
    """The filing a summary is written from: its title and the text the model saw (or, in a
    finished bundle, the title and the cited excerpts)."""

    title: str
    text: str


@dataclass(frozen=True)
class Violation:
    """One rule hit. ``line_no`` is 1-based; 0 means the summary as a whole."""

    rule_id: str
    lang: Lang | None
    line_no: int
    token: str
    span: tuple[int, int]


@dataclass(frozen=True)
class _Matcher:
    patterns: tuple[re.Pattern[str], ...]
    allow: tuple[re.Pattern[str], ...]

    def find(
        self, text: str, exempt: Sequence[tuple[int, int]] = ()
    ) -> list[tuple[str, tuple[int, int]]]:
        allowed = [m.span() for pattern in self.allow for m in pattern.finditer(text)]
        allowed += exempt
        hits = []
        for pattern in self.patterns:
            for m in pattern.finditer(text):
                start, end = m.span()
                if start == end or any(s <= start and end <= e for s, e in allowed):
                    continue
                hits.append((m.group(), (start, end)))
        return sorted(hits, key=lambda hit: hit[1])


@dataclass(frozen=True)
class _Lexicon:
    version: int
    matchers: dict[tuple[str, Lang], _Matcher]
    plan_gated: dict[Lang, tuple[re.Pattern[str], ...]]
    plan_allowed: dict[Lang, tuple[re.Pattern[str], ...]]
    ko_endings: tuple[str, ...]
    ko_subjects: tuple[str, ...]
    ko_name_particles: tuple[str, ...]
    ko_third_party_re: re.Pattern[str]
    # (title pattern, line numbers, ending pattern): N4 endings for one report type (D111).
    ko_report_endings: tuple[tuple[re.Pattern[str], frozenset[int], re.Pattern[str]], ...]
    # (kind, pattern with a "value" group): N1 labels exempt when the source has them (D111).
    labels: tuple[tuple[str, re.Pattern[str]], ...]
    # N3 forms banned in a summary where a year, quarter, round or plant label passed (D111).
    dated_future: dict[Lang, tuple[re.Pattern[str], ...]]
    # N3 attributed predictions banned on every line (D111).
    attributed_prediction: dict[Lang, tuple[re.Pattern[str], ...]]
    en_verbs: tuple[str, ...]
    en_subjects: tuple[str, ...]
    en_name_suffixes: tuple[str, ...]
    en_adverbs: tuple[str, ...]
    url_re: re.Pattern[str]
    line_count: int
    max_chars: dict[Lang, int]
    line_break_re: re.Pattern[str]
    exclamation_re: re.Pattern[str]
    markdown_res: tuple[re.Pattern[str], ...]
    emoji_re: re.Pattern[str]
    hangul_re: re.Pattern[str]


def _word(term: str) -> str:
    return re.escape(term).replace(r"\ ", r"\s+")


def _term_pattern(term: str, mode: str, adjective: bool = False) -> str:
    if mode == "substring":
        return re.escape(term)
    if mode == "word":
        return rf"\b{_word(term)}\b"
    if mode == "inflected_word":
        if " " in term or "-" in term:
            return rf"\b{_word(term)}s?\b"
        comparative = f"|{_EN_COMPARATIVE}" if adjective else ""
        if re.search(r"[^aeiou]y$", term):
            return rf"\b{re.escape(term[:-1])}(?:{_EN_Y_SUFFIXES}{comparative})\b"
        if term.endswith("e"):
            return rf"\b{re.escape(term[:-1])}(?:{_EN_E_SUFFIXES}{comparative})\b"
        return rf"\b{re.escape(term)}(?:{_EN_SUFFIXES}{comparative})?\b"
    raise ValueError(f"unknown match mode {mode!r}")


def _allow_pattern(phrase: str, mode: str) -> str:
    if mode == "substring":
        return re.escape(phrase).replace(r"\ ", r"\s?")
    return _term_pattern(phrase, "word")


def _compile_block(block: dict[str, Any]) -> _Matcher:
    mode = block["match"]
    adjectives = set(block.get("adjectives", ()))
    sources = [_term_pattern(term, mode, term in adjectives) for term in block["terms"]]
    sources += [
        rf"[{_RIEUL_FINAL}]\s?{_allow_pattern(word, 'substring')}"
        for word in block.get("after_rieul", ())
    ]
    sources += [_allow_pattern(phrase, mode) for phrase in block.get("phrases", ())]
    sources += block.get("patterns", [])
    allow = [_allow_pattern(phrase, mode) for phrase in block.get("allow", ())]
    allow += block.get("allow_patterns", [])
    return _Matcher(
        patterns=tuple(re.compile(s, re.IGNORECASE | re.MULTILINE) for s in sources),
        allow=tuple(re.compile(s, re.IGNORECASE) for s in allow),
    )


def _compile_list(sources: Sequence[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(s, re.IGNORECASE) for s in sources)


def _compile_forms(block: dict[str, Any]) -> dict[Lang, tuple[re.Pattern[str], ...]]:
    def expand(source: str) -> str:
        for token, chars in _FINAL_CLASSES.items():
            source = source.replace(token, chars)
        return source

    return {
        lang: tuple(re.compile(expand(s), re.IGNORECASE) for s in block[lang])
        for lang in ("ko", "en")
    }


@lru_cache(maxsize=4)
def load_lexicon(path: Path = LEXICON_PATH) -> _Lexicon:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = {rule["id"]: rule for rule in raw["rules"]}
    matchers = {
        (rule_id, lang): _compile_block(rules[rule_id][lang])
        for rule_id in ("N1", "N2", "N3", "N7", "N9")
        for lang in ("ko", "en")
    }
    n1, n3, n4, n6 = rules["N1"], rules["N3"], rules["N4"], rules["N6"]
    return _Lexicon(
        version=raw["version"],
        matchers=matchers,
        plan_gated={lang: _compile_list(n3[lang]["plan_gated"]) for lang in ("ko", "en")},
        plan_allowed={lang: _compile_list(n3[lang]["plan_allowed"]) for lang in ("ko", "en")},
        ko_endings=tuple(n4["ko"]["endings"]),
        ko_subjects=tuple(n4["ko"]["subjects"]),
        ko_name_particles=tuple(n4["ko"]["name_particles"]),
        ko_third_party_re=re.compile(
            r"^\s*(?:" + "|".join(map(re.escape, n4["ko"]["third_party_subjects"])) + r")들?"
            r"(?:" + "|".join(map(re.escape, n4["ko"]["third_party_particles"])) + r")(?![가-힣])"
        ),
        ko_report_endings=tuple(
            (
                re.compile(entry["title_pattern"]),
                frozenset(entry["lines"]),
                re.compile(
                    "(?:" + "|".join(_allow_pattern(e, "substring") for e in entry["endings"])
                    + ")$"
                ),
            )
            for entry in n4["ko"]["report_endings"]
        ),
        labels=tuple(
            (label["kind"], re.compile(pattern, re.IGNORECASE))
            for label in n1["labels"]
            for pattern in label["patterns"]
        ),
        dated_future=_compile_forms(n3["dated_future"]),
        attributed_prediction=_compile_forms(n3["attributed_prediction"]),
        en_verbs=tuple(n4["en"]["verbs"]),
        en_subjects=tuple(n4["en"]["subjects"]),
        en_name_suffixes=tuple(n4["en"]["name_suffixes"]),
        en_adverbs=tuple(n4["en"]["adverbs"]),
        url_re=re.compile(rules["N5"]["url_pattern"]),
        line_count=n6["line_count"],
        max_chars=dict(n6["max_chars"]),
        line_break_re=re.compile(n6["line_break_pattern"]),
        exclamation_re=re.compile(n6["exclamation_pattern"]),
        markdown_res=tuple(re.compile(s, re.MULTILINE) for s in n6["markdown_patterns"]),
        emoji_re=re.compile(n6["emoji_pattern"]),
        hangul_re=re.compile(rules["N8"]["hangul_pattern"]),
    )


def normalize(text: str) -> str:
    """NFKC, then drop format characters (zero-width joiners and the like)."""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")


def _label_value(kind: str, match: re.Match[str]) -> tuple[str, str]:
    value = match.group("value").lower()
    return kind, _ORDINAL_WORDS.get(value, value).upper()


@lru_cache(maxsize=64)
def _source_labels(
    text: str, labels: tuple[tuple[str, re.Pattern[str]], ...]
) -> frozenset[tuple[str, str]]:
    return frozenset(
        _label_value(kind, m) for kind, pattern in labels for m in pattern.finditer(text)
    )


def _label_spans(
    text: str, source: Source | None, lex: _Lexicon
) -> list[tuple[str, tuple[int, int]]]:
    """(kind, span) of the N1 labels in ``text`` that the source also holds; none without a
    source."""
    if source is None:
        return []
    known = _source_labels(normalize(source.text), lex.labels)
    return [
        (kind, m.span())
        for kind, pattern in lex.labels
        for m in pattern.finditer(text)
        if _label_value(kind, m) in known
    ]


def _report_ending(body: str, line_no: int, source: Source | None, lex: _Lexicon) -> bool:
    if source is None:
        return False
    title = normalize(source.title)
    return any(
        line_no in lines and title_re.search(title) and ending_re.search(body)
        for title_re, lines, ending_re in lex.ko_report_endings
    )


def _attribution_violations(
    text: str,
    lang: Lang,
    line_no: int,
    names: Sequence[str],
    lex: _Lexicon,
    source: Source | None = None,
) -> list[Violation]:
    found = []
    head = text[_LEADING_MARKUP_RE.match(text).end() :]
    if lang == "ko":
        body = text.rstrip(" .!?")
        if not body.endswith(lex.ko_endings) and not _report_ending(body, line_no, source, lex):
            found.append(Violation("N4", lang, line_no, "", (len(body), len(body))))
        if line_no == 1:
            subjects = list(lex.ko_subjects)
            subjects += [name + p for name in names if name for p in lex.ko_name_particles]
            if not head.startswith(tuple(subjects)):
                found.append(Violation("N4", lang, line_no, "", (0, 0)))
        third_party = lex.ko_third_party_re.match(head)
        if third_party:
            found.append(Violation("N4", lang, line_no, third_party.group(), third_party.span()))
        return found
    subjects = "|".join(_word(s) for s in lex.en_subjects)
    names_alt = "|".join(_word(normalize(n)) for n in names if n)
    if names_alt:
        suffixes = "|".join(_word(s) for s in lex.en_name_suffixes)
        subjects += rf"|(?:{names_alt})(?:,?\s+(?:{suffixes}))?"
    adverbs = "|".join(_word(a) for a in lex.en_adverbs)
    verbs = "|".join(_word(v) for v in lex.en_verbs)
    pattern = rf"^\s*(?:{subjects})\s+(?:(?:{adverbs})\s+)?(?:{verbs})\b"
    if not re.match(pattern, head, re.IGNORECASE):
        found.append(Violation("N4", lang, line_no, "", (0, 0)))
    return found


def _matcher_violations(
    rule_id: str,
    text: str,
    lang: Lang,
    line_no: int,
    lex: _Lexicon,
    exempt: Sequence[tuple[int, int]] = (),
) -> list[Violation]:
    return [
        Violation(rule_id, lang, line_no, token, span)
        for token, span in lex.matchers[(rule_id, lang)].find(text, exempt)
    ]


def _name_spans(text: str, names: Sequence[str]) -> list[tuple[int, int]]:
    return [
        m.span()
        for name in names
        if name
        for m in re.finditer(rf"(?<!\w){_word(normalize(name))}(?!\w)", text, re.IGNORECASE)
    ]


def _regex_violations(
    rule_id: str, pattern: re.Pattern[str], text: str, lang: Lang, line_no: int
) -> list[Violation]:
    return [Violation(rule_id, lang, line_no, m.group(), m.span()) for m in pattern.finditer(text)]


def uses_dated_label(
    lines: Sequence[str], source: Source | None, lexicon: _Lexicon | None = None
) -> bool:
    """Whether any line passes N1 through a year, quarter, round or plant label the source
    holds. If one does, N3 ``dated_future`` applies to every line of the summary (D111)."""
    lex = lexicon or load_lexicon()
    return any(
        kind in _DATED_KINDS
        for line in lines
        for kind, _ in _label_spans(normalize(line), source, lex)
    )


def check_line(
    line: str,
    lang: Lang,
    line_no: int = 1,
    company_names: Sequence[str] = (),
    lexicon: _Lexicon | None = None,
    source: Source | None = None,
    dated: bool | None = None,
) -> list[Violation]:
    """Return every failing-rule violation for one line (N1-N4, N6 per line, N7, N8).
    ``source`` opens the two D111 allowances described in the module docstring. ``dated``
    says whether the line's summary uses a year, quarter, round or plant label (see
    :func:`uses_dated_label`); left as None, only this line's own labels decide."""
    lex = lexicon or load_lexicon()
    text = normalize(line)
    found: list[Violation] = []

    n1: list[Violation] = []
    for pattern in _N1_RES:
        n1 += _regex_violations("N1", pattern, text, lang, line_no)
    n1 += _matcher_violations("N1", text, lang, line_no, lex)
    labels = _label_spans(text, source, lex)
    found += [v for v in n1 if not any(s <= v.span[0] and v.span[1] <= e for _, (s, e) in labels)]
    if dated is None:
        dated = any(kind in _DATED_KINDS for kind, _ in labels)
    for pattern in (*lex.attributed_prediction[lang], *(lex.dated_future[lang] if dated else ())):
        found += _regex_violations("N3", pattern, text, lang, line_no)

    # Company names are exempt from N2 only: "Boost Mobile" is a name, "3M" still fails N1.
    found += _matcher_violations(
        "N2", text, lang, line_no, lex, _name_spans(text, company_names)
    )

    found += _matcher_violations("N3", text, lang, line_no, lex)
    attribution = _attribution_violations(text, lang, line_no, company_names, lex, source)
    allowed_spans = [m.span() for p in lex.plan_allowed[lang] for m in p.finditer(text)]
    for pattern in lex.plan_gated[lang]:
        for m in pattern.finditer(text):
            in_allowed_form = any(s <= m.start() and m.end() <= e for s, e in allowed_spans)
            if not (in_allowed_form and not attribution):
                found.append(Violation("N3", lang, line_no, m.group(), m.span()))

    found += attribution

    limit = lex.max_chars[lang]
    if len(text) > limit:
        found.append(Violation("N6", lang, line_no, text[limit:], (limit, len(text))))
    for pattern in (lex.line_break_re, lex.exclamation_re, *lex.markdown_res, lex.emoji_re):
        found += _regex_violations("N6", pattern, text, lang, line_no)

    found += _matcher_violations("N7", text, lang, line_no, lex)

    has_hangul = lex.hangul_re.search(text)
    if lang == "ko" and not has_hangul:
        found.append(Violation("N8", lang, line_no, "", (0, 0)))
    if lang == "en" and has_hangul:
        found += _regex_violations("N8", lex.hangul_re, text, lang, line_no)

    return found


def check_summary(
    lines: Sequence[str],
    lang: Lang,
    company_names: Sequence[str] = (),
    lexicon: _Lexicon | None = None,
    source: Source | None = None,
) -> list[Violation]:
    """Return every failing-rule violation for one language's event summary."""
    lex = lexicon or load_lexicon()
    found = []
    if len(lines) != lex.line_count:
        found.append(Violation("N6", lang, 0, "", (len(lines), len(lines))))
    return found + check_section(lines, lang, company_names, lex, source)


def check_section(
    lines: Sequence[str],
    lang: Lang,
    company_names: Sequence[str] = (),
    lexicon: _Lexicon | None = None,
    source: Source | None = None,
) -> list[Violation]:
    """Every line of one summary through :func:`check_line`, with N3 ``dated_future`` on all of
    them when any one uses a year, quarter, round or plant label (D111). No line-count check."""
    lex = lexicon or load_lexicon()
    dated = uses_dated_label(lines, source, lex)
    found = []
    for index, line in enumerate(lines, start=1):
        found += check_line(line, lang, index, company_names, lex, source, dated)
    return found


def line_warnings(
    line: str, lang: Lang, line_no: int = 1, lexicon: _Lexicon | None = None
) -> list[Violation]:
    """Return N9 soft-word hits for one line. These never block a line."""
    lex = lexicon or load_lexicon()
    return _matcher_violations("N9", normalize(line), lang, line_no, lex)


def summary_warnings(
    lines: Sequence[str], lang: Lang, lexicon: _Lexicon | None = None
) -> list[Violation]:
    lex = lexicon or load_lexicon()
    found = []
    for index, line in enumerate(lines, start=1):
        found += line_warnings(line, lang, index, lex)
    return found


def check_source_url(url: str, lexicon: _Lexicon | None = None) -> list[Violation]:
    """N5: the link must point at DART or SEC EDGAR over HTTPS."""
    lex = lexicon or load_lexicon()
    if lex.url_re.match(url):
        return []
    return [Violation("N5", None, 0, url, (0, len(url)))]
