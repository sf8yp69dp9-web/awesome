#!/usr/bin/env bash
# check_reviews.sh — Daily cron: flag decisions whose review_date has passed.
# Run via cron: 0 8 * * * /path/to/check_reviews.sh >> /path/to/check_reviews.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DECISIONS_FILE="$SCRIPT_DIR/decisions.csv"

if [ ! -f "$DECISIONS_FILE" ]; then
  echo "decisions.csv not found at $DECISIONS_FILE"
  exit 1
fi

today=$(date +%Y-%m-%d)
tmp=$(mktemp)

python3 - "$DECISIONS_FILE" "$today" "$tmp" <<'PYEOF'
import csv, sys

src, today, dst = sys.argv[1], sys.argv[2], sys.argv[3]
changed = 0

with open(src, newline='') as fin, open(dst, 'w', newline='') as fout:
    reader = csv.reader(fin)
    writer = csv.writer(fout, quoting=csv.QUOTE_ALL)
    header = next(reader)
    writer.writerow(header)
    for row in reader:
        if len(row) >= 6:
            review_date = row[4].strip()
            status = row[5].strip()
            if review_date and review_date <= today and status == 'active':
                row[5] = 'REVIEW DUE'
                changed += 1
        writer.writerow(row)

print(f"Flagged {changed} decision(s) as REVIEW DUE.")
PYEOF

mv "$tmp" "$DECISIONS_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] check_reviews.sh complete."
