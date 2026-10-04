#!/usr/bin/env bash
# Resets the demo to a clean, deterministic state: drops and recreates the
# schema, reseeds reason codes and policy chunks, regenerates the synthetic
# dataset with a FIXED seed, and retrains the model. Run this before every
# recording take so nothing carries over from a previous run.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "ERROR: .env not found. Run: cp .env.example .env and fill in real values." >&2; exit 1; }
set -a; . ./.env; set +a
PGUSER_="${POSTGRES_USER:-vigil}"
PGDB_="${POSTGRES_DB:-vigil}"

echo "==> stopping and recreating the db container (fresh volume)"
docker compose down -v db 2>/dev/null || true
docker compose up -d db

echo "==> waiting for postgres to be healthy"
healthy=0
for i in $(seq 1 60); do
  status=$(docker inspect --format='{{.State.Health.Status}}' vigil-db 2>/dev/null || echo "starting")
  [ "$status" = "healthy" ] && { healthy=1; break; }
  sleep 1
done
[ "$healthy" = 1 ] || { echo "ERROR: vigil-db did not become healthy within 60s" >&2; exit 1; }

echo "==> applying migrations (Flyway)"
./scripts/migrate.sh

echo "==> generating synthetic data (fixed seed 20260921)"
(cd data/generator && python3 generate.py)

echo "==> training the model"
(cd services/ml-service && .venv/bin/python -m app.training.train)

echo "==> embedding the policy corpus (needs Ollama; retried at ml-service startup if this fails)"
(cd services/ml-service && .venv/bin/python -m app.training.embed_policy) || echo "    skipped: embedding provider unavailable"

echo "==> registering the trained model"
REGISTRY_SQL=$(mktemp)
trap 'rm -f "$REGISTRY_SQL"' EXIT
python3 - > "$REGISTRY_SQL" <<'PYEOF'
import json, sys
m = json.load(open("services/ml-service/artifacts/metrics.json"))
sql = f"""
INSERT INTO model_registry (version, algorithm, trained_at, training_rows, feedback_rows_used,
  pr_auc, recall_at_1pct_fpr, fp_rate, threshold_low, threshold_high, threshold_decline,
  feature_importance, active, promoted_reason)
VALUES ('{m["version"]}', '{m["algorithm"]}', '{m["trained_at"]}', {m["training_rows"]}, 0,
  {m["pr_auc"]}, {m["recall_at_1pct_fpr"]}, {m["four_way_fp_rate"]},
  {m["threshold_low"]}, {m["threshold_high"]}, {m["threshold_decline"]},
  '{json.dumps(m["feature_importance_top15"])}'::jsonb, true, 'seed_demo.sh');
"""
sys.stdout.write(sql)
PYEOF
docker exec -i vigil-db psql -U "$PGUSER_" -d "$PGDB_" -v ON_ERROR_STOP=1 < "$REGISTRY_SQL"

echo "==> done. Now run ./scripts/run_all.sh to (re)start all three services against this fresh data."
