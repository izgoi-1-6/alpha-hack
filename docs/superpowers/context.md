# Compact project context

**Where things stand (2026-10-26).**
- The user asked for a full-stack credit journey for small-business customers and a credit officer: React + TypeScript + Vite, FastAPI, PostgreSQL.
- The first plan (`plans/2026-10-24-credit-route.md`, Tasks 1–6) built the lifecycle: onboarding, recommendations, a six-stage questionnaire, scoring R1–R12, the officer review, documents, final approval and the Alfa-Business hand-off. Its Task 7 (a baseline-versus-guided comparison) was dropped by the user.
- The user's post-testing revision (`plans/2026-10-25-catalog-ux-revision.md`, Tasks 8–13) is complete:
  - products come from the bank's catalog plus a policy file, with eleven card products;
  - the product screen takes the amount only, on explained two-column cards;
  - purpose, term and pledge are chosen in the questionnaire;
  - the tax regime, staff and representative come read-only from the sources;
  - a mock Госуслуги authority check is needed to add a company;
  - an interactive client walkthrough;
  - no «демо»/«имитация» wording in the app;
  - seven end-to-end browser journeys, a verified Docker stack, a guarded reset script and hand-over docs.
- Next: one final whole-branch review, then hand-over to the user. No push, merge or deployment is authorized.

**Where to look.**
- Run, present and reset the app: [docs/demo.md](../demo.md).
- What is executed and what is assumed, with the known limitations: [docs/evidence.md](../evidence.md).
- The contract: the [design](specs/2026-10-24-credit-route-design.md), as amended by the revision plan's binding rule changes.
- The reasoning: [decisions](../decisions.md), with a table of rulings per task.
- Interfaces: [implementation](../api/implementation.md).
- The catalog and policy rules: [catalog](../catalog.md).

**Repository and workflow.**
- Source checkout: `/Users/ren1kron/Developer/hakatons/alpha-hack` on `main`.
- Active worktree: `.worktrees/credit-route-mvp` on branch `codex/credit-route-mvp` (original base `3e8e842`). The main checkout is unchanged apart from `.git/info/exclude` ignoring `.worktrees/`.
- Work is subagent-driven, one task at a time: implementer → reviewer → fix rounds, each increment committed.
- The SDD scratch (`.superpowers/sdd/<plan>/`, git-ignored) holds briefs, reports, reviews, raw test output and screenshots. Its `progress.md` ledger records every ruling.
- After a context reset, read the ledger, `git log` and the latest report; never redo a completed task.

**Runtime.**
- PostgreSQL runs in the compose container `credit-route-db-1` on 127.0.0.1:5432. It holds the development database `credit_route` and the disposable `credit_route_test`.
- The local API runs on :8000 and Vite on :5173.
- `docker compose up --build -d` runs the same app in containers on the same ports and the same database. Never pass `-v`.
- `scripts/reset-demo.sh` returns the development database to the seed.

**Provenance.**
- Original analyst research lives untracked under `drafts&notes/` in the source checkout. Do not modify it or commit it wholesale.
- The latest analyst artifact is `drafts&notes/credit-route_files/a_Sxsi.html`.
- `data/credit_catalog.json` is the user's `credit_catalog_updated.json` plus card texts. `data/catalog.research.json` keeps the nine archived research claims as history; the app never reads it.
- The scoring table comes from `scoring/alfa_scoring_simple.ipynb`:
  - business age 20/10/0 points;
  - revenue growth 25/15/0;
  - debt load 30/15/0;
  - credit history 25/10/0;
  - 75+ points is low risk, 50–74 medium, below 50 high.
- Rates, legal and program terms in the catalog are research claims, not verified bank policy. The policy file is local decision rules.

**Proof boundaries.** The evidence is technical: backend suites (SQLite and PostgreSQL), browser journeys against the real app, mutation checks and a container smoke test. No real user, conversion or revenue has been measured, and none may be claimed.
