#!/usr/bin/env bash
# manage-services.sh — bootstrap + start/stop/restart for the VIGIL local stack
# (pgvector Postgres, Ollama, the ml-service, the Spring Boot decision-api, and
# the Vite frontend).
#
# First run bootstraps from scratch: creates the ml-service venv, installs
# frontend dependencies, pulls the Ollama models, and brings Postgres up.
# Flyway applies the schema when decision-api boots. Repeat runs just start
# what is already configured.
#
# The data pipeline (synthetic population + training) is deliberately NOT
# automatic — it takes a few minutes and you rarely want it. Run it explicitly
# with './manage-services.sh seed' (delegates to scripts/seed_demo.sh, which
# resets the db to a clean, deterministic state first).
#
# Usage:
#   ./manage-services.sh                      # interactive menu
#   ./manage-services.sh run     [all|apps|db|ml|api|ui]
#   ./manage-services.sh stop    [all|apps|db|ml|api|ui|llm]
#   ./manage-services.sh restart [ ... ]
#   ./manage-services.sh status
#   ./manage-services.sh seed                 # reset db, regenerate data, retrain
#   ./manage-services.sh logs [ml|api|ui]
#
# "apps" = the three app layers only, Postgres and Ollama left alone.
# "stop llm" additionally stops the Ollama daemon (needs sudo); a plain stop
# just unloads the models so nothing is sitting on the GPU.

if [ -z "${BASH_VERSION:-}" ]; then
  echo "Run this with bash: bash $0" >&2
  exit 1
fi
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR"
RUN_DIR="$BASE_DIR/.vigil-run"
if ! mkdir -p "$RUN_DIR" 2>/dev/null; then
  echo "✗ Can't create $RUN_DIR — check you have write permission in $BASE_DIR" >&2
  exit 1
fi

ML_DIR="$BASE_DIR/services/ml-service"
API_DIR="$BASE_DIR/services/decision-api"
UI_DIR="$BASE_DIR/web"
GEN_DIR="$BASE_DIR/data/generator"

OLLAMA_HOST_URL="${OLLAMA_HOST_URL:-http://localhost:11434}"
GEN_MODEL="qwen2.5:3b-instruct-q4_K_M"
EMBED_MODEL="nomic-embed-text"

