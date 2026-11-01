"""Issuer-level credit spread monitor dataset.

For each trading day and issuer:
  - spread_bp: traded-amount-weighted average of (yield - KTB baseline)
    across tenor buckets (tenor-matched, so maturity mix doesn't distort)
  - vs_peer_bp: spread minus same-rating peer median spread
  - chg_5d / chg_20d: momentum of the smoothed spread
De-noised: min 3 trades/issuer-day, 5-day rolling median smoothing.

Universe: top 25 issuers by trailing-90-day traded amount (liquidity screen).
KOSPI mega-caps (Samsung etc.) barely trade bonds; the liquid universe is
banks, capitals and policy banks -- where Korean credit signal actually lives.

Outputs issuers.json
"""
import glob
import json
import os
import re

import numpy as np
import pandas as pd

DATA = os.path.dirname(os.path.abspath(__file__))

TENOR_EDGES = [0, 0.375, 0.75, 1.5, 2.5, 4.0, 7.5, 15, 25, 200]
TENOR_LABELS = ["3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "20Y", "30Y"]
MIN_TRADES = 3
SMOOTH_WIN = 5
UNIVERSE_N = 25


def parse_tenor_years(code) -> float:
    s = str(code).strip().zfill(6)
    if not re.fullmatch(r"\d{6}", s):
        return np.nan
    return int(s[0:2]) + int(s[2:4]) / 12 + int(s[4:6]) / 365


def parse_issuer(name: str) -> str:
    """Extract issuer from Korean bond names.

    '케이비캐피탈580-2' -> '케이비캐피탈', 'NH농협금융지주49-1' -> 'NH농협금융지주',
    '니드원제1차...' -> '니드원제1차', 'E1 ...' -> 'E1', 'JB금융지주...' -> 'JB금융지주'
    """
    s = str(name).strip()
    s = re.split(r"\s+조건부자본증권|\s+신종자본증권", s)[0]
    s = s.split("(")[0].strip()
    m = re.match(r"^((?:[가-힣]+|[A-Za-z]+)+)([0-9]+차)?([0-9]+)?", s)
    if not m:
        return ""
    base, cha, digits = m.group(1), m.group(2), m.group(3)
    if cha:
        return base + cha  # SPC naming: 니드원제1차
    if re.fullmatch(r"[A-Za-z]+", base) and digits:
        return base + digits  # E1
    return base


POLICY_FIN = {"산업금융채권", "농업금융채권", "수산금융채권", "중소기업은행", "한국수출입금융"}
SOVEREIGN_LIKE = {"통화안정증권", "통화안전증권", "통화안정증권DC", "국민주택", "재정증권",
                  "외국환평형기금채권", "국고채권", "국고채이자분리채권"}


def industry_of(issuer: str) -> str:
    """Coarse industry bucket from issuer name (for grouped viewing)."""
    if issuer in POLICY_FIN:
        return "정책금융"
    if issuer in SOVEREIGN_LIKE:
        return "국채/통안"
    if "지역개발채권" in issuer or issuer == "토지주택채권":
        return "특수채"
    if "지방채" in issuer:
        return "지방채"
    if "은행" in issuer or "뱅크" in issuer:
        return "은행"
    if "카드" in issuer:
        return "카드"
    if "캐피탈" in issuer or "커머셜" in issuer or "파이낸스" in issuer:
        return "캐피탈"
    if "지주" in issuer:
        return "금융지주"
    if "증권" in issuer and "공채" not in issuer:
        return "증권"
    if "보험" in issuer:
        return "보험"
    if any(k in issuer for k in ("공사", "공단", "전력", "주택", "토지", "철도", "발전", "가스", "원자력")):
        return "공기업"
    if re.search(r"제.*차$", issuer):
        return "SPC"
    return "일반기업"


def to_num(s):
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False), errors="coerce"
    )


DEDUP_EXTRA_COLS = ["날짜", "시간", "단가(원)", "거래량", "hash", "numbering"]
BASE_COLS = ["종목명", "잔존기간", "신용등급", "수익률", "거래대금"]


def dedup_trades(df):
    """Drop copy rows identified by the source trade hash.

    Full-corpus audit (2026-10-31, HASH-AUDIT.md): rows that share a
    hash are exact copies except for the numbering column, which is a
    copy counter, and no real hash collision exists in 4,476,232 rows.
    Rows without a hash fall back to a full signature over every
    column except numbering and hash, so distinct early rows are kept.
    Files with no hash column at all are returned unchanged.
    """
    if "hash" not in df.columns:
        return df
    h = df["hash"].astype(str).str.strip()
    has_hash = h.notna() & (h != "") & (h.str.lower() != "nan") & (h.str.lower() != "none")
    keep = pd.Series(True, index=df.index)
    hash_part = df[has_hash]
    dup = hash_part.duplicated(subset=["hash"], keep="first")
    keep.loc[dup[dup].index] = False
    null_part = df[~has_hash]
    if len(null_part):
        sig_cols = [c for c in df.columns if c not in ("numbering", "hash")]
        dup_sig = null_part.duplicated(subset=sig_cols, keep="first")
        keep.loc[dup_sig[dup_sig].index] = False
    return df[keep]


