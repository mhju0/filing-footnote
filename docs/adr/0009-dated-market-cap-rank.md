# ADR 0009 — Bundle a dated market-cap rank

Accepted for the internal preview, 2026-11-23.

The company directory offers a market-cap sort alongside company name and filing
recency. Market cap changes independently of filings. The app works offline and
compares rank only within the selected market, with the snapshot date visible
above the results.

The preview contains the descending order of the covered companies at the
November 20, 2026 close. The source is Stock Analysis's dated Market Cap history.
The snapshot is separate from the filing bundle and its data date. Each list
uses the values in its own currency. The values shown by the source were distinct
within each market at its published precision. We keep the order only.
Companies outside the snapshot sort after ranked companies by localized name.

| Order | Korea | US |
|---|---|---|
| 1 | [Samsung Electronics](https://stockanalysis.com/quote/krx/005930/market-cap/) | [Apple](https://stockanalysis.com/stocks/aapl/market-cap/) |
| 2 | [SK hynix](https://stockanalysis.com/quote/krx/000660/market-cap/) | [Microsoft](https://stockanalysis.com/stocks/msft/market-cap/) |
| 3 | [Samsung Biologics](https://stockanalysis.com/quote/krx/207940/market-cap/) | [Alphabet](https://stockanalysis.com/stocks/googl/market-cap/) |
| 4 | [Hyundai Motor](https://stockanalysis.com/quote/krx/005380/market-cap/) | [NVIDIA](https://stockanalysis.com/stocks/nvda/market-cap/) |
| 5 | [Kia](https://stockanalysis.com/quote/krx/000270/market-cap/) | [Amazon](https://stockanalysis.com/stocks/amzn/market-cap/) |
| 6 | [Samsung SDI](https://stockanalysis.com/quote/krx/006400/market-cap/) | [Meta](https://stockanalysis.com/stocks/meta/market-cap/) |
| 7 | [NAVER](https://stockanalysis.com/quote/krx/035420/market-cap/) | [Tesla](https://stockanalysis.com/stocks/tsla/market-cap/) |
| 8 | [LG Electronics](https://stockanalysis.com/quote/krx/066570/market-cap/) | [Walmart](https://stockanalysis.com/stocks/wmt/market-cap/) |
| 9 | [LG Chem](https://stockanalysis.com/quote/krx/051910/market-cap/) | [Costco](https://stockanalysis.com/stocks/cost/market-cap/) |

To refresh, verify the date and order for every company in each market, then
update both lists and the date in `MarketCapSnapshot` in the same change.
