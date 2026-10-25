"""Event-based market-reaction page for the bond monitor.

Computes daily group-median spreads from the user's own trade data (same
methodology as the monitor: per-issuer 5-trading-day rolling median, then
the median across issuers each day), slices a window around each major 2026
event, and writes github_pages/monthly/index.html from template.html with
the data inlined (never a separate data file: the 2026-10-25 cache-skew
lesson).

Daily series are cached in github_pages/monthly/daily_series_v2.json so
re-runs (e.g. verdict edits) are instant.

Groups: ktb (government bonds incl. strips), bank (commercial-bank bucket,
policy banks split off by industry_of), corp (general corporates),
reit (other REITs, JR excluded), construct (builders), estate (private
developers/trusts), sll (SLL JoongAng), sbs (SBS), cb (JoongAng Ilbo).
"""

import glob
import json
import os
import sys

DATA = os.path.dirname(os.path.abspath(__file__))
MONTHLY_DIR = os.path.join(DATA, "github_pages", "monthly")
SERIES_PATH = os.path.join(MONTHLY_DIR, "daily_series_v2.json")

CONSTRUCT_LIST = {"삼성물산", "DL이앤씨", "SK에코플랜트", "HDC현대산업개발",
                  "IPARK현대산업개발", "현대엔지니어링", "포스코이앤씨"}
ESTATE_SET = {"롯데물산", "한국토지신탁", "신한자산신탁", "한국자산신탁",
              "신세계프라퍼티"}


def group_of(issuer, industry_fn):
    if issuer.startswith("국고채"):
        return "ktb"
    if "위탁관리부동산투자회사" in issuer and "제이알" not in issuer:
        return "reit"
    if ("건설" in issuer and "건설기계" not in issuer
            and "도로공사" not in issuer) or issuer in CONSTRUCT_LIST:
        return "construct"
    if issuer in ESTATE_SET or "에스테이트" in issuer or "프라퍼티" in issuer:
        return "estate"
    if issuer == "에스엘엘중앙":
        return "sll"
    if issuer == "SBS" or (issuer.startswith("SBS") and issuer[3:].isdigit()):
        return "sbs"
    if issuer == "중앙일보":
        return "cb"
    ind = industry_fn(issuer)
    if ind == "은행":
        return "bank"
    if ind == "일반기업":
        return "corp"
    return None


def src(outlet, date, topic, url):
    return {"outlet": outlet, "date": date, "topic": topic, "url": url}


