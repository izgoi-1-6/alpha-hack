# Evidence: what was executed, what is assumed, what is limited

This page keeps three things apart:
- the technical checks that were actually run, with their numbers;
- the assumptions and simplifications built into the rules;
- the known limitations.

It makes **no claim about users**. No user study, usability test, conversion or revenue measurement exists. The planned comparison of a plain catalog against the guided route (the old Task 7) was dropped by the user and never ran.

The numbers below come from the final runs of the final fix wave on 2026-10-26, at commit `bbffa22`; only this page and the raw outputs were committed on top. The raw outputs are in [`evidence/`](evidence/). The Docker check and the database reset are the revision Task 13 runs at `77ded11`; their transcripts are there too.

## Executed technical checks

| Check | Command | Result |
|---|---|---|
| Backend suite, isolated SQLite | `cd backend && .venv/bin/pytest` | **1156 passed, 11 skipped** (the PostgreSQL-only race tests) in 162 s; one warning, a Starlette/AnyIO deprecation inside the test client ([output](evidence/final-sqlite.txt)) |
| Backend suite, PostgreSQL 17 | `TEST_DATABASE_URL=…/credit_route_test backend/.venv/bin/pytest -c backend/pytest.ini backend/tests` | **1167 passed** in 362 s, including the concurrency tests on real row locks and partial unique indexes; the same single warning ([output](evidence/final-postgres.txt)) |
| Frontend typecheck and production build | `npm run build --prefix frontend` | `tsc --noEmit` clean; Vite 7.3.7, 92 modules, JS 354.98 kB (105.34 kB gzip), CSS 62.32 kB (12.46 kB gzip) ([output](evidence/final-build.txt)) |
| Browser tests against the running app (Chrome, headless) | `npm run test:e2e --prefix frontend` | **82 of 82 passed** in 5.0 min on the first run (the development database was not reset first); this includes the seven journeys below, the shell checks and the wording guard ([output](evidence/final-e2e.txt)) |
| Catalog and policy validation | `PYTHONPATH=backend backend/.venv/bin/python -m app.products_config check` | `OK: catalog 2026-10-25.1+c0683aa1, rules rules-v2+e3e3ac59, 11 products, 1 overlay` |
| Docker Compose stack (revision Task 13) | `docker compose up --build -d`, then a Chrome smoke script against nginx on :5173 | API and web built and started; the database container was reused, not recreated. All seven smoke checks passed (see below). Then `docker compose stop api web` ([transcript](evidence/task-13-docker.txt)). The final fix wave changed only the image's seed condition, covered by `test_start_scripts.py`; the stack was not rebuilt. |
| Reset of the development database (revision Task 13) | `scripts/reset-demo.sh --yes` | 840 users, 612 companies, 494 applications, 162 documents and 909 saved estimates became 3 accounts and 10 companies; migrations at head `c4d5e6f7a8b9` ([transcript](evidence/task-13-reset.txt)) |
| Reset guards | `backend/tests/test_reset_script.py` (part of both suites) | 25 tests covering DEMO_MODE, the remote-host refusal (a host set in the URL's query included), the confirmation, password masking and neutral output. In Task 13 four mutants that each drop one guard were all caught; the three query-host cases failed before the final fix wave's fix. |
| Start scripts | `backend/tests/test_start_scripts.py` (part of both suites) | 27 tests: `setup.sh` and the API image's start command run on stand-in tools and seed exactly when `app.config` is in demo mode (`DEMO_MODE` unset, or true in any case), never for an empty or other value |
| Mutation checks of the Task 13 fixes | each fix undone in turn, its covering browser test rerun | 12 of 12 caught. A probe of the walkthrough's switch from popover to sheet found one mis-clamped frame (38 px instead of 120 px) with the old code and none with the fix. |
| Final fix wave | each behavioural fix's covering test run before and after it | Every one failed before its fix and passed after it (the docs and the stale `tsconfig.json` entry have none: `tsc` compiles the same 62 files without it). With the server's money formatter reverted to ASCII spaces, journey 1's notice check failed, while the old check on the timeline still passed. |
| Layout sweep (revision Task 13) | nine pages at 360, 390, 1366 and 1440 px (login, registration, company, products, onboarding, applications, queue, review, empty home) | no text under 12 px, no page-level horizontal overflow, every control of the main area and the login tabs at least 44 px tall, no shadow from the hidden phone menu |
| Shell and accessibility checks | `frontend/tests/shell.spec.ts`, part of the browser tests | the login heading at 390 px reads «У вашего бизнеса есть планы.»; «ИП и ООО» stays on one line at 1440, 1100 and 390 px; white text on red reaches 4.69:1 on primary buttons and the current stage number, darker on hover; every focus ring of the stylesheets is opaque, at 3:1 or more on the login page and the dark sidebar; the breadcrumb «/» is hidden from assistive technology; the logout is 44 × 44 and an error notice's «Повторить попытку» 44 px tall. `expectTouchTargets` (journeys 1 and 4, the questionnaire, document and officer specs, and these checks) holds every control of the main area, the sidebar and any error notice on screen to at least 44 px of height. |
| Wording guards | `backend/tests/test_wording.py`, `frontend/tests/wording.spec.ts` | green: no «демо», «демонстрац…», «имитац…» or Latin "demo" in the app's texts or the server's human texts, apart from the named technical exceptions such as the `@demo.local` e-mails |

### The seven journeys (real app, fresh synthetic clients, no injected replies)

| Journey | Path through the app | Recorded outcome |
|---|---|---|
| 1. Main story, walkthrough on | New client → nine-step walkthrough → «Сильный бизнес» added through Госуслуги → amount 2 000 000 ₽ → unsecured term loan → six stages → documents → officer → hand-off | R8 preliminary approval (100 points, scored limit 2 400 000 ₽); both documents accepted; final approval 2 000 000 ₽; hand-off page with Back/Forward/logout. No overflow and 44 px targets at 1366×768 and 390 px on the officer's final decision, the approved status and the hand-off page. The server's own notice, read from the API, keeps «2 000 000 ₽» on one line (U+00A0). |
| 2. Information request | «Средний риск», revolving line 700 000 ₽ | R11 review (65 points, scored limit 600 000 ₽, estimate 1 800 000 ₽). The officer asks about the debt payments and the client answers on the same application. 600 001 ₽ is refused with the bounds; 600 000 ₽ is approved preliminarily (R12). History: CREATED, SUBMITTED, R11, INFO_REQUESTED, INFO_PROVIDED, R12. |
| 3. Refusals | «Высокий риск» 300 000 ₽ twice, then «Сильный бизнес» | R6 automatic refusal (10 points). With tax arrears the case goes to an officer (R5); the preliminary approval is a mandatory stop, so the officer refuses with a reason. At the document stage one document is rejected and the application is finally refused; the packet stays read-only and no longer asks for a corrected file. |
| 4. Missing data and an outage | «Неполные обороты», then «Реестр недоступен», 1 000 000 ₽ each | Declared turnover goes to a specialist (R5, «Заявлено клиентом»). The unavailable registry blocks applying until «Повторить проверку» recovers it, then R8 preliminary approval. Both applications appear in «Мои заявки» at 390 px. |
| 5. Document rework, secured | «Оборудование», secured term loan 4 000 000 ₽ with an 8 000 000 ₽ pledge | R8 preliminary approval (scored limit 4 500 000 ₽) and four documents. The valuation is rejected, replaced and kept as history. A review typed in one officer tab survives a real version conflict caused by another tab. The verified 5 000 000 ₽ bounds the final approval at 3 500 000 ₽. |
| 6. Access | owner, another client, the officer, a signed-out visitor | The owner reads eight resources (200); the session is an HttpOnly, SameSite=Lax cookie and nothing is kept in browser storage. Another client gets 404 on all of them and on the seeded client's company, 404 on a command, and 403 on staff routes. The officer gets the staff view and the file (200) but 403 `CLIENT_REQUIRED` on client routes and «Нет доступа» pages. Signed out, every API route answers 401 and the app shows the login at a clean address. A command with a foreign Origin gets 403. |
| 7. Gov program | «Курский производитель», 20 000 000 ₽ | «Кредит по ПСК для приграничных территорий» fits, with a payment of 683 553 ₽ «в льготный период 12 мес.» (also checked by an independent calculation). R8 preliminary approval: 100 points, scored limit 30 000 000 ₽, unsecured, two documents. |

### The Docker smoke checks (through nginx, 2026-10-26)

Every check below passed:
- health through nginx: `{"status":"ok","demo_mode":true}`;
- quick logins as the officer and the seeded client, with an HttpOnly session cookie;
- a fresh client added «Сильный бизнес» through the Госуслуги dialog;
- a questionnaire submitted to an R8 preliminary approval;
- a 503-byte PDF uploaded and downloaded byte for byte through nginx. Both files sit in the named volume `credit_route_documents` with mode 0600 and not in the host's `var/documents`, matching their database rows;
- the officer's final approval of 2 000 000 ₽;
- `/alfa-business/{id}` loaded directly through nginx (the SPA fallback), showing the final amount and that no money moves.

nginx sends `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`. The database container kept its id and start time (2026-10-24T19:28:36Z) throughout.

## Assumptions and simplifications

- **Catalog facts are research claims.** `data/credit_catalog.json` copies the user's catalog. Rates, amounts, terms, purposes and eligibility are not verified bank policy. The key rate and the rate formulas are checked to agree with each other, not with any real rate.
- **The policy file is local decision rules**:
  - fallbacks for catalog nulls;
  - revenue multiples 3 (low risk) and 1 (medium risk);
  - a medium-risk cap of 1 000 000 ₽;
  - a 70 % loan-to-value on pledges;
  - the payment models and the ranking.
- **Scoring** follows the analyst notebook (business age, revenue growth, debt load and credit history, 100 points in all; 75+ is low risk, 50–74 medium). The rules R1–R12 are explicit, and nothing in them is a calibrated probability of approval.
- **Estimates are not offers.** A card's personal estimate is the low-risk turnover limit before any credit check. Its payment uses one 36-month policy term (clamped to each product's range), so the cards stay comparable; the client's own term is not priced.
- **The sources are fixtures**:
  - ten synthetic companies with generated-checksum ИНН;
  - recoveries scripted per fixture (a registry or BKI outage that a retry fixes);
  - business age counted to the fixture date 2026-10-24, while sessions and deadlines use the real clock.
