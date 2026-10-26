# Credit Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax. Read only your extracted task brief, the spec, and relevant existing code.

**Goal:** A polished Russian-language full-stack SME financing demo, from company onboarding through explained recommendations, preliminary approval, documents, officer final decision, and simulated Alfa-Business handoff.

**Architecture:** React/TypeScript/Vite browser app; a modular FastAPI backend; PostgreSQL with SQLAlchemy and Alembic. One backend owns rules, authorization, state transitions, and audit history. Docker Compose is the reproducible delivery baseline.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg, pytest; Node 24, React, TypeScript, Vite, React Router, lucide-react, Playwright; PostgreSQL 17. Resolve and lock compatible current dependency versions. Prefer plain CSS with shared design tokens over adding a UI framework.

**Spec:** `docs/superpowers/specs/2026-10-24-credit-route-design.md` (produced by Task 1 from the approved roadmap and research).

## Global Constraints

- Russian interface; English code identifiers. Product branding: «Кредитный маршрут», understated red accent, dark navigation, warm neutral canvas, clear typography, generous whitespace, responsive desktop/mobile layouts. Avoid a generic starter-page appearance.
- Exactly three products accept applications: `alfa_term_loan_unsecured`, `alfa_revolving_line_unsecured`, `alfa_term_loan_secured`. Other research catalog products are informational and cannot submit applications.
- Support synthetic ИП and ООО profiles. Public registration always creates CLIENT; CREDIT_OFFICER accounts come only from seed tooling.
- All registry, turnover, BKI, notifications and Alfa-Business integrations are mocks, labeled in the UI. No real SMS, real PII, bank access, signing or disbursement.
- No BKI calls before explicit submission consent; preliminary estimates never promise approval. Product maximum, personal indicative limit, preapproved amount and final amount are distinct.
- Use server-owned opaque session cookies (HttpOnly, SameSite=Lax), password hashing, session expiry/logout, same-origin UI/API via proxy, and Origin checking on authenticated mutations. No auth tokens in localStorage.
- Money is integer RUB or Decimal, never binary float in persisted business calculations. Store UTC timestamps and catalog/rule snapshot versions.
- Resource ownership and staff role checks are enforced server-side. Idempotent submission and officer decisions; optimistic versions for edits/decisions; one active submitted application per company/product.
- Files are private, limited to PDF/JPEG/PNG up to 20 MiB, content checked, stored outside webroot, and available only through authorized API downloads. A demo uploader is not production malware scanning.
- The user authorized continuous implementation of all seven milestones and subagent reviews, without milestone confirmation prompts. Record reversible design rulings and keep going.
- No push, merge, deployment or external messages. Preserve original research. Work on the feature worktree branch, commit each reviewed increment.

## Review Focus

1. Unknown collateral/finance looks like a promise: Task 3 tests unknown inputs and estimates.
2. Cross-customer or cross-role access: Tasks 2, 5, 6 test every relevant resource class.
3. Replayed commands or competing officers duplicate work: Tasks 4–6 test idempotency, versions and transaction guards.
4. Invalid/stale documents or expired preliminary approval allow final approval: Task 6 tests completeness, review and expiry.
5. Comparison analytics invent proof or leak data: Task 7 tests event validation, cohort isolation and measured versus modeled output.

## File boundaries

`backend/app/`: `main.py`, `config.py`, `db.py`; business modules `identity/`, `companies/`, `recommendations/`, `applications/`, `officer/`, `documents/`, `analytics/`, each with focused schemas, service and routes as needed. Shared ORM models can start in `models.py` and be split by domain if they grow. `backend/tests/` mirrors these domains. `frontend/src/`: `app/`, `components/`, `lib/`, and feature folders mirroring the journeys. `data/` contains only curated synthetic fixtures and research/demo catalogs. `docs/` stores canonical contracts and evidence, not duplicated application code.

### Task 1: Canonical specification, demo policy, and fixtures

**Files:** Create the Spec above, `docs/decisions.md`, `docs/test-scenarios/acceptance.md`, `data/demo-products.json`, `data/demo-companies.json`, `data/catalog.research.json`; update existing README placeholders where useful.

**Interfaces:** Produce exact entity fields, enums, API contracts, demo product configuration, fixture identities and acceptance cases consumed by Tasks 2–7. These decisions belong in the spec and JSON, not in downstream guesses.

