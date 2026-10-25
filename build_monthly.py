"""Monthly news + chart page data for the bond monitor.

For each month of 2026-01..2026-09, computes the daily market median spread
from the user's own trade data (same methodology as the monitor: per-issuer
5-trading-day rolling median, then the median across issuers each day),
and pairs it with a short news summary from the Jan-Sep 2026 news timeline.

Emits github_pages/monthly/monthly_data.js. The page itself lives in
github_pages/monthly/index.html (static, built by hand, not generated).
"""

import glob
import json
import os
import sys

DATA = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(DATA, "github_pages", "monthly")

# Short news bullets per month, from the Jan-Sep 2026 corporate bond news
# timeline. Background only; the chart is the user's own trade data.
NEWS = {
    "202601": ["해외 달러 발행 강세로 출발", "국내 연초 효과는 약화"],
    "202602": ["금리 인상 전 금융채 선제 발행 러시"],
    "202603": ["중동발 충격에 수익률 급등", "1분기 발행 전년 대비 24% 감소"],
    "202604": ["첫 상장리츠 부도 (JR글로벌리츠)", "발행은 금융채 중심으로 반등"],
    "202605": ["발행 다시 축소", "일반채 공급 얇아짐"],
    "202606": ["중앙그룹 위기, 계열사 회생 신청", "하위등급 발행 위축"],
    "202607": ["기준금리 2.75%로 첫 인상", "수출입은행 달러 스프레드 역대 최저"],
    "202608": ["기준금리 3.00%로 두 번째 인상", "8월 공모 발행 사실상 폐쇄, 대출·CP로 이동"],
    "202609": ["연중 최고 수익률", "9~10월 13.5조원 만기벽, 발행 연기"],
}


def main():
    sys.path.insert(0, DATA)
    import build_issuers as bi
    import pandas as pd

    parts = []
    for f in sorted(glob.glob(os.path.join(DATA, "result_today_*.xlsx.parquet"))):
        date = f.split("result_today_")[-1].split(".")[0]
        if not ("20260101" <= date <= "20260930"):
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
    months = {}
    for month, g in df.groupby(df["date"].str.slice(0, 6)):
        daily = g.groupby("date")["spread_sm"].median()
        counts = g.groupby("date")["issuer"].nunique()
        med = round(float(daily.median()), 1)
        months[month] = {
            "news": NEWS.get(month, []),
            "dates": [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in daily.index],
            "median": [round(float(v), 1) for v in daily.values],
            "n_issuers": [int(v) for v in counts.values],
            "month_median": med,
            "first": round(float(daily.iloc[0]), 1),
            "last": round(float(daily.iloc[-1]), 1),
        }
        print(month, "days:", len(daily), "median:", med)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "monthly_data.js"), "w") as f:
        f.write("window.MONTHLY_DATA = ")
        json.dump({"months": months}, f, ensure_ascii=False)
        f.write(";")
    print("wrote", os.path.join(OUT_DIR, "monthly_data.js"))


if __name__ == "__main__":
    main()