EVENTS = [
    {
        "id": "mar-shock",
        "title": "3월 중동 오일쇼크",
        "date_label": "2026년 3월",
        "window": "month",
        "month": "202603",
        "topic": ["중동발 유가 충격에 국고 수익률 급등",
                  "1분기 일반채 발행 34.52조원, 전년 대비 24% 감소"],
        "sources": [
            src("서울경제", "2026-03-30", "1분기 일반채 발행 24% 급감",
                "https://en.sedaily.com/news/2026/03/30/corporate-bond-issuance-plunges-24-percent-as-rates-spike"),
            src("한국은행", "2026-04-08", "3월 금융시장 동향",
                "https://www.korea.net/Government/Briefing-Room/Press-Releases/view?articleId=8644&insttCode=A110427&type=O"),
            src("연합뉴스", "2026-04-29", "3월 채권 발행 19.54조원",
                "https://m.korean-vibe.com/news/newsview.php?ncode=179528853429716"),
        ],
        "verdict_qual": "수익률은 뛰었는데 스프레드는 전 그룹이 좁아졌다 (은행 23.8→11.4bp, 일반회사채 53.0→33.3bp). 국고가 더 뛰었다",
    },
    {
        "id": "jr-default",
        "title": "4/27 JR글로벌리츠 부도",
        "date_label": "2026년 4월 27일",
        "window": "around",
        "center": "20260427",
        "topic": ["JR글로벌리츠 400억 단기채 부도, 상장리츠 첫 회생 신청",
                  "등급 A-에서 D로 강등, 소액주주 약 2만 8천 명"],
        "sources": [
            src("아시아경제", "2026-04-30", "JR글로벌리츠 부도, 첫 상장리츠 회생",
                "https://www.asiae.co.kr/en/article/2026043016182113283"),
            src("연합뉴스", "2026-06-02", "4월 채권 발행 22.20조원",
                "https://en.yna.co.kr/view/AEN20260601007300320"),
        ],
        "verdict_qual": "타리츠는 59.3→64.9bp로 소폭 넓어졌다. 건설업 중앙값 하락 (119.5→64.8bp)은 넓었던 종목들의 거래가 끊긴 구성 효과에 가깝다 (SK에코플랜트 120.9→101.2bp, 현대건설 33.9→25.6bp). 시장 전체 전이는 없었다",
        "extra_title": "타리츠·건설업 스프레드 (bp)",
        "extra_keys": ["reit", "construct"],
        "extra_desc": "타리츠는 JR 제외, 건설업은 건설기계·도로공사 제외. 점선은 시장 전체 중앙값이다.",
        "note": "부동산업은 이 기간 거래된 민간 발행자가 롯데물산·한국토지신탁 등 5곳에 그치고 하루 3건 이상 거래일이 거의 없어 별도 선을 그을 수 없었다.",
    },
    {
        "id": "joongang",
        "title": "6/12 중앙그룹 위기",
        "date_label": "2026년 6월 12일",
        "window": "around",
        "center": "20260612",
        "topic": ["JTBC 206억 부도, 중앙그룹 계열사 5곳 회생 신청",
                  "그룹 부채 약 2.75조원, 등급 D·CCC·B-로 강등"],
        "sources": [
            src("연합인포맥스", "2026-06-15", "중앙그룹 투기등급 강등",
                "https://en.infomaxai.com/news/articleView.html?idxno=125357"),
            src("연합인포맥스", "2026-06-19", "중앙그룹 연쇄 부도·회생",
                "https://en.infomaxai.com/news/articleView.html?idxno=126185"),
            src("매일경제", "2026-07-초", "상반기 순발행 2016년 이후 최저",
                "https://www.mk.co.kr/en/stock/12090707"),
        ],
        "verdict_qual": "은행만 조금 넓어졌고 (16.9→20.0bp) 일반회사채는 좁아졌다 (45.0→42.7bp). 시장 전체로 번지지 않았다. 언론계는 아래 차트처럼 중앙일보가 3~4월에 이미 340bp대에서 거래됐다",
        "extra_title": "언론계 스프레드 (2026년 전체, bp)",
        "extra_keys": ["cb", "sbs"],
        "extra_desc": "중앙일보는 3~4월에 이미 320~366bp대에서 거래되며 위기 전부터 스트레스를 반영했고, 6월 전후로는 거래가 끊겼다. SBS는 드문드문 점으로만 보인다. 점선은 시장 전체 중앙값이다.",
        "extra_full_year": True,
        "extra_markers": [{"date": "2026-06-12", "label": "사건", "color": "#dc2626"}],
    },
    {
        "id": "summer",
        "title": "7/16 인상 ~ 9/15 고점",
        "date_label": "2026년 7월 16일 ~ 9월 15일",
        "window": "range",
        "start_center": "20260716",
        "end_center": "20260915",
        "topic": ["기준금리 2.50%→2.75% 첫 인상 (7/16), 3.00% 두 번째 인상 (8/27)",
                  "AA- 3년물 4.750% 연중 최고 (9/15), 9~10월 만기 13.47조원"],
        "sources": [
            src("한국은행", "2026-07-16", "기준금리 2.75% 첫 인상",
                "https://www.bok.or.kr/eng/bbs/E0000634/view.do?nttId=11062944&searchCnd=1&searchKwd&depth2=400417&depth3=400423&depth=400423&pageUnit=10&pageIndex=1&programType=newsDataEng&menuNo=400423&oldMenuNo=400423"),
            src("SBS", "2026-08", "기준금리 3.00% 두 번째 인상",
                "https://news.sbs.co.kr/english/article.do?news_id=N1008725743"),
            src("이데일리", "2026-08-02", "7월 스프레드 67.5bp에서 72.0bp로 확대",
                "https://en.edaily.co.kr/news/eda202608025023/"),
            src("연합인포맥스", "2026-09-07", "9~10월 만기 13.47조원",
                "https://en.infomaxai.com/news/articleView.html?idxno=138173"),
            src("이데일리", "2026-09-18", "AA- 3년물 연중 최고 4.750%",
                "https://en.edaily.co.kr/news/eda202609185678/"),
        ],
        "verdict_qual": "긴축 국면 전체로 보면 시장 중앙값은 32.5→37.3bp로 소폭 넓어졌고, 은행 (10.6→34.2bp)과 일반회사채 (46.1→50.2bp)는 넓어졌다. 중간에 7/16 당일 40.4bp로 튀고 9/15 당일 30.0bp로 좁아지는 등락이 있었다",
        "markers": [
            {"date": "2026-07-16", "label": "인상", "color": "#dc2626"},
            {"date": "2026-08-27", "label": "인상", "color": "#dc2626"},
            {"date": "2026-09-15", "label": "고점", "color": "#9333ea"},
        ],
    },
]

GROUPS = ("market", "ktb", "bank", "corp", "reit", "construct", "estate",
          "sll", "sbs", "cb")


def compute_series():
    sys.path.insert(0, DATA)
    import build_issuers as bi
    import pandas as pd

    parts = []
    for f in sorted(glob.glob(os.path.join(DATA, "result_today_*.xlsx.parquet"))):
        date = f.split("result_today_")[-1].split(".")[0]
        if not ("20260101" <= date <= "20261020"):
            continue
        try:
            r, _t = bi.process_file(f)
        except Exception:
            continue
        if r is not None and len(r):
            parts.append(r)
    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values(["issuer", "date"])
    df["spread_sm"] = (
        df.groupby("issuer")["spread_bp"]
        .transform(lambda s: s.rolling(bi.SMOOTH_WIN, min_periods=1).median())
    )
    df["grp"] = df["issuer"].map(lambda i: group_of(i, bi.industry_of))
    out = {}
    for date, g in df.groupby("date"):
        d = {"market": round(float(g["spread_sm"].median()), 1)}
        for b in GROUPS[1:]:
            sub = g[g["grp"] == b]["spread_sm"]
            d[b] = round(float(sub.median()), 1) if len(sub) else None
        out[date] = d
    return out


