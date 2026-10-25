#!/bin/bash
# Bond data downloader: gentle sequential download from GCP VM Flask server,
# converts each file to snappy parquet (lightweight), deletes original.
# Idempotent: skips files already converted. Safe to re-run / run via cron.
DEST="$HOME/workspace/bond-data"
PY="$DEST/.venv/bin/python"
LIST="$DEST/files.txt"
LOG="$DEST/download.log"
LOCK="$DEST/.lock"
BASE="http://35.227.144.191:8000/download"
INDEX="http://35.227.144.191:8000/"

exec 9>"$LOCK"
flock -n 9 || { echo "$(date '+%H:%M:%S') another run active, exit" >> "$LOG"; exit 0; }

# refresh file list from server index (new files appear on weekdays ~21:10 KST)
index_ok=0
if curl -s -m 60 --retry 3 --retry-delay 10 "$INDEX" -o "$DEST/index.html" && [ -s "$DEST/index.html" ]; then
  grep -o 'href="/download/[^"]*"' "$DEST/index.html" | sed 's/href="\/download\///;s/"//' | sort -u > "$DEST/files.new"
  if [ -s "$DEST/files.new" ]; then
    cp "$DEST/files.txt" "$DEST/files.old" 2>/dev/null
    cat "$DEST/files.old" "$DEST/files.new" 2>/dev/null | sort -u > "$DEST/files.txt"
    new_in_index=$(comm -13 <(sort "$DEST/files.old" 2>/dev/null) <(sort "$DEST/files.new") | wc -l)
    echo "$(date '+%H:%M:%S') index refreshed, $new_in_index new files listed" >> "$LOG"
    rm -f "$DEST/files.old"
    index_ok=1
  fi
  rm -f "$DEST/files.new" "$DEST/index.html"
fi
if [ "$index_ok" -eq 0 ]; then
  # fallback: index is flaky (server drops mid-transfer); probe expected names directly.
  # NOTE: the file server returns 500 (not 404) for missing files.
  # Probe candidates live only in the per-run list, never in files.txt.
  echo "$(date '+%H:%M:%S') index fetch failed, probing expected filenames for last 7 days" >> "$LOG"
  : > "$DEST/probe.tmp"
  probe_n=0
  for d in $(seq 0 6); do
    ymd=$(date -d "-$d days" +%Y%m%d)
    for pat in "result_today_${ymd}.xlsx" "kofia_bis_bond_issue_${ymd}.csv"; do
      if ! grep -qx "$pat" "$DEST/files.txt" 2>/dev/null && [ ! -s "$DEST/$pat.parquet" ]; then
        echo "$pat" >> "$DEST/probe.tmp"; probe_n=$((probe_n+1))
      fi
    done
  done
  echo "$(date '+%H:%M:%S') probed $probe_n candidate filenames" >> "$LOG"
  LENIENT=1
else
  : > "$DEST/probe.tmp"
  LENIENT=0
fi
# per-run list: authoritative files.txt + (index-failed only) probe candidates
cat "$DEST/files.txt" "$DEST/probe.tmp" 2>/dev/null | grep -v '^$' > "$DEST/files.run"
LIST="$DEST/files.run"

convert_one() { # $1 = original path, $2 = parquet path
  "$PY" - "$1" "$2" << 'PYEOF' 2>>"$LOG"
import sys, pandas as pd
src, dst = sys.argv[1], sys.argv[2]
with open(src, 'rb') as fh:
    magic = fh.read(2)
if magic == b'PK':
    df = pd.read_excel(src, engine='openpyxl', dtype=str, keep_default_na=False)
else:  # some .xlsx files are actually CSV content
    df = pd.read_csv(src, encoding='utf-8', dtype=str, keep_default_na=False)
df.to_parquet(dst, compression='snappy', index=False)
chk = pd.read_parquet(dst)
assert chk.shape == df.shape, "shape mismatch after conversion"
PYEOF
}

MD5LOG="$DEST/converted_md5.txt"
touch "$MD5LOG"
md5_of() { md5sum "$1" | cut -d' ' -f1; }
peek_dup() { grep -q "^$(md5_of "$1")$" "$MD5LOG"; }  # 0 = already converted

server_up() { curl -s -m 10 -o /dev/null "$INDEX"; }

consec_fail=0
total=$(wc -l < "$LIST")
i=0; done_n=0
while read -r f; do
  i=$((i+1)); [ -z "$f" ] && continue
  if [[ "$f" == *.parquet ]]; then pq="$DEST/$f"; else pq="$DEST/$f.parquet"; fi
  orig="$DEST/$f"
  if [ -s "$pq" ]; then done_n=$((done_n+1)); continue; fi
  # parquet passthrough: server may serve .parquet directly (pipeline converts upstream)
  if [[ "$f" == *.parquet ]]; then
    if [ ! -s "$orig" ]; then
      curl -s -m 180 --retry 2 --retry-delay 10 -o "$orig.part" "$BASE/$f" \
        && [ -s "$orig.part" ] && mv "$orig.part" "$orig" || { rm -f "$orig.part"; echo "$(date '+%H:%M:%S') FAIL dl $f" >> "$LOG"; sleep 3; continue; }
      sleep 3 # gentle pace
    fi
    if "$PY" -c "import sys,pandas as pd; pd.read_parquet(sys.argv[1]).shape" "$orig" >>"$LOG" 2>&1; then
      done_n=$((done_n+1))
    else
      echo "$(date '+%H:%M:%S') FAIL verify $f" >> "$LOG"; rm -f "$orig"
    fi
    continue
  fi
  if [ ! -s "$orig" ]; then
    code=$(curl -s -m 180 --retry 2 --retry-delay 10 -o "$orig.part" -w "%{http_code}" "$BASE/$f")
    if [ "$code" = "200" ] && [ -s "$orig.part" ]; then
      mv "$orig.part" "$orig"; consec_fail=0
    elif [ "$code" = "404" ] || { [ "$code" = "500" ] && [ "$LENIENT" = "1" ]; }; then
      rm -f "$orig.part"
      echo "$(date '+%H:%M:%S') SKIP $code $f" >> "$LOG"
      sleep 3; continue  # missing file (probe mode); server 500s instead of 404
    else
      rm -f "$orig.part"; consec_fail=$((consec_fail+1))
      echo "$(date '+%H:%M:%S') FAIL dl $f (http $code)" >> "$LOG"
      if [ "$consec_fail" -ge 5 ] && ! server_up; then
        echo "$(date '+%H:%M:%S') SERVER DOWN, exiting gracefully for later retry" >> "$LOG"
        exit 0
      fi
      sleep 3; continue
    fi
    sleep 3 # gentle pace
  fi
  if peek_dup "$orig"; then
    echo "$(date '+%H:%M:%S') DUP $f (same content already converted), skipping" >> "$LOG"
    rm -f "$orig"; done_n=$((done_n+1)); continue
  fi
  if convert_one "$orig" "$pq"; then
    md5_of "$orig" >> "$MD5LOG"
    rm -f "$orig"; done_n=$((done_n+1))
  else
    echo "$(date '+%H:%M:%S') FAIL convert $f" >> "$LOG"
  fi
  if [ $((i % 25)) -eq 0 ]; then
    echo "$(date '+%H:%M:%S') progress $i/$total done=$done_n" >> "$LOG"
  fi
done < "$LIST"
echo "$(date '+%H:%M:%S') DONE done=$done_n/$total" >> "$LOG"
du -sh "$DEST" >> "$LOG"