- **Document checks are structural**: type, magic bytes, parsable structure, no active content, no data after the end. They are not antivirus scanning and they check no authenticity. The officer's acceptance is the only content check.
- **One officer**: the seed creates `officer@demo.local` only. Competing officers are proven by the PostgreSQL race tests, not in the browser.

## Known limitations

- **PDF parsing is frozen (user directive).** The PDF and image validation code is not changed.
  - pypdf's own strict parse can be super-linear on a crafted cross-reference table.
  - Hostile bytes hidden inside a real stream's data count as data.
  - A PDF whose visible text contains an HTML marker such as `<html ` is refused.
  - All three are acceptable for synthetic files only.
- **The mock Госуслуги always confirms**: any client can add any fixture ИНН, and several clients may add the same one. A real ЕСИА would refuse a user who does not represent the company.
- **Factoring is bounded by turnover**: its limit is min(2 000 000 000 ₽, 3 × monthly turnover). There is no receivables model.
- **The medium-risk cap is 1 000 000 ₽ for every product, gov programs included.** A medium-risk company is refused (R7) on «Инвестиционный кредит по ПСК с субсидией» (minimum 25 000 000 ₽): large programs need low risk.
- **No real integrations**:
  - no money moves, no contract is signed, the bank is never contacted;
  - no SMS or e-mail is sent; notifications are in-app records;
  - the Alfa-Business hand-off is a local page.
- **Other technical bounds**:
  - browser tests run in Chrome only, and the Docker stack was verified on one ARM64 Mac;
  - the officer queue has no pagination;
  - the login rate limit is a simple database bucket, not production abuse protection;
  - a crash between storing a file and committing can orphan a file, and the reset keeps uploaded files on disk;
  - the walkthrough's "seen" flag is per browser;
  - two concurrent first reads of lists could in principle deadlock on their lazy expiries. The client's list locks expired rows newest first and the officer's queue in submission order, so two rows falling due at the same instant, read by both at once, could be locked in opposite orders. PostgreSQL would abort one of the two GETs. This is not reachable in demo use.
- **Contrast is measured, not audited**:
  - The Task 13 sweep (nine pages at four widths) and the shell checks of the browser tests measure contrast; no audit tool or assistive-technology user has checked it.
  - White text sits on `#dc2f28` (4.69:1), a shade darker than the brand red `#e5322b` (4.35:1), which stays on everything else. The focus rings are opaque brand red.
  - The light «/» between the breadcrumbs (1.7:1) is decorative and hidden from assistive technology.
