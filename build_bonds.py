"""Per-bond latest stats for drill-down: for target issuers, each traded bond's
most recent yield/spread/amount. English only (user rule).
"""
import glob
import json
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_issuers import (
    parse_issuer, parse_tenor_years, to_num,
    TENOR_EDGES, TENOR_LABELS, DATA,
)

WINDOW_DAYS = 30
MAX_BONDS = 6

# corporate group mapping for contagion view (fallback: industry label)
GROUP_OF = {
    # Hyundai Motor Group
    "현대카드": "현대차그룹", "현대캐피탈": "현대차그룹", "현대커머셜": "현대차그룹",
    "현대건설": "현대차그룹", "현대글로비스": "현대차그룹", "현대엘리베이터": "현대차그룹",
    "현대백화점": "현대차그룹",
    # Shinhan
    "신한은행": "신한금융", "신한카드": "신한금융", "신한금융지주": "신한금융",
    "신한캐피탈": "신한금융",
    # KB
    "국민은행": "KB금융", "국민은행조건부": "KB금융", "케이비캐피탈": "KB금융",
    "케이비국민카드": "KB금융", "KB금융지주": "KB금융",
    # Hana
    "하나은행": "하나금융", "하나캐피탈": "하나금융", "하나카드": "하나금융",
    "하나금융지주": "하나금융",
    # Woori
    "우리은행": "우리금융", "우리금융캐피탈": "우리금융", "우리카드": "우리금융",
    "우리금융조건부": "우리금융", "우리금융에프앤아이": "우리금융",
    "우리희망제2차": "우리금융",
    # NongHyup
    "NH농협금융지주": "농협금융", "농업금융채권": "농협금융",
    "엔에이치농협캐피탈": "농협금융",
    # others
    "메리츠캐피탈": "메리츠금융",
    "롯데카드": "롯데", "롯데캐피탈": "롯데", "롯데지주": "롯데",
    "JB금융지주": "JB금융",
    "iM금융지주": "iM금융", "아이엠캐피탈": "iM금융",
    "BNK캐피탈": "BNK금융",
    "한국투자금융지주": "한국투자", "한국투자캐피탈": "한국투자",
    "한국투자증권": "한국투자",
    "키움캐피탈": "키움", "키움증권": "키움", "키움에프앤아이": "키움",
    "미래에셋캐피탈": "미래에셋", "미래에셋증권": "미래에셋",
    "SK에코플랜트": "SK", "SK이노베이션": "SK", "SK": "SK",
    "SK가스": "SK", "SK케미칼": "SK", "에스케이인천석유화학": "SK",
    "LG전자": "LG", "LG화학": "LG",
    "한화생명보험": "한화",
    "삼성증권": "삼성", "삼성카드": "삼성", "삼성중공업": "삼성",
    "코오롱인더스트리": "코오롱",
    "한솔제지": "한솔", "한솔케미칼": "한솔",
    "IPARK현대산업개발": "HDC",
    "E1": "LS",
    "대신에프앤아이": "대신",
    "유안타증권": "유안타",
    "흥국생명보험": "태광",
    "산은캐피탈": "산은", "산업금융채권": "산은",
    "아이비케이캐피탈": "IBK", "중소기업은행": "IBK",
}


def group_of(issuer, industry):
    return GROUP_OF.get(issuer, industry)


def main():
    with open(os.path.join(DATA, "issuers.json")) as f:
        iss = json.load(f)
    universe = set(iss["meta"]["universe"])
    alerts = {r["issuer"] for r in iss["latest_table"]
              if r.get("chg_5d") is not None and r["chg_5d"] >= 15}
    targets = universe | alerts
    print(f"target issuers: {len(targets)}", file=sys.stderr)

    files = sorted(glob.glob(os.path.join(DATA, "result_today_*.xlsx.parquet")))
    files = files[-WINDOW_DAYS:]
    ktb_med = {}   # (date, bucket) -> median KTB yield
    bond_rows = []  # (issuer, bond, date, yld, amt, bucket)
    for fp in files:
        m = re.search(r"result_today_(\d{8})\.xlsx\.parquet$", fp)
        if not m:
            continue
        date = m.group(1)
        df = pd.read_parquet(fp, columns=["종목명", "잔존기간", "수익률", "거래대금"])
        df["수익률"] = to_num(df["수익률"])
        df["거래대금"] = to_num(df["거래대금"]).fillna(0)
        df = df.dropna(subset=["수익률"])
        df = df[(df["수익률"] > 0) & (df["수익률"] < 30)]
        if len(df) == 0:
            continue
        df["tenor_y"] = df["잔존기간"].map(parse_tenor_years)
        df = df.dropna(subset=["tenor_y"])
        df["bucket"] = pd.cut(df["tenor_y"], bins=TENOR_EDGES, labels=TENOR_LABELS)
        df = df.dropna(subset=["bucket"])
        df["bucket"] = df["bucket"].astype(str)
        name = df["종목명"].astype(str).str.strip()
        kb = df[name.str.startswith("국고채권")].groupby("bucket")["수익률"].median()
        for b, y in kb.items():
            ktb_med[(date, b)] = float(y)
        sub = df[~name.str.startswith("국고채권")].copy()
        sub["issuer"] = name[~name.str.startswith("국고채권")].map(parse_issuer)
        sub = sub[sub["issuer"].isin(targets)]
        for (issuer, bond, bkt), g in sub.groupby(["issuer", "종목명", "bucket"]):
            amt = g["거래대금"].sum()
            yld = (g["수익률"] * g["거래대금"]).sum() / amt if amt else g["수익률"].mean()
            bond_rows.append((issuer, bond, date, round(float(yld), 3),
                              int(amt), bkt))
    # latest record per bond
    latest = {}
    for issuer, bond, date, yld, amt, bkt in bond_rows:
        key = (issuer, bond)
        if key not in latest or date > latest[key][2]:
            latest[key] = (issuer, bond, date, yld, amt, bkt)
    out = {}
    for (issuer, bond), (__, ___, date, yld, amt, bkt) in latest.items():
        k = ktb_med.get((date, bkt))
        spread = round((yld - k) * 100, 1) if k is not None else None
        out.setdefault(issuer, []).append({
            "bond": bond.strip(), "yld": yld,
            "spread": spread, "amt": amt,
        })
    for issuer in out:
        out[issuer].sort(key=lambda x: -x["amt"])
        out[issuer] = out[issuer][:MAX_BONDS]
    with open(os.path.join(DATA, "bonds.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False)
    nb = sum(len(v) for v in out.values())
    print(f"issuers: {len(out)} | bonds: {nb}")


if __name__ == "__main__":
    main()
