#!/usr/bin/env bash
# log_decision.sh — Interactively log a decision to decisions.csv
set -euo pipefail

DECISIONS_FILE="$(dirname "$0")/decisions.csv"

# Ensure file exists with header
if [ ! -f "$DECISIONS_FILE" ]; then
  echo "date,decision,reasoning,expected_outcome,review_date,status" > "$DECISIONS_FILE"
fi

echo "=== Decision Logger ==="
echo ""

read -rp "Decision: " decision
read -rp "Reasoning: " reasoning
read -rp "Expected outcome: " expected_outcome

today=$(date +%Y-%m-%d)
review_date=$(date -d "+30 days" +%Y-%m-%d 2>/dev/null || date -v+30d +%Y-%m-%d)

# Escape double-quotes in fields by doubling them (CSV standard)
escape_csv() {
  local field="$1"
  field="${field//\"/\"\"}"
  echo "\"$field\""
}

row="$(escape_csv "$today"),$(escape_csv "$decision"),$(escape_csv "$reasoning"),$(escape_csv "$expected_outcome"),$(escape_csv "$review_date"),\"active\""
echo "$row" >> "$DECISIONS_FILE"

echo ""
echo "Logged. Review date set for $review_date."
