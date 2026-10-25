# Credit Route Revision Plan — catalog-driven products and simpler client UX

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Read only your extracted task brief, the spec sections it names, this plan's Global Constraints and Binding rule changes, and the code you touch.

**Goal:** Apply the user's post-testing revision to the working app (Tasks 1–6 of `2026-10-24-credit-route.md` are complete):
- loan products driven by the user's catalog JSON plus a demo policy file, with all catalog products available;
- an amount-only product-choice screen with a large slider and explained cards in two columns;
- other parameters chosen in the questionnaire;
- tax regime and employee count from open sources (read-only);
- a mock Госуслуги authority check when adding a company;
- an interactive client walkthrough;
- no "демо"/"имитация" wording in the app;
- end-to-end evidence and hand-over docs.

The comparison/analytics work of the old Task 7 is dropped by user decision.

**Architecture:** unchanged (React/TS/Vite; FastAPI + SQLAlchemy/Alembic; PostgreSQL 17; Docker Compose). A new config layer loads `data/credit_catalog.json` (product facts) and `data/demo-policy.json` (demo decision rules), validates both at startup and exposes one runtime `Product` model to every consumer.

**Spec:** `docs/superpowers/specs/2026-10-24-credit-route-design.md` (demo-spec-v1). Where it conflicts with this plan's "Binding rule changes", this plan wins; each task updates the spec sections it changes.

## Global Constraints

- Russian interface; English code identifiers. Branding «Кредитный маршрут» and the existing visual system (`.superpowers/sdd/2026-10-24-credit-route/ui-reference.md`). Responsive desktop and mobile; no horizontal page overflow at 360–1440 px; text ≥12 px; 44 px targets; visible focus; aria-live for results; NBSP money.
- Synthetic ИП and ООО profiles only. Public registration always creates CLIENT; CREDIT_OFFICER accounts come only from seed tooling.
- Registry, turnover, ФНС/open sources, BKI, Госуслуги, notifications, document checks and Alfa-Business remain local mocks: no real external calls, real PII, SMS, bank access, signing or disbursement. The UI no longer labels them as demo/simulation (user decision).
- No BKI calls before explicit submission consent; preliminary estimates never promise approval. Product maximum, personal indicative limit, preapproved amount and final amount are distinct.
- Server-owned opaque session cookies (HttpOnly, SameSite=Lax), password hashing, session expiry/logout, same-origin UI/API via proxy, Origin checking on authenticated mutations. No auth tokens in localStorage (a walkthrough-seen flag in localStorage is allowed).
- Money is integer RUB or Decimal, never binary float in persisted business calculations. UTC timestamps; catalog/rule versions stamped on snapshots and applications.
- Ownership and staff role checks are server-side. Idempotent commands; optimistic versions; one active submitted application per company/product.
- Files are private, PDF/JPEG/PNG up to 20 MiB, content checked, stored outside webroot, downloaded only through authorized API. The PDF/image validation code is frozen by user decision (do not change it; if it blocks a legitimate case, stop and report — the user may choose to mock parsing).
- The user authorized continuous implementation and subagent reviews. Record reversible design rulings and keep going.
- No push, merge, deployment or external messages. Preserve original research (`drafts&notes/`, `data/catalog.research.json`). Work on branch `codex/credit-route-mvp` in the worktree; commit each reviewed increment.

## Binding rule changes (supersede spec v1 where they conflict)

1. **Products.** Every catalog item with kind `product` or `gov_program`, status `active`, limit_status `open` and `display.as=card` accepts applications, subject to eligibility. `overlay` items render as badges only. The «Исследовательский каталог» and `research_items` disappear from the API and UI. `data/catalog.research.json` stays as history only.
2. **Catalog authority.** The catalog is authoritative for amounts, terms, rates, purposes and eligibility. The demo policy only supplies decision rules and fallbacks for nulls, and may only tighten the catalog, never weaken it (e.g. `collateral.required: true` cannot become optional).
3. **Eligibility.** Only machine-checkable rules apply:
   - entity type (ИП→IP, ЮЛ→LLC);
   - `msp_registry_required` against the company's registry flag;
   - `regions_allow` against the company's region (normalised);
   - `okved_deny_main` entries whose text starts with a code `NN` or range `NN–NN`, compared on the main OKVED 2-digit class.

   Unparseable OKVED text, `categories` and `requirements` are informational: shown on the card, never blocking, never forcing review.
