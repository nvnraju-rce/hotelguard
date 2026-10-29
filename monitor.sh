#!/bin/sh
# Re-runs the checks on a schedule and saves each run to SQLite.
# HOTELGUARD_MODE=offline|live   HOTELGUARD_INTERVAL_HOURS=24   HOTELGUARD_LLM=ollama:llama3.1:8b (optional)
set -e
INTERVAL=$(( ${HOTELGUARD_INTERVAL_HOURS:-24} * 3600 ))
while true; do
  ARGS="--data data --out out"
  [ "${HOTELGUARD_MODE:-offline}" = "offline" ] && ARGS="$ARGS --offline"
  [ -n "${HOTELGUARD_LLM:-}" ] && ARGS="$ARGS --llm $HOTELGUARD_LLM"
  echo "[monitor] $(date -u +%FT%TZ) running: hotelguard.py $ARGS"
  python hotelguard.py $ARGS || echo "[monitor] run failed, will retry next cycle"
  sleep "$INTERVAL"
done
