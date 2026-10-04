#!/usr/bin/env bash
# Applies every db/V*.sql migration with the official Flyway image against the
# running vigil-db container, so flyway_schema_history is created properly and
# decision-api's own Flyway run is a no-op. Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "ERROR: .env not found. Run: cp .env.example .env and fill in real values." >&2; exit 1; }
set -a; . ./.env; set +a
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env}"

docker run --rm --network container:vigil-db \
  -v "$PWD/db:/flyway/sql:ro" \
  flyway/flyway:11-alpine \
  -url="jdbc:postgresql://localhost:5432/${POSTGRES_DB:-vigil}" \
  -user="${POSTGRES_USER:-vigil}" \
  -password="$POSTGRES_PASSWORD" \
  -locations=filesystem:/flyway/sql \
  migrate