4. **Need.** The need is `{requested_amount_rub}` only. Purpose, term and collateral are chosen in questionnaire stage 2 within the chosen product's bounds. `funding_pattern` is removed everywhere.
5. **Source-owned fields.** `tax_regime` and `employees` come from the mock open sources (registry payload), are prefilled and read-only, cannot be set through answers PATCH, and are not officer-requestable.
6. **Authority check.** A mock Госуслуги verification for (user, ИНН) is required to add a company; the mock always confirms. Several users may still add the same ИНН (a real ЕСИА would refuse non-representatives). Stage-5 `representative_name` and `representative_authority_confirmed` come from the verification and are read-only. Submission re-checks that the company has a verification.
7. **Wording.** No «демо», «демонстрац…» or «имитац…» in UI copy or server-sent Russian texts (labels, notices, notifications, errors). Fixture company names lose «Демо»; «Демо-регион» becomes real region names. Technical names stay: `DEMO_MODE`, `@demo.local` emails, file names.
8. **Walkthrough.** An interactive client walkthrough starts automatically on a client's first visit, can be skipped, and can be restarted from «Как это работает».

## Config design

### Catalog file
- `data/credit_catalog.json` is a copy of `/Users/ren1kron/Developer/hakatons/alpha-hack/credit_catalog_updated.json` (schema 3.1, catalog_version 2026-10-25) with these additions:
  - schema becomes `3.2` and `catalog_version` is bumped (e.g. `2026-10-25.1`);
  - per-item `display.summary` (what the loan is), `display.features[]` (3–5 bullets) and `display.best_for` (who it suits). This copy is drafted only from the item's own facts and adds no claims;
  - `amount.max_unsecured` (universal limit: 20 000 000 without collateral);
  - `term.max_months_by_purpose` (`alfa_goscredit_zont`: working_capital 36).
- The path can be overridden with env `CREDIT_CATALOG_PATH`.

### Rates
- `rate_formula` is computed from `params.key_rate.value_percent` by a tiny safe parser: `KEY_RATE`, `KEY_RATE ± number` or a number, with no eval. The result must equal the file's `rate_percent`, otherwise config validation fails.
- `undisclosed` means no payment estimate («Ставка уточняется»).
- A rate defined only for a preferential period (`to_month` set) gives a payment labelled «в льготный период N мес.»; rate certainty is then `preferential`.

### Policy file
`data/demo-policy.json` has `rules_version` `demo-rules-v2`. It holds:
- the entity-type map;
- applyable kinds;
- defaults:
  - amount_min_rub 300 000;
  - amount_max_rub_if_null 2 000 000 000;
  - term_min_months 6 and term_max_months 36;
  - low/medium revenue multiples 3/1;
  - medium cap 1 000 000;
  - LTV 7000 bps;
  - base_documents [BANK_STATEMENT, FINANCIAL_REPORT];
  - collateral_documents [COLLATERAL_OWNERSHIP, COLLATERAL_VALUATION];
- payment model per instrument_type: term_loan and nonrevolving_credit_line → annuity; revolving_credit_line → interest at full utilization; factoring → none;
- per-product overrides: collateral_mode, fallback terms, priority;
- the ranking table: collateral burden none 0 / optional 0 / required 1; rate certainty full 0 / preferential 1 / undisclosed 2;
- the amount slider: log scale, min 300 000, max 2 000 000 000, default 2 000 000, snapping, presets;
- the OKVED parse rule;
- the overlay badge rule: `applies_to` + MSP registry + main OKVED not denied; softer text on collateral-required cards;
- region normalisation.

### Effective terms
`*` marks a policy fallback.

