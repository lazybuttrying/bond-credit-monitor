"""Divergence page data (#10 credit-equity divergence monitor).
English only (user rule). Run from ~/workspace/bond-data.
Stock prices: Naver fchart daily closes. Spreads: backtest/all_issuers_spread.csv.
"""
import io
import json
import os
import subprocess
import sys

import pandas as pd

DATA = os.path.dirname(os.path.abspath(__file__))
BT = os.path.join(DATA, "backtest")

# issuer (as named in all_issuers_spread.csv) -> (ticker, company whose stock it is, tier)
MAPPING = {
    "중소기업은행": ("024110", "기업은행", "A"),
    "삼성카드": ("029780", "삼성카드", "A"),
    "JB금융지주": ("175330", "JB금융지주", "A"),
    "DGB금융지주": ("139130", "iM금융지주", "A"),
    "한국전력공사": ("015760", "한국전력", "A"),
    "한국전력공사채권": ("015760", "한국전력", "A"),
    "한화생명보험": ("088350", "한화생명", "A"),
    "미래에셋증권": ("006800", "미래에셋증권", "A"),
    "삼성증권": ("016360", "삼성증권", "A"),
    "대한항공": ("003490", "대한항공", "A"),
    "한국가스공사": ("036460", "한국가스공사", "A"),
    "LG화학": ("051910", "LG화학", "A"),
    "에스케이하이닉스": ("000660", "SK하이닉스", "A"),
    "롯데케미칼": ("011170", "롯데케미칼", "A"),
    "금호타이어": ("073240", "금호타이어", "A"),
    "삼성중공업": ("010140", "삼성중공업", "A"),
    "현대글로비스": ("086280", "현대글로비스", "A"),
    "한진": ("002320", "한진", "A"),
    "현대제철": ("004020", "현대제철", "A"),
    "국민은행": ("105560", "KB금융", "B"),
    "신한은행": ("055550", "신한지주", "B"),
    "하나은행": ("086790", "하나금융지주", "B"),
    "우리은행": ("316140", "우리금융지주", "B"),
}
WIN = 60
SERIES_DAYS = 250


def fetch_stock(ticker):
    url = (f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}"
           f"&timeframe=day&count=700&requestType=0")
    raw = subprocess.run(["curl", "-sL", "--max-time", "30", url],
                         capture_output=True).stdout.decode("utf-8", "ignore")
    rows = []
    import re
    for m in re.finditer(r'item data="(\d{8})\|[^|]*\|[^|]*\|[^|]*\|(\d+)\|', raw):
        rows.append((m.group(1), float(m.group(2))))
    s = pd.Series(dict(rows)).sort_index()
    return s


def compute_spreads():
    """Issuer-day spreads for the mapped issuers, same methodology as the
    monitor (build_issuers.process_file) + 5d rolling median smoothing."""
    import glob
    sys.path.insert(0, DATA)
    import build_issuers as bi
    parts = []
    for f in sorted(glob.glob(os.path.join(bi.DATA, "result_today_*.xlsx.parquet"))):
        try:
            r, _t = bi.process_file(f)
        except Exception:
            continue
        if r is not None and len(r):
            parts.append(r[r["issuer"].isin(MAPPING) | (r["issuer"] == "한국전력공사채권")])
    df = pd.concat(parts, ignore_index=True)
    df["issuer"] = df["issuer"].replace({"한국전력공사채권": "한국전력공사"})
    df = (df.groupby(["issuer", "date"], as_index=False)
            .apply(lambda g: pd.Series({
                "spread_bp": (g["spread_bp"] * g["amount"]).sum() / g["amount"].sum()
                if g["amount"].sum() > 0 else g["spread_bp"].mean(),
                "n": g["n"].sum()}), include_groups=False))
    df = df.sort_values(["issuer", "date"])
    df["spread_sm"] = df.groupby("issuer")["spread_bp"].transform(
        lambda s: s.rolling(bi.SMOOTH_WIN, min_periods=1).median())
    return df


