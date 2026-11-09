"""Insurance page: insurer investor flows in the OTC bond market.

Data comes only from FreeSIS parquet files already collected for the
monitor: investor-by-bond-type OTC trading (0270) and final quoted
yields (0010). Amounts in the parquet are million KRW; the page shows
eok KRW (million / 100) and jo KRW where noted.

Local preview build: the nav fragment is patched in memory only, the
shared nav_fragment.html file is not modified, and no view counter is
embedded. Both change only if the page is approved for live push.
"""
import json
import os

import pandas as pd

DATA = os.path.dirname(os.path.abspath(__file__))

INVESTORS = [
    ("bank", "은행", "Banks"),
    ("asset_mgmt_public", "자산운용 공모", "Asset mgmt, public funds"),
    ("asset_mgmt_private", "자산운용 사모", "Asset mgmt, private funds"),
    ("insurance", "보험", "Insurance"),
    ("merchant_bank", "종금", "Merchant banks"),
    ("pension_fund", "기금공제", "Pension funds"),
    ("foreign", "외국인", "Foreign"),
    ("government", "국가와 지자체", "Government"),
    ("other_corp", "기타법인", "Other corporates"),
    ("individual", "개인", "Individuals"),
]

BOND_TYPES = [
    ("ktb", "국고채", "KTB"),
    ("special", "특수채", "Special bonds"),
    ("bank", "은행채", "Bank bonds"),
    ("other_financial", "기타금융채", "Other financial bonds"),
    ("msb", "통안증권", "MSB"),
    ("abs", "ABS", "ABS"),
    ("local_gov", "지방채", "Local govt bonds"),
    ("corporate", "회사채", "Corporate bonds"),
]