| Product | Amount (₽) | Term (months) | Collateral |
|---|---|---|---|
| alfa_term_loan_unsecured | 300k–30M | 12–60 | none |
| alfa_term_loan_secured | 500k–150M | 12–120 | required |
| alfa_revolving_line_unsecured | 300k–30M | no term (show catalog note) | none |
| alfa_revolving_line_secured | 500k–60M | 6–60 | required |
| alfa_nonrevolving_line_secured | 500k–60M | 6–60 | required |
| alfa_goscredit_zont | 300k*–50M | 6*–60; working capital ≤36 | none |
| alfa_universal_limit | 300k*–70M; 20M unsecured | 6*–120 | optional |
| alfa_factoring | 300k*–2B*, turnover-bounded | 1*–12 (deferral) | none |
| psk_invest_subsidy | 25M–2B | 6*–120 | optional* |
| psk_working_capital | 500k–500M | 6*–36* | optional* |
| psk_borderline | 300k*–30M | 6*–36* | none |

Personal limit: `min(effective max, turnover limit T, secured ? unsecured cap + ⌊LTV·V⌋ : unsecured cap)`.
- The unsecured cap is 0 when collateral is required, `max_unsecured` for the universal limit, and the effective max otherwise.
- T is low `min(max, 3R)` and medium `min(max, 1 000 000, R)`; high risk gives null.

### Pinned per application
At submit, the application pins:
- `secured` (mode required, or optional with declared collateral);
- `required_documents` (base, plus the collateral documents when secured);
- the effective product terms.

Documents, the officer's `final_terms`, requestable fields and R5 read the pinned values, never a product-level flag.

### Loading and validation
- `backend/app/products_config.py` provides a pure `load_config(catalog_path, policy_path)` that collects every error with its path (e.g. `items[alfa_factoring].amount.max: null, no policy fallback`).
- Module-level loading happens at startup; tests call `load_config` directly.
- `python -m app.products_config check [--catalog P] [--policy P]` validates edits.
- Stamped versions are `catalog_version+sha8(catalog bytes)` and `rules_version+sha8(policy bytes)`, so any edit makes old drafts 409 RECOMMENDATION_STALE.
- Validation rules:
  - known enum values and product ids;
  - document types in the existing 4;
  - each formula result equals its `rate_percent`;
  - the policy only tightens the catalog;
  - every applyable item has its explanation texts;
  - every overlay `applies_to` id exists;
  - the slider reaches every product minimum.

## Review Focus

1. Config edits really change behaviour, and bad config fails fast with a useful message (Task 8).
2. No consumer still reads product-level `collateral_required`/`required_documents` or assumes three products (Tasks 8–9).
3. Oracles stay independent of production helpers (Tasks 8–9).
4. The authority gate cannot be bypassed by a direct API call, and source-owned fields cannot be set by the client (Task 10).
5. No «демо»/«имитация» text remains; no regression in accessibility or layout (Tasks 11–13).

### Task 8: Config-driven catalog, eligibility and amount-only recommendations (backend)

**Files:**
- `data/credit_catalog.json`, `data/demo-policy.json`;
- `backend/app/products_config.py` (+ CLI);
- `backend/app/recommendations/{catalog.py,service.py,schemas.py,router.py}`, `backend/app/applications/products.py` (consume the runtime model);
- `data/demo-companies.json`, `backend/app/companies.py`, `backend/app/seed.py`, `backend/app/models.py`, plus a migration (Company `msp_registry`, registry fields);
- tests and oracle;
- `docs/catalog.md`;
- the spec "Product policy and recommendations" section, `data/README.md`, `docs/decisions.md`.

