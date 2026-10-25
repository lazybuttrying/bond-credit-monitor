"""Check issuers.json for NEW credit-widening alerts.

Prints alert lines for issuers whose 90-day z-score > 2.0 (unusual vs own
history) AND 5-day change >= 10bp (economically meaningful), and who were
not alerted in the last 7 days. Updates the seen-state file.
Exits 0 with no output when there is nothing new.
"""
import json
import os
from datetime import datetime, timedelta

DATA = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(DATA, ".credit_alerts_seen.json")
Z_THRESHOLD = 2.0
MIN_CHG_BP = 10
COOLDOWN_DAYS = 7


def main():
    with open(os.path.join(DATA, "issuers.json")) as f:
        data = json.load(f)
    seen = {}
    if os.path.exists(STATE):
        seen = json.load(open(STATE))
    today = datetime.now().date()
    cutoff = today - timedelta(days=COOLDOWN_DAYS)
    new_alerts = []
    for r in data["latest_table"]:
        z = r.get("z_90d")
        chg = r.get("chg_5d")
        if z is None or chg is None:
            continue
        if not (z > Z_THRESHOLD and chg >= MIN_CHG_BP):
            continue
        last = seen.get(r["issuer"])
        if last and datetime.strptime(last, "%Y-%m-%d").date() >= cutoff:
            continue
        new_alerts.append(r)
        seen[r["issuer"]] = today.strftime("%Y-%m-%d")
    with open(STATE, "w") as f:
        json.dump(seen, f, ensure_ascii=False)
    for r in sorted(new_alerts, key=lambda x: -x["z_90d"]):
        print(
            f"ALERT {r['issuer']} ({r['rating'] or 'NR'}): "
            f"spread {r['spread']}bp, z={r['z_90d']}, 5d change +{r['chg_5d']}bp, "
            f"vs peer {r['vs_peer']:+.0f}bp, trades {r['n']}"
        )


if __name__ == "__main__":
    main()
