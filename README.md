# Кредитный маршрут

A working credit-application app for small businesses (ИП and ООО) and a bank credit officer, built with React/TypeScript/Vite, FastAPI, SQLAlchemy/Alembic and PostgreSQL 17. All company and source data is synthetic, and every external service is a local mock: registry, turnover, ФНС/open sources, the credit bureau (BKI), Госуслуги, notifications, document checks and Alfa-Business. No real registry, bank, BKI, SMS, signing or payment call is ever made.

## What it does

- **Client**:
  - registers or signs in, and adds a company through a mock Госуслуги confirmation of their authority;
  - sees what the sources returned;
  - picks an amount and compares the bank's eleven catalog products on explained, ranked cards, with a personal estimate kept apart from each product's maximum;
  - fills a six-stage questionnaire (the tax regime, staff and representative come read-only from the sources) and submits it with explicit consents. The credit history is requested only after that;
  - follows the result: a preliminary approval, a specialist's review, an information request, waiting for a source, or a refusal;
  - uploads documents and is handed off to Alfa-Business once approved.
- **Credit officer**: works a queue, claims a case, reads the scoring factors and source evidence, asks the client for information, preliminarily approves within server-side bounds or refuses, reviews documents (verifying a pledge's value) and takes the final decision.
- **Walkthrough**: a nine-step interactive guide for a new client, from the first visit to the questionnaire. It can be skipped and restarted from «Как это работает».

Products come from the bank's catalog file plus a policy file, both validated at start-up and editable without code changes ([docs/catalog.md](docs/catalog.md)).

## Quick start

Requires Python 3.12, Node 24/npm and Docker.

```sh
cp .env.example .env
./scripts/setup.sh                 # venv, npm ci, PostgreSQL container, migrations, synthetic seed
./scripts/run-api.sh               # API on http://127.0.0.1:8000
npm run dev --prefix frontend      # UI on http://localhost:5173 (in another terminal)
```

Or run everything in containers: `docker compose up --build -d`, which serves the UI through nginx on http://localhost:5173. Open **http://localhost:5173** (the API only accepts commands from that exact origin).

Seeded accounts, all with the synthetic password `DemoCredit2026!`, have quick-login buttons on the login page:

| Account | Access |
|---|---|
| `client@demo.local` | Client with the ten synthetic fixture companies |
| `other@demo.local` | Client without companies |
| `officer@demo.local` | Credit officer (the only staff account; registration creates clients only) |

[docs/demo.md](docs/demo.md) has the start-up details, every fixture company with what it shows, catalog editing, resetting (`scripts/reset-demo.sh`) and a twelve-minute presentation script. [docs/evidence.md](docs/evidence.md) separates what was executed from what is assumed, and lists the known limitations.

## Verification

```sh
cd backend && .venv/bin/pytest && cd ..                      # isolated SQLite suite
docker compose exec -T db createdb -U credit_route credit_route_test   # once
TEST_DATABASE_URL=postgresql+psycopg://credit_route:credit_route_local@localhost:5432/credit_route_test \
  backend/.venv/bin/pytest -c backend/pytest.ini backend/tests          # PostgreSQL suite (+ race tests)
npm run build --prefix frontend                              # typecheck + production build
npm run test:e2e --prefix frontend                           # Playwright, with the API, Vite and seed running
PYTHONPATH=backend backend/.venv/bin/python -m app.products_config check   # catalog + policy validation
```

The PostgreSQL suite recreates the tables of its disposable `_test` database; never point it at useful data. Browser tests need installed Chrome (or `PLAYWRIGHT_BROWSER_CHANNEL=chromium` after `npx playwright install chromium`), create fresh synthetic clients in the development database, and include seven end-to-end journeys (`frontend/tests/journeys-*.spec.ts`).

## Further reading

- [Presentation and operations](docs/demo.md) · [Evidence and limitations](docs/evidence.md) · [Catalog and policy](docs/catalog.md)
- [Canonical design](docs/superpowers/specs/2026-10-24-credit-route-design.md) · [Decisions](docs/decisions.md) · [Implementation interfaces](docs/api/implementation.md) · [Acceptance scenarios](docs/test-scenarios/acceptance.md)

Uploaded files are stored privately under `var/documents` (git-ignored; `DOCUMENT_STORAGE_DIR` overrides it) and are served only through authorized API downloads. Sessions are server-side, HttpOnly, SameSite=Lax cookies that expire after 12 hours; `COOKIE_SECURE=false` is for localhost HTTP only. `DEMO_MODE=false` makes the seed refuse and hides the fixture list. Do not enter real personal or company data. The original notebooks and research under `scoring/` and `drafts&notes/` are provenance, not live product policy.
