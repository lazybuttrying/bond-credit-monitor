"""Build dashboard dataset from bond trade parquets.

Outputs dashboard_data.json with:
  - curve: daily median yield by tenor bucket for KTB (gukgochaegwon) trades
  - spreads: daily credit spread (bp) by rating x tenor bucket vs KTB baseline
  - meta: coverage info

Tenor parsing: trade 잔존기간 is YYMMDD-packed (e.g. '100000' -> 10y0m0d).
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


def parse_tenor_years(code) -> float:
    s = str(code).strip().zfill(6)
    if not re.fullmatch(r"\d{6}", s):
        return np.nan
    y, m, d = int(s[0:2]), int(s[2:4]), int(s[4:6])
    return y + m / 12 + d / 365


def tenor_bucket(years: pd.Series) -> pd.Series:
    return pd.cut(years, bins=TENOR_EDGES, labels=TENOR_LABELS)


def process_file(path):
    m = re.search(r"result_today_(\d{8})\.xlsx\.parquet$", path)
    if not m:
        return None, None
    date = m.group(1)
    df = pd.read_parquet(path, columns=["종목명", "잔존기간", "신용등급", "수익률"])
    df["수익률"] = pd.to_numeric(df["수익률"], errors="coerce")
    df = df.dropna(subset=["수익률"])
    df = df[(df["수익률"] > 0) & (df["수익률"] < 30)]
    if len(df) == 0:
        return None, None
    df["tenor_y"] = df["잔존기간"].map(parse_tenor_years)
    df = df.dropna(subset=["tenor_y"])
    df["bucket"] = tenor_bucket(df["tenor_y"])
    df = df.dropna(subset=["bucket"])
    name = df["종목명"].astype(str).str.strip()

    # KTB baseline curve
    ktb = df[name.str.startswith("국고채권")]
    curve = (
        ktb.groupby("bucket", observed=True)["수익률"]
        .agg(med="median", n="size")
        .reset_index()
    )
    curve["date"] = date

    # rating spreads vs KTB same-bucket median
    base = ktb.groupby("bucket", observed=True)["수익률"].median()
    rated = df[(df["신용등급"].astype(str).str.strip() != "")]
    g = rated.groupby(["bucket", "신용등급"], observed=True)["수익률"].agg(med="median", n="size")
    spreads = g.reset_index()
    # map over a categorical index returns categorical -> cast to float
    spreads["base"] = spreads["bucket"].map(base).astype(float)
    spreads = spreads.dropna(subset=["base"])
    spreads["spread_bp"] = (spreads["med"] - spreads["base"]) * 100
    spreads["date"] = date
    # de-noise: drop thin buckets (daily OTC medians on few trades are noise)
    spreads = spreads[spreads["n"] >= 5]
    return curve, spreads[["date", "bucket", "신용등급", "spread_bp", "n", "med"]]


def main():
    files = sorted(glob.glob(os.path.join(DATA, "result_today_*.xlsx.parquet")))
    print(f"{len(files)} trade files")
    curves, spreads = [], []
    for i, f in enumerate(files):
        try:
            c, s = process_file(f)
        except Exception as e:  # noqa: BLE001 - keep going on bad files
            print(f"skip {os.path.basename(f)}: {e}")
            continue
        if c is not None and len(c):
            curves.append(c)
        if s is not None and len(s):
            spreads.append(s)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(files)}")
    curve = pd.concat(curves, ignore_index=True)
    spread = pd.concat(spreads, ignore_index=True)
    curve["bucket"] = curve["bucket"].astype(str)
    spread["bucket"] = spread["bucket"].astype(str)
    spread = spread.rename(columns={"신용등급": "rating", "med": "yld", "n": "n"})
    out = {
        "curve": curve.rename(columns={"med": "yld"}).to_dict("records"),
        "spreads": spread.to_dict("records"),
        "meta": {
            "dates": sorted(curve["date"].unique().tolist()),
            "ratings": sorted(spread["rating"].unique().tolist()),
            "tenors": TENOR_LABELS,
            "n_trade_days": int(curve["date"].nunique()),
        },
    }
    with open(os.path.join(DATA, "dashboard_data.json"), "w") as f:
        json.dump(out, f)
    print("curve rows:", len(curve), "| spread rows:", len(spread))
    print("dates:", out["meta"]["dates"][0], "->", out["meta"]["dates"][-1])
    print("ratings:", out["meta"]["ratings"])


if __name__ == "__main__":
    main()
