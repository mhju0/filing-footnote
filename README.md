# Filing Footnote

In progress: plain, neutral summaries of what Korean (DART) and US (SEC) companies officially filed, with the original filing one tap away.

한국(DART)과 미국(SEC) 기업이 공식 제출한 사업보고서와 이벤트 공시를 중립적인 말로 요약해 주는 앱을 만들고 있습니다.

Filing Footnote continues Filing Digest and Filing Agent, two earlier projects by the same owner, and merges them into one offline app for iPhone, iPad and Mac.

## What it is · 소개

Planned: the app will summarise annual reports and event filings (buybacks, dividends, earnings releases, executive changes) in neutral words. Every figure will be an exact decimal taken from structured filing data, and every statement will be attributed to the company that made it. The owner's principle is to never exaggerate: no hype, no judgement words, no predictions, no advice.

계획: 앱은 사업보고서와 이벤트 공시(자사주, 배당, 실적 발표, 임원 변동 등)를 중립적인 말로 요약할 예정입니다. 모든 숫자는 공시의 정형 데이터에서 가져온 정확한 소수로 보여 주고, 모든 서술은 해당 회사의 말로 표시합니다. 과장하지 않는다는 원칙에 따라 홍보성 표현, 평가 표현, 예측, 투자 조언을 쓰지 않습니다.

The finished app will run from a bundled read-only SQLite file built on the owner's Mac. A small read-only API will serve the same file. Running it will cost nothing.

## Status · 현재 상태

**Status:** v0.5.2 code base inherited from Filing Digest; Filing Footnote v0.1 is in progress.

| Area | Today | Planned for v0.1 |
|---|---|---|
| Backend | Filing Digest's FastAPI and PostgreSQL service, annual filings only | Event-filing pipeline; read-only API over the SQLite file |
| Data file | None | Bundled SQLite file with exact decimals |
| App | Filing Digest's iPhone app (SwiftUI) | One SwiftUI app for iPhone, iPad and Mac |
| Checks | `scripts/check.sh` runs lint and offline backend tests | Contract tests for the SQLite file and the text guards |

The code in this repository is still Filing Digest's backend and iPhone app. The event-filing pipeline, the SQLite build and the multiplatform app are planned and not built. [PRODUCT.md](PRODUCT.md) describes the intended product; [docs/adr/](docs/adr/) holds the proposed decisions.

## Run the checks

Requires Python 3.11.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock ruff==0.15.21
scripts/check.sh
```

The last line is `GATE: PASS` or `GATE: FAIL`. The checks run offline: no database, no API keys, and the embedding model is not loaded. The PostgreSQL suite (`make test-db`) is separate and needs a local PostgreSQL with pgvector.

## Documentation

| Document | Contents |
|---|---|
| [PRODUCT.md](PRODUCT.md) | What the product is, who it is for, and its commitments |
| [DESIGN.md](docs/design/DESIGN.md) | Visual system and screens |
| [docs/adr/](docs/adr/) | Architecture decisions |
| [DECISIONS.md](docs/DECISIONS.md) | Decision ledger; entries before D59 describe Filing Digest |
| [CONTEXT.md](CONTEXT.md) | Domain glossary |

Other files under `docs/` describe Filing Digest v0.5.2 and are kept as history.

## License

Copyright (c) 2026 Michael Ju. All rights reserved.
No license is granted for use, copying, modification, or distribution of this code as of 2026-07-30. This repository is public for portfolio review purposes only.
