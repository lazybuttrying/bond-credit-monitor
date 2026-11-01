"""Intraday trade-flow page for the bond monitor.

For each confirmed rating event (rating_changes.json, from track_ratings.py)
whose issuer traded at least 30 times on the event day, build a print-level
panel: time-of-day yield scatter, cumulative amount vs the previous trading
day, hourly buy/sell and flow-type bars, and a sudden-move list (same-bond
consecutive prints moving 10bp+, and 10-minute amount bursts above 3x the
day's median 10-minute window).

Trade cleaning mirrors build_issuers.process_file exactly where it matters:
dedup_trades runs on the production column set (key date + hash, NULL-hash
signature fallback, no-hash files returned unchanged) so every count and
amount matches the published aggregates. The KTB overlay uses the same
tenor buckets as the monitor's spread baseline.

The feed is stopped (last complete day 2026-10-20; the 2026-10-28 file is a
559-row partial), so this page is an archive of event days, and it says so.

Outputs github_pages/intraday/index.html from template.html with the data
inlined (never a separate data file: the 2026-10-25 cache-skew lesson).
Additive only: no production pipeline or published number changes.
"""

import glob
import json
import math
import os
import sys
from datetime import date as ddate
from html import escape

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_issuers import (  # noqa: E402
    TENOR_EDGES,
    TENOR_LABELS,
    dedup_trades,
    parse_issuer,
    parse_tenor_years,
    to_num,
)

DATA = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(DATA, "github_pages", "intraday")
EVENTS_JSON = os.path.join(DATA, "rating_changes.json")

MIN_EVENT_TRADES = 30
MAX_EVENTS = 12
LAST_FULL_DAY = "20261020"  # feed stopped; 20261028 is a 559-row partial
RECENT_MONTHS = 12
JUMP_BP = 10.0
BURST_MULT = 3.0
KTB_CAP = 900

PROD_COLS = ["종목명", "잔존기간", "신용등급", "수익률", "거래대금",
             "날짜", "시간", "단가(원)", "거래량", "hash", "numbering"]
ALL_COLS = PROD_COLS + ["시장구분", "매매구분", "매매유형"]

FTYPE_EN = {"자기": "Proprietary", "중개": "Brokered", "기타": "Other"}
SIDE_EN = {"매수": "Buy", "매도": "Sell"}


def issuer_of(name):
    n = str(name).strip()
    if n.startswith("S-Oil"):
        return "S-Oil"
    return parse_issuer(n)


def parse_time_min(s):
    s = str(s).strip().zfill(6)
    if len(s) != 6 or not s.isdigit():
        return np.nan
    return int(s[:2]) * 60 + int(s[2:4]) + int(s[4:6]) / 60.0


def fmt_time(minutes):
    m = int(minutes)
    return f"{m // 60:02d}:{m % 60:02d}"


