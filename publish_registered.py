#!/usr/bin/env python3
"""Merge registered events into the built events page.

The committed github_pages/index.html carries the hand-written events.
Events registered through GitHub issues live in registered_events.json
and are the source of truth for every id starting with "reg-": this
script rebuilds the page's event list as the hand-written events plus
the registry contents, so additions and removals both propagate.

Used by the publish-registered workflow; also safe to run locally.
The page file is rewritten only when the event list actually changes.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=os.path.join(
        HERE, "github_pages", "index.html"))
    ap.add_argument("--registry", default=os.path.join(
        HERE, "registered_events.json"))
    args = ap.parse_args()

    with open(args.html, encoding="utf-8") as f:
        html = f.read()
    anchor = html.index("EVENTS_DATA = ")
    start = html.index("{", anchor)
    obj, end = json.JSONDecoder().raw_decode(html, start)
    current = obj["events"]

    registry = []
    if os.path.exists(args.registry):
        with open(args.registry, encoding="utf-8") as f:
            registry = json.load(f)

    base = [e for e in current if not str(e.get("id", "")).startswith("reg-")]
    merged = base + registry
    if merged == current:
        print("registered events already in page, nothing to do")
        return 0
    blob = json.dumps({"events": merged}, ensure_ascii=False)
    with open(args.html, "w", encoding="utf-8") as f:
        f.write(html[:start] + blob + html[end:])
    added = [e["id"] for e in registry
             if e["id"] not in {c.get("id") for c in current}]
    removed = [c["id"] for c in current
               if str(c.get("id", "")).startswith("reg-")
               and c["id"] not in {e["id"] for e in registry}]
    print(f"page updated: {len(merged)} events "
          f"(added {added}, removed {removed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
