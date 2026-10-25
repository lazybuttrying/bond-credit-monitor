"""Trend page data: 20-trading-day rolling median spread per issuer,
split into short (<=1Y) / long (>1Y), grouped by industry.
English only (user rule).
"""
import json
import os

import pandas as pd

DATA = os.path.dirname(os.path.abspath(__file__))
WIN = 20
DAYS = 250


def roll20(vals):
    s = pd.Series(vals, dtype="float64")
    return s.rolling(WIN, min_periods=WIN).median()


def main():
    with open(os.path.join(DATA, "issuers.json")) as f:
        iss = json.load(f)

    table = {r["issuer"]: r for r in iss["latest_table"]}
    out = {}  # issuer -> {industry, rating, dates, short[], long[]}
    for name, t in iss.get("series_term", {}).items():
        if name not in table:
            continue
        df = pd.DataFrame({"short": t["short"], "long": t["long"]})
        sm_s = roll20(df["short"]).dropna()
        sm_l = roll20(df["long"]).dropna()
        dates = pd.Series(t["dates"])
        # keep issuer if either leg has >=30 days (no overlap required)
        idx_s = sm_s.index[-DAYS:] if len(sm_s) >= 30 else []
        idx_l = sm_l.index[-DAYS:] if len(sm_l) >= 30 else []
        if len(idx_s) == 0 and len(idx_l) == 0:
            continue
        out[name] = {
            "industry": table[name]["industry"],
            "rating": table[name]["rating"],
            "dates": dates.iloc[sorted(set(idx_s) | set(idx_l))].tolist(),
            "short": [round(float(v), 1) for v in sm_s.loc[idx_s]],
            "short_dates": dates.iloc[idx_s].tolist(),
            "long": [round(float(v), 1) for v in sm_l.loc[idx_l]],
            "long_dates": dates.iloc[idx_l].tolist(),
        }

    all_dates = sorted({d for v in out.values() for d in v["dates"]})
    dates = all_dates[-DAYS:]

    payload = {"dates": dates, "window": WIN, "cutoff": "1Y", "series": {}}
    for name, v in out.items():
        ms = dict(zip(v["short_dates"], v["short"]))
        ml = dict(zip(v["long_dates"], v["long"]))
        payload["series"][name] = {
            "industry": v["industry"],
            "rating": v["rating"],
            "short": [ms.get(d) for d in dates],
            "long": [ml.get(d) for d in dates],
        }

    with open(os.path.join(DATA, "github_pages", "trends_data.js"), "w") as f:
        f.write("window.TRENDS = ")
        json.dump(payload, f, ensure_ascii=False)
        f.write(";")
    n_ind = len({v["industry"] for v in payload["series"].values()})
    print(f"issuers: {len(payload['series'])} | industries: {n_ind} | days: {len(dates)}")
    build_page()


HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>발행자 스프레드 추이 — 회사채 신용 스프레드 모니터</title>
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
  .card .meta { color: #888; font-size: 12px; margin-bottom: 8px; }
  .trow { display: flex; gap: 12px; }
  .tcol { flex: 1; min-width: 0; }
  .tcol h3 { font-size: 13px; margin: 0 0 4px; color: #555; }
  .chart { width: 100%; height: 260px; }
  @media (max-width: 700px) { .trow { flex-direction: column; } }
  .note { color: #888; font-size: 12px; margin-top: 16px; line-height: 1.6; }
</style>
</head>
<body>
<div class="wrap">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <h1 data-i18n="title">발행자 스프레드 추이</h1>
    <button id="langBtn" style="padding:6px 12px;border:1px solid #ccc;border-radius:6px;background:#fff;cursor:pointer;font-size:13px">EN</button>
  </div>
  <div class="sub">/*META_LINE*/</div>
  <div style="margin-bottom:16px"><a class="back" style="margin:0" href="../" data-i18n="back">← 오늘자 스프레드 모니터</a></div>
  <div id="sections"></div>
  <div class="note" data-i18n="note">20거래일 이동중앙값 기준이라 단기 노이즈가 제거됨.
  단기 = 잔존기간 1년 이하, 장기 = 1년 초과. 같은 회사의 단기 스프레드가 치솟으면
  유동성 경색 신호일 수 있음. 스프레드 = 자사 수익률 − 잔존기간 매칭 국고채 수익률.</div>
</div>
<script src="../trends_data.js"></script>
<script>
(function(){
  const T = window.TRENDS;
  const I18N = {
    ko: {
      title: "발행자 스프레드 추이",
      back: "← 오늘자 스프레드 모니터",
      note: "20거래일 이동중앙값 기준이라 단기 노이즈가 제거됨.\n  단기 = 잔존기간 1년 이하, 장기 = 1년 초과. 같은 회사의 단기 스프레드가 치솟으면\n  유동성 경색 신호일 수 있음. 스프레드 = 자사 수익률 − 잔존기간 매칭 국고채 수익률.",
      short: "단기 (≤1년)", long: "장기 (>1년)", median: "중간값",
      count: n => `${n}개 발행자 · 20일 이동중앙값`,
      lang_btn: "EN",
    },
    en: {
      title: "Issuer Spread Trends",
      back: "← Today's Spread Monitor",
      note: "20-trading-day rolling medians filter out short-term noise.\n  Short = remaining maturity ≤1Y, Long = >1Y. A spike in a company's short-term spread\n  may signal liquidity stress. Spread = own yield − tenor-matched KTB yield.",
      short: "Short (≤1Y)", long: "Long (>1Y)", median: "Median",
      count: n => `${n} issuers · 20d rolling median`,
      lang_btn: "한",
    }
  };
  const IND_EN = {
    "은행": "Banks", "카드": "Cards", "캐피탈": "Finance Cos", "금융지주": "Holdings",
    "증권": "Securities", "보험": "Insurance", "정책금융": "Policy Banks",
    "공기업": "Public Corps", "국채/통안": "Govt/MSB", "SPC": "SPCs", "일반기업": "Corporates"
  };
  let LANG = localStorage.getItem('bond-lang') || 'ko';
  const t = k => I18N[LANG][k];
  const indName = ind => LANG === 'en' ? (IND_EN[ind] || ind) : ind;
  const fmtD = d => d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6);
  const dates = T.dates.map(fmtD);
  const groups = {};
  Object.entries(T.series).forEach(([name, s]) => {
    (groups[s.industry] = groups[s.industry] || []).push([name, s]);
  });
  const order = Object.keys(groups).sort((a, b) => groups[b].length - groups[a].length);
  function renderSections(){
    const host = document.getElementById('sections');
    host.innerHTML = order.map((ind, i) =>
      `<div class="card"><h2>${indName(ind)}</h2>` +
      `<div class="meta">${t('count')(groups[ind].length)}</div>` +
      `<div class="trow">` +
      `<div class="tcol"><h3>${t('short')}</h3><div class="chart" id="ch${i}s"></div></div>` +
      `<div class="tcol"><h3>${t('long')}</h3><div class="chart" id="ch${i}l"></div></div>` +
      `</div></div>`
    ).join('');
    order.forEach((ind, i) => {
      const members = groups[ind].sort((a, b) => a[0].localeCompare(b[0], 'ko'));
      drawChart('ch' + i + 's', members, 'short', '#2563eb');
      drawChart('ch' + i + 'l', members, 'long', '#c93a3e');
    });
  }
  function medOf(members, key) {
    return dates.map((_, di) => {
      const vs = members.map(([, s]) => s[key][di]).filter(v => v != null).sort((a, b) => a - b);
      if (!vs.length) return null;
      const m = vs.length >> 1;
      return vs.length % 2 ? vs[m] : (vs[m-1] + vs[m]) / 2;
    });
  }
  function drawChart(id, members, key, color) {
    const traces = members.map(([name, s]) => ({
      x: dates, y: s[key], mode: 'lines', name: name,
      line: { width: 1.5, color: color }, opacity: 0.55,
      hovertemplate: '%{y:.1f}bp<extra>' + name + '</extra>'
    }));
    traces.push({ x: dates, y: medOf(members, key), mode: 'lines', name: t('median'),
      line: { width: 3, color: '#111' } });
    Plotly.newPlot(id, traces, {
      margin: { t: 10, r: 10, b: 40, l: 45 },
      yaxis: { title: 'bp' }, legend: { orientation: 'h', y: -0.35, font: { size: 10 } },
      height: 260
    }, { displayModeBar: false, responsive: true });
  }
  function applyI18n(){
    document.documentElement.lang = LANG === 'ko' ? 'ko' : 'en';
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const v = t(el.dataset.i18n);
      if (typeof v === 'string') el.textContent = v;
    });
    document.title = t('title') + " — " + (LANG === 'ko' ? "회사채 신용 스프레드 모니터" : "Corporate Bond Credit Spread Monitor");
    const lb = document.getElementById('langBtn');
    if (lb) lb.textContent = t('lang_btn');
    renderSections();
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


def build_page():
    with open(os.path.join(DATA, "issuers.json")) as f:
        iss = json.load(f)
    meta = (f"최근 {DAYS}거래일 ({iss['meta']['first_date']} ~ {iss['meta']['last_date']}) · "
            f"20거래일 이동중앙값 · 유동성 상위 발행자")
    html = HTML.replace("/*META_LINE*/", meta)
    outdir = os.path.join(DATA, "github_pages", "trends")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "index.html"), "w") as f:
        f.write(html)
    print("wrote trends/index.html")


if __name__ == "__main__":
    main()
