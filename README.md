# Кредитный маршрут

Russian business-finance demo built with React/TypeScript/Vite, FastAPI, SQLAlchemy/Alembic and PostgreSQL 17. All company/source data is synthetic. No real registry, bank, BKI, SMS or payment calls are made.

The implemented vertical slice includes registration, session login/logout, role-separated demo access, persisted company onboarding, versioned consents, source results and idempotent source retry, plus the preliminary financing calculator: a versioned demo product catalog, explained ranking, an amount/term calculator with indicative payments and immutable saved recommendation snapshots (no BKI request, scoring or approval promise). The applications API is implemented on the backend: drafts from a saved snapshot, the six saved questionnaire stages, explicit consented submission, a local BKI simulator called only after consent, scoring with R1–R11 outcomes (preliminary approval, manual review, rejection, waiting for a source, information requests), retry, cancellation, lazy 14-day expiry and a status history with simulated in-app notifications. The customer application screens and the officer review queue with preliminary decisions are implemented in the UI. The document phase is implemented on the backend: the required-document checklist, private PDF/JPEG/PNG uploads with a structural demo check («Демонстрационная проверка документов», not antivirus scanning), replacement and deletion, officer document review with a verified collateral value, final approval within the verified bounds and a simulated Alfa-Business handoff link (no bank redirect, signing or disbursement); its screens are the next milestone.

Uploaded files are stored privately under `var/documents` (git-ignored; override with `DOCUMENT_STORAGE_DIR`) and are only available through authorized API downloads.

## Local development

Requires Python 3.12, Node 24/npm and Docker Compose. The defaults use loopback ports 5432 (PostgreSQL), 8000 (API) and 5173 (Vite).

```sh
cp .env.example .env
./scripts/setup.sh
./scripts/run-api.sh
# In another terminal:
npm run dev --prefix frontend
```

Open **http://localhost:5173** (the exact allowed UI Origin). Vite proxies `/api` to the API so browser requests remain same-origin. If you change the UI host/port, set `UI_ORIGIN` to that exact origin and restart the API. Run the setup script again safely: migrations and demo seed are idempotent. `.env` is read by the scripts; direct Python commands need those environment variables exported, or use the documented defaults.

The default `credit_route_session` cookie is HttpOnly, SameSite=Lax and expires after 12 hours. `COOKIE_SECURE=false` is permitted only for localhost HTTP development; use `true` with HTTPS. Local published database credentials are synthetic development defaults.

Demo accounts all use password `DemoCredit2026!`:

| Account | Access |
| --- | --- |
| `client@demo.local` | Client, nine seeded companies |
| `other@demo.local` | Separate client, initially no companies |
| `officer@demo.local` | Credit officer; client mutations forbidden |

You can also register a fresh client. Staff accounts only come from demo tooling. Seed IDs and synthetic whitelist INNs come from `data/demo-companies.json`. `DEMO_MODE=false` makes seed refuse to run and hides the fixture-picker endpoint; there is no reset endpoint. Do not enter real personal/company data into this prototype.

## Database and containers

```sh
docker compose up -d --wait db
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend backend/.venv/bin/python -m app.seed
# Optional full container stack (the web container proxies API requests):
docker compose up --build
```

The isolated `credit-route` Compose project has its own named volume. `docker compose down` stops it without deleting data; do not pass `-v` if you want to retain it. The API container applies migrations and seeds only when `DEMO_MODE=true`; the host development path does so in setup. No implicit table creation runs at API import/startup. Dockerfiles are supplied; the verified development baseline uses host Python/Vite and the PostgreSQL container.

## Verification

```sh
# Fast isolated adapter suite
cd backend
.venv/bin/pytest
cd ..
# Disposable PostgreSQL integration DB only; name must end in _test
# Run createdb once:
docker compose exec -T db createdb -U credit_route credit_route_test
TEST_DATABASE_URL=postgresql+psycopg://credit_route:credit_route_local@localhost:5432/credit_route_test backend/.venv/bin/pytest -c backend/pytest.ini backend/tests
npm run typecheck --prefix frontend
npm run build --prefix frontend
# With the local API, Vite and demo seed running; Chrome installed:
npm run test:e2e --prefix frontend
# Or PLAYWRIGHT_BROWSER_CHANNEL=chromium after npx playwright install chromium
```

The PostgreSQL test suite recreates tables in its disposable `_test` database. Never point it at a database containing useful data. Browser tests create synthetic test clients in the development database. The UI uses local system fonts and no external resources. See [implementation interfaces](docs/api/implementation.md), [canonical design](docs/superpowers/specs/2026-10-24-credit-route-design.md) and [acceptance scenarios](docs/test-scenarios/acceptance.md).

Original notebooks and research under `scoring/` and `drafts&notes/` remain provenance, not live product policy.
