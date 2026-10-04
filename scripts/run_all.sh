#!/usr/bin/env bash
# Starts db (docker), ml-service, decision-api and web in the correct
# order, health-gating each step so the next one never starts against a
# service that isn't ready yet. Logs go to /tmp/vigil-*.log. Ctrl+C stops
# the foreground tail; the background services keep running -- use
# `pkill -f "uvicorn app.main"` / `pkill -f com.vigil.VigilApplication` /
# `pkill -f "vite"` to stop them.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

set -a; source .env; set +a

echo "==> stopping any stale service processes from a previous run"
pkill -f "uvicorn app.main" 2>/dev/null || true
pkill -f "com.vigil.VigilApplication" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 1

echo "==> db"
docker compose up -d db
wait_ok() { # $1=label, rest=command that succeeds when ready; 60 tries, 1s apart (override with WAIT_TRIES)
  local label=$1; shift
  for i in $(seq 1 "${WAIT_TRIES:-60}"); do
    "$@" >/dev/null 2>&1 && { echo "    $label healthy"; return 0; }
    sleep 1
  done
  echo "ERROR: $label did not become healthy in time (see /tmp/vigil-*.log)" >&2
  exit 1
}
db_healthy() { [ "$(docker inspect --format='{{.State.Health.Status}}' vigil-db 2>/dev/null || echo starting)" = "healthy" ]; }
wait_ok db db_healthy

echo "==> ml-service"
(cd services/ml-service && nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 \
  > /tmp/vigil-ml-service.log 2>&1 &)
wait_ok ml-service curl -sf http://localhost:8001/health

echo "==> decision-api"
export SPRING_DATASOURCE_URL="jdbc:postgresql://localhost:5433/${POSTGRES_DB:-vigil}"
export SPRING_DATASOURCE_USERNAME="${POSTGRES_USER:-vigil}"
export SPRING_DATASOURCE_PASSWORD="${POSTGRES_PASSWORD}"
export VIGIL_FLYWAY_LOCATION="${ROOT}/db"
export VIGIL_ML_SERVICE_URL="http://localhost:8001"
export MAVEN_HOME="${MAVEN_HOME:-$HOME/.m2/wrapper/dists/apache-maven-3.9.16/56ba1f9f}"
export PATH="$MAVEN_HOME/bin:$PATH"
(cd services/decision-api && nohup mvn -o -q spring-boot:run > /tmp/vigil-decision-api.log 2>&1 &)
WAIT_TRIES=120 wait_ok decision-api curl -sf http://localhost:8081/actuator/health

echo "==> web"
(cd web && nohup npm run dev > /tmp/vigil-web.log 2>&1 &)
wait_ok web curl -sf http://localhost:5174

echo
echo "All services up: http://localhost:5174"
echo "Logs: /tmp/vigil-{ml-service,decision-api,web}.log"
