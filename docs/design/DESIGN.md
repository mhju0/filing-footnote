# Filing Footnote Visual System

Direction: professional and friendly, standard native look. Apple's own apps
(Stocks, Wallet, Settings) and Stripe or Mercury are the quality bar. Each screen
shows less and offers one obvious next tap. There is no themed metaphor. This
replaces the Ledger system inherited from Filing Digest. Older files under
`explorations/` and `logos/` stay as history. Product rules are in `PRODUCT.md`.

## Palette

| Token | Hex | Use |
|---|---|---|
| Pine | `#10645B` | Primary: actions, links, selected tab, category marks |
| Saffron | `#E9A23B` | Accent: only the "새 공시" tag, plus at most one highlight per screen. Text on it is Ink |
| Ink | `#152A31` | Text and the dark latest-filing card |
| Tint | `#E7F0EE` | Category mark and selected-row background |
| Background | `#F5F6F8` | Screen background |
| Muted | `#5B6475` | Secondary text |
| Line | `#E6E9EE` | Separators |

Measured contrast: white on Pine 7.01, Ink on Saffron 6.89, white on Ink 14.92,
Pine on Tint 6.04. Dark appearance values are chosen and measured before the
first UI milestone ships.

## Rules

- SF system fonts only. Numbers use tabular figures.
- Layout floor is iPhone mini (375 pt wide). Targets are at least 44 pt.
- Korean wraps only between words (`keep-all` behaviour).
- Direction is always a sign plus a word ("+6.4% 늘었어요"), never colour alone.
  Korean markets read red as up, so up and down do not use red or green alone.
- Not used: cream backgrounds, pill buttons, italic accents, monospace labels.
- Dynamic Type, VoiceOver labels on every figure and control, light and dark.

## Tabs

기업 · 소식 · 용어

## Screens

1. **Companies list.** Grouped list of companies; tap one.
2. **Company page.** Dark latest-filing card (Ink), the three most recent filings
   with category tags, and one 핵심 숫자 row.
3. **Filing detail.** Three-line summary, 공시에 적힌 숫자, a glossary link, and
   원문 보기 to open the source filing.
4. **Annual at a glance.** One line, then four sections: 무슨 사업, 무엇이 바뀌었나,
   회사가 꼽은 위험, 핵심 숫자.
5. **Figure.** What the number means, earlier years, and the calculation.
6. **Compare with last year.** Same company, metric and basis, with the calculation.
7. **Compare with another company.** Growth rates only, with a caveat about
   accounting standards and year-ends. No currency conversion.
8. **Refusal.** Says plainly why a comparison is not possible and what is.
