"""Event-based market-reaction page for the bond monitor.

Computes daily group-median spreads from the user's own trade data (same
methodology as the monitor: per-issuer 5-trading-day rolling median, then
the median across issuers each day), slices a window around each major 2026
event, and writes the public page to github_pages/index.html from the
template stored under github_pages/monthly/ with the data inlined (never
a separate data file: the 2026-10-25 cache-skew lesson). The monthly
directory is now only internal storage for the template and cached data;
there is no separate public monthly address.

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
    if ind == "정책금융":
        return "policy"
    if ind == "은행":
        return "bank"
    if ind == "일반기업":
        return "corp"
    return None


OUTLET_EN = {
    "서울경제": "Seoul Economic Daily",
    "한국은행": "Bank of Korea",
    "연합뉴스": "Yonhap News",
    "아시아경제": "Asia Business Daily",
    "연합인포맥스": "Yonhap Infomax",
    "매일경제": "Maeil Business Newspaper",
    "이데일리": "Edaily",
    "SBS": "SBS",
}

MARKER_LABEL_EN = {"인상": "Hike", "고점": "Peak", "사건": "Event"}

DATE_EN = {"2026-07-초": "Early Jul 2026"}


def src(outlet, date, topic, url, topic_en=None):
    return {"outlet": outlet, "outlet_en": OUTLET_EN.get(outlet, outlet),
            "date": date, "date_en": DATE_EN.get(date, date), "topic": topic,
            "topic_en": topic_en if topic_en is not None else topic,
            "url": url}


EVENTS = [
    {
        "id": "mar-shock",
        "title": "3월 중동 오일쇼크",
        "title_en": "March Middle East Oil Shock",
        "date_label": "2026년 3월",
        "date_label_en": "March 2026",
        "window": "month",
        "month": "202603",
        "topic": ["중동발 유가 충격에 국고 수익률 급등",
                  "1분기 일반채 발행 34.52조원, 전년 대비 24% 감소"],
        "topic_en": ["KTB yields spiked on the Middle East oil shock",
                     "Q1 regular bond issuance 34.52tn KRW, down 24% year on year"],
        "sources": [
            src("서울경제", "2026-03-30", "1분기 일반채 발행 24% 급감",
                "https://en.sedaily.com/news/2026/03/30/corporate-bond-issuance-plunges-24-percent-as-rates-spike",
                "Q1 regular bond issuance plunges 24%"),
            src("한국은행", "2026-04-08", "3월 금융시장 동향",
                "https://www.korea.net/Government/Briefing-Room/Press-Releases/view?articleId=8644&insttCode=A110427&type=O",
                "March financial market trends"),
            src("연합뉴스", "2026-04-29", "3월 채권 발행 19.54조원",
                "https://m.korean-vibe.com/news/newsview.php?ncode=179528853429716",
                "March bond issuance 19.54tn KRW"),
        ],
        "verdict_qual": "수익률은 뛰었는데 스프레드는 전 그룹이 좁아졌다 (은행 23.8→11.4bp, 일반회사채 53.0→33.3bp). 국고가 더 뛰었다",
        "verdict_en": "Yields jumped, but spreads narrowed in every group (banks 23.8→11.4bp, regular corporates 53.0→33.3bp). KTBs rose even more.",
        "intraday": {
            "date": "20260323",
            "date_reason": "3월 중 국고채권 중앙 수익률이 전날보다 가장 크게 뛴 날 (3.559%에서 3.716%로 15.9bp 상승)",
            "date_reason_en": "The day in March when the median KTB yield jumped most from the previous trading day (3.559% to 3.716%, +15.9bp)",
            "focus_groups": ["bank", "corp"],
            "focus_label": "회사채 (상업은행채, 일반회사채)",
            "focus_label_en": "Corporate bonds (commercial bank bonds, regular corporates)",
            "peer_groups": ["ktb"],
            "peer_label": "국고채권",
            "peer_label_en": "Korea Treasury Bonds",
        },
    },
    {
        "id": "jr-default",
        "title": "4/27 JR글로벌리츠 부도",
        "title_en": "Apr 27 JR Global REIT Default",
        "date_label": "2026년 4월 27일",
        "date_label_en": "April 27, 2026",
        "window": "around",
        "center": "20260427",
        "topic": ["JR글로벌리츠 400억 단기채 부도, 상장리츠 첫 회생 신청",
                  "등급 A-에서 D로 강등, 소액주주 약 2만 8천 명"],
        "topic_en": ["JR Global REIT defaulted on 40bn KRW of short-term bonds, the first listed REIT to file for rehabilitation",
                     "Rating cut from A- to D, about 28,000 retail shareholders"],
        "sources": [
            src("아시아경제", "2026-04-30", "JR글로벌리츠 부도, 첫 상장리츠 회생",
                "https://www.asiae.co.kr/en/article/2026043016182113283",
                "JR Global REIT default, first listed REIT rehabilitation"),
            src("연합뉴스", "2026-06-02", "4월 채권 발행 22.20조원",
                "https://en.yna.co.kr/view/AEN20260601007300320",
                "April bond issuance 22.20tn KRW"),
        ],
        "verdict_qual": "타리츠는 59.3→64.9bp로 소폭 넓어졌다. 건설업 중앙값 하락 (119.5→64.8bp)은 넓었던 종목들의 거래가 끊긴 구성 효과에 가깝다 (SK에코플랜트 120.9→101.2bp, 현대건설 33.9→25.6bp). 시장 전체 전이는 없었다",
        "verdict_en": "Other REITs widened slightly, 59.3→64.9bp. The construction median's drop (119.5→64.8bp) is mostly a composition effect: the widest names stopped trading (SK에코플랜트 120.9→101.2bp, 현대건설 33.9→25.6bp). There was no market-wide contagion.",
        "extra_title": "타리츠·건설업 스프레드 (bp)",
        "extra_title_en": "Other REITs and Construction Spreads (bp)",
        "extra_keys": ["reit", "construct"],
        "extra_desc": "타리츠는 JR 제외, 건설업은 건설기계·도로공사 제외. 점선은 시장 전체 중앙값이다.",
        "extra_desc_en": "Other REITs exclude JR; construction excludes construction machinery and road corporations. The dotted line is the whole-market median.",
        "note": "부동산업은 이 기간 거래된 민간 발행자가 롯데물산, 한국토지신탁 등 5곳에 그치고 하루 3건 이상 거래일이 거의 없어 별도 선을 그을 수 없었다.",
        "note_en": "Real estate could not get its own line: only five private issuers (롯데물산, 한국토지신탁 and others) traded in this window, with almost no days of 3+ trades.",
        "intraday": {
            "date": "20260427",
            "focus_issuers": ["제이알글로벌위탁관리부동산투자회사"],
            "focus_label": "JR글로벌리츠",
            "focus_label_en": "JR Global REIT",
            "peer_groups": ["reit", "construct"],
            "peer_label": "타리츠, 건설업",
            "peer_label_en": "Other REITs, construction",
        },
    },
    {
        "id": "joongang",
        "title": "6/12 중앙그룹 위기",
        "title_en": "Jun 12 JoongAng Group Crisis",
        "date_label": "2026년 6월 12일",
        "date_label_en": "June 12, 2026",
        "window": "around",
        "center": "20260612",
        "topic": ["JTBC 206억 부도, 중앙그룹 계열사 5곳 회생 신청",
                  "그룹 부채 약 2.75조원, 등급 D·CCC·B-로 강등"],
        "topic_en": ["JTBC defaulted on 20.6bn KRW, five JoongAng Group affiliates filed for rehabilitation",
                     "Group debt about 2.75tn KRW, ratings cut to D, CCC and B-"],
        "sources": [
            src("연합인포맥스", "2026-06-15", "중앙그룹 투기등급 강등",
                "https://en.infomaxai.com/news/articleView.html?idxno=125357",
                "JoongAng Group cut to speculative grade"),
            src("연합인포맥스", "2026-06-19", "중앙그룹 연쇄 부도·회생",
                "https://en.infomaxai.com/news/articleView.html?idxno=126185",
                "JoongAng Group serial defaults and rehabilitation filings"),
            src("매일경제", "2026-07-초", "상반기 순발행 2016년 이후 최저",
                "https://www.mk.co.kr/en/stock/12090707",
                "First-half net issuance lowest since 2016"),
        ],
        "verdict_qual": "은행만 조금 넓어졌고 (16.9→20.0bp) 일반회사채는 좁아졌다 (45.0→42.7bp). 시장 전체로 번지지 않았다. 언론계는 아래 차트처럼 중앙일보가 3~4월에 이미 340bp대에서 거래됐다",
        "verdict_en": "Only banks widened slightly (16.9→20.0bp); regular corporates narrowed (45.0→42.7bp). It did not spread to the whole market. In media, as the chart below shows, 중앙일보 was already trading in the 340bp range in March and April.",
        "extra_title": "언론계 스프레드 (2026년 전체, bp)",
        "extra_title_en": "Media Spreads (full-year 2026, bp)",
        "extra_keys": ["cb", "sbs"],
        "extra_desc": "중앙일보는 3~4월에 이미 320~366bp대에서 거래되며 위기 전부터 스트레스를 반영했고, 6월 전후로는 거래가 끊겼다. SBS는 거래일이 6일뿐이라 큰 파란 마름모로 표시했다. 점선은 시장 전체 중앙값이다.",
        "extra_desc_en": "중앙일보 already traded in the 320-366bp range in March and April, pricing stress well before the crisis, and stopped trading around June. SBS traded on only six days, so it is shown as large blue diamonds. The dotted line is the whole-market median.",
        "extra_full_year": True,
        "extra_markers": [{"date": "2026-06-12", "label": "사건", "color": "#dc2626"}],
        "intraday": {
            "date": "20260612",
            "focus_issuers": ["에스엘엘중앙", "중앙일보"],
            "focus_label": "중앙그룹 (에스엘엘중앙, 중앙일보)",
            "focus_label_en": "JoongAng Group (SLL JoongAng, JoongAng Ilbo)",
            "peer_groups": ["sbs"],
            "peer_label": "SBS (언론 피어)",
            "peer_label_en": "SBS (media peer)",
        },
    },
    {
        "id": "summer",
        "title": "7/16 인상 ~ 9/15 고점",
        "title_en": "Jul 16 Hike to Sep 15 Peak",
        "date_label": "2026년 7월 16일 ~ 9월 15일",
        "date_label_en": "July 16 - September 15, 2026",
        "window": "range",
        "start_center": "20260716",
        "end_center": "20260915",
        "topic": ["기준금리 2.50%→2.75% 첫 인상 (7/16), 3.00% 두 번째 인상 (8/27)",
                  "AA- 3년물 4.750% 연중 최고 (9/15), 9~10월 만기 13.47조원"],
        "topic_en": ["First hike 2.50% to 2.75% (Jul 16), second hike to 3.00% (Aug 27)",
                     "AA- 3Y at 4.750%, a year high (Sep 15); 13.47tn KRW maturing in Sep-Oct"],
        "sources": [
            src("한국은행", "2026-07-16", "기준금리 2.75% 첫 인상",
                "https://www.bok.or.kr/eng/bbs/E0000634/view.do?nttId=11062944&searchCnd=1&searchKwd&depth2=400417&depth3=400423&depth=400423&pageUnit=10&pageIndex=1&programType=newsDataEng&menuNo=400423&oldMenuNo=400423",
                "First hike to 2.75%"),
            src("SBS", "2026-08", "기준금리 3.00% 두 번째 인상",
                "https://news.sbs.co.kr/english/article.do?news_id=N1008725743",
                "Second hike to 3.00%"),
            src("이데일리", "2026-08-02", "7월 스프레드 67.5bp에서 72.0bp로 확대",
                "https://en.edaily.co.kr/news/eda202608025023/",
                "July spreads widen from 67.5bp to 72.0bp"),
            src("연합인포맥스", "2026-09-07", "9~10월 만기 13.47조원",
                "https://en.infomaxai.com/news/articleView.html?idxno=138173",
                "13.47tn KRW maturing in Sep-Oct"),
            src("이데일리", "2026-09-18", "AA- 3년물 연중 최고 4.750%",
                "https://en.edaily.co.kr/news/eda202609185678/",
                "AA- 3Y at a year-high 4.750%"),
        ],
        "verdict_qual": "긴축 국면 전체로 보면 시장 중앙값은 32.5→37.3bp로 소폭 넓어졌고, 은행 (10.6→34.2bp)과 일반회사채 (46.1→50.2bp)는 넓어졌다. 중간에 7/16 당일 40.4bp로 튀고 9/15 당일 30.0bp로 좁아지는 등락이 있었다",
        "verdict_en": "Across the tightening phase, the market median widened slightly, 32.5→37.3bp, with banks (10.6→34.2bp) and regular corporates (46.1→50.2bp) wider. In between, it spiked to 40.4bp on Jul 16 itself and narrowed to 30.0bp on Sep 15.",
        "markers": [
            {"date": "2026-07-16", "label": "인상", "color": "#dc2626"},
            {"date": "2026-08-27", "label": "인상", "color": "#dc2626"},
            {"date": "2026-09-15", "label": "고점", "color": "#9333ea"},
        ],
        "intraday": {
            "date": "20260716",
            "date_reason": "첫 번째 기준금리 인상일",
            "date_reason_en": "The first policy rate hike day",
            "focus_groups": ["bank", "corp"],
            "focus_label": "회사채 (상업은행채, 일반회사채)",
            "focus_label_en": "Corporate bonds (commercial bank bonds, regular corporates)",
            "peer_groups": ["ktb"],
            "peer_label": "국고채권",
            "peer_label_en": "Korea Treasury Bonds",
        },
    },
    {
        "id": "kofr-loans",
        "title": "10/26 KOFR 기반 기업대출 출시",
        "title_en": "Oct 26 KOFR-Based Corporate Loans Launch",
        "date_label": "2026년 10월 26일 (사전 베이스라인)",
        "date_label_en": "October 26, 2026 (pre-event baseline)",
        "window": "pre",
        "topic": ["산업은행과 기업은행이 KOFR 기반 기업대출을 시작, 각 5천억원씩 합계 1조원",
                  "기준금리는 30일 평균 KOFR, 만기 최대 1년, 지방 중소기업 우대금리 적용",
                  "가계대출 적용은 아직 논의 중이라 후속 관찰 항목이다"],
        "topic_en": ["KDB and IBK start KOFR-based corporate loans, 500bn KRW each, 1tn KRW in total",
                     "Benchmark is the 30-day average KOFR, maturities up to 1 year, preferential rates for regional SMEs",
                     "Household loan adoption is still under discussion, a follow-up watch item"],
        "sources": [
            src("서울경제", "2026-10-25", "Korea Launches First KOFR-Based Corporate Loans, Household Rollout Pending",
                "https://en.sedaily.com/finance/2026/10/25/korea-launches-first-kofr-based-corporate-loans-household",
                "Korea Launches First KOFR-Based Corporate Loans, Household Rollout Pending"),
        ],
        "verdict_qual": "사전 카드다. 거래 데이터가 2026-10-20에서 멈춰 있어 사건일(10-26) 이후 구간은 아직 없다. 사건 후 판정은 데이터 복구 뒤 20거래일이 지난 뒤 확정한다",
        "verdict_en": "This is a pre-event card. Trade data stops at 2026-10-20, so the post-event window (after Oct 26) does not exist yet. The post-event verdict will be finalized 20 trading days after the data feed recovers.",
        "markers": [],
        "chart_title": "차트: 사건 전 60거래일, 동일 잔존기간 국고채를 기준으로 한 상업은행채와 일반회사채 스프레드 (bp)",
        "chart_title_en": "Chart: Commercial bank and regular corporate spreads versus maturity-matched KTBs, 60 trading days before the event (bp)",
        "chart_desc": "스프레드는 각 채권의 수익률에서 같은 날짜와 같은 잔존기간 구간에 속한 국고채 수익률 중앙값을 뺀 값이다. 검은 가로선은 국고채 기준인 0bp다. 점선은 시장 전체 중앙값이다. 선이 끊긴 구간은 해당 그룹 거래가 없어 중앙값을 못 구한 날이다. 사건일 이후 구간은 데이터 복구되는 대로 붙는다.",
        "chart_desc_en": "Each spread is a bond yield minus the median KTB yield in the same date and remaining-maturity bucket. The black horizontal line is the KTB benchmark at 0 bp. The dotted line is the whole-market median. Gaps are days when a group had no trades to compute a median. The post-event window will be attached once the data feed recovers.",
        "extra_title": "정책금융채 스프레드 (bp)",
        "extra_title_en": "Policy Bank Bond Spreads (bp)",
        "extra_keys": ["policy"],
        "extra_desc": "정책금융채는 산업금융채권(산업은행), 중소기업은행(기업은행) 등 정책금융 발행자 기준이다. 대출 주체가 정책금융기관이라 별도 차트로 분리했다. 점선은 시장 전체 중앙값이다.",
        "extra_desc_en": "Policy bank bonds are grouped by policy-finance issuers such as 산업은행 (KDB bonds) and 중소기업은행 (IBK). They are charted separately because the lenders here are policy institutions. The dotted line is the whole-market median.",
        "note": "이 카드는 사건 전 60거래일(2026-07-22~2026-10-20) 사전 베이스라인이다. 사건 후 60거래일 차트와 전후 20일 중앙값 판정 수치는 데이터 복구 후 업데이트한다.",
        "note_en": "This card is a pre-event baseline over the 60 trading days before the event (2026-07-22 to 2026-10-20). The post-event 60-day chart and the 20-day pre/post median verdict figures will be updated after the data feed recovers.",
        "intraday": {
            "date": "20261026",
            "focus_issuers": ["산업금융채권", "중소기업은행"],
            "focus_label": "정책금융 (산업은행, 기업은행)",
            "focus_label_en": "Policy finance (KDB, IBK bonds)",
            "peer_groups": ["bank"],
            "peer_label": "상업은행채",
            "peer_label_en": "Commercial bank bonds",
        },
    },
]

GROUPS = ("market", "ktb", "bank", "corp", "reit", "construct", "estate",
          "sll", "sbs", "cb", "policy")


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


def intraday_payload(cfg, industry_fn):
    """Event-day intraday flow for the event page: the focus issuer(s) or
    group, plus peer companies (same industry group), from print-level
    trades cleaned exactly like the intraday page (build_intraday.load_day).

    Cumulative amounts use 10-minute bins (overview page, not the
    print-level intraday page). A focus with zero trades on the event day
    is a result, not a failure: the payload says so and the peer series
    still renders, so the contrast with a normally trading market is
    visible.
    """
    import build_intraday as bid

    out = {
        "date": fmt(cfg["date"]),
        "focus_label": cfg["focus_label"],
        "focus_label_en": cfg.get("focus_label_en", cfg["focus_label"]),
        "peer_label": cfg["peer_label"],
        "peer_label_en": cfg.get("peer_label_en", cfg["peer_label"]),
        "status": "ok",
    }
    if cfg.get("date_reason"):
        out["date_reason"] = cfg["date_reason"]
        out["date_reason_en"] = cfg.get("date_reason_en", cfg["date_reason"])
    df = bid.load_day(cfg["date"])
    if df is None:
        out["status"] = "no_data"
        return out
    df = df.copy()
    df["grp"] = df["issuer"].map(lambda i: group_of(i, industry_fn))
    focus_mask = df["issuer"].isin(cfg.get("focus_issuers", []))
    if cfg.get("focus_groups"):
        focus_mask = focus_mask | df["grp"].isin(cfg["focus_groups"])
    peer_mask = df["issuer"].isin(cfg.get("peer_issuers", []))
    if cfg.get("peer_groups"):
        peer_mask = peer_mask | df["grp"].isin(cfg["peer_groups"])
    peer_mask = peer_mask & ~focus_mask
    focus = df[focus_mask]
    peer = df[peer_mask]

    def bin_cum(sub):
        if not len(sub):
            return []
        bins = (sub["t_min"] // 10 * 10).astype(int)
        per_bin = sub.groupby(bins)["amt"].sum().sort_index()
        pts, run = [], 0.0
        for b, amt in per_bin.items():
            run += float(amt)
            pts.append([int(b), round(run / 10000.0, 2)])
        return pts

    hours = sorted(set(int(v // 60) for v in focus["t_min"])
                   | set(int(v // 60) for v in peer["t_min"]))

    def hourly(sub):
        vals = []
        for h in hours:
            g = sub[(sub["t_min"] >= h * 60) & (sub["t_min"] < (h + 1) * 60)]
            vals.append(round(float(g["amt"].sum()) / 10000.0, 2))
        return vals

    scatter = None
    if cfg.get("focus_issuers") and 0 < len(focus) <= 400:
        scatter = {
            "t": [round(float(v), 2) for v in focus["t_min"]],
            "y": [round(float(v), 3) for v in focus["yld"]],
            "s": [bid.marker_size(float(v)) for v in focus["amt"]],
            "amt": [round(float(v) / 10000.0, 2) for v in focus["amt"]],
            "text": [f"{b} {ts}" for b, ts in zip(focus["bond"], focus["time_str"])],
        }
    top_peers = [
        {"name": str(name), "n": int(n)}
        for name, n in peer["issuer"].value_counts().head(3).items()
    ]
    out.update({
        "focus_n": int(len(focus)),
        "focus_amt": round(float(focus["amt"].sum()) / 10000.0, 1),
        "peer_n": int(len(peer)),
        "peer_amt": round(float(peer["amt"].sum()) / 10000.0, 1),
        "market_n": int(len(df)),
        "top_peers": top_peers,
        "cum_focus": bin_cum(focus),
        "cum_peer": bin_cum(peer),
        "hourly": {"h": hours, "focus": hourly(focus), "peer": hourly(peer)},
        "scatter": scatter,
    })
    if not len(focus):
        out["status"] = "no_focus_trades"
    return out


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
        if ev["window"] == "pre":
            return dates[-60:]
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
        markers = [dict(m, label_en=MARKER_LABEL_EN.get(m["label"], m["label"]))
                   for m in markers]
        if ev["window"] == "around":
            c = idx[ev["center"]]
            pre = median([series[d]["market"] for d in dates[max(0, c - 20):c]])
            post = median([series[d]["market"] for d in dates[c + 1:c + 21]])
            evt_val = series[ev["center"]]["market"]
            stats = (f"사건 전 20일 중앙값 {pre}bp → 사건 후 20일 {post}bp "
                     f"(사건일 {evt_val}bp)")
            stats_en = (f"Median 20d before {pre}bp → 20d after {post}bp "
                        f"(event day {evt_val}bp)")
        elif ev["window"] == "month":
            mar_vals = [series[d]["market"] for d in win
                        if d.startswith(ev["month"])]
            stats = (f"3월 한 달 시장 중앙값 {mar_vals[0]}bp → "
                     f"{mar_vals[-1]}bp")
            stats_en = (f"Market median through March {mar_vals[0]}bp → "
                        f"{mar_vals[-1]}bp")
        elif ev["window"] == "pre":
            pre = median([series[d]["market"] for d in dates[-20:]])
            stats = (f"사건 전 20일 시장 중앙값 {pre}bp "
                     f"(데이터 마지막 거래일 {fmt(dates[-1])}, "
                     f"사건 후 구간은 데이터 복구 후 추가)")
            stats_en = (f"Market median, 20d before the event {pre}bp "
                        f"(last data trading day {fmt(dates[-1])}; "
                        f"the post-event window is added after the feed recovers)")
        else:
            f20 = median([series[d]["market"] for d in win[:20]])
            l20 = median([series[d]["market"] for d in win[-20:]])
            stats = (f"윈도우 앞 20일 중앙값 {f20}bp → 뒤 20일 {l20}bp "
                     f"(7/16 당일 {series['20260716']['market']}bp, "
                     f"9/15 당일 {series['20260915']['market']}bp)")
            stats_en = (f"Median, first 20d of window {f20}bp → last 20d {l20}bp "
                        f"(Jul 16 itself {series['20260716']['market']}bp, "
                        f"Sep 15 itself {series['20260915']['market']}bp)")
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
            "title_en": ev.get("title_en", ev["title"]),
            "date_label": ev["date_label"],
            "date_label_en": ev.get("date_label_en", ev["date_label"]),
            "topic": ev["topic"],
            "topic_en": ev.get("topic_en", ev["topic"]),
            "sources": ev["sources"], "verdict": ev["verdict_qual"],
            "verdict_en": ev.get("verdict_en", ev["verdict_qual"]),
            "stats": stats, "stats_en": stats_en,
            "dates": [fmt(d) for d in win],
            "series": {k: s[k] for k in ("market", "ktb", "bank", "corp")},
            "markers": markers,
        }
        if ev.get("chart_title"):
            out["chart_title"] = ev["chart_title"]
            out["chart_title_en"] = ev.get("chart_title_en", ev["chart_title"])
        if ev.get("chart_desc"):
            out["chart_desc"] = ev["chart_desc"]
            out["chart_desc_en"] = ev.get("chart_desc_en", ev["chart_desc"])
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
                "title_en": ev.get("extra_title_en", ev["extra_title"]),
                "desc_en": ev.get("extra_desc_en", ev["extra_desc"]),
                "dates": [fmt(d) for d in edates],
                "series": eseries,
                "keys": ev["extra_keys"],
                "markers": [dict(m, label_en=MARKER_LABEL_EN.get(
                    m["label"], m["label"]))
                    for m in ev.get("extra_markers", [])],
            }
        if "note" in ev:
            out["note"] = ev["note"]
            out["note_en"] = ev.get("note_en", ev["note"])
        if "intraday" in ev:
            sys.path.insert(0, DATA)
            import build_issuers as bi
            intra = intraday_payload(ev["intraday"], bi.industry_of)
            out["intraday"] = intra
            print(f"  intraday {intra['date']}: status={intra['status']} "
                  f"focus={intra.get('focus_n')} peer={intra.get('peer_n')} "
                  f"market={intra.get('market_n')}")
        out_events.append(out)
    tpl = open(os.path.join(MONTHLY_DIR, "template.html"), encoding="utf-8").read()
    payload = json.dumps({"events": out_events}, ensure_ascii=False)
    assert "/*EVENTS_JSON*/" in tpl
    html = tpl.replace("/*EVENTS_JSON*/", payload)
    assert "EVENTS_JSON" not in html
    nav = open(os.path.join(DATA, "github_pages", "nav_fragment.html"), encoding="utf-8").read()
    assert "<!--NAV-->" in html
    html = html.replace("<!--NAV-->", nav)
    # The events page is the site main page. It is served only from the
    # root index, with no event pre-selected on load.
    root_path = os.path.join(DATA, "github_pages", "index.html")
    with open(root_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote root index.html", len(html.encode("utf-8")), "bytes")


if __name__ == "__main__":
    main()
