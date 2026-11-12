#!/usr/bin/env python3
"""Register a bond event from an article URL.

Server-side port of the events page link analysis (template.html
parseArticle, findIssuer, buildAnalyzed). Reads the committed analysis
cache (github_pages/monthly/daily_analysis_v2.json), so it runs anywhere
with no trade data: locally, or in GitHub Actions from an issue.

On success the built event payload is appended to registered_events.json
(build_events.py merges it into the page on the next build) and a JSON
line {"ok": true, "id", "title"} is printed. On rejection a JSON line
{"ok": false, "reason", "reason_ko", "reason_en"} is printed and the
exit code is 3. Fetch or setup failures exit 2.

Usage:
  register_event.py --url https://...
  register_event.py --issue-body "text containing the URL"
  register_event.py --url ... --dry-run
"""
import argparse
import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA = os.path.join(
    HERE, "github_pages", "monthly", "daily_analysis_v2.json")
DEFAULT_REGISTRY = os.path.join(HERE, "registered_events.json")

STR = {
    "ko": {
        "no_date": "기사에서 날짜를 찾지 못해 분석할 수 없습니다.",
        "offshore": "해외에서 발행한 채권이라 국내 체결 데이터에 흔적이 남지 않습니다. 이 모니터는 국내 회사채 체결만 다룹니다.",
        "not_corp": "회사채 사건으로 읽히지 않습니다. 기사에서 국내 회사채 발행자를 찾지 못했고 회사채 관련 표현도 없었습니다. 이 페이지는 회사채 사건만 다룹니다.",
        "out_range": "데이터 범위 밖의 기사입니다. 체결 데이터는 2024년 4월부터 있어 그 이전 기사는 읽을 수 없습니다.",
        "future_date": "기사 날짜가 오늘보다 뒤라 아직 사건으로 등록할 수 없습니다.",
        "duplicate": "이미 등록된 사건입니다. 같은 기사나 같은 날짜의 같은 발행자 사건이 이미 있습니다.",
        "note": "자동 분석 카드입니다. 기사를 읽어 날짜와 발행자를 추정했고, 판정은 사람이 쓴 문장이 아니라 전후 20일 중앙값 수치로 자동 생성했습니다.",
        "group_only": "기사에서 특정 발행자를 찾지 못해 시장 전체로 읽었습니다.",
        "narrowed": "좁아졌습니다", "widened": "넓어졌습니다",
        "flat": "거의 그대로였습니다",
        "auto": "자동 분석 결과입니다",
        "no_post": "사건 후 데이터가 아직 없어 전 20일 수치만 확정했습니다",
        "event_label": "사건",
        "stage_http": "연결 실패 (사이트 응답 오류)",
        "stage_empty": "본문 없음 (빈 응답)",
        "stage_blocked": "차단됨 (사이트가 읽기를 막음)",
        "stage_network": "네트워크 오류 또는 시간 초과",
    },
    "en": {
        "no_date": "No date could be found in the article, so it cannot be analyzed.",
        "offshore": "This bond was issued offshore, so it leaves no trace in domestic trade data. This monitor covers domestic corporate bond trades only.",
        "not_corp": "This does not read as a corporate bond event. No domestic corporate bond issuer was found in the article, and there was no corporate bond wording either. This page covers corporate bond events only.",
        "out_range": "This article is outside the data range. Trade data starts in April 2024, so earlier articles cannot be read.",
        "future_date": "The article date is in the future, so it cannot be registered as an event yet.",
        "duplicate": "This event is already registered. The same article, or the same issuer on the same date, already has an event.",
        "note": "This is an automatic analysis card. The date and issuer were extracted from the article, and the verdict is generated from 20-day median figures, not hand-written.",
        "group_only": "No specific issuer was found in the article, so this is read at the whole-market level.",
        "narrowed": "narrowed", "widened": "widened", "flat": "barely moved",
        "auto": "Automatic analysis",
        "no_post": "There is no post-event data yet, so only the 20 days before are final",
        "event_label": "Event",
        "stage_http": "request failed (site response error)",
        "stage_empty": "empty body (blank response)",
        "stage_blocked": "blocked (the site refused the reader)",
        "stage_network": "network error or timeout",
    },
}

