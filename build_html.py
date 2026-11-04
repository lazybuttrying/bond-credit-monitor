"""Build self-contained credit monitor dashboard HTML.

Reads issuers.json + dashboard_data.json, emits bond-credit-monitor.html
(single file, Plotly via CDN, data embedded as JSON).
"""
import json
import os
import re
import subprocess
from datetime import datetime

DATA = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DATA, "bond-credit-monitor.html")

HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>회사채 신용 스프레드 모니터</title>
<script src="https://cdn.plot.ly/plotly-basic-2.35.2.min.js"></script>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
         margin: 0; padding: 16px; background: #f7f8fa; color: #1a1a1a; }
  .wrap { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 8px 0 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 20px; }
  .card { background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 16px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .card h2 { font-size: 16px; margin: 0 0 12px; }
  @media (min-width: 768px) {
    .twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
  }
  .alert { border-left: 4px solid #e5484d; background: #fff5f5; padding: 10px 12px;
           border-radius: 0 8px 8px 0; margin-bottom: 8px; font-size: 14px; }
  .alert b { color: #c93a3e; }
  .alert .meta { color: #888; font-size: 12px; }
  .asub { color: #666; font-size: 13px; margin-bottom: 10px; }
  .sig { background: #fff8e6; border: 1px solid #f0d98c; border-radius: 8px;
         padding: 10px 12px; margin-bottom: 12px; font-size: 13px; }
  .sigrow { margin-bottom: 6px; }
  .sigrow:last-child { margin-bottom: 0; }
  .sigrow > span { color: #666; }
  .sig-t { font-weight: 700; font-size: 13px; margin-bottom: 8px; color: #8a6d1b; }
  .siglist { color: #666; font-size: 12px; }
  .alert[data-clickable] { cursor: pointer; }
  .alert[data-clickable]:hover { background: #ffefef; }
  .chev { color: #c93a3e; font-size: 12px; }
  .bondwrap { margin: -4px 0 8px; }
  .bondrow td { background: #fafafa; padding: 0 !important; }
  .bondrow .bonds { border: none; border-radius: 0; }
  .bonds { background: #fafafa; border: 1px solid #eee; border-radius: 8px;
           padding: 8px 12px; font-size: 12.5px; }
  .bond { display: flex; justify-content: space-between; gap: 8px; padding: 5px 0;
          border-bottom: 1px dashed #e5e5e5; }
  .bond:last-child { border-bottom: 0; }
  .bond .bname { font-weight: 600; flex: 1; min-width: 0; overflow: hidden;
                 text-overflow: ellipsis; white-space: nowrap; }
  .bond span:not(.bname) { white-space: nowrap; color: #555; }
  .bond .up { color: #c93a3e; font-weight: 700; }
  .bonds .none { color: #999; }
  .agrp { margin-bottom: 10px; }
  .agrp-h { font-weight: 700; font-size: 13px; margin-bottom: 6px; }
  .agrp-h span { font-weight: 400; color: #888; font-size: 12px; margin-left: 4px; }
  .ok { color: #2a7d4f; font-size: 14px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 6px; text-align: right; border-bottom: 1px solid #eee; }
  th:first-child, td:first-child { text-align: left; }
  th { color: #666; font-weight: 600; cursor: pointer; user-select: none; white-space: nowrap; }
  th:hover { color: #111; }
  .up { color: #c93a3e; font-weight: 700; }
  .dn { color: #2a7d4f; }
  select { font-size: 15px; padding: 8px 10px; border-radius: 8px; border: 1px solid #ddd;
           width: 100%; margin-bottom: 8px; background: #fff; }
  .note { font-size: 12px; color: #888; margin-top: 12px; line-height: 1.6; }
  .tblwrap { overflow-x: auto; }
  tr.grp td { background: #eef2f7; font-weight: 700; font-size: 13px; padding: 10px 6px;
              position: sticky; top: 0; }
  tr.grp td span { font-weight: 400; color: #666; font-size: 12px; margin-left: 6px; }
</style>
</head>
<body>
<div class="wrap">
<!--NAV-->
  <div style="display:flex;justify-content:space-between;align-items:center">
    <h1 data-i18n="title">회사채 신용 스프레드 모니터</h1>
    <button id="langBtn" style="padding:6px 12px;border:1px solid #ccc;border-radius:6px;background:#fff;cursor:pointer;font-size:13px">EN</button>
  </div>
  <div class="sub" id="metaLine"></div>

  <div class="card">
    <h2 data-i18n="curve">국채 수익률 곡선</h2>
    <div id="curve"></div>
  </div>

  <div class="card">
    <h2 data-i18n="trend_title">발행자 추이</h2>
    <select id="issuerSel"></select>
    <div id="ts"></div>
  </div>

  <div class="twocol">
  <div class="card">
    <h2 data-i18n="alerts">확대 주의보</h2>
    <div id="alerts"></div>
    <div class="note" data-i18n="alerts_note">최근 5거래일간 스프레드가 15bp 이상 벌어진 발행자. 시장이 해당 회사의 신용위험을
    다시 가격하기 시작했다는 신호일 수 있음. (5일 이동중앙값 기준, 일 3건 이상 거래된 발행자만 집계)</div>
  </div>

  <div class="card">
    <h2 data-i18n="rating_title">최근 등급 변경</h2>
    <div id="ratingEvents"></div>
    <div class="note" data-i18n="rating_note">KOFIA 거래 데이터의 종목별 신용등급 변화를 종목 단위로 추적해 탐지. 등급은 평가사 발표 후 거래 데이터에 반영된 날짜 기준이며, 2거래일 이상 지속된 변화만 확정으로 표시.</div>
  </div>
  </div>

  <div class="card">
    <h2 data-i18n="table_title">발행자 스프레드 (최신일 기준)</h2>
    <div class="tblwrap"><table id="tbl">
      <thead><tr>
        <th data-k="issuer" data-i18n="th_issuer">발행자</th><th data-k="rating" data-i18n="th_rating">등급</th>
        <th data-k="spread" data-i18n="th_spread">스프레드(bp)</th><th data-k="vs_peer" data-i18n="th_vs_peer">동급대비(bp)</th>
        <th data-k="z_90d" data-i18n="th_z">정상대비(z)</th>
        <th data-k="chg_5d" data-i18n="th_chg5d">5일변화</th><th data-k="chg_20d" data-i18n="th_chg20d">20일변화</th>
        <th data-k="n" data-i18n="th_n">거래건수</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
    <div class="note" data-i18n="table_note">스프레드 = 회사채 수익률 − 잔존기간 매칭 국채 수익률 (거래대금 가중평균).
    동급대비 = 동일 신용등급 발행자들의 중간값 대비 괴리. 양수 = 동급보다 위험하게 거래됨.</div>
  </div>

</div>

<script>
const ISSUERS = /*ISSUERS_JSON*/;
const CURVE = /*CURVE_JSON*/;
const ALERTS = /*ALERTS_JSON*/;
const META = /*META_JSON*/;
const RATING = /*RATING_JSON*/;
window.BONDS = /*BONDS_JSON*/;
const TENORS = ["3M","6M","1Y","2Y","3Y","5Y","10Y","20Y","30Y"];

// ---- i18n ----
const I18N = {
ko: {
  title: "회사채 신용 스프레드 모니터",
  curve: "국채 수익률 곡선",
  alerts: "확대 주의보",
  alerts_note: "최근 5거래일간 스프레드가 15bp 이상 벌어진 발행자. 시장이 해당 회사의 신용위험을 다시 가격하기 시작했다는 신호일 수 있음. (5일 이동중앙값 기준, 일 3건 이상 거래된 발행자만 집계)",
  table_title: "발행자 스프레드 (최신일 기준)",
  th_issuer: "발행자", th_rating: "등급", th_spread: "스프레드(bp)", th_vs_peer: "동급대비(bp)",
  th_chg5d: "5일변화", th_chg20d: "20일변화", th_n: "거래건수", th_z: "정상대비(z)",
  table_note: "스프레드 = 회사채 수익률 − 잔존기간 매칭 국채 수익률 (거래대금 가중평균). 동급대비 = 동일 신용등급 발행자들의 중간값 대비 괴리. 양수 = 동급보다 위험하게 거래됨.",
  trend_title: "발행자 추이",
  nav_logo: "회사채 신용 스프레드 모니터", nav_menu: "메뉴 ▾", nav_monitor: "모니터",
  nav_trends: "산업별 전체 추이",
  nav_concepts: "신용평가 개념 가이드",
  nav_structure: "차환 리스크·등급 내 분산",
  nav_divergence: "신용-주식 괴리",
  nav_monthly: "사건별 시장 반응",
  nav_intraday: "장중 체결 흐름",
  rating_title: "최근 등급 변경",
  rating_note: "KOFIA 거래 데이터의 종목별 신용등급 변화를 종목 단위로 추적해 탐지. 등급은 평가사 발표 후 거래 데이터에 반영된 날짜 기준이며, 2거래일 이상 지속된 변화만 확정으로 표시.",
  rating_none: "탐지된 등급 변경 없음",
  rating_up: "상향", rating_down: "하향",
  rating_bonds: n => `종목 ${n}개`,
  rating_spread_at: v => `변경 시점 스프레드 ${v}bp`,
  rating_pre20: v => `직전 20일 ${v > 0 ? '+' : ''}${v}bp`,
  stock_5d: (n, v) => `주가(${n}) 5일 ${v > 0 ? '+' : ''}${v}%`,
  stock_20d: (n, v) => `주가(${n}) 20거래일 ${v > 0 ? '+' : ''}${v}%`,
  lang_btn: "EN",
  curve_y: "수익률(%)", curve_x: "잔존기간",
  chart_fail: "차트를 불러오지 못했습니다 (차트 라이브러리 연결 실패). 아래 표 데이터는 정상입니다.",
  chart_fail_plain: "차트를 불러오지 못했습니다 (차트 라이브러리 연결 실패).",
  no_alerts: "현재 5일 기준 급격한 스프레드 확대 종목 없음",
  alerts_sub: n => `5일간 15bp 이상 확대 ${n}곳 — 클릭하면 보유 채권 나열`,
  contagion: "계열 내 전파 신호",
  simultaneous: n => `${n}곳 동시 확대`,
  issuers_count: n => `${n}곳`,
  sev_surge: "급등", sev_sharp: "크게 확대", sev_widen: "확대", sev_hint: "확대 조짐",
  high90: "90일 최고치",
  above_peer: (r, v) => `동급(${r}) 평균보다 +${v}bp 높음`,
  below_peer: (r, v) => `동급(${r}) 평균보다 ${v}bp 낮음`,
  days20: v => `20일간 +${v}bp`,
  days5: v => `5일간 +${v}bp`,
  current: v => `현재 ${v}bp`,
  no_bonds: "최근 거래 채권 데이터 없음",
  yield: "수익률", spread: "스프레드", eokwon: "억원",
  median: "중간값",
  spread_bp: v => `${v} 스프레드(bp)`,
  peer_median: r => `${r} 등급 중간값(bp)`,
  ind_median: v => `${v} 중간값(bp)`,
  meta: (a, b, n, u, upd) => `데이터: ${a} ~ ${b} (${n}거래일) · 유니버스 ${u}개 발행자 · 업데이트 ${upd}`,
  updated: "업데이트",
  method_title: "스프레드 계산식",
  method_body: `1. 스프레드(bp) = (채권 수익률 − 동일 만기 국고채 수익률) × 100<br>
&ensp;&ensp;— Fabozzi 『Bond Markets, Analysis and Strategies』의 credit spread / G-spread 정의<br>
2. 만기 버킷 매칭: 3M / 6M / 1Y / 2Y / 3Y / 5Y / 10Y / 20Y / 30Y<br>
&ensp;&ensp;— 동일 만기 국채 대비 스프레드(G-spread) 개념<br>
3. 발행자-일별 스프레드 = Σ(버킷별 스프레드 × 버킷 거래대금) / Σ(버킷 거래대금)<br>
&ensp;&ensp;— FINRA TRACE의 거래량 가중 집계 방식<br>
4. 단기 = 잔존기간 1년 이하 / 장기 = 1년 초과<br>
&ensp;&ensp;— BIS의 money market 정의 (1년 이하 단기자금시장)<br>
5. 단기 스프레드 급등 = 유동성 경색 신호 / 장기 스프레드 확대 = 펀더멘털 우려<br>
&ensp;&ensp;— Duffie &amp; Singleton 『Credit Risk』의 스프레드 기간구조 해석`,
},
en: {
  title: "Corporate Bond Credit Spread Monitor",
  curve: "KTB Yield Curve",
  alerts: "Widening Alerts",
  alerts_note: "Issuers whose spreads widened 15bp+ over 5 trading days. May signal the market repricing credit risk. (5-day rolling median, issuers with 3+ trades/day only)",
  table_title: "Issuer Spreads (Latest)",
  th_issuer: "Issuer", th_rating: "Rating", th_spread: "Spread(bp)", th_vs_peer: "vs Peer(bp)",
  th_chg5d: "5d Chg", th_chg20d: "20d Chg", th_n: "Trades", th_z: "vs Normal(z)",
  table_note: "Spread = corporate yield − tenor-matched KTB yield (amount-weighted). vs Peer = deviation from same-rating median. Positive = trading riskier than peers.",
  trend_title: "Issuer Trends",
  nav_logo: "Corporate Bond Credit Monitor", nav_menu: "Menu ▾", nav_monitor: "Monitor",
  nav_trends: "All trends by industry",
  nav_concepts: "Credit concepts guide",
  nav_structure: "Refinancing & dispersion",
  nav_divergence: "Credit-equity divergence",
  nav_monthly: "Market moves by event",
  nav_intraday: "Intraday trade flow",
  rating_title: "Recent Rating Changes",
  rating_note: "Detected by tracking per-bond rating changes in KOFIA trade data. Dates are when the change appeared in trade data after the agency announcement; only changes persisting 2+ trading days are confirmed.",
  rating_none: "No rating changes detected",
  rating_up: "upgrade", rating_down: "downgrade",
  rating_bonds: n => `${n} bonds`,
  rating_spread_at: v => `spread at change ${v}bp`,
  rating_pre20: v => `prior 20d ${v > 0 ? '+' : ''}${v}bp`,
  stock_5d: (n, v) => `${n} stock 5d ${v > 0 ? '+' : ''}${v}%`,
  stock_20d: (n, v) => `${n} stock 20d ${v > 0 ? '+' : ''}${v}%`,
  lang_btn: "한",
  curve_y: "Yield (%)", curve_x: "Tenor",
  chart_fail: "Could not load the chart (chart library connection failed). The table data below is unaffected.",
  chart_fail_plain: "Could not load the chart (chart library connection failed).",
  no_alerts: "No issuers with sharp spread widening over 5 days",
  alerts_sub: n => `${n} issuers widened 15bp+ in 5d — click for bond list`,
  contagion: "Intra-group Contagion Signal",
  simultaneous: n => `${n} issuers widening together`,
  issuers_count: n => `${n} issuers`,
  sev_surge: "surging", sev_sharp: "sharply wider", sev_widen: "widening", sev_hint: "widening signs",
  high90: "90d high",
  above_peer: (r, v) => `+${v}bp above ${r} peer avg`,
  below_peer: (r, v) => `${v}bp below ${r} peer avg`,
  days20: v => `+${v}bp over 20d`,
  days5: v => `+${v}bp over 5d`,
  current: v => `${v}bp now`,
  no_bonds: "No recent bond trade data",
  yield: "Yield", spread: "Spread", eokwon: "₩100m",
  median: "Median",
  spread_bp: v => `${v} spread (bp)`,
  peer_median: r => `${r} peer median (bp)`,
  ind_median: v => `${v} median (bp)`,
  meta: (a, b, n, u, upd) => `Data: ${a} – ${b} (${n} trading days) · ${u}-issuer universe · Updated ${upd}`,
  updated: "Updated",
  method_title: "Spread Formula",
  method_body: `1. Spread (bp) = (bond yield − same-maturity KTB yield) × 100<br>
&ensp;&ensp;— Fabozzi <i>Bond Markets, Analysis and Strategies</i>: credit spread / G-spread definition<br>
2. Tenor-bucket matching: 3M / 6M / 1Y / 2Y / 3Y / 5Y / 10Y / 20Y / 30Y<br>
&ensp;&ensp;— G-spread concept (spread over same-maturity government bond)<br>
3. Issuer-day spread = Σ(bucket spread × bucket traded amount) / Σ(bucket amount)<br>
&ensp;&ensp;— FINRA TRACE volume-weighted aggregation<br>
4. Short = remaining maturity ≤ 1Y / Long = &gt; 1Y<br>
&ensp;&ensp;— BIS money market definition (short-term funding market ≤ 1 year)<br>
5. Short-term spread spike = liquidity stress signal / long-term widening = fundamental concern<br>
&ensp;&ensp;— Duffie &amp; Singleton <i>Credit Risk</i>: term-structure interpretation of spreads`,
}
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
const _rerender = [];
function applyI18n(){
  document.documentElement.lang = LANG === 'ko' ? 'ko' : 'en';
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const v = t(el.dataset.i18n);
    if (typeof v === 'string') el.textContent = v;
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const v = t(el.dataset.i18nHtml);
    if (typeof v === 'string') el.innerHTML = v;
  });
  document.title = t('title');
  const mb = document.getElementById('metaLine');
  if (mb && typeof META !== 'undefined')
    mb.textContent = t('meta')(META.first, META.last, META.n_days, META.n_universe, META.updated);
  const lb = document.getElementById('langBtn');
  if (lb) lb.textContent = t('lang_btn');
  _rerender.forEach(fn => fn());
}
function setLang(l){
  LANG = l;
  localStorage.setItem('bond-lang', l);
  applyI18n();
}
document.addEventListener('DOMContentLoaded', () => {
  const lb = document.getElementById('langBtn');
  if (lb) lb.addEventListener('click', () => setLang(LANG === 'ko' ? 'en' : 'ko'));
  applyI18n();
});

// ---- yield curve ----
function drawCurve(){
  const el = document.getElementById('curve');
  try {
    if (typeof Plotly === 'undefined') throw new Error('chart library unavailable');
    const traces = CURVE.series.map(s => ({
      x: TENORS, y: TENORS.map(t => { const p = s.points.find(q => q.tenor === t); return p ? p.yld : null; }),
      mode: 'lines+markers', name: s.date, line: { width: s.latest ? 3 : 1.5, dash: s.latest ? 'solid' : 'dot' }
    }));
    Plotly.newPlot('curve', traces, {
      margin: { t: 10, r: 10, b: 40, l: 45 },
      yaxis: { title: t('curve_y'), tickformat: '.2f' }, xaxis: { title: t('curve_x') },
      legend: { orientation: 'h', y: -0.25 }, height: 340
    }, { displayModeBar: false, responsive: true });
  } catch (e) {
    if (el) el.innerHTML = `<div style="color:#666;font-size:14px;padding:16px 0;">${t('chart_fail')}</div>`;
  }
}
_rerender.push(drawCurve);
drawCurve();

// ---- alerts v2: group contagion + click drill-down to bonds ----
function bondRows(issuer){
  const bs = (window.BONDS || {})[issuer];
  if (!bs || !bs.length) return `<div class="bonds"><span class="none">${t('no_bonds')}</span></div>`;
  return '<div class="bonds">' + bs.map(b =>
    `<div class="bond"><span class="bname">${b.bond}</span>` +
    `<span>${t('yield')} ${b.yld}%</span>` +
    `<span class="${b.spread >= 50 ? 'up' : ''}">${t('spread')} ${b.spread >= 0 ? '+' : ''}${b.spread}bp</span>` +
    `<span>${(b.amt / 1e8).toFixed(1)}${t('eokwon')}</span></div>`
  ).join('') + '</div>';
}
function alertCard(r){
  const bits = [t('days5')(r.chg_5d) + ' ' + `<b>${t('sev_' + r.sev)}</b>`, t('current')(r.spread)];
  if (r.high90) bits.push(t('high90'));
  if (r.vs_peer >= 30) bits.push(t('above_peer')(r.rating, Math.round(r.vs_peer)));
  else if (r.vs_peer <= -30) bits.push(t('below_peer')(r.rating, Math.round(r.vs_peer)));
  if (r.chg_20d != null && r.chg_20d >= 30) bits.push(t('days20')(r.chg_20d));
  if (r.stock_5d != null) bits.push(`<span class="${r.stock_5d >= 0 ? 'dn' : 'up'}">${t('stock_5d')(r.stock_name, r.stock_5d)}</span>`);
  const hasBonds = (window.BONDS || {})[r.issuer];
  return `<div class="alert" data-issuer="${r.issuer}"${hasBonds ? ' data-clickable="1"' : ''}>` +
    `<b>${r.issuer}</b> <span class="meta">${r.rating} · ${indName(r.industry)}</span>` +
    `${hasBonds ? ' <span class="chev">▸</span>' : ''}<br>${bits.join(' · ')}</div>`;
}
function renderAlerts(){
  const el = document.getElementById('alerts');
  const A = ALERTS;
  if (!A.items.length) { el.innerHTML = `<div class="ok">${t('no_alerts')}</div>`; return; }
  let h = `<div class="asub">${t('alerts_sub')(A.items.length)}</div>`;
  if (A.group_signals.length) {
    h += `<div class="sig"><div class="sig-t">${t('contagion')}</div>` + A.group_signals.map(s =>
      `<div class="sigrow">▸ <b>${s.group}</b> ${t('simultaneous')(s.count)}<br>` +
      `<span class="siglist">${s.top.map(x => `${x.issuer} +${x.chg_5d}bp`).join(' · ')}</span></div>`
    ).join('') + '</div>';
  }
  const groups = {};
  A.items.forEach(r => { (groups[r.group] = groups[r.group] || []).push(r); });
  const order = Object.keys(groups).sort((a, b) => groups[b][0].chg_5d - groups[a][0].chg_5d);
  h += order.map(g =>
    `<div class="agrp"><div class="agrp-h">${indName(g)} <span>${t('issuers_count')(groups[g].length)}</span></div>` +
    groups[g].map(alertCard).join('') + '</div>'
  ).join('');
  el.innerHTML = h;
  el.querySelectorAll('.alert[data-clickable]').forEach(card => {
    card.addEventListener('click', () => {
      const iss = card.dataset.issuer;
      const next = card.nextElementSibling;
      if (next && next.classList.contains('bondwrap')) {
        next.remove();
        card.querySelector('.chev').textContent = '▸';
        return;
      }
      const w = document.createElement('div');
      w.className = 'bondwrap';
      w.innerHTML = bondRows(iss);
      card.after(w);
      card.querySelector('.chev').textContent = '▾';
    });
  });
}
_rerender.push(renderAlerts);

// ---- rating change events (KOFIA per-bond tracking) ----
function renderRating(){
  const el = document.getElementById('ratingEvents');
  if (!el) return;
  const items = (RATING && RATING.recent) || [];
  if (!items.length) { el.innerHTML = `<div class="ok">${t('rating_none')}</div>`; return; }
  el.innerHTML = items.map(e => {
    const d = `${e.date.slice(0,4)}-${e.date.slice(4,6)}-${e.date.slice(6)}`;
    const arrow = e.direction === 'down' ? '▼' : '▲';
    const col = e.direction === 'down' ? '#c93a3e' : '#2a7d4f';
    const bits = [`<span style="color:${col};font-weight:700">${arrow} ${e.from} → ${e.to}</span>`,
                  t(e.direction === 'down' ? 'rating_down' : 'rating_up'),
                  t('rating_bonds')(e.n_bonds)];
    if (e.spread_at != null) bits.push(t('rating_spread_at')(e.spread_at));
    if (e.chg_pre20 != null) bits.push(t('rating_pre20')(e.chg_pre20));
    if (e.stock_20d != null) bits.push(`<span style="color:${e.stock_20d >= 0 ? '#2a7d4f' : '#c93a3e'}">${t('stock_20d')(e.stock_name, e.stock_20d)}</span>`);
    return `<div style="padding:7px 0;border-bottom:1px dashed #e5e5e5;font-size:13.5px">` +
      `<b>${e.issuer}</b> <span style="color:#888;font-size:12px">${d}</span><br>${bits.join(' · ')}</div>`;
  }).join('');
}
_rerender.push(renderRating);

// ---- table (grouped by industry) ----
(function(){
  const tb = document.querySelector('#tbl tbody');
  let sortKey = 'spread', sortDir = -1;
  function fmt(v, suf){ return v == null ? '-' : (v > 0 ? '+' : '') + v + (suf || ''); }
  function rowHtml(r){
    const hasB = (window.BONDS || {})[r.issuer];
    return `<tr${hasB ? ` data-issuer="${r.issuer}" style="cursor:pointer"` : ''}>
      <td><b>${r.issuer}</b>${r.in_universe ? '' : ' <span style="color:#aaa">·</span>'}${hasB ? ' <span style="color:#aaa;font-size:10px">▸</span>' : ''}</td>
      <td>${r.rating || '-'}</td><td>${r.spread}</td>
      <td class="${r.vs_peer >= 20 ? 'up' : ''}">${fmt(r.vs_peer)}</td>
      <td class="${r.z_90d >= 2 ? 'up' : (r.z_90d <= -2 ? 'dn' : '')}">${r.z_90d == null ? '-' : (r.z_90d > 0 ? '+' : '') + r.z_90d}</td>
      <td class="${r.chg_5d >= 15 ? 'up' : (r.chg_5d <= -15 ? 'dn' : '')}">${fmt(r.chg_5d)}</td>
      <td class="${r.chg_20d >= 30 ? 'up' : (r.chg_20d <= -30 ? 'dn' : '')}">${fmt(r.chg_20d)}</td>
      <td>${r.n}</td></tr>`;
  }
  function med(a){ const s = a.slice().sort((x,y)=>x-y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m-1]+s[m])/2; }
  function render(){
    const groups = {};
    ISSUERS.latest_table.forEach(r => { (groups[r.industry] = groups[r.industry] || []).push(r); });
    const order = Object.keys(groups).sort((a, b) =>
      med(groups[b].map(r => r.spread)) - med(groups[a].map(r => r.spread)));
    tb.innerHTML = order.map(ind => {
      const rows = groups[ind].slice().sort((a, b) => {
        const av = a[sortKey], bv = b[sortKey];
        if (av == null) return 1; if (bv == null) return -1;
        return (typeof av === 'string' ? av.localeCompare(bv, 'ko') : av - bv) * sortDir;
      });
      const m = med(groups[ind].map(r => r.spread)).toFixed(1);
      return `<tr class="grp"><td colspan="8">${indName(ind)} <span>${t('median')} ${m}bp · ${t('issuers_count')(groups[ind].length)}</span></td></tr>` +
             rows.map(rowHtml).join('');
    }).join('');
  }
  document.querySelectorAll('#tbl th').forEach(th => th.addEventListener('click', () => {
    const k = th.dataset.k;
    if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = (k === 'issuer' || k === 'rating') ? 1 : -1; }
    render();
  }));
  // table row click -> bond drill-down
  tb.addEventListener('click', e => {
    const tr = e.target.closest('tr[data-issuer]');
    if (!tr) return;
    const iss = tr.dataset.issuer;
    const next = tr.nextElementSibling;
    if (next && next.classList.contains('bondrow')) { next.remove(); return; }
    const br = document.createElement('tr');
    br.className = 'bondrow';
    br.innerHTML = `<td colspan="8">${bondRows(iss)}</td>`;
    tr.after(br);
  });
  _rerender.push(render);
  render();
})();

// ---- issuer time series ----
(function(){
  const sel = document.getElementById('issuerSel');
  const names = Object.keys(ISSUERS.series).sort((a, b) => a.localeCompare(b, 'ko'));
  sel.innerHTML = names.map(n => `<option>${n}</option>`).join('');
  function draw(){
    const s = ISSUERS.series[sel.value];
    const fmtD = d => d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6);
    const peer = s.spread_sm.map((v, i) => v - s.vs_peer[i]);
    const ind = ISSUERS.industries[s.industry];
    const traces = [
      { x: s.dates.map(fmtD), y: s.spread_sm, mode: 'lines', name: t('spread_bp')(sel.value), line: { width: 2.5, color: '#2563eb' } },
      { x: s.dates.map(fmtD), y: peer, mode: 'lines', name: t('peer_median')(s.rating),
        line: { width: 1.5, dash: 'dash', color: '#999' } }
    ];
    if (ind) traces.push({ x: ind.dates.map(fmtD), y: ind.spread_sm, mode: 'lines',
      name: t('ind_median')(indName(s.industry)), line: { width: 1.5, dash: 'dot', color: '#b45309' } });
    const evs = ((RATING && RATING.by_issuer) || {})[sel.value] || [];
    const shapes = evs.map(e => ({ type: 'line', x0: fmtD(e.date), x1: fmtD(e.date),
      yref: 'paper', y0: 0, y1: 1,
      line: { color: e.direction === 'down' ? '#e5484d' : '#2a7d4f', width: 1.5, dash: 'dot' } }));
    const anns = evs.map(e => ({ x: fmtD(e.date), yref: 'paper', y: 1.02, showarrow: false,
      text: `${e.from}→${e.to}`, font: { size: 10, color: e.direction === 'down' ? '#e5484d' : '#2a7d4f' } }));
    try {
      if (typeof Plotly === 'undefined') throw new Error('chart library unavailable');
      Plotly.newPlot('ts', traces, {
        margin: { t: 24, r: 10, b: 40, l: 50 },
        yaxis: { title: 'bp' }, legend: { orientation: 'h', y: -0.28 }, height: 340,
        shapes: shapes, annotations: anns
      }, { displayModeBar: false, responsive: true });
    } catch (e) {
      const el = document.getElementById('ts');
      if (el) el.innerHTML = `<div style="color:#666;font-size:14px;padding:16px 0;">${t('chart_fail_plain')}</div>`;
    }
  }
  sel.addEventListener('change', draw);
  sel.value = names.includes('한국전력공사채권') ? '한국전력공사채권' : names[0];
  _rerender.push(draw);
  draw();
})();
</script>
<div class="wrap" style="padding-top:0">
<div class="card">
<details>
<summary style="cursor:pointer;font-weight:600" data-i18n="method_title">스프레드 계산식</summary>
<div class="note" style="margin-top:8px;line-height:1.8" data-i18n-html="method_body">
1. 개별 거래 스프레드(bp) = (채권 수익률 − 동일 잔존기간 버킷의 국고채 수익률 중간값) × 100<br>
2. 잔존기간 버킷: 3M / 6M / 1Y / 2Y / 3Y / 5Y / 10Y / 20Y / 30Y (잔존기간은 YYMMDD 형식)<br>
3. 발행자-일별 스프레드 = Σ(버킷별 중간 스프레드 × 버킷 거래대금) / Σ(버킷 거래대금) — 거래대금 가중평균<br>
4. 일 3건 미만 거래된 발행자-일은 제외<br>
5. 5거래일 이동중앙값으로 평활화<br>
6. 동급대비(bp) = 자사 스프레드 − 동일 신용등급 발행자들의 당일 중간값<br>
7. 5일변화 = 평활 스프레드 − 5거래일 전 값 / 20일변화 = 20거래일 전 값 대비<br>
8. 단기 = 잔존기간 1년 이하 버킷만으로 3번 계산 / 장기 = 1년 초과 버킷만으로 계산
</div>
</details>
</div>
<div class="note" style="text-align:center;border-top:1px solid #eee;padding-top:12px">
<a href="https://sdykim.me/" style="color:#888">sdykim.me</a> · Doyeon Kim
</div></div>
<script>/*VIEWCOUNT*/(function(){try{fetch('https://abacus.jasoncameron.dev/hit/sdykim-bond-credit-monitor/monitor',{keepalive:true}).catch(function(){});}catch(e){}})();</script>
</body>
</html>
"""


# issuer -> (ticker, listed company name), same mapping as the divergence page.
# Bond issuers that are banks map to their listed holding company.
STOCK_MAP = {
    "중소기업은행": ("024110", "기업은행"),
    "삼성카드": ("029780", "삼성카드"),
    "JB금융지주": ("175330", "JB금융지주"),
    "DGB금융지주": ("139130", "iM금융지주"),
    "한국전력공사": ("015760", "한국전력"),
    "한국전력공사채권": ("015760", "한국전력"),
    "한화생명보험": ("088350", "한화생명"),
    "미래에셋증권": ("006800", "미래에셋증권"),
    "삼성증권": ("016360", "삼성증권"),
    "대한항공": ("003490", "대한항공"),
    "한국가스공사": ("036460", "한국가스공사"),
    "LG화학": ("051910", "LG화학"),
    "에스케이하이닉스": ("000660", "SK하이닉스"),
    "롯데케미칼": ("011170", "롯데케미칼"),
    "금호타이어": ("073240", "금호타이어"),
    "삼성중공업": ("010140", "삼성중공업"),
    "현대글로비스": ("086280", "현대글로비스"),
    "한진": ("002320", "한진"),
    "현대제철": ("004020", "현대제철"),
    "국민은행": ("105560", "KB금융"),
    "신한은행": ("055550", "신한지주"),
    "하나은행": ("086790", "하나금융지주"),
    "우리은행": ("316140", "우리금융지주"),
}

_stock_cache = {}


def fetch_stock_closes(ticker):
    """Daily closes from Naver fchart, {YYYYMMDD: close}. Empty on failure."""
    if ticker in _stock_cache:
        return _stock_cache[ticker]
    out = {}
    try:
        url = (f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}"
               f"&timeframe=day&count=700&requestType=0")
        raw = subprocess.run(["curl", "-sL", "--max-time", "30", url],
                             capture_output=True).stdout.decode("utf-8", "ignore")
        for m in re.finditer(r'item data="(\d{8})\|[^|]*\|[^|]*\|[^|]*\|(\d+)\|', raw):
            out[m.group(1)] = float(m.group(2))
    except Exception:
        out = {}
    _stock_cache[ticker] = out
    return out


def stock_ret(issuer, asof, window):
    """Stock return (%) over `window` trading days ending at/before `asof`.

    Returns (listed_name, pct), or (None, None) when the issuer is unmapped
    or stock data is missing. Never raises: a failed fetch just hides the
    stock line on the page.
    """
    m = STOCK_MAP.get(issuer)
    if not m:
        return None, None
    closes = fetch_stock_closes(m[0])
    if len(closes) < window + 1:
        return None, None
    dates = sorted(closes)
    idx = [i for i, d in enumerate(dates) if d <= asof]
    if not idx or idx[-1] < window:
        return None, None
    i = idx[-1]
    base = closes[dates[i - window]]
    last = closes[dates[i]]
    if not base:
        return None, None
    return m[1], round(100 * (last / base - 1), 1)


def build_alerts(iss):
    """Alert payload: items with severity + 90d-high flag, grouped by corporate
    group, plus group-level contagion signals (>=2 alerts in one group)."""
    from collections import defaultdict
    from build_bonds import group_of, GROUP_OF
    real_groups = set(GROUP_OF.values())
    table = iss["latest_table"]
    series = iss["series"]
    bad = [r for r in table if r.get("chg_5d") is not None and r["chg_5d"] >= 15]
    bad.sort(key=lambda r: -r["chg_5d"])
    items = []
    for r in bad:
        s = series.get(r["issuer"])
        high = False
        if s and s["spread_sm"]:
            w = s["spread_sm"][-90:]
            high = r["spread"] >= max(w) - 1e-9
        c5 = r["chg_5d"]
        sev = "surge" if c5 >= 100 else "sharp" if c5 >= 50 else "widen" if c5 >= 30 else "hint"
        item = {
            "issuer": r["issuer"], "rating": r["rating"], "industry": r["industry"],
            "group": group_of(r["issuer"], r["industry"]),
            "spread": r["spread"], "vs_peer": r["vs_peer"],
            "chg_5d": r["chg_5d"], "chg_20d": r["chg_20d"],
            "sev": sev, "high90": high,
        }
        sname, sret = stock_ret(r["issuer"], iss["meta"]["last_date"], 5)
        if sret is not None:
            item["stock_name"] = sname
            item["stock_5d"] = sret
        items.append(item)
    by_grp = defaultdict(list)
    for r in items:
        by_grp[r["group"]].append(r)
    signals = []
    for grp, rs in by_grp.items():
        # only real corporate groups count as contagion; industry fallbacks
        # (e.g. 정책금융: 수산금융채권 + 한국수출입금융 are unrelated) do not
        if grp not in real_groups:
            continue
        if len(rs) >= 2:
            signals.append({
                "group": grp, "count": len(rs),
                "top": [{"issuer": x["issuer"], "chg_5d": x["chg_5d"]} for x in rs[:4]],
            })
    signals.sort(key=lambda x: -x["count"])
    return {"items": items, "group_signals": signals}


def build_rating_payload(iss, recent_n=12):
    """Rating-change payload from track_ratings.py output.

    recent: latest events across all issuers, enriched with spread context
    when the issuer is in the monitor series. by_issuer: events per series
    issuer, used as chart markers.
    """
    path = os.path.join(DATA, "rating_changes.json")
    if not os.path.exists(path):
        return {"recent": [], "by_issuer": {}}
    with open(path) as f:
        events = json.load(f)["events"]
    series = iss["series"]

    def context(issuer, date):
        s = series.get(issuer)
        if not s:
            return None, None
        dates = s["dates"]
        idx = [i for i, d in enumerate(dates) if d <= date]
        if not idx:
            return None, None
        i = idx[-1]
        at = s["spread_sm"][i]
        pre = round(at - s["spread_sm"][i - 20], 1) if i >= 20 else None
        return (round(at, 1) if at is not None else None), pre

    by_issuer = {}
    for e in events:
        if e["issuer"] in series:
            by_issuer.setdefault(e["issuer"], []).append(
                {"date": e["date"], "from": e["from"], "to": e["to"],
                 "direction": e["direction"]})
    recent = []
    for e in sorted(events, key=lambda x: x["date"], reverse=True)[:recent_n]:
        at, pre = context(e["issuer"], e["date"])
        rec = {"issuer": e["issuer"], "date": e["date"],
               "from": e["from"], "to": e["to"],
               "direction": e["direction"], "n_bonds": e["n_bonds"],
               "spread_at": at, "chg_pre20": pre}
        sname, sret = stock_ret(e["issuer"], e["date"], 20)
        if sret is not None:
            rec["stock_name"] = sname
            rec["stock_20d"] = sret
        recent.append(rec)
    return {"recent": recent, "by_issuer": by_issuer}


def main():
    with open(os.path.join(DATA, "issuers.json")) as f:
        iss = json.load(f)
    with open(os.path.join(DATA, "dashboard_data.json")) as f:
        dash = json.load(f)

    with open(os.path.join(DATA, "bonds.json")) as f:
        bonds = json.load(f)

    # curve: latest + ~30d prior
    curve = dash["curve"]
    dates = sorted({r["date"] for r in curve})
    latest_d = dates[-1]
    prev_d = next((d for d in reversed(dates) if d <= str(int(latest_d) - 100)), dates[0])
    def pts(d):
        return [{"tenor": r["bucket"], "yld": round(r["yld"], 3)}
                for r in curve if r["date"] == d]
    curve_json = {"series": [
        {"date": prev_d, "latest": False, "points": pts(prev_d)},
        {"date": latest_d, "latest": True, "points": pts(latest_d)},
    ]}

    # trim issuer series payload: keep full history (already compact)
    meta = {
        "first": iss['meta']['first_date'], "last": iss['meta']['last_date'],
        "n_days": iss['meta']['n_days'], "n_universe": len(iss['meta']['universe']),
        "updated": datetime.now().strftime('%Y-%m-%d %H:%M'),
    }
    html = HTML.replace("/*ISSUERS_JSON*/", json.dumps(iss, ensure_ascii=False))
    html = html.replace("/*CURVE_JSON*/", json.dumps(curve_json, ensure_ascii=False))
    html = html.replace("/*ALERTS_JSON*/", json.dumps(build_alerts(iss), ensure_ascii=False))
    html = html.replace("/*BONDS_JSON*/", json.dumps(bonds, ensure_ascii=False))
    html = html.replace("/*META_JSON*/", json.dumps(meta))
    html = html.replace("/*RATING_JSON*/", json.dumps(build_rating_payload(iss), ensure_ascii=False))
    nav = open(os.path.join(DATA, "github_pages", "nav_fragment.html"), encoding="utf-8").read()
    assert "<!--NAV-->" in html
    html = html.replace("<!--NAV-->", nav)
    with open(OUT, "w") as f:
        f.write(html)
    print("wrote", OUT, f"{os.path.getsize(OUT)/1024:.0f}KB")


SLIM_DAYS = 75


def build_github(out_dir):
    """Slim variant for GitHub Pages: index.html + data.js (each < 120KB).

    Series trimmed to last SLIM_DAYS trading days, only fields the page uses.
    """
    with open(os.path.join(DATA, "issuers.json")) as f:
        iss = json.load(f)
    with open(os.path.join(DATA, "dashboard_data.json")) as f:
        dash = json.load(f)
    with open(os.path.join(DATA, "bonds.json")) as f:
        bonds = json.load(f)

    slim_series = {}
    for name, s in iss["series"].items():
        n = len(s["dates"])
        k = max(0, n - SLIM_DAYS)
        slim_series[name] = {
            "rating": s["rating"],
            "industry": s["industry"],
            "dates": s["dates"][k:],
            "spread_sm": s["spread_sm"][k:],
            "vs_peer": s["vs_peer"][k:],
        }
    slim_ind = {}
    for ind, s in iss["industries"].items():
        n = len(s["dates"])
        k = max(0, n - SLIM_DAYS)
        slim_ind[ind] = {"dates": s["dates"][k:], "spread_sm": s["spread_sm"][k:]}
    slim_iss = {
        "meta": iss["meta"],
        "series": slim_series,
        "industries": slim_ind,
        "latest_table": iss["latest_table"],
    }

    curve = dash["curve"]
    dates = sorted({r["date"] for r in curve})
    latest_d = dates[-1]
    prev_d = next((d for d in reversed(dates) if d <= str(int(latest_d) - 100)), dates[0])
    def pts(d):
        return [{"tenor": r["bucket"], "yld": round(r["yld"], 3)}
                for r in curve if r["date"] == d]
    data = {
        "issuers": slim_iss,
        "curve": {"series": [
            {"date": prev_d, "latest": False, "points": pts(prev_d)},
            {"date": latest_d, "latest": True, "points": pts(latest_d)},
        ]},
        "alerts": build_alerts(iss),
        "rating": build_rating_payload(iss),
        "meta": {
            "first": prev_d, "last": iss['meta']['last_date'],
            "n_days": 75, "n_universe": len(iss['meta']['universe']),
            "updated": datetime.now().strftime('%Y-%m-%d %H:%M'),
        },
    }
    html = HTML.replace(
        "const ISSUERS = /*ISSUERS_JSON*/;\nconst CURVE = /*CURVE_JSON*/;\nconst ALERTS = /*ALERTS_JSON*/;\nconst META = /*META_JSON*/;\nconst RATING = /*RATING_JSON*/;",
        "const ISSUERS = window.DASHBOARD_DATA.issuers;\nconst CURVE = window.DASHBOARD_DATA.curve;\nconst ALERTS = window.DASHBOARD_DATA.alerts;\nconst META = window.DASHBOARD_DATA.meta;\nconst RATING = window.DASHBOARD_DATA.rating;",
    )
    html = html.replace("<script>\nconst ISSUERS", '<script src="data.js"></script>\n<script src="bonds.js"></script>\n<script>\nconst ISSUERS')
    # bonds.js already sets window.BONDS; leaving the placeholder line would be
    # a syntax error (assignment with no value) that kills the whole script.
    html = html.replace("window.BONDS = /*BONDS_JSON*/;\n", "")
    nav = open(os.path.join(DATA, "github_pages", "nav_fragment.html"), encoding="utf-8").read()
    assert "<!--NAV-->" in html
    html = html.replace("<!--NAV-->", nav)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "data.js"), "w") as f:
        f.write("window.DASHBOARD_DATA = ")
        json.dump(data, f, ensure_ascii=False)
        f.write(";")
    with open(os.path.join(out_dir, "bonds.js"), "w") as f:
        f.write("window.BONDS = ")
        json.dump(bonds, f, ensure_ascii=False)
        f.write(";")
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(html)
    for fn in ("index.html", "data.js"):
        p = os.path.join(out_dir, fn)
        print("wrote", p, f"{os.path.getsize(p)/1024:.0f}KB")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--github":
        # The site root is a redirect to the events page (the main page);
        # the dashboard itself lives under monitor/.
        build_github(os.path.join(DATA, "github_pages", "monitor"))
    else:
        main()