**Interfaces:**
- `GET /api/v1/catalog` returns `{catalog_version, rules_version, key_rate, amount_slider, products:[runtime product incl. display texts, effective terms, rate certainty, payment model, collateral mode, conditions_to_confirm, eligibility summary], overlays:[…]}`. `research_items` is removed.
- `POST /companies/{id}/recommendations` takes `{requested_amount_rub}`. Items gain `badges[]` and `conditions_to_confirm[]`. Checks: company_active, entity_type, msp_registry, region, okved, program_status, amount_min, catalog_max, turnover, collateral, amount_capacity. Status: failed → does_not_fit; unknown → needs_info; else fits.
- `can_apply` requires company_active, entity_type, msp_registry, region, okved, program_status, amount_min and catalog_max to pass.
- Ranking key: (status, known shortfall with unknown = full request, collateral burden, rate certainty, bps or 0, policy priority, id).

Steps:
- [ ] Add failing tests:
  - config loading and every validation rule, including a broken copy failing with a path message;
  - rate formula parser;
  - effective-terms golden table (literal values, independent of the loader);
  - OKVED parse set per product (the "кроме 55, 56" text never bans 55/56);
  - eligibility checks per fixture;
  - recommendation statuses, `can_apply`, ranking and payments by an independent oracle reading the raw data files with its own code (Fraction arithmetic);
  - version hash staleness;
  - `GET /catalog` shape;
  - no `research_items`;
  - zero BKI calls.
- [ ] Implement the config layer and switch every consumer to it. Remove `data/demo-products.json` usage; keep the file only if tests or history need it, and say so. Remove `funding_pattern` from the need.
- [ ] Update the fixtures:
  - real regions, `msp_registry`, `tax_regime`, `employees`, `director_name`;
  - names without «Демо»;
  - drop `funding_pattern` and `held_out_tasks`;
  - `fixture_version` `demo-fixtures-v2`;
  - add `gov_manufacturer`: ООО, OKVED 25.62, Курская область, MSP registry, R 12 000 000, P 10 500 000, debt 2 000 000, clean history, checksum-valid synthetic 99… ИНН.

  Then update the seed (10 companies), the migration and the related tests.
- [ ] Rewrite the spec product section and decisions; write `docs/catalog.md` (how to edit the catalog/policy and validate).
- [ ] Verify the SQLite and PostgreSQL suites, the migration on a scratch DB, and `npm run build` (frontend types may need minimal adaptation to keep building; the UI redesign is Task 11).
- [ ] Reset the dev DB (`alembic downgrade base` + `upgrade head` + seed, or an equivalent documented reset), restart the API and record live examples. Commit.

### Task 9: Questionnaire, scoring, officer and documents on runtime products (backend)

**Files:**
- `backend/app/applications/{stages.py,schemas.py,service.py,scoring.py,checks.py,views.py,info_requests.py,products.py}`;
- `backend/app/officer/{policy.py,views.py,service.py}`, `backend/app/documents/service.py`;
- migration if pinned fields need columns;
- tests and `backend/tests/application_oracle.py`;
- `docs/test-scenarios/acceptance.md`, the spec questionnaire/scoring/documents sections.

**Interfaces:** the dialog stage-2 contract per product:
- purpose options are the product's purposes, preselected if there is only one;
- `requested_amount_rub` is prefilled from the snapshot, with product bounds;
- `term_months` follows the product range, is absent for no-term products and is limited by `max_months_by_purpose`;
- `collateral` is required, optional or hidden by collateral mode;
- no `funding_pattern`.

Submit pins `secured`, `required_documents` and the effective terms in `submitted_input_snapshot`. Officer `final_approval` bounds and documents read the pinned values.

Steps:
- [ ] Add failing tests:
  - stage-2 rules per product kind;
  - R1 corrections (bounds, per-purpose term, collateral on a mode-none product, eligibility on product_id);
  - R3 (term not needed for no-term products; collateral details when required, or optional and declared);
  - R7 with effective minimums;
  - limits per the formula, incl. the universal limit's unsecured cap and optional collateral;
  - payment models;
  - pinned `secured`/documents;
  - officer preapproval and final bounds per product;
  - documents per pinned list;
  - one end-to-end submit per product family (term, line, secured, universal, factoring, gov program with `gov_manufacturer`).

  The oracle reads the data files with its own code.