def process_file(path):
    m = re.search(r"result_today_(\d{8})\.xlsx\.parquet$", path)
    if not m:
        return None
    date = m.group(1)
    try:
        df = pd.read_parquet(path, columns=BASE_COLS + DEDUP_EXTRA_COLS)
        df = dedup_trades(df)
        df = df.drop(columns=[c for c in DEDUP_EXTRA_COLS if c in df.columns])
    except Exception:
        df = pd.read_parquet(path, columns=BASE_COLS)
    df["수익률"] = to_num(df["수익률"])
    df["거래대금"] = to_num(df["거래대금"]).fillna(0)
    df = df.dropna(subset=["수익률"])
    df = df[(df["수익률"] > 0) & (df["수익률"] < 30)]
    if len(df) == 0:
        return None
    df["tenor_y"] = df["잔존기간"].map(parse_tenor_years)
    df = df.dropna(subset=["tenor_y"])
    df["bucket"] = pd.cut(df["tenor_y"], bins=TENOR_EDGES, labels=TENOR_LABELS)
    df = df.dropna(subset=["bucket"])
    name = df["종목명"].astype(str).str.strip()
    df["issuer"] = name.map(parse_issuer)
    df["rating"] = df["신용등급"].astype(str).str.strip()
    df = df[df["issuer"] != ""]
    if len(df) == 0:
        return None

    ktb = df[name.str.startswith("국고채권")]
    base = ktb.groupby("bucket", observed=True)["수익률"].median()

    # per-trade spread vs tenor-matched KTB baseline
    df["base_y"] = df["bucket"].map(base).astype(float)
    df = df.dropna(subset=["base_y"])
    df["spread_bp"] = (df["수익률"] - df["base_y"]) * 100

    # per (issuer, bucket): median spread + traded amount
    g = df.groupby(["issuer", "bucket"], observed=True)
    ib = g.agg(
        med_spread=("spread_bp", "median"),
        amount=("거래대금", "sum"),
        n=("spread_bp", "size"),
        rating=("rating", lambda s: s.mode().iat[0] if len(s.mode()) else ""),
    ).reset_index()

    # issuer-day: amount-weighted avg across buckets (attribute-weighted)
    def wavg(sub):
        w = sub["amount"].clip(lower=0)
        if w.sum() <= 0:
            return pd.Series({"spread_bp": sub["med_spread"].mean()})
        return pd.Series({"spread_bp": float(np.average(sub["med_spread"], weights=w))})

    # short/long split (1Y cutoff): same weighting within each term
    SHORT_B = {"3M", "6M", "1Y"}
    def term_wavg(sub, buckets):
        t = sub[sub["bucket"].astype(str).isin(buckets)]
        if len(t) == 0 or t["n"].sum() < MIN_TRADES:
            return None
        w = t["amount"].clip(lower=0)
        if w.sum() <= 0:
            return float(t["med_spread"].mean())
        return float(np.average(t["med_spread"], weights=w))

    iss = (
        ib.groupby("issuer", observed=True)
        .apply(wavg, include_groups=False)
        .reset_index()
    )
    agg2 = (
        ib.groupby("issuer", observed=True)
        .agg(n=("n", "sum"), amount=("amount", "sum"), rating=("rating", "first"))
        .reset_index()
    )
    iss = iss.merge(agg2, on="issuer")
    iss = iss[iss["n"] >= MIN_TRADES]
    iss["date"] = date
    # term split per issuer-day
    ALL_B = set(TENOR_LABELS)
    term_rows = []
    for issuer, sub in ib.groupby("issuer", observed=True):
        s = term_wavg(sub, SHORT_B)
        lg = term_wavg(sub, ALL_B - SHORT_B)
        if s is not None or lg is not None:
            term_rows.append({"date": date, "issuer": issuer,
                              "short_bp": s, "long_bp": lg})
    term = pd.DataFrame(term_rows) if term_rows else None
    return iss[["date", "issuer", "rating", "spread_bp", "n", "amount"]], term


