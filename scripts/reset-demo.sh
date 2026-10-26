#!/usr/bin/env bash
# Resets the local database to the synthetic seed: alembic downgrade base, upgrade head, then the seed. Every user,
# company, application, consent and document record is deleted; the seeded accounts and their companies come back.
# Uploaded files in the document storage directory are not touched.
#
# Usage: scripts/reset-demo.sh [--yes] [--dry-run] [--force-remote]
#   --yes           confirm without the question (otherwise type "yes" when asked)
#   --dry-run       make every check, then print the steps instead of running them
#   --force-remote  allow a database host other than localhost, 127.0.0.1 or db, or one set in the URL's query
#
# Guards: DEMO_MODE must be true as the app reads it (unset counts as true, as in the app and setup.sh); the
# database host must be local unless --force-remote; the reset must be confirmed. The environment wins over .env,
# which only supplies what the environment leaves unset. Stop the API first and start it again afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."

confirmed=false
dry_run=false
force_remote=false
for argument in "$@"; do
  case "$argument" in
    --yes) confirmed=true ;;
    --dry-run) dry_run=true ;;
    --force-remote) force_remote=true ;;
    -h | --help)
      sed -n '2,13p' "$0" | sed -E 's/^# ?//'
      exit 0
      ;;
    *)
      echo "Unknown option: $argument (see --help)." >&2
      exit 2
      ;;
  esac
done

# .env supplies what the environment leaves unset: the same file setup.sh and run-api.sh read.
if [[ -f .env ]]; then
  env_pattern='^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$'
  while IFS= read -r env_line || [[ -n "$env_line" ]]; do
    [[ "$env_line" =~ $env_pattern ]] || continue
    env_key="${BASH_REMATCH[1]}"
    env_value="${BASH_REMATCH[2]}"
    if declare -p "$env_key" >/dev/null 2>&1; then continue; fi
    env_value="${env_value%\"}"
    env_value="${env_value#\"}"
    export "$env_key=$env_value"
  done <.env
fi

# 1. Only where the app itself seeds: DEMO_MODE=true (compared like app.config: case-insensitive, unset is true).
mode="$(printf '%s' "${DEMO_MODE-true}" | tr '[:upper:]' '[:lower:]')"
if [[ "$mode" != true ]]; then
  echo "Refusing to reset: DEMO_MODE is \"${DEMO_MODE-}\". The reset runs only with DEMO_MODE=true." >&2
  exit 1
fi

# 2. Only a local database, unless forced: the host of DATABASE_URL (the app's default when unset). libpq also takes a
# host from the query (host=, hostaddr=), and that one wins, so any such parameter counts as not local; so does a
# %-encoded parameter name, which SQLAlchemy decodes before libpq reads it.
url="${DATABASE_URL-postgresql+psycopg://credit_route:credit_route_local@localhost:5432/credit_route}"
authority="${url#*://}"
authority="${authority%%/*}"
authority="${authority##*@}"
if [[ "$authority" == \[* ]]; then
  host="${authority%%]*}"
  host="${host#[}"
else
  host="${authority%%:*}"
fi
query=""
if [[ "$url" == *\?* ]]; then query="${url#*\?}"; fi
query_host='(^|&)(host|hostaddr|[^&=]*%[^&=]*)='
if [[ "$query" =~ $query_host ]]; then host="${BASH_REMATCH[2]}= in the query"; fi
shown="$(printf '%s' "$url" | sed -E 's#(://[^:/@]*):[^@/]*@#\1:***@#')"
case "$host" in
  localhost | 127.0.0.1 | db) ;;
  *)
    if [[ "$force_remote" != true ]]; then
      echo "Refusing to reset: the database host \"$host\" is not local (localhost, 127.0.0.1 or db)." >&2
      echo "Pass --force-remote only for a disposable database." >&2
      exit 1
    fi
    echo "Warning: resetting a database on \"$host\" (--force-remote)." >&2
    ;;
esac

# 3. An explicit confirmation.
if [[ "$confirmed" != true ]]; then
  {
    echo "This deletes every user, company, application, consent and document record in"
    echo "  $shown"
    echo "and recreates the seeded accounts and companies. Uploaded files are kept."
    printf 'Type yes to continue: '
  } >&2
  answer=""
  read -r answer || true
  if [[ "$answer" != yes ]]; then
    echo "Cancelled: nothing was changed." >&2
    exit 1
  fi
fi

alembic=(backend/.venv/bin/alembic -c backend/alembic.ini)
if [[ "$dry_run" == true ]]; then
  echo "Dry run for $shown: nothing is changed. The reset would run:"
  echo "  1/3 ${alembic[*]} downgrade base"
  echo "  2/3 ${alembic[*]} upgrade head"
  echo "  3/3 PYTHONPATH=backend backend/.venv/bin/python -m app.seed"
  exit 0
fi
if [[ ! -x backend/.venv/bin/alembic ]]; then
  echo "backend/.venv is missing: run ./scripts/setup.sh first." >&2
  exit 1
fi

export DATABASE_URL="$url"
echo "Resetting $shown"
echo "1/3 Removing every table (alembic downgrade base)"
"${alembic[@]}" downgrade base
echo "2/3 Creating the schema (alembic upgrade head)"
"${alembic[@]}" upgrade head
echo "3/3 Loading the synthetic seed"
PYTHONPATH=backend backend/.venv/bin/python -m app.seed >/dev/null
counts="$(
  PYTHONPATH=backend backend/.venv/bin/python - <<'PY'
from sqlalchemy import func, select
from app.db import SessionLocal
from app.models import Company, User
with SessionLocal() as db:
    users = db.scalar(select(func.count()).select_from(User))
    companies = db.scalar(select(func.count()).select_from(Company))
print(f"{users} accounts and {companies} companies")
PY
)"
echo "Done: $counts. Start the API again if you stopped it."