OUTLETS = {
    "yna.co.kr": ["연합뉴스", "Yonhap News"],
    "en.yna.co.kr": ["연합뉴스", "Yonhap News"],
    "hyundaimotorgroup.com": ["현대자동차그룹", "Hyundai Motor Group"],
    "sedaily.com": ["서울경제", "Seoul Economic Daily"],
    "en.sedaily.com": ["서울경제", "Seoul Economic Daily"],
    "mk.co.kr": ["매일경제", "Maeil Business Newspaper"],
    "edaily.co.kr": ["이데일리", "Edaily"],
    "en.edaily.co.kr": ["이데일리", "Edaily"],
    "asiae.co.kr": ["아시아경제", "Asia Business Daily"],
    "infomaxai.com": ["연합인포맥스", "Yonhap Infomax"],
}

BOND_CTX = re.compile(r"(회사채|공모채|수요예측|채권|사채|발행|스프레드|민평|등급)")
OFFSHORE = re.compile(r"(달러채|해외\s*공모채|외화채|달러\s*표시|글로벌\s*공모채)")
BONDISH = re.compile(r"(회사채|공모채|채권\s*발행|사채|녹색채권|ESG\s*채권)")
BLOCK_MARKERS = ("Verifying you are human", "Just a moment",
                 "Attention Required", "Access denied", "captcha")


def js_num(v):
    """Format a number the way a JS template literal would print it."""
    if v is None:
        return "null"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return repr(v)


