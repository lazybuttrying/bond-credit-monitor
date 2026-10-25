# Bond Credit Monitor Dashboard — build spec

## Data (already computed, do NOT recompute methodology)
- `~/workspace/bond-data/issuers.json` — main dataset
  - `meta`: {last_date, first_date, n_days, universe[25 issuers]}
  - `series`: {issuer: {rating, industry, dates[], spread[], spread_sm[], vs_peer[], chg_5d[], n[]}}
    - spread = company spread in bp (already tenor-matched vs KTB, amount-weighted)
    - spread_sm = 5-trading-day rolling median (plot this, not raw)
    - vs_peer = spread_sm minus same-rating peer median
  - `industries`: {industry: {dates[], spread_sm[]}} — industry daily medians
  - `latest_table`: [{issuer, rating, industry, spread, vs_peer, chg_5d, chg_20d, n, in_universe}]
- `~/workspace/bond-data/dashboard_data.json` — KTB yield curve history
  - `curve`: [{date, bucket, yld}] bucket in [3M,6M,1Y,2Y,3Y,5Y,10Y,20Y,30Y]
  - use latest date + ~30 days prior for the curve chart

## Page sections (Korean UI, mobile-first, max-width ~960px)
1. Header: title "회사채 신용 스프레드 모니터", subtitle with data range + update time
2. 국채 수익률 곡선: Plotly line chart, x=tenor (categorical 3M→30Y), two traces
   (latest solid, prior dotted)
3. 확대 주의보: cards for latest_table rows with chg_5d >= 15 →
   "{issuer} ({rating}) — 5일간 +{chg_5d}bp 확대, 현재 {spread}bp (동급대비 {vs_peer}bp)".
   If none: "현재 5일 기준 급격한 스프레드 확대 종목 없음"
4. 발행자 스프레드 표 (latest date): columns 발행자|등급|스프레드(bp)|동급대비(bp)|5일변화|20일변화|거래건수.
   Group rows by industry with sticky group header rows showing industry name,
   median spread and company count. Clickable column headers to sort within groups.
   Red bold when chg_5d >= 15, green when chg_5d <= -15.
5. 발행자 추이: dropdown of universe issuers → Plotly time series with 3 traces:
   issuer spread_sm (blue solid), same-rating peer median (gray dashed, = spread_sm - vs_peer),
   industry median (orange dotted, from industries[series.industry]).
6. Footnote explaining methodology: spread = corporate yield − tenor-matched KTB yield,
   amount-weighted; vs_peer = vs same-rating median; smoothed with 5-day rolling median;
   issuers with < 3 trades/day excluded.

## Technical
- Single page, Plotly.js via CDN, data embedded as JSON (no runtime fetches)
- Industries: 은행, 카드, 캐피탈, 금융지주, 증권, 보험, 정책금융, 공기업, 국채/통안, SPC, 일반기업