def fmt(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def median(vals):
    v = sorted([x for x in vals if x is not None])
    if not v:
        return None
    n = len(v)
    return round(v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2, 1)


def main():
    if os.path.exists(SERIES_PATH):
        series = json.load(open(SERIES_PATH))
        print("loaded cached series:", len(series), "days")
    else:
        series = compute_series()
        json.dump(series, open(SERIES_PATH, "w"))
        print("computed series:", len(series), "days")
    dates = sorted(series.keys())
    idx = {d: i for i, d in enumerate(dates)}

    def window_for(ev):
        if ev["window"] == "month":
            last = max(d for d in dates if d.startswith(ev["month"]))
            return dates[:idx[last] + 61]
        if ev["window"] == "around":
            c = idx[ev["center"]]
            return dates[max(0, c - 60):c + 61]
        c0 = idx[ev["start_center"]]
        c1 = idx[ev["end_center"]]
        return dates[max(0, c0 - 60):c1 + 61]

    out_events = []
    for ev in EVENTS:
        win = window_for(ev)
        s = {k: [series[d][k] for d in win] for k in GROUPS}
        markers = ev.get("markers")
        if markers is None:
            markers = [{"date": h, "label": "인상", "color": "#dc2626"}
                       for h in ("2026-07-16", "2026-08-27")
                       if h.replace("-", "") in win]
        if ev["window"] == "around":
            c = idx[ev["center"]]
            pre = median([series[d]["market"] for d in dates[max(0, c - 20):c]])
            post = median([series[d]["market"] for d in dates[c + 1:c + 21]])
            evt_val = series[ev["center"]]["market"]
            stats = (f"사건 전 20일 중앙값 {pre}bp → 사건 후 20일 {post}bp "
                     f"(사건일 {evt_val}bp)")
        elif ev["window"] == "month":
            mar_vals = [series[d]["market"] for d in win
                        if d.startswith(ev["month"])]
            stats = (f"3월 한 달 시장 중앙값 {mar_vals[0]}bp → "
                     f"{mar_vals[-1]}bp")
        else:
            f20 = median([series[d]["market"] for d in win[:20]])
            l20 = median([series[d]["market"] for d in win[-20:]])
            stats = (f"윈도우 앞 20일 중앙값 {f20}bp → 뒤 20일 {l20}bp "
                     f"(7/16 당일 {series['20260716']['market']}bp, "
                     f"9/15 당일 {series['20260915']['market']}bp)")
        # group pre/post (or first/last) diagnostics for verdict writing
        diag = {}
        if ev["window"] == "around":
            c = idx[ev["center"]]
            for k in ("ktb", "bank", "corp", "reit", "construct", "estate",
                      "sll", "sbs", "cb"):
                pre_days = dates[max(0, c - 20):c]
                post_days = dates[c + 1:c + 21]
                diag[k] = (median([series[d][k] for d in pre_days]),
                           median([series[d][k] for d in post_days]),
                           sum(1 for d in pre_days + post_days
                               if series[d][k] is None))
        print(f"{ev['id']}: win {win[0]}..{win[-1]} ({len(win)}d) "
              f"markers={[m['date'] for m in markers]}")
        print(f"  diag: {diag}")
        out = {
            "id": ev["id"], "title": ev["title"],
            "date_label": ev["date_label"], "topic": ev["topic"],
            "sources": ev["sources"], "verdict": ev["verdict_qual"],
            "stats": stats, "dates": [fmt(d) for d in win],
            "series": {k: s[k] for k in ("market", "ktb", "bank", "corp")},
            "markers": markers,
        }
        if "extra_keys" in ev:
            if ev.get("extra_full_year"):
                edates = dates
                eseries = {k: [series[d][k] for d in edates]
                           for k in ev["extra_keys"] + ["market"]}
            else:
                edates = win
                eseries = {k: s[k] for k in ev["extra_keys"] + ["market"]}
            out["extra"] = {
                "title": ev["extra_title"], "desc": ev["extra_desc"],
                "dates": [fmt(d) for d in edates],
                "series": eseries,
                "keys": ev["extra_keys"],
                "markers": ev.get("extra_markers", []),
            }
        if "note" in ev:
            out["note"] = ev["note"]
        out_events.append(out)
    tpl = open(os.path.join(MONTHLY_DIR, "template.html"), encoding="utf-8").read()
    payload = json.dumps({"events": out_events}, ensure_ascii=False)
    assert "/*EVENTS_JSON*/" in tpl
    html = tpl.replace("/*EVENTS_JSON*/", payload)
    assert "EVENTS_JSON" not in html
    with open(os.path.join(MONTHLY_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote index.html", len(html.encode("utf-8")), "bytes")


if __name__ == "__main__":
    main()