def ana_median(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    n = len(v)
    mid = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    return math.floor(mid * 10 + 0.5) / 10


def ana_fmt(d):
    return d[:4] + "-" + d[4:6] + "-" + d[6:8]


def ana_dir(pre, post, lang):
    s = STR[lang]
    if pre is None or post is None:
        return s["flat"]
    if post < pre - 0.5:
        return s["narrowed"]
    if post > pre + 0.5:
        return s["widened"]
    return s["flat"]


def parse_article(text, url):
    m = re.search(r"^Title:\s*(.+)$", text, re.M)
    title = m.group(1).strip() if m else ""
    if " | " in title:
        title = title.split(" | ")[0].strip()
    idx = text.find("Markdown Content:")
    body = text[idx + len("Markdown Content:"):] if idx >= 0 else text
    date_str = None
    pub = re.search(r"^Published Time:\s*(\d{4})-(\d{2})-(\d{2})", text, re.M)
    if pub:
        date_str = pub.group(1) + pub.group(2) + pub.group(3)
    if not date_str:
        um = re.search(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", url)
        if um:
            date_str = um.group(1) + um.group(2) + um.group(3)
    if not date_str:
        bm = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", body[:3000])
        if bm:
            date_str = (bm.group(1) + bm.group(2).zfill(2)
                        + bm.group(3).zfill(2))
    return {"title": title, "dateStr": date_str, "body": body}


def name_appears(name, text, is_body):
    if re.search(r"[A-Za-z]", name):
        esc = re.escape(name)
        return re.search(r"(?<![A-Za-z0-9])" + esc + r"(?![A-Za-z0-9])",
                         text) is not None
    if is_body and len(name) <= 2:
        i = text.find(name)
        while i >= 0:
            around = text[max(0, i - 60):i + len(name) + 60]
            if BOND_CTX.search(around):
                return True
            i = text.find(name, i + 1)
        return False
    return name in text


def find_issuer(ana, title, body):
    names = sorted(
        (nm for nm in ana["issuers"]
         if len(nm) >= 2 and not re.fullmatch(r"[A-Za-z]{1,3}\d+", nm)),
        key=len, reverse=True)
    hit = None
    for n in names:
        if name_appears(n, title, False):
            hit = n
            break
    head = body[:3000]
    for n in names:
        if not name_appears(n, head, True):
            continue
        if not hit:
            return n
        if len(n) > len(hit) and n.startswith(hit):
            return n
        break
    return hit


def extract_topics(body):
    flat = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", body)
    flat = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", flat)
    flat = re.sub(r"[#>*`]", " ", flat)
    flat = re.sub(r"\s+", " ", flat)
    sentences = re.split(r"(?<=[.。])\s+|(?<=다\.)\s+", flat)
    picks = []
    for s in sentences:
        t = s.strip()
        if (25 <= len(t) <= 160 and re.search(r"\d", t)
                and re.search(r"(발행|채권|금리|규모|조달|스프레드)", t)
                and not re.search(r"(메뉴|조회수|분량|뉴스 듣기|로그인|회원가입)", t)):
            picks.append(t)
            if len(picks) >= 2:
                break
    return picks


def outlet_for(url):
    m = re.match(r"https?://([^/]+)", url)
    host = m.group(1) if m else ""
    if host.startswith("www."):
        host = host[4:]
    return OUTLETS.get(host, [host, host])


def build_payload(ana, parsed, url, outlet, issuer_index):
    """Port of buildAnalyzed. Returns (payload, None) or (None, reason)."""
    dates = ana["dates"]
    d = parsed["dateStr"]
    head = parsed["title"] + "\n" + parsed["body"][:2000]
    if not d:
        return None, "no_date"
    if d < dates[0]:
        return None, "out_range"
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    if d > today:
        return None, "future_date"
    if OFFSHORE.search(head):
        return None, "offshore"
    issuer = find_issuer(ana, parsed["title"], parsed["body"])
    if not issuer and not BONDISH.search(head):
        return None, "not_corp"
    if d in dates:
        c = dates.index(d)
    else:
        c = 0
        for i, dd in enumerate(dates):
            if dd < d:
                c = i
    w0 = max(0, c - 60)
    w1 = min(len(dates), c + 61)
    win = dates[w0:w1]
    pos = {dd: i for i, dd in enumerate(dates)}
    pre_idx = dates[max(0, c - 20):c]
    post_idx = dates[c + 1:c + 21]

    def pick(arr, idxs):
        return [arr[pos[x]] for x in idxs]

    g = ana["groups"]
    m_pre = ana_median(pick(g["market"], pre_idx))
    m_post = ana_median(pick(g["market"], post_idx))
    m_day = g["market"][c]
    series = {"market": g["market"][w0:w1], "bank": g["bank"][w0:w1],
              "corp": g["corp"][w0:w1]}
    i_pre = i_post = None
    if issuer:
        s = ana["issuers"][issuer]["s"]
        series["issuer"] = s[w0:w1]
        i_pre = ana_median(pick(s, pre_idx))
        i_post = ana_median(pick(s, post_idx))
    markers = [{"date": ana_fmt(dates[c]), "label": STR["ko"]["event_label"],
                "label_en": "Event", "color": "#dc2626"}]
    # Mirrors the page exactly: the page checks the formatted needle
    # against raw YYYYMMDD window dates, so hike markers never appear
    # on analyzed cards today. Kept identical on purpose.
    for h in ("2026-07-16", "2026-08-27"):
        if h in win:
            markers.append({"date": h, "label": "인상", "label_en": "Hike",
                            "color": "#dc2626"})
    no_post = len(post_idx) == 0
    ko, en = STR["ko"], STR["en"]
    if no_post:
        stats = f"사건 전 20일 중앙값 {js_num(m_pre)}bp (사건일 {js_num(m_day)}bp)"
        stats_en = f"Median 20d before {js_num(m_pre)}bp (event day {js_num(m_day)}bp)"
    else:
        stats = (f"사건 전 20일 중앙값 {js_num(m_pre)}bp → 사건 후 20일 "
                 f"{js_num(m_post)}bp (사건일 {js_num(m_day)}bp)")
        stats_en = (f"Median 20d before {js_num(m_pre)}bp → 20d after "
                    f"{js_num(m_post)}bp (event day {js_num(m_day)}bp)")
    if issuer:
        if no_post:
            verdict = (f"{ko['auto']}. {issuer} 스프레드는 사건 전 20일 중앙값 "
                       f"{js_num(i_pre)}bp였습니다. {ko['no_post']}. "
                       f"시장 중앙값은 {js_num(m_pre)}bp였습니다.")
            verdict_en = (f"{en['auto']}. The {issuer} spread had a 20-day "
                          f"median of {js_num(i_pre)}bp before the event. "
                          f"{en['no_post']}. The market median was "
                          f"{js_num(m_pre)}bp.")
        else:
            verdict = (f"{ko['auto']}. {issuer} 스프레드는 사건 전 20일 중앙값 "
                       f"{js_num(i_pre)}bp에서 사건 후 20일 {js_num(i_post)}bp로 "
                       f"{ana_dir(i_pre, i_post, 'ko')}. 시장 중앙값은 "
                       f"{js_num(m_pre)}bp에서 {js_num(m_post)}bp로 "
                       f"{ana_dir(m_pre, m_post, 'ko')}.")
            verdict_en = (f"{en['auto']}. The {issuer} spread "
                          f"{ana_dir(i_pre, i_post, 'en')} from a 20-day median "
                          f"of {js_num(i_pre)}bp before to {js_num(i_post)}bp "
                          f"after. The market median "
                          f"{ana_dir(m_pre, m_post, 'en')}, {js_num(m_pre)}bp "
                          f"to {js_num(m_post)}bp.")
    else:
        if no_post:
            verdict = (f"{ko['auto']}. {ko['group_only']} 시장 중앙값은 사건 전 "
                       f"20일 {js_num(m_pre)}bp였습니다. {ko['no_post']}.")
            verdict_en = (f"{en['auto']}. {en['group_only']} The market median "
                          f"was {js_num(m_pre)}bp over the 20 days before. "
                          f"{en['no_post']}.")
        else:
            verdict = (f"{ko['auto']}. {ko['group_only']} 시장 중앙값은 사건 전 "
                       f"20일 {js_num(m_pre)}bp에서 사건 후 20일 "
                       f"{js_num(m_post)}bp로 {ana_dir(m_pre, m_post, 'ko')}.")
            verdict_en = (f"{en['auto']}. {en['group_only']} The market median "
                          f"{ana_dir(m_pre, m_post, 'en')}, {js_num(m_pre)}bp "
                          f"to {js_num(m_post)}bp.")
    topics = extract_topics(parsed["body"])
    title = parsed["title"]
    short_title = title[:46] + "…" if len(title) > 46 else title
    slug = str(issuer_index[issuer]) if issuer else "g"
    payload = {
        "id": f"reg-{d}-{slug}",
        "title": short_title, "title_en": short_title,
        "date_label": ana_fmt(d), "date_label_en": ana_fmt(d),
        "topic": topics, "topic_en": topics,
        "verdict": verdict, "verdict_en": verdict_en,
        "stats": stats, "stats_en": stats_en,
        "dates": [ana_fmt(x) for x in win], "series": series,
        "markers": markers,
        "issuer_name": issuer or "",
        "ana": {"date": d, "issuer": issuer} if issuer else None,
        "note": ko["note"], "note_en": en["note"],
        "sources": [{"outlet": outlet[0], "outlet_en": outlet[1],
                     "date": ana_fmt(d), "date_en": ana_fmt(d),
                     "topic": title or url, "topic_en": title or url,
                     "url": url}],
        "registered": True,
    }
    return payload, None


def fetch_article(url):
    req = urllib.request.Request(
        "https://r.jina.ai/" + url,
        headers={"User-Agent": "bond-event-register/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            text = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError:
        return None, "stage_http"
    except Exception:
        return None, "stage_network"
    if len(text) < 400:
        return None, "stage_empty"
    if any(m in text for m in BLOCK_MARKERS):
        return None, "stage_blocked"
    return text, None


def reject(reason):
    print(json.dumps({"ok": False, "reason": reason,
                      "reason_ko": STR["ko"][reason],
                      "reason_en": STR["en"][reason]}, ensure_ascii=False))
    return 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--issue-body")
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    url = args.url
    if not url and args.issue_body:
        m = re.search(r"https?://[^\s)\]]+", args.issue_body)
        url = m.group(0) if m else None
    if not url:
        print(json.dumps({"ok": False, "reason": "no_url"}))
        return 2
    if not os.path.exists(args.data):
        print(json.dumps({"ok": False, "reason": "no_data_file"}))
        return 2
    ana = json.load(open(args.data, encoding="utf-8"))
    issuer_index = {nm: i for i, nm in enumerate(ana["issuers"])}

    text, stage = fetch_article(url)
    if stage:
        return reject(stage)
    parsed = parse_article(text, url)
    payload, reason = build_payload(ana, parsed, url, outlet_for(url),
                                    issuer_index)
    if reason:
        return reject(reason)

    registry = []
    if os.path.exists(args.registry):
        registry = json.load(open(args.registry, encoding="utf-8"))
    for e in registry:
        srcs = e.get("sources") or []
        if any(s.get("url") == url for s in srcs):
            return reject("duplicate")
        if e.get("ana") == payload["ana"] and payload["ana"] is not None:
            return reject("duplicate")
        if (e.get("ana") is None and payload["ana"] is None
                and e.get("date_label") == payload["date_label"]):
            return reject("duplicate")
    base_id = payload["id"]
    n = 2
    ids = {e["id"] for e in registry}
    while payload["id"] in ids:
        payload["id"] = f"{base_id}-{n}"
        n += 1
    if not args.dry_run:
        registry.append(payload)
        with open(args.registry, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "id": payload["id"],
                      "title": payload["title"],
                      "issuer": payload["issuer_name"],
                      "date": payload["date_label"],
                      "dry_run": args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
