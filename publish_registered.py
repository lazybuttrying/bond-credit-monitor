#!/usr/bin/env python3
"""Merge registered events into the built events page.

The committed github_pages/index.html inlines only event metadata
(button labels and search fields); each event's full payload lives in
github_pages/events-data/<id>.json and is fetched on first selection.
Events registered through GitHub issues live in registered_events.json
and are the source of truth for every id starting with "reg-": this
script rebuilds the page's inline reg-* metadata from the registry,
writes each registry payload file, and deletes payload files whose
event left the registry, so additions and removals both propagate.
Hand-written events and their payload files are left untouched; they
are owned by build_events.py.

Used by the publish-registered workflow; also safe to run locally.
Files are rewritten only when their content actually changes.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

META_KEYS = ("id", "title", "title_en", "date_label", "date_label_en",
             "issuer_name", "registered")
SEARCH_SOURCE_KEYS = ("topic", "topic_en", "outlet", "outlet_en", "url")


def json_clean(obj):
    """Map float NaN to None recursively so the payload files stay
    strict JSON (the page fetches and parses them with
    response.json(), not as inline script)."""
    if isinstance(obj, float):
        return None if obj != obj else obj
    if isinstance(obj, dict):
        return {k: json_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_clean(v) for v in obj]
    return obj


def event_meta(ev):
    """Inline stub for one event: button and search metadata only.
    Mirrors event_meta in build_events.py."""
    meta = {k: ev[k] for k in META_KEYS if k in ev}
    if "topic" in ev:
        meta["topic"] = ev["topic"]
    if "topic_en" in ev:
        meta["topic_en"] = ev["topic_en"]
    if ev.get("sources"):
        meta["sources"] = [
            {k: s[k] for k in SEARCH_SOURCE_KEYS if k in s}
            for s in ev["sources"]]
    return meta


def write_if_changed(path, text):
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


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
    merged = base + [event_meta(e) for e in registry]

    data_dir = os.path.join(os.path.dirname(os.path.abspath(args.html)),
                            "events-data")
    os.makedirs(data_dir, exist_ok=True)
    changed_files = []
    wanted = set()
    for e in registry:
        fn = e["id"] + ".json"
        wanted.add(fn)
        blob = json.dumps(json_clean(e), ensure_ascii=False,
                          allow_nan=False)
        if write_if_changed(os.path.join(data_dir, fn), blob):
            changed_files.append(fn)
    for fn in sorted(os.listdir(data_dir)):
        if fn.startswith("reg-") and fn.endswith(".json") \
                and fn not in wanted:
            os.remove(os.path.join(data_dir, fn))
            changed_files.append(fn + " (deleted)")

    if merged == current and not changed_files:
        print("registered events already in page, nothing to do")
        return 0
    if merged != current:
        blob = json.dumps({"events": merged}, ensure_ascii=False)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html[:start] + blob + html[end:])
    added = [e["id"] for e in registry
             if e["id"] not in {c.get("id") for c in current}]
    removed = [c["id"] for c in current
               if str(c.get("id", "")).startswith("reg-")
               and c["id"] not in {e["id"] for e in registry}]
    print(f"registry synced: {len(merged)} events "
          f"(added {added}, removed {removed}), "
          f"payload files changed: {changed_files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