- [ ] Implement it. Move `secured_investment`'s need purpose to business_development (its outcome stays R8 4 000 000). Remove `funding_pattern` from stages, schemas, SCORED_ANSWERS and info requests. Raise the amount input cap to the policy maximum.
- [ ] Recompute and update the acceptance numbers and spec sections; record rulings (the medium-risk 1M cap applies to gov programs; factoring is turnover-bounded).
- [ ] Verify the suites and build, restart the API, record live examples. Commit.

### Task 10: Source-owned tax regime/employees, mock Госуслуги authority check, wording (backend)

**Files:**
- `backend/app/companies.py`, `backend/app/identity.py` (or a new `backend/app/authority.py`), `backend/app/models.py`, migration, `backend/app/seed.py`;
- `backend/app/applications/{stages.py,schemas.py,service.py,info_requests.py}`, `backend/app/officer/*` (requestable fields);
- every server-sent Russian text that says демо/имитация (labels, notices, notifications, document review notice, consent texts);
- tests; docs.

**Interfaces:**
- `POST /api/v1/identity/gosuslugi/verify {inn}`, with key and Origin, always confirms → 201 `{verification_id, inn, person_name, role, verified_at, expires_at}`.
  - The person name comes from the fixture's `director_name`; for a non-fixture ИНН the existing REGISTRY_NOT_FOUND rule applies.
- `POST /companies` additionally requires `authority_verification_id`, which must be unexpired (30 min), unused, for the same user and ИНН. Otherwise 403 `AUTHORITY_NOT_VERIFIED`.
- The company stores the verification. Submit re-checks that it exists.
- Stage 5: name and authority are prefilled from the verification and read-only; `beneficial_owners_confirmed` stays a client checkbox.
- `tax_regime` and `employees` are prefilled from the registry payload, read-only and rejected in answers PATCH as source-owned; registry unavailable keeps R4.