def main():
    files = sorted(glob.glob(os.path.join(DATA, "result_today_*.xlsx.parquet")))
    print(f"{len(files)} trade files")
    parts = []
    term_parts = []
    for i, f in enumerate(files):
        try:
            r, t = process_file(f)
        except Exception as e:  # noqa: BLE001 - keep going on bad files
            print(f"skip {os.path.basename(f)}: {e}")
            continue
        if r is not None and len(r):
            parts.append(r)
        if t is not None and len(t):
            term_parts.append(t)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(files)}")
    alld = pd.concat(parts, ignore_index=True)
    alld["date"] = alld["date"].astype(str)
    # KTB is the baseline (spread 0 by construction): never in universe/peers
    alld = alld[alld["issuer"] != "국고채권"]
    alld["industry"] = alld["issuer"].map(industry_of)
    alld = alld.sort_values(["issuer", "date"]).reset_index(drop=True)

    # universe: top 25 by trailing-90-day traded amount
    last_date = alld["date"].max()
    cutoff_90 = sorted(alld["date"].unique())[-90]
    recent = alld[alld["date"] >= cutoff_90]
    universe = (
        recent.groupby("issuer")["amount"].sum().nlargest(UNIVERSE_N).index.tolist()
    )
    print("universe:", universe)

    # smoothing per issuer (5-trading-day rolling median)
    alld["spread_sm"] = (
        alld.groupby("issuer")["spread_bp"]
        .transform(lambda s: s.rolling(SMOOTH_WIN, min_periods=1).median())
    )
    # momentum
    alld["chg_5d"] = alld.groupby("issuer")["spread_sm"].transform(
        lambda s: s - s.shift(5)
    )
    alld["chg_20d"] = alld.groupby("issuer")["spread_sm"].transform(
        lambda s: s - s.shift(20)
    )
    # peer-relative: same rating median spread that day
    peer = alld.groupby(["date", "rating"])["spread_sm"].median().rename("peer_sm")
    alld = alld.merge(peer, on=["date", "rating"], how="left")
    alld["vs_peer_bp"] = alld["spread_sm"] - alld["peer_sm"]
    # industry daily median (for chart overlay)
    ind_med = (
        alld.groupby(["date", "industry"])["spread_sm"]
        .median()
        .reset_index()
        .sort_values(["industry", "date"])
    )

    dates = sorted(alld["date"].unique().tolist())
    series = {}
    for iss, sub in alld[alld["issuer"].isin(universe)].groupby("issuer"):
        sub = sub.sort_values("date")
        series[iss] = {
            "rating": sub["rating"].iloc[-1],
            "industry": sub["industry"].iloc[-1],
            "dates": sub["date"].tolist(),
            "spread": [round(v, 1) for v in sub["spread_bp"]],
            "spread_sm": [round(v, 1) for v in sub["spread_sm"]],
            "vs_peer": [round(v, 1) for v in sub["vs_peer_bp"]],
            "chg_5d": [round(v, 1) if pd.notna(v) else None for v in sub["chg_5d"]],
            "n": [int(v) for v in sub["n"]],
        }
    industries = {}
    for ind, sub in ind_med.groupby("industry"):
        industries[ind] = {
            "dates": sub["date"].tolist(),
            "spread_sm": [round(v, 1) for v in sub["spread_sm"]],
        }
    # term-split series (short <=1Y, long >1Y) for universe, 20d-median-ready
    termd = pd.concat(term_parts, ignore_index=True) if term_parts else None
    series_term = {}
    if termd is not None:
        termd["date"] = termd["date"].astype(str)
        termd = termd[termd["issuer"].isin(universe)].sort_values(["issuer", "date"])
        for iss, sub in termd.groupby("issuer"):
            sub = sub.sort_values("date")
            series_term[iss] = {
                "dates": sub["date"].tolist(),
                "short": [round(v, 1) if pd.notna(v) else None for v in sub["short_bp"]],
                "long": [round(v, 1) if pd.notna(v) else None for v in sub["long_bp"]],
            }
    # latest-day table (all issuers passing filter, not just universe)
    # 90-day z-score vs own history: (latest - 90d mean) / 90d std
    zmap = {}
    for iss, sub in alld.groupby("issuer"):
        sm = sub.sort_values("date")["spread_sm"].dropna()
        if len(sm) >= 90:
            tail = sm.iloc[-90:]
            sd = tail.std()
            if sd > 1e-6:
                zmap[iss] = round(float((sm.iloc[-1] - tail.mean()) / sd), 2)
    latest = alld[alld["date"] == last_date].sort_values("spread_bp", ascending=False)
    table = [
        {
            "issuer": r.issuer,
            "rating": r.rating,
            "industry": r.industry,
            "spread": round(r.spread_sm, 1),
            "vs_peer": round(r.vs_peer_bp, 1),
            "chg_5d": round(r.chg_5d, 1) if pd.notna(r.chg_5d) else None,
            "chg_20d": round(r.chg_20d, 1) if pd.notna(r.chg_20d) else None,
            "z_90d": zmap.get(r.issuer),
            "n": int(r.n),
            "in_universe": r.issuer in universe,
        }
        for r in latest.itertuples()
    ]
    out = {
        "meta": {
            "last_date": last_date,
            "n_days": len(dates),
            "first_date": dates[0],
            "universe": universe,
        },
        "series": series,
        "series_term": series_term,
        "industries": industries,
        "latest_table": table,
    }
    with open(os.path.join(DATA, "issuers.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print("issuers:", len(series), "| table rows:", len(table), "| days:", len(dates))


if __name__ == "__main__":
    main()