# decision-api has no mvnw, and a fresh shell often doesn't have Maven on PATH
# even when one is installed via the wrapper cache under ~/.m2 (that dir is
# only on PATH in shells that source the profile line that adds it). Find it
# ourselves rather than failing every command that shells out to `mvn`.
if ! command -v mvn >/dev/null 2>&1; then
  mvn_candidate=$(ls -d "$HOME"/.m2/wrapper/dists/apache-maven-*/*/bin/mvn 2>/dev/null | sort -V | tail -1)
  [ -n "$mvn_candidate" ] && export PATH="$(dirname "$mvn_candidate"):$PATH"
fi

c_g=$'\033[32m'; c_r=$'\033[31m'; c_y=$'\033[33m'; c_b=$'\033[36m'; c_0=$'\033[0m'
ok()   { echo "${c_g}✓${c_0} $*"; }
err()  { echo "${c_r}✗${c_0} $*"; }
warn() { echo "${c_y}!${c_0} $*"; }
info() { echo "${c_b}→${c_0} $*"; }

# ---------------------------------------------------------------- helpers ----

# NB: no `... | grep -q` anywhere in this script. `grep -q` exits on its first
# match, which SIGPIPEs the upstream command, and `set -o pipefail` then reports
# the whole pipeline as failed. It is a race, so it passes locally and fails on
# someone else's terminal. Read the output into a variable first, then match it.
port_in_use() {
  local listening
  listening=$(ss -ltn 2>/dev/null | awk '{print $4}')
  grep -qE "[.:]$1\$" <<< "$listening"
}
pid_alive()   { kill -0 "$1" 2>/dev/null; }

whoever_owns_port() { # $1=port -> pid or empty
  ss -ltnp 2>/dev/null | grep ":$1 " | grep -oP 'pid=\K[0-9]+' | head -1
}

wait_for_port() { # $1=port $2=timeout_secs $3=label
  local port=$1 timeout=$2 label=$3 waited=0
  while ! port_in_use "$port"; do
    sleep 1; waited=$((waited + 1))
    if [ "$waited" -ge "$timeout" ]; then
      err "$label didn't come up on port $port within ${timeout}s"
      return 1
    fi
  done
  ok "$label listening on port $port (${waited}s)"
}

wait_for_http() { # $1=url $2=timeout_secs $3=label — for services that bind before they're ready
  local url=$1 timeout=$2 label=$3 waited=0
  while ! curl -fsS -m 3 "$url" >/dev/null 2>&1; do
    sleep 2; waited=$((waited + 2))
    if [ "$waited" -ge "$timeout" ]; then
      err "$label never became healthy at $url within ${timeout}s"
      return 1
    fi
  done
  ok "$label healthy (${waited}s)"
}

check_prereqs() {
  local missing=()
  for cmd in docker node npm python3 java curl ss openssl; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done
  command -v javac >/dev/null 2>&1 || missing+=("javac (JDK, not just a JRE)")
  if [ "${#missing[@]}" -gt 0 ]; then
    err "missing required tools: ${missing[*]}"
    err "install: Docker, Node 20+, Python 3.12+, 'sudo apt install openjdk-21-jdk-headless', curl, iproute2"
    return 1
  fi
  command -v mvn >/dev/null 2>&1 || { err "'mvn' not on PATH — decision-api has no wrapper, a system/local Maven is required"; return 1; }
  local java_major
  java_major=$(java -version 2>&1 | head -1 | grep -oP '"\K[0-9]+' || echo 0)
  if [ "$java_major" -lt 21 ]; then
    err "Java $java_major found; decision-api needs 21+"
    return 1
  fi
}

load_env() {
  if [ ! -f "$BASE_DIR/.env" ]; then return 1; fi
  set -a
  # shellcheck disable=SC1091
  . "$BASE_DIR/.env"
  set +a
}

# ------------------------------------------------------------------ ollama ---

ollama_up() { curl -fsS -m 3 "$OLLAMA_HOST_URL/api/tags" >/dev/null 2>&1; }

# `systemctl cat` exits 0 when the unit exists and needs no pipe.
has_ollama_unit() { systemctl cat ollama.service >/dev/null 2>&1; }

ensure_ollama() {
  if ollama_up; then return 0; fi
  if ! command -v ollama >/dev/null 2>&1; then
    err "Ollama is not installed. Install it with:"
    err "  curl -fsSL https://ollama.com/install.sh | sh"
    return 1
  fi
  warn "Ollama is installed but not responding — trying to start it"
  if has_ollama_unit; then
    sudo systemctl start ollama 2>/dev/null || warn "couldn't start the ollama service (sudo needed?)"
  else
    setsid nohup ollama serve >"$RUN_DIR/ollama.log" 2>&1 </dev/null & disown
  fi
  local waited=0
  while ! ollama_up; do
    sleep 2; waited=$((waited + 2))
    [ "$waited" -ge 30 ] && { err "Ollama never came up at $OLLAMA_HOST_URL"; return 1; }
  done
  ok "Ollama responding at $OLLAMA_HOST_URL"
}

ensure_models() {
  local have missing=()
  have=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')
  for m in "$GEN_MODEL" "$EMBED_MODEL"; do
    grep -q "^${m%%:*}" <<< "$have" || missing+=("$m")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    for m in "${missing[@]}"; do
      info "pulling $m (this is a few GB, once)"
      ollama pull "$m" || { err "failed to pull $m"; return 1; }
    done
  fi
  ok "Ollama models present"
}

# Unloads every resident model so nothing holds VRAM. The daemon stays up: it
# costs nothing idle, and keeping it means the next start does not re-pull.
unload_models() {
  if ! ollama_up; then
    warn "Ollama not running — nothing loaded"
    return 0
  fi
  local loaded
  loaded=$(ollama ps 2>/dev/null | tail -n +2 | awk '{print $1}' | grep -v '^$')
  if [ -z "$loaded" ]; then
    ok "no models resident — GPU already clear"
  else
    while read -r m; do
      [ -z "$m" ] && continue
      ollama stop "$m" >/dev/null 2>&1 && ok "unloaded $m from memory"
    done <<< "$loaded"
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    sleep 2
    info "GPU now: $(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
  fi
}

stop_ollama_daemon() {
  unload_models

  if has_ollama_unit; then
    info "stopping the ollama service (sudo will prompt)"
    if sudo systemctl stop ollama; then
      ok "ollama service stopped"
    else
      err "couldn't stop the ollama service — try 'sudo systemctl stop ollama' by hand"
      return 1
    fi
    return 0
  fi

  local pid
  # The bracket keeps the pattern from matching this script's own command line,
  # which `pgrep -f` will happily do if the string appears in it.
  pid=$(pgrep -f '[o]llama serve' | head -1)
  if [ -z "$pid" ]; then
    warn "no 'ollama serve' process found — already stopped"
    return 0
  fi

  # Installed by the official script, the daemon runs as the `ollama` user, so
  # an unprivileged kill fails with EPERM. Try plainly, then escalate, and say
  # which of the two actually happened rather than claiming it was never there.
  if kill "$pid" 2>/dev/null; then
    ok "stopped ollama (pid $pid)"
  elif sudo kill "$pid" 2>/dev/null; then
    ok "stopped ollama (pid $pid, needed sudo)"
  else
    err "found ollama at pid $pid but could not stop it (runs as $(ps -o user= -p "$pid" 2>/dev/null | tr -d ' '))"
    err "try: sudo kill $pid"
    return 1
  fi
}

# -------------------------------------------------------------- postgres -----

ensure_docker() {
  docker info >/dev/null 2>&1 && return 0
  err "Docker daemon not reachable. Is Docker Desktop / the daemon running?"
  return 1
}

start_db() {
  ensure_docker || return 1
  load_env || { err "no .env yet — copy .env.example to .env and fill it in first"; return 1; }
  ( cd "$BASE_DIR" && docker compose up -d db >/dev/null 2>&1 ) || { err "docker compose failed to start db"; return 1; }
  local waited=0
  while true; do
    local status
    status=$(docker inspect --format='{{.State.Health.Status}}' vigil-db 2>/dev/null || echo starting)
    [ "$status" = "healthy" ] && break
    sleep 1; waited=$((waited + 1))
    [ "$waited" -ge 40 ] && { err "PostgreSQL never became healthy"; return 1; }
  done
  ok "PostgreSQL ready on ${POSTGRES_PORT:-5433} (${waited}s)"
}

stop_db() {
  ensure_docker || return 1
  ( cd "$BASE_DIR" && docker compose stop db >/dev/null 2>&1 )
  ok "stopped PostgreSQL (data volume preserved)"
}

# --------------------------------------------------------------- bootstrap ---

write_env() {
  [ -f "$BASE_DIR/.env" ] && return 0
  [ -f "$BASE_DIR/.env.example" ] || { err "no .env.example to copy from"; return 1; }
  sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 16)|" \
      -e "s|^VIGIL_JWT_SECRET=.*|VIGIL_JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')|" \
      -e "s|^VIGIL_DEMO_PASSWORD=.*|VIGIL_DEMO_PASSWORD=$(openssl rand -hex 12)|" \
      "$BASE_DIR/.env.example" > "$BASE_DIR/.env"
  chmod 600 "$BASE_DIR/.env"
  ok "generated $BASE_DIR/.env with fresh secrets (gitignored, mode 600)"
}

ensure_python_env() {
  [ -x "$ML_DIR/.venv/bin/python" ] && return 0
  info "creating the ml-service venv (first run, takes a minute)"
  ( cd "$ML_DIR" && python3 -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt )
  [ -x "$ML_DIR/.venv/bin/python" ] && ok "ml-service venv ready" || { err "venv creation failed"; return 1; }
}

ensure_node_modules() {
  [ -d "$UI_DIR/node_modules" ] && return 0
  info "installing frontend dependencies"
  ( cd "$UI_DIR" && npm install >/dev/null 2>&1 ) && ok "frontend dependencies installed"
}

bootstrap_first_time() {
  local fresh=0
  [ -f "$BASE_DIR/.env" ] || fresh=1
  [ -x "$ML_DIR/.venv/bin/python" ] || fresh=1
  [ -d "$UI_DIR/node_modules" ] || fresh=1
  [ "$fresh" = 1 ] || return 0

  echo
  info "first-time setup detected"
  write_env || return 1
  ensure_python_env || return 1
  ensure_node_modules
  echo
}

warn_if_no_data() {
  [ -f "$ML_DIR/artifacts/model.pkl" ] || {
    warn "no trained model at $ML_DIR/artifacts/model.pkl — decisions will fail"
    warn "run './manage-services.sh seed' (resets the db and retrains from fresh synthetic data)"
  }
}

# -------------------------------------------------------------- app layers ---

declare -A APP_DIR=(   [ml]="$ML_DIR"        [api]="$API_DIR"      [ui]="$UI_DIR" )
declare -A APP_PORT=(  [ml]=8001             [api]=8081            [ui]=5174 )
declare -A APP_LABEL=( [ml]="ml-service"     [api]="decision-api"  [ui]="Frontend" )
declare -A APP_HEALTH=(
  [ml]="http://localhost:8001/health"
  [api]="http://localhost:8081/actuator/health"
  [ui]="http://localhost:5174"
)
APP_ORDER=(ml api ui)   # order matters: decision-api calls ml-service, the web app calls decision-api

app_command() { # $1=key — echoes the command to exec, with env already exported
  case "$1" in
    ml)  echo ".venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001" ;;
    api) echo "mvn -o -q spring-boot:run" ;;
    ui)  echo "npm run dev -- --host 0.0.0.0 --port 5174" ;;
  esac
}

export_app_env() { # $1=key — the env each layer needs, derived from .env
  case "$1" in
    api)
      export SPRING_DATASOURCE_URL="jdbc:postgresql://localhost:${POSTGRES_PORT:-5433}/${POSTGRES_DB:-vigil}"
      export SPRING_DATASOURCE_USERNAME="${POSTGRES_USER:-vigil}"
      export SPRING_DATASOURCE_PASSWORD="${POSTGRES_PASSWORD:-}"
      export VIGIL_JWT_SECRET="${VIGIL_JWT_SECRET:-}"
      export VIGIL_JWT_TTL_MINUTES="${VIGIL_JWT_TTL_MINUTES:-60}"
      export VIGIL_ML_SERVICE_URL="http://localhost:8001"
      export VIGIL_ML_TIMEOUT_MS="${VIGIL_ML_TIMEOUT_MS:-150}"
      export VIGIL_DEMO_PASSWORD="${VIGIL_DEMO_PASSWORD:-}"
      export VIGIL_FLYWAY_LOCATION="filesystem:$BASE_DIR/db"
      export SERVER_PORT="${SERVER_PORT:-8081}"
      ;;
    # ml-service reads $BASE_DIR/.env itself (pydantic-settings env_file), and
    # the frontend's dev proxy is hardcoded in vite.config.js — neither needs
    # anything exported here.
  esac
}

preflight_app() { # $1=key
  case "$1" in
    ml)  ensure_python_env ;;
    ui)  ensure_node_modules ;;
    api) command -v mvn >/dev/null 2>&1 || { err "'mvn' not on PATH"; return 1; } ;;
  esac
  return 0
}

# Known failure signatures, so a wall of stack trace becomes one sentence.
diagnose_log() { # $1=key
  local log="$RUN_DIR/$1.log"
  [ -f "$log" ] || return 0

  if grep -qi "release version 21 not supported" "$log"; then
    err "only a JRE is installed — 'sudo apt install openjdk-21-jdk-headless'"
  fi
  if grep -qiE "password authentication failed|no password was provided" "$log"; then
    err "Postgres rejected the credentials — .env and the running container disagree."
    err "if you regenerated .env, the old volume still has the old password: 'docker compose down -v db' then start again"
  fi
  if grep -qi "Connection to localhost:${POSTGRES_PORT:-5433} refused" "$log"; then
    err "Postgres isn't up — './manage-services.sh run db' first"
  fi
  if grep -qiE "Address already in use|address already in use" "$log"; then
    err "${APP_LABEL[$1]}: port ${APP_PORT[$1]} is already bound — see './manage-services.sh status'"
  fi
  if grep -qi "model not loaded" "$log"; then
    err "no trained model — './manage-services.sh seed'"
  fi
  if grep -qiE "Connection refused.*11434|ollama request failed" "$log"; then
    err "can't reach Ollama at $OLLAMA_HOST_URL — 'systemctl start ollama'"
  fi
  if grep -qi "VIGIL_JWT_SECRET is not set" "$log"; then
    err "VIGIL_JWT_SECRET is missing from .env"
  fi
  return 0
}

start_app() { # $1=key
  local key=$1
  local dir=${APP_DIR[$key]} port=${APP_PORT[$key]} label=${APP_LABEL[$key]}
  local pidfile="$RUN_DIR/$key.pid" log="$RUN_DIR/$key.log"

  if [ -f "$pidfile" ] && pid_alive "$(cat "$pidfile")"; then
    ok "$label already running (pid $(cat "$pidfile"))"
    return 0
  fi

  preflight_app "$key" || return 1

  if port_in_use "$port"; then
    local owner_pid; owner_pid=$(whoever_owns_port "$port")
    warn "$label: port $port already in use (pid ${owner_pid:-unknown}), not tracked by this script"
    if [ -t 0 ] && [ -n "$owner_pid" ]; then
      read -rp "  Kill it and start $label anyway? [y/N] " ans
      if [[ "$ans" =~ ^[Yy]$ ]]; then kill "$owner_pid" 2>/dev/null; sleep 2
      else err "$label: skipped"; return 1; fi
    else
      err "$label: skipped (port busy, can't prompt)"; return 1
    fi
  fi

  info "starting $label..."
  # setsid makes the tracked pid a process-group leader, so stop_app can kill the
  # whole tree (maven's forked JVM, vite's child) rather than just the wrapper.
  ( cd "$dir" && export_app_env "$key" && exec setsid bash -c "$(app_command "$key")" ) >"$log" 2>&1 &
  echo $! > "$pidfile"

  local timeout=60
  [ "$key" = api ] && timeout=150   # maven resolves and compiles before it binds
  if ! wait_for_port "$port" "$timeout" "$label"; then
    tail -n 20 "$log" | sed 's/^/    /'
    diagnose_log "$key"
    return 1
  fi
  # Binding is not readiness: Spring binds early, and uvicorn is up before its
  # first DB round-trip. Confirm the health endpoint actually answers.
  wait_for_http "${APP_HEALTH[$key]}" 90 "$label" || {
    tail -n 20 "$log" | sed 's/^/    /'; diagnose_log "$key"; return 1; }
}

group_alive() { kill -0 -- "-$1" 2>/dev/null; }

stop_app() { # $1=key
  local key=$1
  local pidfile="$RUN_DIR/$key.pid" label=${APP_LABEL[$key]} port=${APP_PORT[$key]}
  local pid=""
  [ -f "$pidfile" ] && pid=$(cat "$pidfile")

  if [ -n "$pid" ] && { pid_alive "$pid" || group_alive "$pid"; }; then
    kill -TERM -- "-$pid" 2>/dev/null
    for _ in 1 2 3 4 5 6; do { pid_alive "$pid" || group_alive "$pid"; } || break; sleep 1; done
    { pid_alive "$pid" || group_alive "$pid"; } && kill -9 -- "-$pid" 2>/dev/null
    ok "stopped $label (pid $pid + its process group)"
    rm -f "$pidfile"
    return 0
  fi
  rm -f "$pidfile" 2>/dev/null

  if ! port_in_use "$port"; then
    warn "$label: not running (port $port free)"
    return 0
  fi

  local owner_pid; owner_pid=$(whoever_owns_port "$port")
  if [ -z "$owner_pid" ]; then
    err "$label: port $port in use but the owning pid isn't visible (permissions?) — leaving it"
    return 1
  fi
  warn "$label: not tracked by this script, but port $port is held by pid $owner_pid — stopping it"
  local pgid; pgid=$(ps -o pgid= -p "$owner_pid" 2>/dev/null | tr -d ' ')
  local target="$owner_pid"; [ -n "$pgid" ] && target="-$pgid"
  kill -TERM -- "$target" 2>/dev/null
  for _ in 1 2 3 4 5; do port_in_use "$port" || break; sleep 1; done
  port_in_use "$port" && { kill -9 -- "$target" 2>/dev/null; sleep 1; }
  port_in_use "$port" && { err "$label: port $port still held after killing $owner_pid"; return 1; }
  ok "stopped $label (untracked pid $owner_pid, port $port freed)"
}

# ------------------------------------------------------------ top-level ops --

resolve_scope() {
  local t="${1:-all}"
  case "$t" in
    all|"")      RESOLVED_SCOPE="all";    RESOLVED_KEYS=("${APP_ORDER[@]}") ;;
    apps)        RESOLVED_SCOPE="apps";   RESOLVED_KEYS=("${APP_ORDER[@]}") ;;
    db)          RESOLVED_SCOPE="db";     RESOLVED_KEYS=() ;;
    llm)         RESOLVED_SCOPE="llm";    RESOLVED_KEYS=() ;;
    ml|api|ui)   RESOLVED_SCOPE="single"; RESOLVED_KEYS=("$t") ;;
    *) return 1 ;;
  esac
}

do_start() {
  resolve_scope "${1:-all}" || { err "unknown target: $1"; return 1; }
  check_prereqs || return 1

  if [ "$RESOLVED_SCOPE" = "llm" ]; then
    ensure_ollama && ensure_models; return $?
  fi
  if [ "$RESOLVED_SCOPE" = "db" ]; then
    bootstrap_first_time; start_db; return $?
  fi

  if [ "$RESOLVED_SCOPE" = "all" ]; then
    bootstrap_first_time || return 1
    ensure_ollama || return 1
    ensure_models || return 1
    start_db || { err "Postgres failed to come up — aborting"; return 1; }
    warn_if_no_data
  else
    load_env || { err "no .env yet — run './manage-services.sh run all' first"; return 1; }
    port_in_use "${POSTGRES_PORT:-5433}" || warn "Postgres isn't up; the app layers depend on it"
    ollama_up || warn "Ollama isn't responding; narratives and the copilot will fail"
  fi

  for key in "${RESOLVED_KEYS[@]}"; do
    start_app "$key" || { err "${APP_LABEL[$key]} failed — fix the error above, then re-run"; return 1; }
  done

  echo
  ok "Frontend     http://localhost:5174"
  info "decision-api http://localhost:8081   ml-service http://localhost:8001/docs"
  info "Sign in as analyst / admin, password is VIGIL_DEMO_PASSWORD from .env"
}

do_stop() {
  resolve_scope "${1:-all}" || { err "unknown target: $1"; return 1; }

  if [ "$RESOLVED_SCOPE" = "llm" ]; then stop_ollama_daemon; return 0; fi
  if [ "$RESOLVED_SCOPE" = "db" ]; then stop_db; return 0; fi

  for ((i=${#RESOLVED_KEYS[@]}-1; i>=0; i--)); do stop_app "${RESOLVED_KEYS[$i]}"; done

  if [ "$RESOLVED_SCOPE" = "all" ]; then
    stop_db
    # Free the GPU. The daemon stays up because it costs nothing idle and
    # keeping it avoids re-pulling several GB next time.
    unload_models
    echo
    info "Ollama's daemon is still running with no model resident."
    info "To stop it entirely: ./manage-services.sh stop llm"
  fi
}

do_restart() { do_stop "${1:-all}"; sleep 2; do_start "${1:-all}"; }

do_seed() {
  [ -x "$BASE_DIR/scripts/seed_demo.sh" ] || { err "scripts/seed_demo.sh not found or not executable"; return 1; }
  check_prereqs || return 1
  ensure_ollama || return 1
  ensure_models || return 1
  ensure_python_env || return 1
  "$BASE_DIR/scripts/seed_demo.sh"
}

do_logs() {
  local key="${1:-}"
  if [ -z "$key" ]; then
    err "which log? ml | api | ui"
    return 1
  fi
  local log="$RUN_DIR/$key.log"
  [ -f "$log" ] || { err "no log at $log"; return 1; }
  tail -f "$log"
}

do_status() {
  echo "-- infrastructure --"
  ( cd "$BASE_DIR" && docker compose ps --format "table {{.Service}}\t{{.Status}}" 2>/dev/null ) | head -5
  if ollama_up; then
    local resident
    resident=$(ollama ps 2>/dev/null | tail -n +2 | awk '{print $1}' | paste -sd, -)
    if [ -n "$resident" ]; then
      ok "Ollama — up, resident: $resident"
    else
      ok "Ollama — up, no model resident (GPU clear)"
    fi
    command -v nvidia-smi >/dev/null 2>&1 && \
      info "GPU $(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
  else
    err "Ollama — not responding at $OLLAMA_HOST_URL"
  fi

  echo
  echo "-- app layers --"
  for key in "${APP_ORDER[@]}"; do
    local pidfile="$RUN_DIR/$key.pid" port=${APP_PORT[$key]} label=${APP_LABEL[$key]}
    if [ -f "$pidfile" ] && pid_alive "$(cat "$pidfile")"; then
      ok "$label — running (pid $(cat "$pidfile"), port $port)"
    elif port_in_use "$port"; then
      warn "$label — port $port in use, but not by a process this script started"
    else
      err "$label — not running"
    fi
  done

  echo
  echo "-- data --"
  [ -f "$ML_DIR/artifacts/model.pkl" ] && ok "trained model present" || err "no trained model — run 'seed'"
  [ -f "$BASE_DIR/data/generated/applications.csv" ] \
    && ok "synthetic population present ($(( $(wc -l < "$BASE_DIR/data/generated/applications.csv") - 1 )) applications)" \
    || err "no generated data — run 'seed'"
}

# --------------------------------------------------------------- entry point --

action="${1:-}"
target="${2:-}"

if [ -z "$action" ]; then
  echo "VIGIL local stack manager"
  select opt in "run" "restart" "stop" "status" "seed" "logs" "quit"; do
    [ -n "${opt:-}" ] && action="$opt" && break
  done
  echo
  case "$action" in
    run|start|restart|stop)
      echo "Target:"
      select t in \
        "everything (Postgres + Ollama + all three layers)" \
        "app layers only (leave Postgres and Ollama alone)" \
        "db   — PostgreSQL + pgvector (5433)" \
        "ml   — ml-service (8001)" \
        "api  — decision-api (8081)" \
        "ui   — Frontend (5174)" \
        "llm  — Ollama daemon" \
        "cancel"
      do
        case "$t" in
          "everything"*)      target="all";  break ;;
          "app layers only"*) target="apps"; break ;;
          "db   "*) target="db";  break ;;
          "ml   "*) target="ml";  break ;;
          "api  "*) target="api"; break ;;
          "ui   "*) target="ui";  break ;;
          "llm  "*) target="llm"; break ;;
          cancel) exit 0 ;;
          *) echo "invalid choice, try again" ;;
        esac
      done
      ;;
    logs)
      echo "Which log?"
      select t in "ml" "api" "ui" "cancel"; do
        [ "$t" = cancel ] && exit 0
        [ -n "${t:-}" ] && target="$t" && break
      done
      ;;
  esac
fi
target="${target:-all}"

case "$action" in
  run|start) do_start "$target" ;;
  restart)   do_restart "$target" ;;
  stop)      do_stop "$target" ;;
  status)    do_status ;;
  seed)      do_seed ;;
  logs)      do_logs "$target" ;;
  quit)      exit 0 ;;
  *)
    echo "Usage: $0 [run|restart|stop] [all|apps|db|ml|api|ui|llm]"
    echo "       $0 status | seed | logs [ml|api|ui]"
    exit 1
    ;;
esac
