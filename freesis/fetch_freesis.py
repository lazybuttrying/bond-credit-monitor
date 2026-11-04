"""FreeSIS (KOFIA capital-market statistics portal) bond statistics collector.

Source: https://freesis.kofia.or.kr/meta/getMetaDataList.do
Verified 2026-11-04: the endpoint is public, no session cookie or API key
is required. Table metadata (headers, search variables, units) comes from
the companion endpoint /meta/getSrvData.do.

Design notes (all verified by direct calls):
- OBJ_NM is "<service_id>BO" for every bond service.
- dmSearch variables: tmpV1 = period type ("D" daily, "M" monthly,
  "Y" yearly), tmpV45 = start date (YYYYMMDD), tmpV46 = end date.
  Time-series tables return nothing when tmpV46 is empty, snapshot
  tables (final yields, issuance, lending) take a single date in tmpV45.
- tmpV40 is the display unit divisor. Keep "1000000" (million KRW):
  with "1" the server masks large values with "######".
- Amounts below are million KRW unless a column says otherwise.
- Publication lag is one business day for trading and issuance tables.

Output: one parquet per table under data/, deduplicated on its key
columns, plus the raw JSON of every call under raw/ for audit.
English only in code; Korean appears only as source data labels.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import date, timedelta

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
RAW_DIR = os.path.join(BASE, "raw")
ENDPOINT = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
UNIT_DIVISOR = "1000000"  # million KRW; "1" makes the server mask values

# bond-type columns shared by the trading / maturity tables, in field order
TYPE_FIELDS = ["TMPV3", "TMPV4", "TMPV5", "TMPV6", "TMPV7",
               "TMPV8", "TMPV9", "TMPV10", "TMPV11"]
TYPE_NAMES = ["ktb", "local_gov", "special", "msb", "bank",
              "other_financial", "corporate", "abs", "total"]

METRIC_BY_LABEL = {"Volume": "volume", "Value": "value", "Contract": "count",
                   "거래량": "volume", "거래대금": "value", "거래건": "count"}

BOND_TYPE_EN = {
    "국채": "ktb", "지방채": "local_gov", "특수채": "special",
    "통안증권": "msb", "은행채": "bank", "기타금융채": "other_financial",
    "회사채": "corporate", "ABS": "abs", "계": "total", "전체": "total",
}
TRADE_TYPE_EN = {
    "총거래": "total", "매도": "sell", "매수": "buy", "순매수": "net_buy",
}
INVESTOR_FIELDS = ["TMPV3", "TMPV4", "TMPV5", "TMPV6", "TMPV7", "TMPV8",
                   "TMPV9", "TMPV10", "TMPV11", "TMPV12", "TMPV13", "TMPV14"]
INVESTOR_NAMES = ["total", "dealer_interbank", "bank", "asset_mgmt_public",
                  "asset_mgmt_private", "insurance", "merchant_bank",
                  "pension_fund", "foreign", "government", "other_corp",
                  "individual"]


def fetch(obj_nm, start, end="", extra=None, tag=""):
    """One POST to getMetaDataList.do; returns the ds1 row list."""
    dm = {"tmpV40": UNIT_DIVISOR, "tmpV41": "1", "tmpV1": "D",
          "tmpV45": start, "tmpV46": end, "OBJ_NM": obj_nm}
    if extra:
        dm.update(extra)
    body = json.dumps({"dmSearch": dm}).encode("utf-8")
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                ENDPOINT, data=body, method="POST",
                headers={"Content-Type": "application/json; charset=utf-8",
                         "User-Agent": "Mozilla/5.0",
                         "X-Requested-With": "XMLHttpRequest"})
            with urllib.request.urlopen(req, timeout=40) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            rows = payload.get("ds1") or []
            stamp = f"{obj_nm}_{tag or start}_{int(time.time())}"
            with open(os.path.join(RAW_DIR, stamp + ".json"), "w") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            return rows
        except Exception as err:  # retry on transient network errors
            last_err = err
            time.sleep(2 * (attempt + 1))
    print(f"FAIL {obj_nm} {start}..{end}: {last_err}", file=sys.stderr)
    return []


def business_days(start, end):
    days, cur = [], start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


def save(table, df, keys):
    """Append df to data/<table>.parquet, dedupe on keys, keep sorted."""
    if df.empty:
        print(f"{table}: no rows")
        return 0
    path = os.path.join(DATA_DIR, table + ".parquet")
    if os.path.exists(path):
        old = pd.read_parquet(path)
        df = pd.concat([old, df], ignore_index=True)
    df = df.drop_duplicates(subset=keys, keep="last").sort_values(keys)
    df.to_parquet(path, compression="snappy", index=False)
    print(f"{table}: {len(df)} rows total -> {path}")
    return len(df)


def typed_rows(rows, date_value=None):
    """Map TMPV type columns of trading-style tables to English names."""
    out = []
    for r in rows:
        rec = {name: r.get(field) for field, name
               in zip(TYPE_FIELDS, TYPE_NAMES)}
        rec["metric"] = (METRIC_BY_LABEL.get(r.get("TMPV12"))
                         or METRIC_BY_LABEL.get(r.get("TMPV2")))
        rec["date"] = date_value or str(r.get("TMPV1")).replace("-", "")
        out.append(rec)
    return [r for r in out if r["metric"]]


def collect_trade_status(start, end):
    frames = []
    for market, code in (("otc", "1"), ("exchange", "2")):
        rows = fetch("STATBND0100000250BO", start, end,
                     {"tmpV75": code, "tmpV91": "1"}, tag=f"trade_{market}")
        recs = typed_rows(rows)
        for rec in recs:
            rec["market"] = market
        frames.extend(recs)
        time.sleep(1)
    df = pd.DataFrame(frames)
    return df, ["date", "market", "metric"]


def collect_trade_by_maturity(start, end):
    rows = fetch("STATBND0100000260BO", start, end, tag="trade_maturity")
    # this table has no date column: one call aggregates exactly the
    # requested range; the metric label sits in TMPV2, the bucket in TMPV1
    frames = []
    for r in rows:
        rec = {name: r.get(field) for field, name
               in zip(TYPE_FIELDS, TYPE_NAMES)}
        rec["metric"] = METRIC_BY_LABEL.get(r.get("TMPV2"))
        rec["bucket"] = r.get("TMPV1")
        rec["start"] = start
        rec["end"] = end
        frames.append(rec)
    frames = [f for f in frames if f["metric"]]
    return pd.DataFrame(frames), ["start", "end", "bucket", "metric"]


def collect_maturity_schedule(start, end):
    rows = fetch("STATBND0100000240BO", start, end, tag="maturity")
    frames = []
    for r in rows:
        label = str(r.get("TMPV1"))
        if not label[:4].isdigit():  # skip the trailing total row
            continue
        rec = {name: r.get(field) for field, name in zip(
            ["TMPV2", "TMPV3", "TMPV4", "TMPV5", "TMPV6",
             "TMPV7", "TMPV8", "TMPV9", "TMPV10"],
            TYPE_NAMES)}
        rec["date"] = label.replace("-", "")
        frames.append(rec)
    return pd.DataFrame(frames), ["date"]


def collect_issuance(days):
    frames = []
    for d in days:
        ymd = d.strftime("%Y%m%d")
        rows = fetch("STATBND0100000230BO", ymd, ymd, tag="issuance")
        for r in rows:
            frames.append({
                "date": ymd,
                "bond_type": BOND_TYPE_EN.get(r.get("TMPV1"), r.get("TMPV1")),
                "issued": r.get("TMPV2"), "redeemed": r.get("TMPV3"),
                "net_issued": r.get("TMPV4"), "outstanding": r.get("TMPV5"),
                "share_pct": r.get("TMPV6"), "issue_count": r.get("TMPV7"),
            })
        time.sleep(1)
    return pd.DataFrame(frames), ["date", "bond_type"]


def collect_investor_otc(days):
    frames = []
    for d in days:
        ymd = d.strftime("%Y%m%d")
        rows = fetch("STATBND0100000270BO", ymd, ymd,
                     {"tmpV67": "1", "tmpV76": "00", "tmpV92": "00",
                      "tmpV77": "00", "tmpV93": "00"}, tag="investor")
        for r in rows:
            rec = {name: r.get(field) for field, name
                   in zip(INVESTOR_FIELDS, INVESTOR_NAMES)}
            rec["date"] = ymd
            rec["trade_type"] = TRADE_TYPE_EN.get(r.get("TMPV1"),
                                                  r.get("TMPV1"))
            rec["bond_type"] = BOND_TYPE_EN.get(r.get("TMPV2"),
                                                r.get("TMPV2"))
            frames.append(rec)
        time.sleep(1)
    keys = ["date", "trade_type", "bond_type"]
    return pd.DataFrame(frames), keys


def collect_final_yields(days):
    frames = []
    for d in days:
        ymd = d.strftime("%Y%m%d")
        rows = fetch("STATBND0100000010BO", ymd, "", tag="yields")
        for r in rows:
            frames.append({
                "date": ymd, "instrument": r.get("TMPV1"),
                "tenor_bucket": r.get("TMPV2"),
                "am": r.get("TMPV3"), "pm": r.get("TMPV4"),
                "change": r.get("TMPV5"), "prev_pm": r.get("TMPV6"),
                "year_high": r.get("TMPV8"), "year_low": r.get("TMPV9"),
            })
        time.sleep(1)
    return pd.DataFrame(frames), ["date", "instrument"]


def collect_lending(days):
    frames = []
    for d in days:
        ymd = d.strftime("%Y%m%d")
        rows = fetch("STATBND0100000280BO", ymd, "", tag="lending")
        for r in rows:
            if r.get("TMPV2") == "-":  # trailing total row
                continue
            frames.append({
                "date": ymd, "issue_name": r.get("TMPV1"),
                "isin": r.get("TMPV2"), "executed": r.get("TMPV3"),
                "redeemed": r.get("TMPV4"), "balance": r.get("TMPV5"),
            })
        time.sleep(1)
    return pd.DataFrame(frames), ["date", "isin"]


def validate(df_trade):
    """Cross-checks: type columns sum to total; investor table agrees."""
    if df_trade.empty:
        return
    val = df_trade[(df_trade["metric"] == "value")]
    parts = ["ktb", "local_gov", "special", "msb", "bank",
             "other_financial", "corporate", "abs"]
    bad = val[val[parts].sum(axis=1) != val["total"]]
    print(f"validate trade_status: {len(val)} value rows, "
          f"{len(bad)} total-mismatch rows")
    inv_path = os.path.join(DATA_DIR, "investor_otc.parquet")
    if os.path.exists(inv_path):
        inv = pd.read_parquet(inv_path)
        inv = inv[(inv["trade_type"] == "total")
                  & (inv["bond_type"] == "corporate")]
        otc = val[(val["market"] == "otc")].set_index("date")["corporate"]
        merged = inv.set_index("date")["total"].rename("investor")
        both = pd.concat([otc, merged], axis=1, join="inner")
        diff = (both["corporate"] - both["investor"]).abs().max()
        print(f"validate investor vs trade_status corporate OTC value: "
              f"{len(both)} shared dates, max diff {diff}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYYMMDD")
    ap.add_argument("--end", required=True, help="YYYYMMDD")
    ap.add_argument("--with-lending", action="store_true",
                    help="also collect lending-by-issue (no corporates)")
    ap.add_argument("--only", default="",
                    help="comma list subset: trade,issuance,investor,yields")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    start = date.fromisoformat(
        f"{args.start[:4]}-{args.start[4:6]}-{args.start[6:]}")
    end = date.fromisoformat(
        f"{args.end[:4]}-{args.end[4:6]}-{args.end[6:]}")
    days = business_days(start, end)
    print(f"collecting {args.start}..{args.end} ({len(days)} business days)")

    def want(name):
        return not only or name in only

    if want("trade"):
        df, keys = collect_trade_status(args.start, args.end)
        save("trade_status", df, keys)
        df_mat, keys_mat = collect_trade_by_maturity(args.start, args.end)
        save("trade_by_maturity", df_mat, keys_mat)
        df_m, keys_m = collect_maturity_schedule(args.start, args.end)
        save("maturity_schedule", df_m, keys_m)
    if want("issuance"):
        df_i, keys_i = collect_issuance(days)
        save("issuance", df_i, keys_i)
    if want("investor"):
        df_v, keys_v = collect_investor_otc(days)
        save("investor_otc", df_v, keys_v)
    if want("yields"):
        df_y, keys_y = collect_final_yields(days)
        save("final_yields", df_y, keys_y)
    if args.with_lending:
        df_l, keys_l = collect_lending(days)
        save("lending_by_issue", df_l, keys_l)
    if want("trade"):
        validate(pd.read_parquet(
            os.path.join(DATA_DIR, "trade_status.parquet")))


if __name__ == "__main__":
    main()