Steps:
- [ ] Add failing tests:
  - the verification endpoint;
  - the onboarding gate (missing, expired, used, other user's, other ИНН verification);
  - direct-API bypass attempts;
  - seed creates verifications for seeded companies;
  - stage-5 prefill/read-only;
  - source-owned field rejection;
  - officer cannot request them;
  - a no-«демо»/«имитац» text test over server-sent strings and fixture names.
- [ ] Implement, migrate, update the seed, docs and spec sections.
- [ ] Verify the suites and build, migrate dev (reset if needed), restart the API, record live examples. Commit.

### Task 11: UI revision — amount slider, explained two-column cards, questionnaire and onboarding changes, wording (frontend)

**Files:**
- `frontend/src/features/recommendations/*` (Recommendations.tsx, ProductCard.tsx, a new AmountSlider);
- `frontend/src/features/applications/{StageFields.tsx,Wizard.tsx,ReviewStage.tsx,fields.ts}`;
- `frontend/src/features/companies/Onboarding.tsx` (+ a new Госуслуги dialog), `frontend/src/features/identity/Auth.tsx`, `frontend/src/components.tsx` (DemoBadge removal), `frontend/src/api.ts`;
- styles; `frontend/tests/*`.

**Interfaces:** consumes the Task 8–10 APIs.

Steps:
- [ ] Product choice screen:
  - one large log-scale amount slider from the catalog's `amount_slider` config, with presets, a typed value, NBSP money, keyboard support and an aria valuetext;
  - remove the need panel, the «Обычный каталог» mode and the research section;
  - cards in a two-column grid (one column below ~900 px), all products;
  - each card shows status, a «Что это» summary, «Особенности» bullets, «Кому подходит», the personal estimate vs maximum, the rate or «Ставка уточняется», the term or «бессрочно», payment with its preferential label, badges, a «Условия программы» disclosure, and «Начать анкету» gated by `can_apply`.
- [ ] Questionnaire:
  - stage-2 controls per the server contract;
  - read-only source fields (tax regime, employees, representative name/authority) rendered as static values with a source note;
  - review stage updated.
- [ ] Onboarding: after choosing the ИНН/company, a «Подтвердить через Госуслуги» step. It opens a mock dialog (native `<dialog>`, pattern from `UnsavedFieldsDialog.tsx`, neutral styling, no real logos or trademarks) showing the person and role, then «Подтвердить». The confirmed state shows a check; then consents, then «Добавить и проверить».
- [ ] Wording sweep: remove every «Демо»/«демо»/«имитация»/«демонстрац…» from UI copy and `DemoBadge` uses. The quick-login buttons become «Войти как клиент» / «Войти как специалист» / «Новый клиент».
- [ ] Update the Playwright specs: card counts come from `/catalog`, `helpers.ts onboard()` passes through Госуслуги, and the research/need-panel/mode tests are removed. Add tests for:
  - slider keyboard and presets;
  - the 2-column grid at 1366×768 and 1 column at 390 px;
  - card explanations;
  - read-only source fields;
  - the Госуслуги gate;
  - no «демо» text on main pages.

  Build plus the full e2e suite. Commit.

### Task 12: Interactive client walkthrough (frontend)

**Files:** `frontend/src/features/tour/*` (Tour component, steps, persistence), small anchors (`data-tour`) in the existing pages, a «Как это работает» button in the top bar, styles, `frontend/tests/tour.spec.ts`, and a Playwright init script disabling the tour in the other specs.

Steps:
- [ ] Build the tour:
  - a custom Tour with an anchored popover and spotlight; bottom sheet under 760 px; z-index above the sticky top bar (40);
  - focus moves into the popover and back; Escape skips; `prefers-reduced-motion` respected;
  - it never blocks the highlighted control;
  - progress «Шаг N из M», «Назад» / «Далее» / «Пропустить».
- [ ] Steps:
  1. add a company;
  2. choose an ИНН/company;
  3. Госуслуги;
  4. consents;
  5. company sources and «Подобрать финансирование»;
  6. amount slider;
  7. card explanations and status;
  8. «Начать анкету»;
  9. questionnaire intro (end).

  It advances on route change or «Далее» and skips steps whose anchor is absent.
- [ ] It auto-starts on a client's first visit. Persistence: `localStorage` `credit-route.tour.v1.<userId>`, read and written inside try/catch, with no breakage when storage is unavailable. It can be restarted from «Как это работает». Officers never see it.
- [ ] Tests: the full walk on desktop and 390 px; skip; restart; no auto-start after completion; existing specs unaffected. Build plus e2e. Commit.

### Task 13: End-to-end evidence, start-up tooling and hand-over docs

**Files:** `frontend/tests/journeys*.spec.ts`, `scripts/` (reset/start helpers), `compose.yaml` if needed, `docs/demo.md`, `docs/evidence.md`, `README.md`, `docs/superpowers/context.md`, and the files touched by the ledgered UI minors.

Steps:
- [ ] Playwright journeys against the real app:
  - strong approval through documents to final approval and hand-off;
  - medium officer flow with an information request;
  - rejection;
  - missing data / registry recovery;
  - document rejection and replacement;
  - cross-role and cross-client access;
  - one gov-program application with `gov_manufacturer`.

  Run them and record the genuine results.
- [ ] Full SQLite and PostgreSQL suites and the build. Check that `docker compose up --build` works (stop the local API/Vite first, then restore them), including one upload and download through nginx and the storage volume.
- [ ] Demo reset tooling (`scripts/reset-demo.sh` or a seed flag) with an explicit confirmation guard; it refuses when `DEMO_MODE=false`.
- [ ] `docs/demo.md`: start-up (local and Docker), accounts, fixture list, how to edit the catalog/policy and validate, a short presentation script. `docs/evidence.md`: executed technical checks vs. assumptions, no user-study claims, known limitations (frozen PDF parsing, mock Госуслуги, factoring simplification, medium-risk cap). README and context summary.
- [ ] Sweep the ledgered UI minors from Tasks 3/4b/5b/6b (listed in the old plan's ledger) and review responsive screenshots; fix obvious visual/accessibility defects. Commit.
