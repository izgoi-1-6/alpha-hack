# Кредитный маршрут

Russian-language synthetic SME financing demo: company onboarding, three explained financing choices, preliminary review, documents, officer final decision and simulated Alfa-Business handoff.

Approved stack: React + TypeScript + Vite, FastAPI, PostgreSQL. Application implementation is in progress; this commit establishes executable policy and synthetic data contracts. All bank/registry/BKI integrations and rates are demo assumptions.

- [Canonical design and API contract](docs/superpowers/specs/2026-10-24-credit-route-design.md)
- [Recorded demo decisions](docs/decisions.md)
- [Acceptance cases and evidence boundaries](docs/test-scenarios/acceptance.md)
- [Synthetic data and research archive](data/README.md)

`backend/` owns auth, company data, recommendations, applications, staff decisions, private documents and analytics. `frontend/` provides customer and officer journeys. `docs/` records contracts and executed evidence. Startup instructions follow with the runnable application; no runtime is claimed at this stage.
