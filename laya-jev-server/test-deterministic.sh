#!/usr/bin/env bash
# Test if the Laya server is deterministic: same request N times -> same answer.
# Usage: ./test-deterministic.sh [URL] [N]
#   URL  default http://192.168.0.124:8000
#   N    number of identical requests (default 5)

URL="${1:-http://192.168.0.124:8000}"
N="${2:-5}"

read -r -d '' PAYLOAD <<'EOF'
{
  "state": {
    "from": "customer@acme.com",
    "subject": "Duplicate billing on March invoice #4411",
    "body": "Hi team, we were billed twice for March. Please refund the duplicate before Friday or we will cancel our plan."
  },
  "questions": {
    "department": {"type": "choice", "instructions": "Which department should handle this email?",
      "criteria": {"billing": "invoices, refunds", "technical": "bugs", "sales": "pricing", "other": "rest"}},
    "urgency": {"type": "score", "instructions": "How urgent is this request?",
      "criteria": ["not urgent", "soon", "critical deadline"]},
    "churn_risk": {"type": "noul", "instructions": "Does the user threaten to cancel?"}
  }
}
EOF

echo "Testing determinism: $N identical requests -> $URL/v1/decisions"
hashes=()
for i in $(seq 1 "$N"); do
  body=$(curl -s -m 60 "$URL/v1/decisions" -H 'Content-Type: application/json' -d "$PAYLOAD")
  if [ -z "$body" ]; then
    echo "request $i: EMPTY RESPONSE (server down?)"
    exit 1
  fi
  h=$(printf '%s' "$body" | sha256sum | cut -d' ' -f1)
  hashes+=("$h")
  echo "request $i: ${h:0:16}..."
done

first="${hashes[0]}"
same=1
for h in "${hashes[@]:1}"; do
  [ "$h" != "$first" ] && same=0
done

echo
if [ "$same" = 1 ]; then
  echo "DETERMINISTIC: all $N responses identical ✔"
else
  echo "NOT DETERMINISTIC: responses differ ✘"
  echo "diff details:"
  curl -s -m 60 "$URL/v1/decisions" -H 'Content-Type: application/json' -d "$PAYLOAD" > /tmp/laya_a.json
  curl -s -m 60 "$URL/v1/decisions" -H 'Content-Type: application/json' -d "$PAYLOAD" > /tmp/laya_b.json
  diff /tmp/laya_a.json /tmp/laya_b.json | head -20
fi
[ "$same" = 1 ]
