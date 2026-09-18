"""Smoke tests for the Laya Decisions API (server.py) at http://192.168.0.124:8000/.

Run from anywhere (only needs `requests`):
    python test.py
    BASE_URL=http://192.168.0.124:8000 python test.py
"""

import json
import os
import sys

import requests

BASE_URL = os.environ.get("BASE_URL", "http://192.168.0.124:8000")
TIMEOUT = 120  # first request may load the model

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{PASS if cond else FAIL}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def post(path, payload):
    return requests.post(BASE_URL + path, json=payload, timeout=TIMEOUT)


# ---------------------------------------------------------------------------
print(f"Testing Laya API at {BASE_URL}\n")

# 1. Health
r = requests.get(BASE_URL + "/health", timeout=10)
check("health: status 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
check("health: model field", r.json().get("model") == "laya", str(r.json()))

# 2. Jev-style decisions request (same shape as jev.py)
email = {
    "from": "customer@acme.com",
    "subject": "Duplicate billing on March invoice #4411",
    "body": "Hi team, we were billed twice for March. Please refund the duplicate before Friday or we will cancel our plan.",
}
questions = {
    "department": {
        "type": "choice",
        "instructions": "Which department should handle this email?",
        "criteria": {
            "billing": "invoices, payments, refunds",
            "technical": "bugs, outages, integrations",
            "sales": "pricing, contracts, demos",
            "other": "everything else",
        },
    },
    "urgency": {
        "type": "score",
        "instructions": "How urgent is this request?",
        "criteria": ["not urgent", "soon", "critical deadline or blocking issue"],
    },
    "churn_risk": {"type": "noul", "instructions": "Does the user threaten to cancel or switch to a competitor?"},
    "is_phishing": {"type": "noul", "instructions": "Is this email a phishing or scam attempt?"},
}

r = post("/v1/decisions", {"model": "laya", "state": email, "questions": questions})
check("decisions: status 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
answers = r.json().get("answers", {})
check("decisions: model field", r.json().get("model") == "laya", str(r.json())[:200])

dep = answers.get("department", {})
check("choice: has answer", "choice" in dep, json.dumps(dep)[:200])
check("choice: valid option", dep.get("choice") in questions["department"]["criteria"], str(dep.get("choice")))
probs = dep.get("probabilities", {})
check("choice: probabilities sum to ~1", abs(sum(probs.values()) - 1.0) < 0.02, str(probs))
check("choice: confidence present", isinstance(dep.get("confidence"), (int, float)), str(dep.get("confidence")))

urg = answers.get("urgency", {})
check("score: has answer", "score" in urg, json.dumps(urg)[:200])
check("score: within rubric", 0.0 <= urg.get("score", -1) <= len(questions["urgency"]["criteria"]) - 1, str(urg.get("score")))
check("score: probabilities present", isinstance(urg.get("probabilities"), dict), str(urg.get("probabilities"))[:200])

for qid in ("churn_risk", "is_phishing"):
    n = answers.get(qid, {}).get("noul")
    check(f"noul ({qid}): 0..1", isinstance(n, (int, float)) and 0.0 <= n <= 1.0, str(n))

# 3. Plain-text state (Jev accepts strings too)
r = post("/v1/decisions", {
    "state": "Help! My payouts have been failing for 3 days.",
    "questions": {"is_urgent": {"type": "noul", "instructions": "Does this message convey urgency?"}},
})
check("text state: status 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
check("text state: noul answer", "noul" in r.json().get("answers", {}).get("is_urgent", {}), r.text[:300])

# 4. Jev alias route
r = post("/decisions", {"state": email, "questions": questions})
check("alias /decisions: status 200", r.status_code == 200, f"got {r.status_code}")

# 5. Validation errors -> 422
r = post("/v1/decisions", {"state": "hi", "questions": {"q": {"type": "bogus", "instructions": "x"}}})
check("bad type: 422", r.status_code == 422, f"got {r.status_code}")

r = post("/v1/decisions", {"state": "hi", "questions": {"q": {"type": "choice", "instructions": "x"}}})
check("choice without criteria: 422", r.status_code == 422, f"got {r.status_code}")

r = post("/v1/decisions", {"state": "hi", "questions": {}})
check("empty questions: 422", r.status_code == 422, f"got {r.status_code}")

# ---------------------------------------------------------------------------
print()
failed = [name for name, ok, _ in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("Failed:", *failed, sep="\n  - ")
sys.exit(1 if failed else 0)
