#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env ]]; then set -a; source .env; set +a; fi
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock
npm ci --prefix frontend
docker compose up -d --wait db
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
if [[ "${DEMO_MODE:-true}" == true ]]; then PYTHONPATH=backend backend/.venv/bin/python -m app.seed; fi
