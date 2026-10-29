#!/bin/sh
# Prepares the database folder; seeds demo history on first start if HOTELGUARD_SEED_DEMO=1.
set -e
DB="${HOTELGUARD_DB:-/app/db/hotelguard.db}"
mkdir -p "$(dirname "$DB")" /app/out
if [ "${HOTELGUARD_SEED_DEMO:-0}" = "1" ] && [ ! -f "$DB" ]; then
  echo "[entrypoint] No database found, seeding demo history at $DB"
  python seed_demo.py
fi
exec "$@"