def fmt_date(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def fmt_eok(raw_manwon):
    return f"{raw_manwon / 10000.0:,.1f}"


def load_day(date):
    """One day of trades, cleaned exactly like production where it counts."""
    path = os.path.join(DATA, f"result_today_{date}.xlsx.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path, columns=ALL_COLS)
    sub = df[[c for c in PROD_COLS if c in df.columns]].copy()
    kept = dedup_trades(sub)
    df = df.loc[kept.index].copy()
    df["yld"] = to_num(df["수익률"])
    df["amt"] = to_num(df["거래대금"]).fillna(0)
    df = df.dropna(subset=["yld"])
    df = df[(df["yld"] > 0) & (df["yld"] < 30)]
    df["tenor_y"] = df["잔존기간"].map(parse_tenor_years)
    df = df.dropna(subset=["tenor_y"])
    df["bucket"] = pd.cut(df["tenor_y"], bins=TENOR_EDGES, labels=TENOR_LABELS)
    df = df.dropna(subset=["bucket"])
    df["bucket"] = df["bucket"].astype(str)
    df["bond"] = df["종목명"].astype(str).str.strip()
    df["issuer"] = df["bond"].map(issuer_of)
    df["t_min"] = df["시간"].map(parse_time_min)
    df = df.dropna(subset=["t_min"])
    df["time_str"] = df["시간"].astype(str).str.strip().str.zfill(6).map(
        lambda s: f"{s[:2]}:{s[2:4]}:{s[4:6]}")
    df["side"] = df["매매구분"].astype(str).str.strip()
    df["ftype"] = df["매매유형"].astype(str).str.strip()
    return df.sort_values("t_min", kind="stable").reset_index(drop=True)


def all_file_dates():
    out = []
    for p in glob.glob(os.path.join(DATA, "result_today_*.xlsx.parquet")):
        base = os.path.basename(p)
        out.append(base[len("result_today_"):len("result_today_") + 8])
    return sorted(out)


def prev_trading_day(date, dates):
    prev = [d for d in dates if d < date]
    return prev[-1] if prev else None


def side_key(side):
    if side == "매수":
        return "buy"
    if side == "매도":
        return "sell"
    return "other"


def marker_size(amt_raw):
    eok = amt_raw / 10000.0
    return round(min(26.0, max(5.0, 4.0 + 3.0 * math.sqrt(max(eok, 0.0)))), 1)


def cum_series(sub):
    pts = []
    run = 0.0
    for _, r in sub.iterrows():
        run += float(r["amt"])
        pts.append([round(float(r["t_min"]), 2), round(run / 10000.0, 2)])
    return pts


def sudden_moves(sub):
    """Return (moves, jump_count, burst_count). Each move is a dict with
    render-ready ko/en detail strings."""
    moves = []
    for bond, g in sub.groupby("bond", sort=False):
        prev = None
        for _, r in g.iterrows():
            if prev is not None:
                d = float(r["yld"]) - float(prev["yld"])
                if abs(d) * 100 >= JUMP_BP - 1e-9:
                    amt = float(r["amt"])
                    side_ko = str(r["side"])
                    ft_ko = str(r["ftype"])
                    detail_ko = (f"{prev['yld']:.3f}% → {r['yld']:.3f}% "
                                 f"({d * 100:+.1f}bp), {side_ko}, "
                                 f"{fmt_eok(amt)}억원, {ft_ko}")
                    detail_en = (f"{prev['yld']:.3f}% → {r['yld']:.3f}% "
                                 f"({d * 100:+.1f}bp), "
                                 f"{SIDE_EN.get(side_ko, 'Other')}, "
                                 f"{fmt_eok(amt)} (KRW 100M), "
                                 f"{FTYPE_EN.get(ft_ko, 'Other')}")
                    moves.append({
                        "kind": "jump", "t": float(r["t_min"]),
                        "time": str(r["time_str"]), "bond": str(bond),
                        "detail_ko": detail_ko, "detail_en": detail_en,
                        "absbp": abs(d) * 100,
                    })
            prev = r
    sub = sub.assign(bin=(sub["t_min"] // 10 * 10).astype(int))
    bins = sub.groupby("bin")
    bin_amt = bins["amt"].sum()
    if len(bin_amt):
        med = float(bin_amt.median())
        for b, total in bin_amt.items():
            if med > 0 and total > BURST_MULT * med:
                g = sub[sub["bin"] == b]
                buy_amt = float(g[g["side"] == "매수"]["amt"].sum())
                buy_pct = round(100.0 * buy_amt / float(total)) if total else 0
                ft = g.groupby("ftype")["amt"].sum()
                dom = str(ft.idxmax())
                detail_ko = (f"{fmt_time(b)}부터 10분간 {fmt_eok(float(total))}억원 "
                             f"({len(g)}건), 매수 비중 {buy_pct}%, 주요 유형 {dom}")
                detail_en = (f"{fmt_eok(float(total))} (KRW 100M) in the 10 minutes "
                             f"from {fmt_time(b)} ({len(g)} trades), buy share "
                             f"{buy_pct}%, mostly {FTYPE_EN.get(dom, 'Other')}")
                moves.append({
                    "kind": "burst", "t": float(b),
                    "time": fmt_time(b), "bond": "",
                    "detail_ko": detail_ko, "detail_en": detail_en,
                    "absbp": 0.0,
                })
    jumps = [m for m in moves if m["kind"] == "jump"]
    bursts = [m for m in moves if m["kind"] == "burst"]
    if len(jumps) > 30:
        jumps = sorted(jumps, key=lambda m: -m["absbp"])[:30]
        moves = sorted(jumps + bursts, key=lambda m: (m["t"], m["kind"]))
    else:
        moves = sorted(moves, key=lambda m: (m["t"], m["kind"]))
    return moves, len(jumps), len(bursts)


def event_payload(ev, day_df, base_df):
    issuer = ev["issuer"]
    sub = day_df[day_df["issuer"] == issuer]
    bonds = sorted(sub["bond"].unique().tolist())
    bond_idx = {b: i for i, b in enumerate(bonds)}

    scatter = {"buy": {"t": [], "y": [], "s": [], "amt": [], "text": []},
               "sell": {"t": [], "y": [], "s": [], "amt": [], "text": []},
               "other": {"t": [], "y": [], "s": [], "amt": [], "text": []}}
    for _, r in sub.iterrows():
        g = scatter[side_key(str(r["side"]))]
        g["t"].append(round(float(r["t_min"]), 2))
        g["y"].append(round(float(r["yld"]), 3))
        g["s"].append(marker_size(float(r["amt"])))
        g["amt"].append(round(float(r["amt"]) / 10000.0, 2))
        g["text"].append(f"{r['bond']} {r['time_str']}")

    buckets = set(sub["bucket"].unique().tolist())
    ktb = day_df[day_df["bond"].str.startswith("국고채권")
                 & day_df["bucket"].isin(buckets)]
    capped = False
    if len(ktb) > KTB_CAP:
        step = int(np.ceil(len(ktb) / KTB_CAP))
        ktb = ktb.iloc[::step]
        capped = True
    ktb_xy = {"t": [round(float(v), 2) for v in ktb["t_min"]],
              "y": [round(float(v), 3) for v in ktb["yld"]]}

    base_sub = None
    if base_df is not None:
        cand = base_df[base_df["issuer"] == issuer]
        if len(cand):
            base_sub = cand
    cum = {"ev": cum_series(sub),
           "base": cum_series(base_sub) if base_sub is not None else None}

    hours = sorted(set(int(v // 60) for v in sub["t_min"]))
    hourly = {"h": hours, "buy": [], "sell": [], "own": [], "bro": []}
    for h in hours:
        g = sub[(sub["t_min"] >= h * 60) & (sub["t_min"] < (h + 1) * 60)]
        hourly["buy"].append(round(float(g[g["side"] == "매수"]["amt"].sum()) / 10000.0, 2))
        hourly["sell"].append(round(float(g[g["side"] == "매도"]["amt"].sum()) / 10000.0, 2))
        hourly["own"].append(round(float(g[g["ftype"] == "자기"]["amt"].sum()) / 10000.0, 2))
        bro = g[g["ftype"].isin(["중개", "기타"])]["amt"].sum()
        hourly["bro"].append(round(float(bro) / 10000.0, 2))

    moves, n_jumps, n_bursts = sudden_moves(sub)
    payload = {
        "scatter": {**scatter, "ktb": ktb_xy},
        "cum": cum,
        "hourly": hourly,
    }
    meta = {
        "issuer": issuer, "date": ev["date"], "from": ev["from"],
        "to": ev["to"], "direction": ev["direction"],
        "notches": ev.get("notches"), "n_bonds_event": ev.get("n_bonds"),
        "n": int(len(sub)), "total_raw": float(sub["amt"].sum()),
        "baseline_date": base_df.attrs.get("date") if base_df is not None else None,
        "baseline_n": int(len(base_sub)) if base_sub is not None else 0,
        "moves": moves, "n_jumps": n_jumps, "n_bursts": n_bursts,
        "ktb_points": int(len(ktb)), "ktb_capped": capped,
        "n_bonds_traded": len(bonds),
    }
    return payload, meta


def render_moves_rows(moves):
    if not moves:
        return ('<p class="stats"><span class="ko">이 날은 기준을 넘는 급격한 움직임이 '
                '없었습니다.</span><span class="en">No move crossed the thresholds '
                'on this day.</span></p>')
    rows = []
    for m in moves:
        kind_ko = "수익률 점프" if m["kind"] == "jump" else "거래 집중"
        kind_en = "Yield jump" if m["kind"] == "jump" else "Amount burst"
        bond = escape(m["bond"]) if m["bond"] else (
            '<span class="ko">발행자 전체</span><span class="en">Whole issuer</span>')
        rows.append(
            f'<tr><td style="white-space:nowrap">{escape(m["time"])}</td>'
            f'<td>{bond}</td>'
            f'<td><span class="kind {m["kind"]}"><span class="ko">{kind_ko}</span>'
            f'<span class="en">{kind_en}</span></span></td>'
            f'<td><span class="ko">{escape(m["detail_ko"])}</span>'
            f'<span class="en">{escape(m["detail_en"])}</span></td></tr>')
    return ('<div class="tblwrap"><table class="moves"><thead><tr>'
            '<th><span class="ko">시각</span><span class="en">Time</span></th>'
            '<th><span class="ko">종목</span><span class="en">Bond</span></th>'
            '<th><span class="ko">구분</span><span class="en">Type</span></th>'
            '<th><span class="ko">상세</span><span class="en">Detail</span></th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')


def render_panel(eid, meta):
    issuer = escape(meta["issuer"])
    direction = meta["direction"]
    badge_cls = "up" if direction == "up" else "down"
    dir_ko = "상향" if direction == "up" else "하향"
    dir_en = "Upgrade" if direction == "up" else "Downgrade"
    notch = meta["notches"]
    notch_ko = f"{notch}노치 " if notch else ""
    notch_en = f"{notch}-notch " if notch else ""
    bdate = fmt_date(meta["baseline_date"]) if meta["baseline_date"] else ""
    total = fmt_eok(meta["total_raw"])
    if meta["baseline_date"]:
        base_ko = (f"직전 거래일({bdate}) 거래는 {meta['baseline_n']}건이었습니다.")
        base_en = (f"Previous trading day ({bdate}): {meta['baseline_n']} trades.")
        if meta["baseline_n"] == 0:
            base_ko = f"직전 거래일({bdate})에는 이 발행자 거래가 없었습니다."
            base_en = (f"Previous trading day ({bdate}): no trades in this issuer.")
    else:
        base_ko = "직전 거래일 파일이 없습니다."
        base_en = "No previous trading day file."
    return f"""<section class="card evpanel" id="panel-{eid}" style="display:none">
  <h2>{issuer} {escape(str(meta['from']))} → {escape(str(meta['to']))}<span class="badge {badge_cls}"><span class="ko">{dir_ko}</span><span class="en">{dir_en}</span></span></h2>
  <p class="stats ko">등급 변경 {notch_ko}{dir_ko}, 사건일 {fmt_date(meta['date'])}. 사건일 거래 {meta['n']}건, 총 거래대금 {total}억원. {base_ko}</p>
  <p class="stats en">Rating change, {notch_en}{dir_en.lower()}, event day {fmt_date(meta['date'])}. {meta['n']} trades on the event day, total amount {total} (KRW 100M). {base_en}</p>
  <h3 class="chart-title"><span class="ko">체결 산포도</span><span class="en">Trade prints</span></h3>
  <p class="chart-desc ko">점 크기 = 거래금액. 색은 매수와 매도 방향입니다. 회색 점은 같은 날 거래된 국고채권 중 이 발행자가 거래한 잔존기간 구간과 같은 구간의 체결입니다.</p>
  <p class="chart-desc en">Dot size = amount. Color is the buy or sell direction. Gray dots are same-day Korea Treasury Bond prints in the same remaining-maturity buckets this issuer traded in.</p>
  <div class="chart" id="sc-{eid}"></div>
  <h3 class="chart-title"><span class="ko">누적 거래대금, 사건일과 직전 거래일</span><span class="en">Cumulative amount, event day vs previous day</span></h3>
  <p class="chart-desc ko">기울기가 가팔라지는 구간이 거래가 몰린 시간입니다.</p>
  <p class="chart-desc en">Where the slope steepens, trading was concentrated.</p>
  <div class="chart" id="cu-{eid}"></div>
  <div class="trow">
    <div class="tcol">
      <h3 class="chart-title"><span class="ko">시간대별 매수와 매도 금액</span><span class="en">Hourly buy vs sell amount</span></h3>
      <div class="chart" id="hb-{eid}"></div>
    </div>
    <div class="tcol">
      <h3 class="chart-title"><span class="ko">시간대별 매매유형 금액</span><span class="en">Hourly amount by flow type</span></h3>
      <div class="chart" id="hf-{eid}"></div>
    </div>
  </div>
  <h3 class="chart-title"><span class="ko">급격한 움직임</span><span class="en">Sudden moves</span></h3>
  {render_moves_rows(meta['moves'])}
  <p class="note ko">기준: 같은 종목의 연속 체결에서 수익률이 10bp 이상 움직인 경우, 그리고 10분 구간 거래금액이 그날 거래가 있는 10분 구간 중앙값의 3배를 넘은 경우를 표시합니다.</p>
  <p class="note en">Thresholds: consecutive prints in the same bond moving 10bp or more, and 10-minute windows whose amount exceeds 3x the median of the day's non-empty 10-minute windows.</p>
</section>"""


def render_button(eid, meta):
    return (f'<button data-ev="{eid}">{escape(meta["issuer"])} '
            f'{escape(str(meta["from"]))}→{escape(str(meta["to"]))}<br>'
            f'<span class="d">{fmt_date(meta["date"])}, {meta["n"]}'
            f'<span class="ko">건</span><span class="en"> trades</span></span></button>')


def main():
    events = json.load(open(EVENTS_JSON, encoding="utf-8"))["events"]
    dates = all_file_dates()
    y, m, d = int(LAST_FULL_DAY[:4]), int(LAST_FULL_DAY[4:6]), int(LAST_FULL_DAY[6:])
    # 12 calendar months before the last full day
    cutoff = ddate(y - 1, m, d).strftime("%Y%m%d")
    print(f"recent-12-month cutoff: {cutoff} (last full day {LAST_FULL_DAY})")

    day_cache = {}

    def get_day(date):
        if date not in day_cache:
            df = load_day(date)
            if df is not None:
                df.attrs["date"] = date
            day_cache[date] = df
        return day_cache[date]

    eligible = []
    for ev in events:
        df = get_day(ev["date"])
        if df is None:
            print(f"skip {ev['issuer']} {ev['date']}: no file")
            continue
        n = int((df["issuer"] == ev["issuer"]).sum())
        if n >= MIN_EVENT_TRADES:
            eligible.append((ev, n))
            print(f"eligible: {ev['date']} {ev['issuer']} {n} trades "
                  f"({ev['from']}->{ev['to']} {ev['direction']})")
    eligible.sort(key=lambda en: (0 if en[0]["date"] >= cutoff else 1, -en[1]))
    selected = eligible[:MAX_EVENTS]
    print(f"selected {len(selected)} of {len(eligible)} eligible "
          f"({len(events)} rating events total)")

    out_events, buttons, panels = [], [], []
    for i, (ev, _n) in enumerate(selected):
        eid = f"ev{i}"
        day_df = get_day(ev["date"])
        bdate = prev_trading_day(ev["date"], dates)
        base_df = get_day(bdate) if bdate else None
        payload, meta = event_payload(ev, day_df, base_df)
        payload["id"] = eid
        out_events.append(payload)
        buttons.append(render_button(eid, meta))
        panels.append(render_panel(eid, meta))
        print(f"{eid}: {meta['date']} {meta['issuer']} n={meta['n']} "
              f"total={fmt_eok(meta['total_raw'])}억 baseline={bdate} "
              f"(n={meta['baseline_n']}) jumps={meta['n_jumps']} "
              f"bursts={meta['n_bursts']} ktb={meta['ktb_points']}"
              f"{' capped' if meta['ktb_capped'] else ''} "
              f"bonds={meta['n_bonds_traded']}")

    tpl = open(os.path.join(OUT_DIR, "template.html"), encoding="utf-8").read()
    assert "/*INTRADAY_JSON*/" in tpl
    assert "/*BUTTONS_HTML*/" in tpl
    assert "/*PANELS_HTML*/" in tpl
    assert "<!--NAV-->" in tpl
    payload_json = json.dumps({"events": out_events}, ensure_ascii=False)
    html = tpl.replace("/*INTRADAY_JSON*/", payload_json)
    html = html.replace("/*BUTTONS_HTML*/", "\n".join(buttons))
    html = html.replace("/*PANELS_HTML*/", "\n".join(panels))
    nav = open(os.path.join(DATA, "github_pages", "nav_fragment.html"),
               encoding="utf-8").read()
    html = html.replace("<!--NAV-->", nav)
    for token in ("INTRADAY_JSON", "BUTTONS_HTML", "PANELS_HTML", "<!--NAV-->"):
        assert token not in html, f"leftover placeholder: {token}"
    out_path = os.path.join(OUT_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", out_path, len(html.encode("utf-8")), "bytes")


if __name__ == "__main__":
    main()
