#!/usr/bin/env bash
# review.sh — Surface all decisions flagged REVIEW DUE from decisions.csv
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DECISIONS_FILE="$SCRIPT_DIR/decisions.csv"

if [ ! -f "$DECISIONS_FILE" ]; then
  echo "decisions.csv not found at $DECISIONS_FILE"
  exit 1
fi

python3 - "$DECISIONS_FILE" <<'PYEOF'
import csv, sys

src = sys.argv[1]

with open(src, newline='') as fin:
    reader = csv.DictReader(fin)
    flagged = [row for row in reader if row.get('status', '').strip() == 'REVIEW DUE']

if not flagged:
    print("No decisions are due for review.")
    sys.exit(0)

print(f"{'='*60}")
print(f"  DECISIONS DUE FOR REVIEW ({len(flagged)} item(s))")
print(f"{'='*60}")

for i, row in enumerate(flagged, 1):
    print(f"\n[{i}] Date logged : {row['date']}")
    print(f"    Decision    : {row['decision']}")
    print(f"    Reasoning   : {row['reasoning']}")
    print(f"    Expected    : {row['expected_outcome']}")
    print(f"    Review due  : {row['review_date']}")
    print(f"    Status      : {row['status']}")
    print(f"  {'-'*56}")
PYEOF
