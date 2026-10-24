# API

FastAPI / SQLAlchemy 2 / PostgreSQL 17. See the [root setup](../README.md) and [successor interfaces](../docs/api/implementation.md).

From the repository root, apply migrations with `backend/.venv/bin/alembic -c backend/alembic.ini upgrade head`, then start with `./scripts/run-api.sh`. OpenAPI lives at `http://127.0.0.1:8000/docs`. Mutations require `Origin: http://localhost:5173` even in integration drivers.

Run `.venv/bin/pytest` from this directory. Set `TEST_DATABASE_URL` to a disposable PostgreSQL database ending in `_test` for integration verification. Without it, tests use isolated SQLite memory databases. No live external services are called.
