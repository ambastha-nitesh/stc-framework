#!/usr/bin/env bash
# Phase B smoke test. Exercises the compose stack end-to-end:
# liveness probe, readiness probe, one query round-trip, metrics endpoint.
#
# Exit code 0 = all checks passed. Non-zero indicates which stage failed.
set -euo pipefail

HOST="${STC_HOST:-http://localhost:8000}"
METRICS="${METRICS_HOST:-http://localhost:9090}"
RETRIES="${RETRIES:-30}"
SLEEP_SECS="${SLEEP_SECS:-2}"

wait_for() {
    local url=$1
    local label=$2
    for i in $(seq 1 "${RETRIES}"); do
        if curl -fsS -o /dev/null "${url}"; then
            echo "[ok] ${label} ready after ${i} attempt(s)"
            return 0
        fi
        sleep "${SLEEP_SECS}"
    done
    echo "[fail] ${label} did not come up within $((RETRIES * SLEEP_SECS))s" >&2
    return 1
}

wait_for "${HOST}/healthz" "/healthz"
wait_for "${HOST}/readyz" "/readyz"

echo "[info] /spec metadata:"
curl -fsS "${HOST}/v1/spec" | head -c 400 || true
echo

echo "[info] posting a minimal query..."
curl -fsS -X POST "${HOST}/v1/query" \
    -H "content-type: application/json" \
    -d '{"query": "Smoke test — hello.", "tenant_id": "smoke"}' \
    | head -c 400
echo

echo "[info] sampling Prometheus metrics..."
# Metrics are served on the Flask app port as well; the :9090 side
# ships only when STC_METRICS_ENABLED is on. Try both.
if ! curl -fsS "${HOST}/metrics" | head -c 200 >/dev/null; then
    curl -fsS "${METRICS}/metrics" | head -c 200
fi
echo
echo "[ok] smoke test complete"