def main():
    tickers = sorted({v[0] for v in MAPPING.values()})
    stocks = {}
    for tk in tickers:
        s = fetch_stock(tk)
        if len(s) > 100:
            stocks[tk] = s
        print("stock", tk, len(s), "days, last", s.index[-1] if len(s) else None)
    if not stocks:
        print("FATAL: no stock data")
        sys.exit(1)

    spr = compute_spreads()
    asof_spread = spr["date"].max()
    asof_stock = max(s.index[-1] for s in stocks.values())

    points, series = [], {}
    for issuer, g in spr.groupby("issuer"):
        tk, label, tier = MAPPING[issuer]
        if tk not in stocks:
            continue
        g = g.sort_values("date")
        sm = g.set_index("date")["spread_sm"].dropna()
        st = stocks[tk]
        if len(sm) < WIN + 10 or len(st) < WIN + 10:
            continue
        s_chg = float(sm.iloc[-5:].median() - sm.iloc[-WIN - 5:-WIN].median())
        p_ret = float(100 * (st.iloc[-1] / st.iloc[-1 - WIN] - 1))
        # quadrant: credit and equity agree when signs oppose (spread down = good)
        if p_ret >= 0 and s_chg <= 0:
            quad = "agree_good"
        elif p_ret < 0 and s_chg > 0:
            quad = "agree_bad"
        elif p_ret >= 0 and s_chg > 0:
            quad = "div_credit_worse"   # stock up, credit worsening
        else:
            quad = "div_credit_better"  # stock down, credit improving
        score = round(abs(p_ret) + abs(s_chg) / 2, 1) if quad.startswith("div") else 0
        points.append({"issuer": issuer, "label": label, "ticker": tk, "tier": tier,
                       "stock_ret60": round(p_ret, 1), "spread_chg60": round(s_chg, 1),
                       "spread_now": round(float(sm.iloc[-1]), 1),
                       "quadrant": quad, "score": score})
        if quad.startswith("div"):
            tail = g.tail(SERIES_DAYS)
            st_tail = st[[d for d in st.index if d >= tail["date"].iloc[0]]]
            base = st_tail.iloc[0] if len(st_tail) else None
            series[issuer] = {
                "dates": tail["date"].tolist(),
                "spread": [round(float(v)) if pd.notna(v) else None for v in tail["spread_sm"]],
                "stock_idx": ([round(float(100 * v / base)) for v in
                               st[[d for d in tail["date"] if d in st.index]]] if base else []),
                "stock_dates": [d for d in tail["date"] if d in st.index],
            }
    points.sort(key=lambda p: -p["score"])
    payload = {"asof_spread": asof_spread, "asof_stock": asof_stock, "window": WIN,
               "points": points, "series": series}
    print("divergence_data.js bytes:", len(json.dumps(payload, ensure_ascii=False).encode()))
    for out_js in [os.path.join(DATA, "divergence_data.js"),
                   os.path.join(DATA, "github_pages", "divergence_data.js")]:
        with open(out_js, "w") as f:
            f.write("window.DIVERGENCE = ")
            json.dump(payload, f, ensure_ascii=False)
            f.write(";")
    print(f"points {len(points)} | divergent: "
          f"{[(p['issuer'], p['score']) for p in points if p['score'] > 0]}")
    build_page(payload)


HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>신용-주식 괴리 모니터 — 회사채 신용 스프레드 모니터</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body { font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; margin: 0;
         background: #f5f6f8; color: #222; }
  .wrap { max-width: 960px; margin: 0 auto; padding: 16px; }
  h1 { font-size: 22px; margin: 8px 0 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 6px; }
  .back { font-size: 13px; margin-bottom: 16px; display: inline-block; }
  .card { background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 16px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .card h2 { font-size: 16px; margin: 0 0 4px; }
  .card .meta { color: #888; font-size: 12px; margin-bottom: 8px; line-height: 1.5; }
  .chart { width: 100%; height: 380px; }
  .mini { width: 100%; height: 220px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 6px 8px; border-bottom: 1px solid #eee; text-align: right; }
  th:first-child, td:first-child { text-align: left; }
  .pos { color: #c0392b; } .neg { color: #2471a3; }
  .note { color: #888; font-size: 12px; margin-top: 16px; line-height: 1.6; }
  .tblwrap { overflow-x: auto; }
</style>
</head>
<body>
<div class="wrap">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <h1 data-i18n="title">신용-주식 괴리 모니터</h1>
    <button id="langBtn" style="padding:6px 12px;border:1px solid #ccc;border-radius:6px;background:#fff;cursor:pointer;font-size:13px">EN</button>
  </div>
  <div class="sub">/*META_LINE*/</div>
  <div style="margin-bottom:16px">
    <a class="back" style="margin:0" href="../" data-i18n="back">← 오늘자 스프레드 모니터</a>
    &nbsp;·&nbsp;<a class="back" style="margin:0" href="../structure/" data-i18n="to_struct">차환 리스크와 등급 내 분산 →</a>
  </div>

  <div class="card">
    <h2 data-i18n="scat_t">60일 괴리 맵 — 주가 수익률 × 스프레드 변화</h2>
    <div class="meta" data-i18n="scat_m">오른쪽 위(주가↑·스프레드↑)와 왼쪽 아래(주가↓·스프레드↓)가 괴리 구간. 두 시장이 반대 얘기를 하는 발행자.</div>
    <div class="chart" id="scat"></div>
  </div>

  <div class="card">
    <h2 data-i18n="tbl_t">괴리 순위</h2>
    <div class="meta" data-i18n="tbl_m">괴리 점수 = |주가 60일 수익률| + |스프레드 60일 변화|/2. 방향이 어긋난 경우만 점수 부여.</div>
    <div class="tblwrap"><table id="tbl"></table></div>
  </div>

  <div id="minis"></div>

  <div class="note" data-i18n="note">스프레드는 장외 실거래 기준 자사 스프레드 (5일 이동평균). 주가는 KRX 종가.
  B등급 표기는 은행채 발행자의 상장 모회사 주가와 비교한 것. 괴리는 예측 신호가 아니라 두 시장의 정보가 엇갈리는 지점을 표시하는 용도.</div>
</div>
<script src="../divergence_data.js"></script>
<script>
(function(){
  const D = window.DIVERGENCE;
  const I18N = {
    ko: { title: "신용-주식 괴리 모니터", back: "← 오늘자 스프레드 모니터", to_struct: "차환 리스크와 등급 내 분산 →",
      scat_t: "60일 괴리 맵 — 주가 수익률 × 스프레드 변화",
      scat_m: "오른쪽 위(주가↑·스프레드↑)와 왼쪽 아래(주가↓·스프레드↓)가 괴리 구간. 두 시장이 반대 얘기를 하는 발행자.",
      tbl_t: "괴리 순위",
      tbl_m: "괴리 점수 = |주가 60일 수익률| + |스프레드 60일 변화|/2. 방향이 어긋난 경우만 점수 부여.",
      note: "스프레드는 장외 실거래 기준 자사 스프레드 (5일 이동평균). 주가는 KRX 종가. B 표기는 은행채 발행자를 상장 모회사 주가와 비교한 것. 괴리는 예측 신호가 아니라 두 시장의 정보가 엇갈리는 지점을 표시하는 용도. 발행자 스프레드는 그 기간에 거래된 종목 구성 (후순위/선순위 등) 에 따라 계단식으로 움직일 수 있음.",
      issuer: "발행자", stock: "주가 60일%", sprd: "스프레드 60일(bp)", now: "현재(bp)", quad: "구분", score: "괴리 점수",
      q: { div_credit_worse: "신용 악화형", div_credit_better: "신용 개선형", agree_good: "동반 개선", agree_bad: "동반 악화" },
      x: "주가 60일 수익률 (%)", y: "스프레드 60일 변화 (bp)", stock_idx: "주가 (시작=100)", sprd_l: "스프레드 (bp)",
      lang_btn: "EN" },
    en: { title: "Credit-Equity Divergence Monitor", back: "← Today's Spread Monitor", to_struct: "Refinancing Risk & Dispersion →",
      scat_t: "60-Day Divergence Map — Stock Return × Spread Change",
      scat_m: "Top-right (stock up, spread up) and bottom-left (stock down, spread down) are the divergence zones — two markets telling opposite stories.",
      tbl_t: "Divergence Ranking",
      tbl_m: "Score = |60d stock return| + |60d spread change|/2. Scored only when directions disagree.",
      note: "Spreads are own-issuer OTC trade-based spreads (5d average). Prices are KRX closes. Tier B compares bank bond issuers with their listed parents. Divergence marks where the two markets' information disagrees; it is not a predictive signal. An issuer's spread can move in steps when the mix of traded bonds changes (e.g. subordinated vs senior).",
      issuer: "Issuer", stock: "Stock 60d %", sprd: "Spread 60d (bp)", now: "Now (bp)", quad: "Type", score: "Score",
      q: { div_credit_worse: "Credit worsening", div_credit_better: "Credit improving", agree_good: "Both improving", agree_bad: "Both worsening" },
      x: "Stock 60d return (%)", y: "Spread 60d change (bp)", stock_idx: "Stock (start=100)", sprd_l: "Spread (bp)",
      lang_btn: "한" }
  };
  let LANG = localStorage.getItem('bond-lang') || 'ko';
  const t = k => I18N[LANG][k];
  const QC = { div_credit_worse: "#c0392b", div_credit_better: "#2471a3", agree_good: "#aab4bd", agree_bad: "#e8a33d" };
  const fmtD = d => d.slice(0,4) + "-" + d.slice(4,6) + "-" + d.slice(6);
  function drawScat(){
    const traces = Object.keys(QC).map(q => {
      const pts = D.points.filter(p => p.quadrant === q);
      return { x: pts.map(p => p.stock_ret60), y: pts.map(p => p.spread_chg60),
        mode: "markers+text", name: t('q')[q], text: pts.map(p => p.issuer),
        textposition: "top center", marker: { size: 9, color: QC[q] },
        hovertemplate: "%{text}<br>" + "%{x:.1f}% / %{y:.0f}bp<extra></extra>" };
    });
    Plotly.newPlot("scat", traces, { margin: { t: 10, r: 10, b: 45, l: 50 },
      xaxis: { title: t('x'), zeroline: true, zerolinewidth: 1.5 },
      yaxis: { title: t('y'), zeroline: true, zerolinewidth: 1.5 },
      legend: { orientation: "h", y: -0.3, font: { size: 10 } }, height: 380 },
      { displayModeBar: false, responsive: true });
  }
  function drawMinis(){
    const top = D.points.filter(p => p.score > 0).slice(0, 6);
    const host = document.getElementById('minis');
    host.innerHTML = top.map((p, i) =>
      `<div class="card"><h2>${p.issuer}</h2><div class="meta">${t('q')[p.quadrant]} · ${p.label} (${p.ticker})</div><div class="mini" id="mini${i}"></div></div>`).join("");
    top.forEach((p, i) => {
      const s = D.series[p.issuer];
      if (!s) return;
      Plotly.newPlot("mini" + i, [
        { x: s.stock_dates.map(fmtD), y: s.stock_idx, mode: "lines", name: t('stock_idx'),
          line: { color: "#111", width: 1.6 }, yaxis: "y" },
        { x: s.dates.map(fmtD), y: s.spread, mode: "lines", name: t('sprd_l'),
          line: { color: "#c0392b", width: 1.6 }, yaxis: "y2" } ],
        { margin: { t: 8, r: 45, b: 30, l: 45 }, height: 220,
          yaxis: { title: t('stock_idx') }, yaxis2: { title: t('sprd_l'), overlaying: "y", side: "right" },
          legend: { orientation: "h", y: -0.3, font: { size: 10 } } },
        { displayModeBar: false, responsive: true });
    });
  }
  function render(){
    drawScat(); drawMinis();
    const rows = [...D.points].sort((a, b) => b.score - a.score);
    document.getElementById('tbl').innerHTML =
      `<tr><th>${t('issuer')}</th><th>${t('stock')}</th><th>${t('sprd')}</th><th>${t('now')}</th><th>${t('quad')}</th><th>${t('score')}</th></tr>` +
      rows.map(p => `<tr><td>${p.issuer}${p.tier === 'B' ? ' (B)' : ''}</td>` +
        `<td class="${p.stock_ret60 < 0 ? "pos" : "neg"}">${p.stock_ret60.toFixed(1)}</td>` +
        `<td class="${p.spread_chg60 > 0 ? "pos" : "neg"}">${p.spread_chg60 > 0 ? "+" : ""}${p.spread_chg60.toFixed(0)}</td>` +
        `<td>${p.spread_now.toFixed(0)}</td><td>${t('q')[p.quadrant]}</td><td>${p.score ? p.score.toFixed(1) : "-"}</td></tr>`).join("");
  }
  function applyI18n(){
    document.documentElement.lang = LANG === 'ko' ? 'ko' : 'en';
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const v = t(el.dataset.i18n);
      if (typeof v === 'string') el.textContent = v;
    });
    document.title = t('title') + " — " + (LANG === 'ko' ? "회사채 신용 스프레드 모니터" : "Corporate Bond Credit Spread Monitor");
    document.getElementById('langBtn').textContent = t('lang_btn');
    render();
  }
  document.getElementById('langBtn').addEventListener('click', () => {
    LANG = LANG === 'ko' ? 'en' : 'ko';
    localStorage.setItem('bond-lang', LANG);
    applyI18n();
  });
  applyI18n();
})();
</script>
<div class="wrap" style="padding-top:0"><div class="note" style="text-align:center;border-top:1px solid #eee;padding-top:12px">
<a href="https://sdykim.me/" style="color:#888">sdykim.me</a> · Doyeon Kim
</div></div>
</body>
</html>"""


def build_page(payload):
    meta = (f"스프레드 {payload['asof_spread']} · 주가 {payload['asof_stock']} · "
            f"{payload['window']}거래일 변화 기준 · 상장 맵핑 발행자 {len(payload['points'])}곳")
    html = HTML.replace("/*META_LINE*/", meta)
    outdir = os.path.join(DATA, "github_pages", "divergence")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "index.html"), "w") as f:
        f.write(html)
    print("wrote divergence/index.html")


if __name__ == "__main__":
    main()
