"""Detect agency rating changes from KOFIA trade data itself.

The trade files carry a per-bond credit-rating column. Ratings attach to
bonds, not issuers: one issuer's senior and subordinated bonds carry
different ratings, so issuer-level daily modes flip with trading mix.
This tracker therefore works per bond:

- per bond: a differing rating becomes pending; confirmed once the new
  rating is seen on >= 2 trading days of that bond (filters blank/glitch
  one-day artifacts)
- issuer events: cluster an issuer's confirmed per-bond changes whose
  first-seen dates fall within 14 calendar days and share a direction;
  a cluster needs >= 2 bonds, or exactly 1 when that bond is the only
  bond of the issuer ever tracked (flagged single_bond)
- representative from/to of a cluster = the change of its largest-amount
  bond, so senior bonds speak for the issuer

Modes:
  --backfill   rescan all trade files, rebuild state + events
  (default)    scan only files newer than the state's last date
Outputs: rating_changes.json (issuer events), .ratings_state.json
Prints NEW_EVENT lines for newly confirmed issuer events (cron report).
"""
import glob
import json
import os
import re
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_issuers import parse_issuer  # noqa: E402

DATA = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(DATA, ".ratings_state.json")
EVENTS_OUT = os.path.join(DATA, "rating_changes.json")

SCALE = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
         "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC",
         "C", "D"]
SKIP_ISSUERS = {"국고채권", "통화안정증권", "국민주택채권", "외국환평형기금채권"}
CLUSTER_DAYS = 14


def file_date(path):
    m = re.search(r"result_today_(\d{8})\.xlsx\.parquet$", path)
    return m.group(1) if m else None


def scan_file(path):
    """Return {bond: (rating, amount, issuer)} modal rating per bond."""
    df = pd.read_parquet(path, columns=["종목명", "신용등급", "거래대금"])
    df["rating"] = df["신용등급"].astype(str).str.strip()
    df = df[df["rating"].isin(SCALE)]
    if len(df) == 0:
        return {}
    df["bond"] = df["종목명"].astype(str).str.strip()
    df["amt"] = pd.to_numeric(df["거래대금"], errors="coerce").fillna(0)
    g = df.groupby(["bond", "rating"], observed=True)["amt"].sum()
    out = {}
    for bond, sub in g.groupby(level=0):
        rating = sub.idxmax()[1] if sub.max() > 0 else sub.index[0][1]
        issuer = parse_issuer(bond)
        if bond.startswith("S-Oil"):
            issuer = "S-Oil"
        if issuer and issuer not in SKIP_ISSUERS:
            out[bond] = (rating, float(sub.sum()), issuer)
    return out


def direction(frm, to):
    if frm in SCALE and to in SCALE:
        d = SCALE.index(to) - SCALE.index(frm)
        return ("down" if d > 0 else "up"), abs(d)
    return None, None


def apply_day(bonds_state, bond_events, date, scanned):
    for bond, (rating, amt, issuer) in scanned.items():
        st = bonds_state.setdefault(
            bond, {"issuer": issuer, "confirmed": None, "since": None,
                   "pending": None, "pending_days": 0, "pending_since": None,
                   "max_amt": 0})
        st["issuer"] = issuer
        st["max_amt"] = max(st["max_amt"], amt)
        if st["confirmed"] is None:
            st.update(confirmed=rating, since=date)
            continue
        if rating == st["confirmed"]:
            st.update(pending=None, pending_days=0, pending_since=None)
            continue
        if st["pending"] == rating:
            st["pending_days"] += 1
        else:
            st.update(pending=rating, pending_days=1, pending_since=date)
        if st["pending_days"] >= 2:
            dirn, notches = direction(st["confirmed"], rating)
            bond_events.append({
                "bond": bond, "issuer": issuer, "from": st["confirmed"],
                "to": rating, "date": st["pending_since"],
                "confirmed_date": date, "direction": dirn,
                "notches": notches, "max_amt": st["max_amt"]})
            st.update(confirmed=rating, since=st["pending_since"],
                      pending=None, pending_days=0, pending_since=None)


def cluster_events(bond_events, bonds_state):
    """Cluster per-bond changes into issuer-level events."""
    issuer_bond_count = {}
    for st in bonds_state.values():
        issuer_bond_count[st["issuer"]] = issuer_bond_count.get(st["issuer"], 0) + 1
    by_issuer = {}
    for ev in bond_events:
        by_issuer.setdefault(ev["issuer"], []).append(ev)
    out = []
    for issuer, evs in by_issuer.items():
        # Bonds trade sparsely, so one agency action trickles in over
        # months as each bond next trades. Merge consecutive bond events
        # with the same (from, to, direction); a different key in between
        # starts a new issuer event.
        evs = sorted(evs, key=lambda e: e["date"])
        clusters = []
        for ev in evs:
            key = (ev["from"], ev["to"], ev["direction"])
            if clusters and clusters[-1][0] == key:
                clusters[-1][1].append(ev)
            else:
                clusters.append((key, [ev]))
        for key, cluster in clusters:
            single = len(cluster) == 1
            if single and issuer_bond_count.get(issuer, 0) > 1:
                continue  # lone bond moving alone: instrument-level, skip
            rep = max(cluster, key=lambda e: e["max_amt"])
            out.append({
                "issuer": issuer, "from": rep["from"], "to": rep["to"],
                "date": cluster[0]["date"],
                "confirmed_date": max(e["confirmed_date"] for e in cluster),
                "direction": key[2],
                "notches": rep["notches"], "n_bonds": len(cluster),
                "single_bond": single})
    return sorted(out, key=lambda e: e["date"])


def main():
    backfill = "--backfill" in sys.argv
    files = sorted(glob.glob(os.path.join(DATA, "result_today_*.xlsx.parquet")))
    files = [f for f in files if file_date(f)]
    if backfill or not os.path.exists(STATE):
        bonds_state, bond_events, last, known = {}, [], None, set()
    else:
        with open(STATE) as f:
            saved = json.load(f)
        bonds_state = saved["bonds"]
        bond_events = saved["bond_events"]
        last = saved["last_date"]
        known = {(e["issuer"], e["date"], e["from"], e["to"])
                 for e in cluster_events(bond_events, bonds_state)}
    todo = files if (backfill or last is None) else [f for f in files if file_date(f) > last]
    for f in todo:
        date = file_date(f)
        apply_day(bonds_state, bond_events, date, scan_file(f))
        last = date
    issuer_events = cluster_events(bond_events, bonds_state)
    new_events = [e for e in issuer_events
                  if (e["issuer"], e["date"], e["from"], e["to"]) not in known]
    with open(STATE, "w") as fp:
        json.dump({"bonds": bonds_state, "bond_events": bond_events,
                   "last_date": last}, fp, ensure_ascii=False)
    with open(EVENTS_OUT, "w") as fp:
        json.dump({"events": issuer_events,
                   "n_bonds_tracked": len(bonds_state),
                   "n_bond_events": len(bond_events),
                   "last_date": last}, fp, ensure_ascii=False, indent=1)
    print(f"scanned {len(todo)} files, tracked {len(bonds_state)} bonds, "
          f"{len(bond_events)} bond events, {len(issuer_events)} issuer events, "
          f"{len(new_events)} new")
    for ev in new_events:
        print("NEW_EVENT", json.dumps(ev, ensure_ascii=False))


if __name__ == "__main__":
    main()
