"""Lead-lag analysis: agency rating changes vs bond spread moves.

Uses voting-right credit_changed.csv events and the same spread
methodology as build_issuers.process_file on raw KOFIA trade files.
Window: 2024-09-02 .. 2025-04-30 (pre-event history + event window).
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_issuers import process_file  # noqa: E402

DATA = os.path.dirname(os.path.abspath(__file__))
EVENTS_CSV = os.path.join(DATA, "voting-right", "credit_changed.csv")
OUT_JSON = os.path.join(DATA, "rating_events.json")

AGENCIES = [("kis_grd_nm_bf", "KIS_GRD_NM", "KIS"),
            ("kmcc_grd_nm_bf", "KMCC_GRD_NM", "KMCC"),
            ("nice_grd_nm_bf", "NICE_GRD_NM", "NICE")]

SCALE = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
         "BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "CC", "C", "D"]


def notch(rating):
    return SCALE.index(rating) if rating in SCALE else None


def load_events():
    df = pd.read_csv(EVENTS_CSV, dtype=str).fillna("")
    ev = []
    for _, r in df.iterrows():
        for bf_col, af_col, label in AGENCIES:
            bf, af = r[bf_col], r[af_col]
            if bf and af and bf != af:
                nb, na = notch(bf), notch(af)
                ev.append({
                    "date": r["TRD_DT"].replace("/", ""),
                    "name": r["name"], "agency": label,
                    "bf": bf, "af": af,
                    "direction": "down" if (nb is not None and na is not None
                                            and na > nb) else "up",
                    "notches": (na - nb) if (nb is not None and na is not None) else None,
                })
    return pd.DataFrame(ev).drop_duplicates().sort_values("date")


def main():
    events = load_events()
    print(f"{len(events)} change events, {events['name'].nunique()} companies")

    files = sorted(glob.glob(os.path.join(DATA, "result_today_*.xlsx.parquet")))
    files = [f for f in files if "20240901" <= os.path.basename(f)[13:21] <= "20250430"]
    print(f"{len(files)} trade files in window")
    parts = []
    for f in files:
        out = process_file(f)
        if out is not None:
            parts.append(out[0])
    daily = pd.concat(parts, ignore_index=True)
    print(f"issuer-days total: {len(daily)}, issuers: {daily['issuer'].nunique()}")

    results = []
    for name, grp in events.groupby("name"):
        # find parsed issuer candidates containing a distinctive fragment
        frag = name.replace("HD", "").strip()
        cands = [i for i in daily["issuer"].unique()
                 if frag and frag in i or i in name]
        # explicit aliases for HD names spelled out in bond tickers
        alias = {"HD현대": "에이치디현대", "HD현대중공업": "에이치디현대중공업"}
        if name in alias:
            cands = [alias[name]]
        sub = daily[daily["issuer"].isin(cands)].sort_values("date")
        rec = {"name": name, "parsed_issuers": cands,
               "n_days": int(sub["date"].nunique()), "events": []}
        if len(sub):
            s = sub.groupby("date")["spread_bp"].first().sort_index()
            sm = s.rolling(5, min_periods=1).median()
            for _, e in grp.iterrows():
                ed = e["date"]
                idx = sm.index[sm.index <= ed]
                row = {"date": ed, "agency": e["agency"], "bf": e["bf"],
                       "af": e["af"], "direction": e["direction"],
                       "notches": e["notches"]}
                if len(idx):
                    i = len(idx) - 1
                    row["spread_at"] = round(float(sm.iloc[i]), 1)
                    if i >= 20:
                        row["chg_pre20"] = round(float(sm.iloc[i] - sm.iloc[i - 20]), 1)
                    if i >= 60:
                        row["chg_pre60"] = round(float(sm.iloc[i] - sm.iloc[i - 60]), 1)
                    # z vs trailing 90 obs up to event
                    win = sm.iloc[max(0, i - 90):i + 1]
                    if len(win) >= 30 and win.std() > 0:
                        row["z_at"] = round(float((sm.iloc[i] - win.mean()) / win.std()), 2)
                rec["events"].append(row)
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False))

    with open(OUT_JSON, "w") as f:
        json.dump({"events": results,
                   "scale_note": "spread = 5d rolling median, same method as monitor"},
                  f, ensure_ascii=False, indent=1)
    print("wrote", OUT_JSON)


if __name__ == "__main__":
    main()