- [ ] Read `docs/superpowers/context.md`, original analyst HTML, relevant original catalog, notebook and fixture README. Preserve sources, cite their paths and clearly flag demo assumptions.
- [ ] Write a compact decision-complete spec including auth, company data, three product parameters/purposes/limits/ranking, six questionnaire stages, two-stage credit lifecycle, staff actions, required documents, expiry and analytics. Use original R1–R12 score factors; adapt outcomes to preliminary approval instead of final OFFERED. Known missing data or unavailable mock services must have explicit recoverable outcomes.
- [ ] Choose and record bounded demo parameters for revolving and secured products. Use turnover capacity for every personal limit; unknown collateral gives needs_info and no confirmed secured limit. Collateral value is client-declared until officer review. Rates are explicitly demo rates. Ranking considers purpose, funding pattern and amount before indicative price.
- [ ] Define states `DRAFT`, `CHECKING`, `WAIT_EXTERNAL`, `MANUAL_REVIEW`, `NEED_INFO`, `PREAPPROVED`, `DOCS_UPLOADED`, `DOCS_REWORK`, `APPROVED`, `REJECTED`, `CANCELLED`, `EXPIRED`. PREAPPROVED expires after 14 days. Need-info answers resume the same application and return to review; no arbitrary status PATCH.
- [ ] Create at least six synthetic company scenarios (strong, medium risk, poor fit/high risk, inactive, missing turnover, registry unavailable), including checksum-valid 10/12 digit INNs generated for mocks. Freeze business fixture reference date for repeatable test cases while normal app time remains current/injectable.
- [ ] Map old fixture expectations to the new lifecycle; identify real integration tests versus self-consistency oracle checks. Define evidence scenarios in which a held-out answer key predates recommendation outcomes.
- [ ] Validate JSON, identifier consistency, INN checksums, all boundary examples, and document completeness using a small temporary verification script; report the command/results. Commit.

### Task 2: Running app, authentication, and company onboarding

**Files:** Create backend project/config/db/models, identity and companies modules, migrations, focused tests; frontend shell/components/lib/api and identity/company features; Dockerfiles, `compose.yaml`, `.env.example`, `.gitignore`, startup/seed scripts and README instructions.

**Interfaces:** Implement spec's `/api/v1/auth/register`, `/login`, `/logout`, `/me`, `/companies` and company/precheck reads. Produce reusable `get_current_user`, `require_officer`, scoped company access, injectable clock, DB transactions, standardized API errors and frontend API client; document exact signatures for successors in `docs/api/implementation.md`.

- [ ] Add failing tests for registration/login/logout, staff-role injection, cross-user access, valid/invalid INNs, inactive company, missing/unavailable registry, refresh persistence and required onboarding consent.
- [ ] Implement PostgreSQL-backed auth/company lifecycle with idempotent seed command and Alembic initial migration. SQLite may be a fast test adapter but PostgreSQL is the integration baseline.
- [ ] Build polished responsive login/register, persistent shell/navigation, company onboarding and precheck results. Include seeded demo login affordances and fixture picker, clear simulation label, accessible fields/loading/errors. Use local resources; no remote font dependency.
- [ ] Run targeted tests, complete backend suite, TypeScript check and production frontend build. Verify Docker Compose config and available runtime startup. Record exact commands and infrastructure limits. Commit.

### Task 3: Recommendations and interactive amount calculator

**Files:** recommendations module/tests, catalog loading, frontend recommendation feature; extend shared API contract and migrations if needed.

**Interfaces:** `GET /api/v1/catalog`; owned company recommendation endpoint following spec, saved recommendation snapshot identifier consumed by application creation. Pure recommendation service consumes company+need+versioned policies and returns checks, status, ranked items, personal limit and reasons.

- [ ] Add failing tests for purpose/funding pattern matching, amount below/at/above limit, unknown turnover/collateral, inactive company, research-only items, deterministic ties, preserved snapshots and zero BKI calls.
- [ ] Implement server recommendations and saved versioned snapshots with the spec's demo rules. Research catalog entries are informational. Explain unknown prerequisites; founder ownership is not guarantor consent.
- [ ] Build purpose/funding-pattern controls, amount input and accessible slider, ranked cards, indicative payment with its assumptions, criteria explanations and useful alternatives. Basic-catalog mode can be introduced here as the later experiment baseline.
- [ ] Verify meaningful unit/API tests plus frontend type/build; add a browser recommendation check when Playwright setup is available. Commit.

### Task 4: Saved questionnaire, submission, scoring and customer status

**Files:** applications module/schemas/scoring/service/routes/tests, migration, customer applications/dialog/history frontend.

**Interfaces:** spec's create/list/detail, answers PATCH, explicit submit, retry-check, cancel and history endpoints. Staff tasks consume persisted `Application`, `Evaluation`, `StatusHistory`, `Consent` and revision fields. Reuse recommendation snapshot and ownership helper.