def fmt_date(d):
    d = str(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def build_payload():
    fdir = os.path.join(DATA, "freesis", "data")
    inv = pd.read_parquet(os.path.join(fdir, "investor_otc.parquet"))
    corp = inv[inv["bond_type"] == "corporate"]

    net = corp[corp["trade_type"] == "net_buy"].copy()
    net = net.sort_values("date")
    days = int(net["date"].nunique())
    first, last = str(net["date"].min()), str(net["date"].max())

    net["ym"] = net["date"].astype(str).str[:6]
    monthly = net.groupby("ym")["insurance"].sum() / 100.0
    monthly_list = [
        {"ym": f"{ym[:4]}-{ym[4:]}", "net_eok": round(float(v), 0)}
        for ym, v in monthly.items()
    ]

    buy = corp[corp["trade_type"] == "buy"]
    sell = corp[corp["trade_type"] == "sell"]
    buy_share = round(100 * float(buy["insurance"].sum()) / float(buy["total"].sum()), 1)
    sell_share = round(100 * float(sell["insurance"].sum()) / float(sell["total"].sum()), 1)
    net_eok = round(float(net["insurance"].sum()) / 100.0, 0)

    investors = []
    sums = net[[c for c, _, _ in INVESTORS]].sum() / 100.0
    for col, ko, en in INVESTORS:
        investors.append({"ko": ko, "en": en, "net_eok": round(float(sums[col]), 0)})
    investors.sort(key=lambda r: r["net_eok"])

    all_net = inv[inv["trade_type"] == "net_buy"]
    by_type = all_net.groupby("bond_type")["insurance"].sum() / 100.0
    bond_types = [
        {"ko": ko, "en": en, "net_eok": round(float(by_type.get(code, 0.0)), 0)}
        for code, ko, en in BOND_TYPES
    ]
    bond_types.sort(key=lambda r: r["net_eok"], reverse=True)

    tot = inv[inv["trade_type"] == "total"]
    ins_by_type = tot.groupby("bond_type")["insurance"].sum()
    ins_total = float(ins_by_type.get("합계", ins_by_type.sum()))
    ktb_share = round(100 * float(ins_by_type.get("ktb", 0)) / ins_total, 1)
    corp_share = round(100 * float(ins_by_type.get("corporate", 0)) / ins_total, 1)

    y = pd.read_parquet(os.path.join(fdir, "final_yields.parquet"))
    y["pm"] = pd.to_numeric(y["pm"], errors="coerce")
    piv = y.pivot_table(index="date", columns="instrument", values="pm", aggfunc="first")
    ktb_name, aa_name = "국고채권(3년)", "회사채(무보증3년)AA-"
    dates = [d for d in piv.index if pd.notna(piv[ktb_name][d]) and pd.notna(piv[aa_name][d])]
    yields = {
        "dates": [fmt_date(d) for d in dates],
        "ktb_pct": [round(float(piv[ktb_name][d]), 3) for d in dates],
        "spread_bp": [round(float((piv[aa_name][d] - piv[ktb_name][d]) * 100), 1) for d in dates],
    }
    stats = {
        "days": days,
        "first": fmt_date(first),
        "last": fmt_date(last),
        "net_eok": net_eok,
        "net_jo": round(net_eok / 10000.0, 2),
        "buy_share": buy_share,
        "sell_share": sell_share,
        "ktb_share": ktb_share,
        "corp_share": corp_share,
        "spread_start": yields["spread_bp"][0],
        "spread_end": yields["spread_bp"][-1],
        "ktb_change_bp": round((yields["ktb_pct"][-1] - yields["ktb_pct"][0]) * 100, 1),
        "worst_ym": min(monthly_list, key=lambda r: r["net_eok"])["ym"],
        "worst_eok": min(monthly_list, key=lambda r: r["net_eok"])["net_eok"],
    }
    return {"stats": stats, "monthly": monthly_list, "investors": investors,
            "bond_types": bond_types, "yields": yields}


HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>보험사 투자자 흐름 — 회사채 신용 스프레드 모니터</title>
<script src="https://cdn.plot.ly/plotly-basic-2.35.2.min.js"></script>
<style>
  body { font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; margin: 0;
         background: #f5f6f8; color: #222; }
  .wrap { max-width: 960px; margin: 0 auto; padding: 16px; }
  h1 { font-size: 22px; margin: 8px 0 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 6px; line-height: 1.6; }
  .card { background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 16px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .card h2 { font-size: 16px; margin: 0 0 4px; }
  .card .meta { color: #888; font-size: 12px; margin-bottom: 8px; line-height: 1.6; }
  .chart { width: 100%; }
  .cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
  @media (max-width: 700px) { .cards { grid-template-columns: repeat(2, 1fr); } }
  .stat { background: #fff; border-radius: 12px; padding: 14px 16px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .stat .k { color: #888; font-size: 12px; margin-bottom: 6px; line-height: 1.5; }
  .stat .v { font-size: 22px; font-weight: 700; }
  .stat .v.neg { color: #c93a3e; }
  .stat .v.pos { color: #2563eb; }
  .stat .d { color: #666; font-size: 12px; margin-top: 4px; line-height: 1.5; }
  .explain { background: #eef4ff; border-radius: 12px; padding: 16px; margin-bottom: 16px;
             line-height: 1.8; font-size: 14px; }
  .explain p { margin: 0 0 6px; }
  .note { color: #888; font-size: 12px; margin-top: 16px; line-height: 1.6; }
  .fallback { color: #c93a3e; font-size: 13px; padding: 12px 0; }
</style>
</head>
<body>
<div class="wrap">
<!--NAV-->
  <div style="display:flex;justify-content:space-between;align-items:center">
    <h1 data-i18n="title">보험사 투자자 흐름</h1>
    <button id="langBtn" style="padding:6px 12px;border:1px solid #ccc;border-radius:6px;background:#fff;cursor:pointer;font-size:13px">EN</button>
  </div>
  <div class="sub" id="metaLine"></div>
  <div class="sub" id="headline" style="color:#222;font-size:14px"></div>
  <div class="cards" id="statCards"></div>
  <div class="card"><h2 data-i18n="ch1_title"></h2><div class="meta" data-i18n="ch1_meta"></div>
    <div class="chart" id="chMonthly" style="height:300px"></div></div>
  <div class="card"><h2 data-i18n="ch2_title"></h2><div class="meta" data-i18n="ch2_meta"></div>
    <div class="chart" id="chInvestors" style="height:340px"></div></div>
  <div class="card"><h2 data-i18n="ch3_title"></h2><div class="meta" data-i18n="ch3_meta"></div>
    <div class="chart" id="chTypes" style="height:320px"></div></div>
  <div class="card"><h2 data-i18n="ch4_title"></h2><div class="meta" data-i18n="ch4_meta"></div>
    <div class="chart" id="chYields" style="height:300px"></div></div>
  <div class="explain" id="explainBox"></div>
  <div class="note" data-i18n="note"></div>
</div>
<script>
const P = /*INSURANCE_JSON*/;
(function(){
  const S = P.stats;
  const I18N = {
    ko: {
      title: "보험사 투자자 흐름",
      headline: `금리 상승기 ${S.days}거래일 동안 보험은 회사채만 대규모로 팔고 국고채를 샀다.`,
      meta: `장외 거래 기준, ${S.first} ~ ${S.last}, ${S.days}거래일. 출처: 금융투자협회 FreeSIS 투자자별 거래와 최종호가수익률.`,
      c1k: "보험 회사채 순매수", c1d: `${S.days}거래일 합계`,
      c2k: "보험 매도 비중과 매수 비중", c2d: "회사채 전체 거래에서 보험이 차지한 비중",
      sell: "매도", buy: "매수",
      c3k: "보험 거래의 채권 구성", c3d: "전체 채권 거래대금 기준",
      ktb: "국고채", corp: "회사채",
      c4k: "AA- 스프레드와 국고채 3년 금리", c4d: "같은 기간 변화",
      spread: "스프레드",
      ch1_title: "보험 회사채 순매수, 월별",
      ch1_meta: "양수는 순매수, 음수는 순매도. 2026년 1월과 2월만 의미 있게 양수이고, 가장 큰 순매도는 " + S.worst_ym + " " + Math.abs(S.worst_eok).toLocaleString() + "억원이다.",
      ch2_title: "회사채 순매수, 투자자별",
      ch2_meta: "보험이 가장 큰 순매도 주체다. 국가와 지자체도 소폭 순매도이고, 나머지 투자자는 전부 순매수다.",
      ch3_title: "보험 순매수, 채권 종류별",
      ch3_meta: "국고채는 대규모 순매수, 회사채만 순매도다. 회사채를 팔고 국고채를 산 교체 그림이다.",
      ch4_title: "금리와 스프레드, 같은 기간",
      ch4_meta: "국고채 3년 금리와 회사채 무보증 3년 AA- 스프레드. 보험 순매도가 이어진 기간과 겹친다.",
      eok: "억원",
      explain: [
        "보험사는 장기 부채에 맞춰 채권을 오래 들고 가는 투자자다.",
        "금리가 오르면 보유 채권 평가가 떨어지고 K-ICS 금리위험 요구자본이 커진다.",
        "스프레드까지 벌어지면 회사채는 국고채보다 평가 하락이 더 크다.",
        "그래서 금리 상승기에 보험이 회사채를 줄이고 국고채를 늘리는 흐름은 자산과 부채의 금리 민감도를 맞추려는 움직임으로 읽을 수 있다.",
        "단, 이 페이지의 거래 데이터만으로 그 인과를 확정하지는 않는다."
      ],
      note: "이 페이지는 매매 흐름만 보여준다. 보험사의 채권 보유 잔고나 특정 보험사의 K-ICS 비율 같은 공시 숫자는 다루지 않는다. 거래대금은 장외 기준이고 단위는 억원이다.",
      nav_logo: "회사채 신용 스프레드 모니터", nav_menu: "메뉴 ▾", nav_monitor: "모니터",
      nav_trends: "산업별 전체 추이", nav_concepts: "신용평가 개념 가이드",
      nav_structure: "차환 리스크와 등급 내 분산", nav_divergence: "신용-주식 괴리",
      nav_monthly: "사건별 시장 반응", nav_intraday: "장중 체결 흐름",
      nav_insurance: "보험사 투자자 흐름",
      lang_btn: "EN"
    },
    en: {
      title: "Insurer Flows",
      headline: `Over ${S.days} trading days of rising rates, insurers sold corporate bonds heavily and bought KTBs instead.`,
      meta: `OTC trading, ${S.first} ~ ${S.last}, ${S.days} trading days. Source: KOFIA FreeSIS investor trading and final quoted yields.`,
      c1k: "Insurer net buying, corporate bonds", c1d: `Total over ${S.days} trading days`,
      c2k: "Insurer share of selling vs buying", c2d: "Share of all corporate bond trading",
      sell: "Sell side", buy: "Buy side",
      c3k: "What insurers trade", c3d: "Share of all insurer bond trading value",
      ktb: "KTB", corp: "Corporate",
      c4k: "AA- spread and 3Y KTB yield", c4d: "Change over the same period",
      spread: "Spread",
      ch1_title: "Insurer net buying of corporate bonds, monthly",
      ch1_meta: "Positive is net buying, negative is net selling. Only Jan and Feb 2026 are meaningfully positive. The largest net selling month is " + S.worst_ym + " at KRW " + Math.abs(S.worst_eok).toLocaleString() + "00M.",
      ch2_title: "Corporate bond net buying, by investor",
      ch2_meta: "Insurers are the largest net sellers. Government is a small net seller too, and every other investor group is a net buyer.",
      ch3_title: "Insurer net buying, by bond type",
      ch3_meta: "Large net buying of KTBs, net selling only in corporate bonds. A rotation out of corporates into KTBs.",
      ch4_title: "Rates and spreads over the same period",
      ch4_meta: "3Y KTB yield and the unguaranteed 3Y AA- corporate spread, overlapping the insurer net selling period.",
      eok: "KRW 100M",
      explain: [
        "Insurers hold bonds for a long time to match long-term liabilities.",
        "When rates rise, bond valuations fall and K-ICS interest-rate risk capital charges grow.",
        "When spreads widen on top of that, corporate bonds lose more value than KTBs.",
        "So insurers cutting corporates and adding KTBs in a rising-rate period reads as an attempt to align the rate sensitivity of assets and liabilities.",
        "The trading data on this page alone does not prove that causality."
      ],
      note: "This page shows trading flows only. It does not cover insurer bond holdings or any single insurer's disclosed figures such as its K-ICS ratio. Trading value is OTC, in KRW 100M units.",
      nav_logo: "Corporate Bond Credit Monitor", nav_menu: "Menu ▾", nav_monitor: "Monitor",
      nav_trends: "All trends by industry", nav_concepts: "Credit concepts guide",
      nav_structure: "Refinancing and dispersion", nav_divergence: "Credit-equity divergence",
      nav_monthly: "Market moves by event", nav_intraday: "Intraday trade flow",
      nav_insurance: "Insurer flows",
      lang_btn: "한"
    }
  };
  let LANG = localStorage.getItem('bond-lang') || 'ko';
  const t = k => I18N[LANG][k];
  const fmtJo = v => (v < 0 ? "-" : "+") + Math.abs(v).toLocaleString() + (LANG === 'ko' ? "억원" : "");
  function safePlot(id, traces, layout) {
    const el = document.getElementById(id);
    if (typeof Plotly === 'undefined') {
      el.innerHTML = '<div class="fallback">Chart library failed to load.</div>';
      return;
    }
    try {
      Plotly.newPlot(id, traces, layout, { displayModeBar: false, responsive: true });
    } catch (e) {
      el.innerHTML = '<div class="fallback">Chart failed to render.</div>';
    }
  }
  function render() {
    document.documentElement.lang = LANG;
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const v = t(el.dataset.i18n);
      if (typeof v === 'string') el.textContent = v;
    });
    document.title = t('title') + " — " + (LANG === 'ko' ? "회사채 신용 스프레드 모니터" : "Corporate Bond Credit Spread Monitor");
    document.getElementById('metaLine').textContent = t('meta');
    document.getElementById('headline').textContent = t('headline');
    document.getElementById('langBtn').textContent = t('lang_btn');
    const cards = [
      { k: t('c1k'), v: (S.net_jo < 0 ? "-" : "+") + Math.abs(S.net_jo).toFixed(2) + (LANG === 'ko' ? "조원" : " tn"), cls: S.net_eok < 0 ? "neg" : "pos", d: t('c1d') },
      { k: t('c2k'), v: t('sell') + " " + S.sell_share + "% / " + t('buy') + " " + S.buy_share + "%", cls: "", d: t('c2d') },
      { k: t('c3k'), v: t('ktb') + " " + S.ktb_share + "% / " + t('corp') + " " + S.corp_share + "%", cls: "", d: t('c3d') },
      { k: t('c4k'), v: S.spread_start + "bp → " + S.spread_end + "bp", cls: "", d: t('c4d') + ", KTB " + (S.ktb_change_bp > 0 ? "+" : "") + S.ktb_change_bp + "bp" }
    ];
    document.getElementById('statCards').innerHTML = cards.map(c =>
      `<div class="stat"><div class="k">${c.k}</div><div class="v ${c.cls}">${c.v}</div><div class="d">${c.d}</div></div>`).join('');
    document.getElementById('explainBox').innerHTML = t('explain').map(p => `<p>${p}</p>`).join('');
    const m = P.monthly;
    safePlot('chMonthly', [{
      x: m.map(r => r.ym), y: m.map(r => r.net_eok), type: 'bar',
      marker: { color: m.map(r => r.net_eok >= 0 ? '#2563eb' : '#c93a3e') },
      hovertemplate: '%{y:,}<extra></extra>'
    }], { margin: { t: 10, r: 10, b: 40, l: 55 }, yaxis: { title: t('eok'), zeroline: true }, height: 300 });
    const inv = P.investors;
    safePlot('chInvestors', [{
      x: inv.map(r => r.net_eok), y: inv.map(r => LANG === 'ko' ? r.ko : r.en),
      type: 'bar', orientation: 'h',
      marker: { color: inv.map(r => r.net_eok >= 0 ? '#2563eb' : '#c93a3e') },
      hovertemplate: '%{x:,}<extra></extra>'
    }], { margin: { t: 10, r: 10, b: 40, l: 130 }, xaxis: { title: t('eok'), zeroline: true }, height: 340 });
    const bt = P.bond_types;
    safePlot('chTypes', [{
      x: bt.map(r => r.net_eok), y: bt.map(r => LANG === 'ko' ? r.ko : r.en),
      type: 'bar', orientation: 'h',
      marker: { color: bt.map(r => r.net_eok >= 0 ? '#2563eb' : '#c93a3e') },
      hovertemplate: '%{x:,}<extra></extra>'
    }], { margin: { t: 10, r: 10, b: 40, l: 110 }, xaxis: { title: t('eok'), zeroline: true }, height: 320,
          yaxis: { autorange: 'reversed' } });
    const yy = P.yields;
    safePlot('chYields', [
      { x: yy.dates, y: yy.ktb_pct, mode: 'lines', name: 'KTB 3Y (%)',
        line: { width: 2, color: '#2563eb' }, hovertemplate: '%{y:.2f}%<extra>KTB 3Y</extra>' },
      { x: yy.dates, y: yy.spread_bp, mode: 'lines', name: 'AA- ' + t('spread') + ' (bp)', yaxis: 'y2',
        line: { width: 2, color: '#c93a3e' }, hovertemplate: '%{y:.1f}bp<extra>AA-</extra>' }
    ], { margin: { t: 10, r: 50, b: 40, l: 45 },
         yaxis: { title: '%' }, yaxis2: { title: 'bp', overlaying: 'y', side: 'right', showgrid: false },
         legend: { orientation: 'h', y: -0.25, font: { size: 10 } }, height: 300 });
  }
  document.getElementById('langBtn').addEventListener('click', () => {
    LANG = LANG === 'ko' ? 'en' : 'ko';
    localStorage.setItem('bond-lang', LANG);
    render();
  });
  render();
})();
</script>
<div class="wrap" style="padding-top:0"><div class="note" style="text-align:center;border-top:1px solid #eee;padding-top:12px">
<a href="https://sdykim.me/" style="color:#888">sdykim.me</a> / Doyeon Kim
</div></div>
</body>
</html>"""


def build_page(payload):
    html = HTML.replace("/*INSURANCE_JSON*/", json.dumps(payload, ensure_ascii=False))
    nav_path = os.path.join(DATA, "github_pages", "nav_fragment.html")
    with open(nav_path, encoding="utf-8") as f:
        nav = f.read()
    anchor = '<a href="/bond-credit-monitor/divergence/" data-i18n="nav_divergence" style="margin-left:48px">신용-주식 괴리</a>'
    assert anchor in nav, "divergence nav anchor not found"
    insurance_link = ('\n  <a href="/bond-credit-monitor/insurance/" data-i18n="nav_insurance" '
                      'style="margin-left:64px">보험사 투자자 흐름</a>')
    nav = nav.replace(anchor, anchor + insurance_link)
    assert "<!--NAV-->" in html
    html = html.replace("<!--NAV-->", nav)
    outdir = os.path.join(DATA, "github_pages", "insurance")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out} ({len(html)} bytes)")


def build_standalone():
    """Self-contained preview copy with Plotly inlined.

    The in-app file viewer cannot load the CDN script, so the normal
    page shows the chart fallback there. The standalone copy inlines a
    cached Plotly build and renders anywhere. Skipped silently when no
    cached Plotly file exists; the live page keeps the CDN reference.
    """
    cache = "/tmp/plotly-basic.min.js"
    if not os.path.exists(cache):
        print("standalone skipped: no cached plotly at", cache)
        return
    page = os.path.join(DATA, "github_pages", "insurance", "index.html")
    with open(page, encoding="utf-8") as f:
        html = f.read()
    with open(cache, encoding="utf-8") as f:
        plotly = f.read()
    tag = '<script src="https://cdn.plot.ly/plotly-basic-2.35.2.min.js"></script>'
    if tag not in html or "</script" in plotly:
        print("standalone skipped: tag mismatch or unsafe plotly content")
        return
    out = os.path.join(DATA, "insurance_preview_standalone.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html.replace(tag, "<script>\n" + plotly + "\n</script>"))
    print(f"wrote {out}")


def main():
    payload = build_payload()
    s = payload["stats"]
    print(f"days {s['days']} | net {s['net_eok']} eok | buy {s['buy_share']}% sell {s['sell_share']}%")
    print(f"monthly {len(payload['monthly'])} | investors {len(payload['investors'])} | yield days {len(payload['yields']['dates'])}")
    build_page(payload)
    build_standalone()


if __name__ == "__main__":
    main()
