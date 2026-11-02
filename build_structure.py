"""Structure page data (#4 maturity/refinancing wall + #6 within-rating dispersion).
English only (user rule). Run from ~/workspace/bond-data.
"""
import glob
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_issuers as bi

DATA = os.path.dirname(os.path.abspath(__file__))
NOTCH = {"AAA": 0, "AA+": 1, "AA": 2, "AA-": 3, "A+": 4, "A": 5, "A-": 6,
         "BBB+": 7, "BBB": 8, "BBB-": 9, "BB+": 10, "BB": 11, "BB-": 12,
         "B+": 13, "B": 14, "B-": 15, "CCC": 16}
NOTCH_LBL = {v: k for k, v in NOTCH.items()}


def band_of(rating):
    if not rating:
        return "unrated"
    if rating == "AAA":
        return "AAA"
    if rating.startswith("AA"):
        return "AA"
    if rating.startswith("A"):
        return "A"
    return "BBB-"


def main():
    issue_f = sorted(glob.glob(os.path.join(DATA, "kofia_bis_bond_issue_*.csv.parquet")))[-1]
    import re
    asof = re.search(r"(\d{8})", os.path.basename(issue_f)).group(1)
    df = pd.read_parquet(issue_f)
    print("issue file:", os.path.basename(issue_f), "rows:", len(df),
          "| kinds:", df["채권종류"].value_counts().to_dict())

    state = json.load(open(os.path.join(DATA, ".ratings_state.json")))["bonds"]
    norm = lambda s: str(s).replace(" ", "")
    bond_rating = {norm(b): v["confirmed"] for b, v in state.items() if v.get("confirmed")}
    bond_issuer = {norm(b): v["issuer"] for b, v in state.items() if v.get("issuer")}

    df["만기일"] = df["만기일"].astype(str)
    out = df[df["만기일"] > asof].copy()
    out["amt"] = bi.to_num(out["발행액"]).fillna(0)
    key = out["종목명"].map(norm)
    out["rating"] = key.map(bond_rating).fillna("")
    out["issuer"] = key.map(bond_issuer)
    miss = out["issuer"].isna()
    out.loc[miss, "issuer"] = out.loc[miss, "종목명"].map(bi.parse_issuer)
    # fallback: amount-weighted modal rating of the same issuer's rated bonds
    rated = out[out["rating"] != ""]
    modal_by_issuer = (rated.groupby("issuer")
                       .apply(lambda g: g.sort_values("amt", ascending=False)["rating"].iloc[0],
                              include_groups=False))
    no_r = out["rating"] == ""
    out.loc[no_r, "rating"] = out.loc[no_r, "issuer"].map(modal_by_issuer).fillna("")
    out["band"] = out["rating"].map(band_of)
    # kind field is mostly 'unknown'; classify private credit by issuer industry
    PRIVATE = {"은행", "카드", "캐피탈", "금융지주", "증권", "보험", "일반기업"}
    out["industry"] = out["issuer"].map(bi.industry_of)
    credit = out[out["industry"].isin(PRIVATE)].copy()
    print(f"outstanding rows {len(out)} | credit rows {len(credit)} | "
          f"credit amt {credit['amt'].sum()/10000:.1f}tn KRW")

    # ---- #4 maturity wall: monthly amounts by rating band, next 36 months
    credit["ym"] = credit["만기일"].str[:6]
    y0 = int(asof[:4]) * 12 + int(asof[4:6])
    months, wall = [], {b: [] for b in ["AAA", "AA", "A", "BBB-", "unrated"]}
    for i in range(1, 37):
        y, m = divmod(y0 + i - 1, 12)
        ym = f"{y}{m + 1:02d}"
        months.append(ym)
        g = credit[credit["ym"] == ym].groupby("band")["amt"].sum()
        for b in wall:
            wall[b].append(round(float(g.get(b, 0)) / 10000, 3))  # trillion KRW

    # ---- #4 issuer refinancing table
    iss = json.load(open(os.path.join(DATA, "issuers.json")))
    table = {r["issuer"]: r for r in iss["latest_table"]}
    horizon12 = {f"{(y0 + i - 1) // 12}{(y0 + i - 1) % 12 + 1:02d}" for i in range(1, 13)}
    import re as _re
    rows = []
    for name, g in credit.groupby("issuer"):
        total = g["amt"].sum()
        due12 = g[g["ym"].isin(horizon12)]["amt"].sum()
        rated = g[g["rating"] != ""]
        modal = (rated.sort_values("amt", ascending=False)["rating"].iloc[0]
                 if len(rated) else "")
        # keep identifiable, material issuers only: >=1tn outstanding, >=0.2tn due,
        # a known rating, and a name that is not a raw bond label (e.g. 'KT197')
        if total < 10000 or due12 < 2000 or not modal:
            continue
        if _re.search(r"\d$", name) or name not in table and _re.search(r"\d", name):
            continue
        t = table.get(name, {})
        rows.append({
            "issuer": name, "industry": bi.industry_of(name), "rating": modal,
            "outstanding": round(total / 10000, 2), "due12": round(due12 / 10000, 2),
            "due12_share": round(100 * due12 / total, 1) if total else 0,
            "spread": t.get("spread"), "z_90d": t.get("z_90d"),
        })
    rows.sort(key=lambda r: -r["due12_share"])
    refinance = rows[:24]

    # ---- #6 within-rating dispersion (latest_table snapshot)
    snap = [r for r in iss["latest_table"] if r.get("rating") in NOTCH]
    med_by_notch = {}
    for r in snap:
        med_by_notch.setdefault(NOTCH[r["rating"]], []).append(r["spread"])
    med_curve = sorted((n, float(pd.Series(v).median())) for n, v in med_by_notch.items()
                       if len(v) >= 2)
    dispersion, ratings_summary = [], []
    # linear fit of median spread vs notch for implied-rating inversion
    fit = None
    if len(med_curve) >= 3:
        import numpy as np
        xs = np.array([s for _, s in med_curve]); ys = np.array([n for n, _ in med_curve], dtype=float)
        ws = np.array([len(med_by_notch[n]) for n, _ in med_curve], dtype=float)
        slope, intercept = np.polyfit(xs, ys, 1, w=ws)
        fit = (float(slope), float(intercept))
    for r in snap:
        med = float(pd.Series([x["spread"] for x in snap if x["rating"] == r["rating"]]).median())
        gap = r["spread"] - med
        implied = None
        if fit:
            slope, intercept = fit
            implied = float(min(10.0, max(0.0, slope * r["spread"] + intercept)))
        dispersion.append({
            "issuer": r["issuer"], "rating": r["rating"], "industry": r["industry"],
            "spread": r["spread"], "rating_median": round(med, 1), "gap_bp": round(gap, 1),
            "implied": (NOTCH_LBL.get(int(round(implied))) if implied is not None else None),
            "gap_notches": (round(NOTCH[r["rating"]] - implied, 1) if implied is not None else None),
            "n_trades": r["n"],
        })
    dispersion.sort(key=lambda r: -abs(r["gap_bp"]))
    for rating in ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-"]:
        g = [r["spread"] for r in snap if r["rating"] == rating]
        if len(g) >= 2:
            s = pd.Series(g)
            ratings_summary.append({"rating": rating, "n": len(g),
                                    "median": round(float(s.median()), 1),
                                    "q1": round(float(s.quantile(0.25)), 1),
                                    "q3": round(float(s.quantile(0.75)), 1),
                                    "iqr": round(float(s.quantile(0.75) - s.quantile(0.25)), 1)})

    payload = {
        "asof_issue": asof, "asof_spread": iss["meta"]["last_date"],
        "wall": {"months": months, "bands": wall},
        "credit_total_tn": round(float(credit["amt"].sum()) / 10000, 1),
        "refinance": refinance,
        "ratings_summary": ratings_summary,
        "dispersion": dispersion[:30],
        "strip": [{"issuer": r["issuer"], "rating": r["rating"], "spread": r["spread"],
                   "industry": r["industry"]} for r in snap],
    }
    with open(os.path.join(DATA, "structure_data.js"), "w") as f:
        f.write("window.STRUCTURE = ")
        json.dump(payload, f, ensure_ascii=False)
        f.write(";")
    print(f"wall months {months[0]}..{months[-1]} | refinance rows {len(refinance)} | "
          f"dispersion {len(dispersion)} | strip {len(payload['strip'])}")
    build_page(payload)


HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>차환 리스크와 등급 내 분산 — 회사채 신용 스프레드 모니터</title>
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
  .chart { width: 100%; height: 340px; }
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
<!--NAV-->
  <div style="display:flex;justify-content:space-between;align-items:center">
    <h1 data-i18n="title">차환 리스크와 등급 내 분산</h1>
    <button id="langBtn" style="padding:6px 12px;border:1px solid #ccc;border-radius:6px;background:#fff;cursor:pointer;font-size:13px">EN</button>
  </div>
  <div class="sub" id="metaLine"></div>

  <div class="card">
    <h2 data-i18n="wall_t">월별 만기 도래액 (등급 구간별)</h2>
    <div class="meta" data-i18n="wall_m">회사채+금융채 잔존분 기준. 막대가 높은 달에 만기가 몰려 있고, 아래쪽 등급 비중이 클수록 차환 부담이 큼.</div>
    <div class="chart" id="wall"></div>
  </div>

  <div class="card">
    <h2 data-i18n="refi_t">차환 집중 발행자 — 12개월 내 만기 비중 순</h2>
    <div class="meta" data-i18n="refi_m">잔존 총액 1,000억원 이상 발행자. 만기 비중이 높은데 스프레드까지 벌어져 있으면 차환 비용이 뛰는 구간.</div>
    <div class="tblwrap"><table id="refi"></table></div>
  </div>

  <div class="card">
    <h2 data-i18n="strip_t">등급 내 스프레드 분포</h2>
    <div class="meta" data-i18n="strip_m">같은 등급 안에서도 스프레드가 크게 벌어짐. 점 하나 = 발행자 하나 (최근 거래 기준).</div>
    <div class="chart" id="strip"></div>
  </div>

  <div class="card">
    <h2 data-i18n="disp_t">같은 등급, 다른 가격 — 등급 중앙값과의 괴리</h2>
    <div class="meta" data-i18n="disp_m">괴리(bp) = 자사 스프레드 − 같은 등급 발행자 중앙값. 시장평가등급은 등급별 중앙값 곡선에 자사 스프레드를 대입해 역산한 값.</div>
    <div class="tblwrap"><table id="disp"></table></div>
  </div>

  <div class="note" data-i18n="note">잔존액은 발행액 기준 근사 (부분상환 미반영). 종목 등급은 장외 거래에서 확인된 최신 등급.
  스프레드는 모니터와 동일하게 잔존기간 매칭 국고채 대비, 5거래일 이동중앙값.</div>