- [ ] Add failing tests for saved/revised answers, required fields/consent, informational-product refusal, score thresholds, terminal stop factors, request above capacity, unavailable BKI, retry recovery, duplicate active application, replayed submission and stale versions.
- [ ] Implement the six guided stages, snapshot validation and transactionally guarded state machine. BKI mock is called only after submit with current consent. Low risk can PREAPPROVE, medium risk goes to MANUAL_REVIEW, hard failure rejects; no final approval before documents/officer.
- [ ] Build resumable guided application UI, saved progress, editable review, unchecked submission consent, My Applications, timeline, retry and cancel actions. Supported unknown collateral must be supplied before secured submission.
- [ ] Verify backend tests, frontend type/build and persistence through reload; record examples of actual API outcomes. Commit.

### Task 5: Officer review queue and preliminary decisions

**Files:** officer module/tests, staff UI queue/detail/evidence/decision components and migration if required.

**Interfaces:** `/api/v1/officer/applications` and detail, claim, request-info, preapprove, reject commands defined by spec; existing application history/actions appear in customer views. Decisions require current version and assigned officer, with nonempty reasons.

- [ ] Add failing tests for customer/staff permissions, competing assignment, stale decision, repeated idempotent decisions, amount bounds, required reasons, need-info response and return to the same officer case.
- [ ] Implement evidence review and guarded commands, record reasons/actor/time in history, enforce one assignee with DB conditional updates or locks, and avoid trusting arbitrary client-selected statuses.
- [ ] Build officer queue filters and evidence view with score factors, source status, amount difference and actionable decision controls. Customer can respond to an information request and track its resolution.
- [ ] Run focused/full backend tests and frontend type/build; exercise a medium-risk manual approval and a rejection. Commit.

### Task 6: Documents, officer final approval, expiry and demo handoff

**Files:** documents module/storage/tests, customer upload/replacement frontend, officer document review and final decision frontend, handoff page and migration.

**Interfaces:** spec's checklist/upload/download/delete/complete endpoints; officer accept/reject-document and final approve/reject commands; approved-only `/api/v1/integrations/alfa-business/link` returning local demo URL. Record all business transitions through existing service.

- [ ] Add failing tests for preapproval gating, ownership/download access, file size/type/content/path safety, partial checklist, rejected file replacement, no final approval with unaccepted documents, revisions, expiry and idempotent final decisions.
- [ ] Implement private file storage with cleanup on failed transactions, required checklist rules, secure downloads and explicit simulated verification labeling. Reject active/HTML disguised files. No claim of production antivirus scanning.
- [ ] Build uploads with per-document feedback/progress, officer document inspection and reasons, final decision controls and customer outcome/handoff. Enforce expiry on reads/actions using injectable clock; accepted evidence cannot be silently replaced after final approval.
- [ ] Verify complete customer→officer→document correction→approval journey with backend integration tests and browser checks. Commit.

### Task 7: Measured comparison, end-to-end evidence and demo handoff

> **Superseded by [`2026-10-25-catalog-ux-revision.md`](2026-10-25-catalog-ux-revision.md).** The comparison and analytics work is dropped by user decision (that plan's line 15); the end-to-end evidence, start-up tooling and hand-over docs became its Task 13.

**Files:** analytics module/tests and frontend evidence/comparison feature, `frontend/e2e/`, Playwright config, demo reset/start tooling, `docs/demo.md`, `docs/evidence.md`, README and final context summary.

**Interfaces:** validated first-party event endpoint and officer-only aggregate summary; identical fixture/product data for baseline versus guided modes; explicit experiment mode/cohort and event timestamps. Business impact calculation is a separate transparent scenario model.

- [ ] Define and test event allowlist/payload limits, ownership, server timestamps, cohort attribution and empty/no-evidence results. Separate recommendation from held-out expected product/choice criteria; never report seeded or automated runs as real user study results.
- [ ] Implement comparison tasks with baseline catalog and guided recommendations, capture selection time and correctness against predeclared expectations, completion and abandonment where observable. Show counts/denominators and simulation flags. Add editable business assumptions with visible formula rather than claimed revenue uplift.
- [ ] Add Playwright tests running against real app/backend for strong approval, medium-risk officer flow, rejection, missing data/recovery, document replacement and cross-role access. Run them and record genuine results. Run full backend suite, frontend type/build and PostgreSQL integration checks.
- [ ] Provide repeatable Docker startup, local-development instructions, explicit demo-only reset guard/confirmation, demo credentials, fixture list and short presentation script. Review responsive screenshots and fix obvious visual/accessibility defects within this task.
- [ ] Produce evidence report separating executed technical checks, scenario simulation, real user observations (none unless provided) and modeled business impact. Preserve unresolved external product/risk/legal prerequisites as future work, not as implemented features. Commit.
