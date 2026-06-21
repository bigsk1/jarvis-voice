#!/usr/bin/env bash
set -Eeuo pipefail

cd /app

mode="${JARVIS_MODE:-cloud}"
if [ "$mode" = "local" ]; then
  set -a
  # shellcheck disable=SC1091
  source config/local.env
  set +a
  export LLM_PROVIDER=ollama
else
  set -a
  # shellcheck disable=SC1091
  source config/cloud.env
  set +a
  export LLM_PROVIDER="${LLM_PROVIDER:-anthropic}"
fi

echo "$mode" > logs/services_mode

pids=()

start_daemon() {
  local name="$1"
  local script="$2"
  local log_file="logs/${name}.log"
  local pid_file="logs/${name}.pid"

  echo "Starting ${name}..."
  python -u "$script" >> "$log_file" 2>&1 &
  local pid=$!
  pids+=("$pid")
  echo "$pid" > "$pid_file"
}

stop_all() {
  echo "Stopping Jarvis background services..."
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}

trap stop_all TERM INT EXIT

start_daemon follow_up_daemon services/follow_up_daemon.py
sleep 1
start_daemon reminder_scheduler services/reminder_scheduler.py
sleep 1
start_daemon scheduled_task_runner services/scheduled_task_runner.py
sleep 1
start_daemon self_healing_daemon services/self_healing_daemon.py

echo "Jarvis background services are running in foreground mode."
wait -n "${pids[@]}"