</div>
<script src="../structure_data.js"></script>
<script>
(function(){
  const S = window.STRUCTURE;
  const I18N = {
    ko: { title: "차환 리스크와 등급 내 분산", back: "← 오늘자 스프레드 모니터", to_div: "신용-주식 괴리 →",
      wall_t: "월별 만기 도래액 (등급 구간별)", refi_t: "차환 집중 발행자 — 12개월 내 만기 비중 순",
      strip_t: "등급 내 스프레드 분포", disp_t: "같은 등급, 다른 가격 — 등급 중앙값과의 괴리",
      wall_m: "민간 신용채권 (은행·카드·캐피탈·증권·보험·일반기업) 잔존분 기준. 막대가 높은 달에 만기가 몰려 있고, 아래쪽 등급 비중이 클수록 차환 부담이 큼.",
      refi_m: "잔존 총액 1조원 이상 발행자. 만기 비중이 높은데 스프레드까지 벌어져 있으면 차환 비용이 뛰는 구간.",
      strip_m: "같은 등급 안에서도 스프레드가 크게 벌어짐. 점 하나 = 발행자 하나 (최근 거래 기준).",
      disp_m: "괴리(bp) = 자사 스프레드 − 같은 등급 발행자 중앙값. 시장평가등급은 등급별 중앙값 곡선에 자사 스프레드를 대입해 역산한 값.",
      note: "잔존액은 발행액 기준 근사 (부분상환 미반영). 종목 등급은 장외 거래에서 확인된 최신 등급, 없으면 같은 발행자의 대표 등급. 스프레드는 모니터와 동일하게 잔존기간 매칭 국고채 대비, 5거래일 이동중앙값. 금융지주의 후순위·조건부 자본증권은 구조적으로 선순위보다 넓게 거래되므로 시장평가등급이 실제 등급보다 낮게 나올 수 있음.",
      unrated: "무등급/미거래", tn: "조원", issuer: "발행자", rating: "등급", sector: "산업", out: "잔존(조)",
      due12: "12개월 내 만기(조)", share: "만기 비중%", spread: "스프레드(bp)",
      gap: "괴리(bp)", implied: "시장평가등급", notch: "등급차",
      meta: (a, b, c) => `발행 데이터 ${a} · 스프레드 ${b} · 민간 신용채권 잔존 ${c}조원`,
      nav_monitor: "모니터", nav_trends: "산업별 전체 추이", nav_concepts: "신용평가 개념 가이드",
      nav_structure: "차환 리스크·등급 내 분산", nav_divergence: "신용-주식 괴리",
      nav_monthly: "사건별 시장 반응", nav_intraday: "장중 체결 흐름",
      lang_btn: "EN" },
    en: { title: "Refinancing Risk & Within-Rating Dispersion", back: "← Today's Spread Monitor", to_div: "Credit-Equity Divergence →",
      wall_t: "Monthly Maturity Wall (by Rating Band)", refi_t: "Refinancing Concentration — Share Maturing within 12M",
      strip_t: "Spread Distribution within Ratings", disp_t: "Same Rating, Different Price — Gap vs Rating Median",
      wall_m: "Outstanding private credit bonds (banks, cards, finance companies, securities, insurers, corporates). Taller bars = maturity concentration; a larger low-rating share means heavier refinancing burden.",
      refi_m: "Issuers with ≥1tn KRW outstanding. High maturity share plus a wide spread marks the costly refinancing zone.",
      strip_m: "Spreads fan out widely even inside one rating. One dot = one issuer (latest trades).",
      disp_m: "Gap (bp) = own spread − median of same-rating issuers. Market-implied rating inverts own spread on the rating-median curve.",
      note: "Outstanding approximated by issued amount (partial redemptions not reflected). Bond ratings are the latest confirmed in OTC trades, else the issuer's representative rating. Spreads match the monitor: tenor-matched KTB, 5-trading-day rolling median. Subordinated and contingent capital bonds of financial holdings trade structurally wider than senior debt, so their market-implied rating can print below the actual rating.",
      unrated: "Unrated/no trades", tn: "tn KRW", issuer: "Issuer", rating: "Rating", sector: "Sector", out: "Outstanding(tn)",
      due12: "Due ≤12M(tn)", share: "Due share %", spread: "Spread(bp)",
      gap: "Gap(bp)", implied: "Implied rating", notch: "Notch gap",
      meta: (a, b, c) => `Issue data ${a} · Spreads as of ${b} · Private credit outstanding ${c}tn KRW`,
      nav_monitor: "Monitor", nav_trends: "All trends by industry", nav_concepts: "Credit concepts guide",
      nav_structure: "Refinancing & dispersion", nav_divergence: "Credit-equity divergence",
      nav_monthly: "Market moves by event", nav_intraday: "Intraday trade flow",
      lang_btn: "한" }
  };
  const IND_EN = {
    "은행": "Banks", "카드": "Cards", "캐피탈": "Finance Cos", "금융지주": "Holdings",
    "증권": "Securities", "보험": "Insurance", "정책금융": "Policy Banks",
    "공기업": "Public Corps", "국채/통안": "Govt/MSB", "SPC": "SPCs", "일반기업": "Corporates",
    "지방채": "Local Govt Bonds", "특수채": "Special Bonds"
  };
  let LANG = localStorage.getItem('bond-lang') || 'ko';
  const t = k => I18N[LANG][k];
  const indName = ind => LANG === 'en' ? (IND_EN[ind] || ind) : ind;
  const BANDC = { AAA: "#1f6fb2", AA: "#5b9bd5", A: "#e8a33d", "BBB-": "#c0392b", unrated: "#bbbbbb" };
  function drawWall(){
    const traces = Object.keys(S.wall.bands).map(b => ({
      x: S.wall.months.map(m => m.slice(0,4) + "-" + m.slice(4)), y: S.wall.bands[b],
      type: "bar", name: b === "unrated" ? t('unrated') : b, marker: { color: BANDC[b] } }));
    Plotly.newPlot("wall", traces, { barmode: "stack",
      margin: { t: 10, r: 10, b: 40, l: 50 }, yaxis: { title: t('tn') },
      legend: { orientation: "h", y: -0.25, font: { size: 10 } }, height: 340 },
      { displayModeBar: false, responsive: true });
  }
  function drawStrip(){
    const order = ["AAA","AA+","AA","AA-","A+","A","A-","BBB+","BBB","BBB-"];
    const traces = order.filter(r => S.strip.some(s => s.rating === r)).map(r => ({
      x: S.strip.filter(s => s.rating === r).map(s => s.spread),
      y: S.strip.filter(s => s.rating === r).map(() => r),
      mode: "markers", name: r, marker: { size: 8, opacity: 0.75 },
      text: S.strip.filter(s => s.rating === r).map(s => s.issuer),
      hovertemplate: "%{text}: %{x:.0f}bp<extra></extra>" }));
    Plotly.newPlot("strip", traces, { margin: { t: 10, r: 10, b: 40, l: 45 },
      xaxis: { title: "bp" }, height: 340, showlegend: false },
      { displayModeBar: false, responsive: true });
  }
  function tbl(id, rows, cols){
    const el = document.getElementById(id);
    el.innerHTML = "<tr>" + cols.map(c => `<th>${c.h}</th>`).join("") + "</tr>" +
      rows.map(r => "<tr>" + cols.map(c => `<td>${c.f(r)}</td>`).join("") + "</tr>").join("");
  }
  function render(){
    drawWall(); drawStrip();
    tbl("refi", S.refinance, [
      { h: t('issuer'), f: r => r.issuer },
      { h: t('rating'), f: r => r.rating || "-" },
      { h: t('sector'), f: r => indName(r.industry) },
      { h: t('out'), f: r => r.outstanding.toFixed(1) },
      { h: t('due12'), f: r => r.due12.toFixed(1) },
      { h: t('share'), f: r => r.due12_share.toFixed(1) },
      { h: t('spread'), f: r => r.spread == null ? "-" : `<span class="${r.spread >= 60 ? "pos" : ""}">${r.spread.toFixed(0)}</span>` }]);
    tbl("disp", S.dispersion, [
      { h: t('issuer'), f: r => r.issuer },
      { h: t('rating'), f: r => r.rating },
      { h: t('spread'), f: r => r.spread.toFixed(0) },
      { h: t('gap'), f: r => `<span class="${r.gap_bp > 0 ? "pos" : "neg"}">${r.gap_bp > 0 ? "+" : ""}${r.gap_bp.toFixed(0)}</span>` },
      { h: t('implied'), f: r => r.implied || "-" },
      { h: t('notch'), f: r => r.gap_notches == null ? "-" : r.gap_notches.toFixed(1) }]);
  }
  function applyI18n(){
    document.documentElement.lang = LANG === 'ko' ? 'ko' : 'en';
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const v = t(el.dataset.i18n);
      if (typeof v === 'string') el.textContent = v;
    });
    document.title = t('title') + " — " + (LANG === 'ko' ? "회사채 신용 스프레드 모니터" : "Corporate Bond Credit Spread Monitor");
    document.getElementById('metaLine').textContent =
      t('meta')(S.asof_issue, S.asof_spread, S.credit_total_tn);
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
    html = HTML
    nav = open(os.path.join(DATA, "github_pages", "nav_fragment.html"), encoding="utf-8").read()
    assert "<!--NAV-->" in html
    html = html.replace("<!--NAV-->", nav)
    outdir = os.path.join(DATA, "github_pages", "structure")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "index.html"), "w") as f:
        f.write(html)
    with open(os.path.join(DATA, "github_pages", "structure_data.js"), "w") as f:
        f.write("window.STRUCTURE = ")
        json.dump(payload, f, ensure_ascii=False)
        f.write(";")
    print("wrote structure/index.html + structure_data.js")


if __name__ == "__main__":
    main()
