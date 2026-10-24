# Implemented foundation interfaces

Task 2. Root paths below are relative to this repository. The canonical contract is `docs/superpowers/specs/2026-10-24-credit-route-design.md`; these are concrete reusable interfaces for subsequent modules. Add new routers under `/api/v1` in `backend/app/main.py`.

## Backend dependencies and transactions

- `app.db.Base`: SQLAlchemy declarative base. Add models to the same metadata and import them from Alembic `migrations/env.py` before generating new revisions.
- `app.db.engine`, `SessionLocal`: configured by `DATABASE_URL`, default PostgreSQL+psycopg on localhost. `SessionLocal` uses `expire_on_commit=False`.
- `app.db.get_db() -> Generator[sqlalchemy.orm.Session, None, None]`: one request transaction; commits after successful endpoint, rolls back on exceptions. Endpoints call `flush()` when IDs/constraints are needed. Do not commit halfway through business commands. Error `Response` returns still commit (used to persist failed login attempts). Script callers use `with SessionLocal.begin() as db:`.
- `app.identity.Db = Annotated[Session, Depends(get_db)]`, `Now = Annotated[datetime, Depends(utc_now)]` are reusable FastAPI aliases.
- `app.clock.utc_now() -> datetime`: UTC wall clock; tests override `app.dependency_overrides[utc_now]`. `as_utc(datetime) -> datetime` handles SQLite's naive adapter timestamps; `iso_utc(datetime) -> str` writes UTC `Z`. Fixture reference dates are exclusively business dates.
- Migrations: `477de883cdb2` (identity/company/consent/idempotency entities) and `070eeaa75839` (precheck sequence). Apply with `backend/.venv/bin/alembic -c backend/alembic.ini upgrade head`. API startup does not create tables.

## Identity and ownership

- `app.identity.get_current_user(request: Request, db: Db, now: Now) -> User`: resolves SHA-256 digest of the opaque cookie, rejects revoked/expired sessions at 401; never accepts role/owner from request bodies.
- `CurrentUser`, `ClientUser`, `OfficerUser` are `Annotated[User, Depends(...)]` aliases. `require_client(user: CurrentUser) -> User` and `require_officer(user: CurrentUser) -> User` enforce roles with 403. New officer routes must use `OfficerUser`; owner routes use `ClientUser`.
- `app.companies.get_owned_company(db: Session, company_id: str, user_id: str, *, for_update: bool=False) -> Company`: combines owner/resource predicates, 404 for foreign or absent resources. `for_update=True` acquires the PostgreSQL row lock. Call it before idempotency replay on company commands. No general officer bypass is included; officer routes must enforce their own explicit read policy.
- `app.identity.public_user(User) -> dict`: only id/email/display_name/role. `password_hasher` is Argon2id. Raw passwords and raw cookie tokens are never persisted. Cookie name is `credit_route_session`; fixed expiry 12 hours, revoked on logout. No sliding extension. Multiple login sessions are independent.
- Global `check_origin(request: Request) -> None` enforces exact `settings.ui_origin` on POST/PUT/PATCH/DELETE including auth. CORS allows that origin with credentials. `Cache-Control: no-store` and `nosniff` apply to API responses. Vite/nginx proxy `/api`.
- Failed logins are DB-persisted buckets keyed by hash(email + peer address), limited to ten failures per fifteen minutes. This is a demo bound, not production abuse protection.

## Models and sources

`app.models` exports `User`, `AuthSession` (table sessions), `LoginAttempt`, `Company`, `Precheck`, `Consent`, `IdempotencyRecord`, `new_id() -> str` (UUID4). UUIDs are stored as 36-character strings; money columns use BigInteger; timestamps use timezone-aware DateTime. Consent `application_id` is nullable String until an application migration adds its FK. Do not rewrite consent rows: create new grants.

`app.companies.FIXTURES` is the immutable JSON dataset and `SOURCES` maps whitelist INN to synthetic source fixture. Those internal fixtures contain later BKI/held-out oracle data: **never return or persist the whole fixture as a precheck or client payload**. `append_precheck(db, company, source, now) -> Precheck` explicitly copies only registry and turnover fields, no BKI. Internal `company_version` uniquely sequences snapshots per company so tied test clocks cannot return the wrong snapshot; it is omitted from the public API. `latest_precheck(db, company_id) -> Precheck`, `company_result(db, company) -> {company,precheck}` retrieve the latest version. No source GET consumes/retries a mock response.

`create_company(db, owner_id, source, now, *, seeded=False) -> Company` inserts company, precheck and both onboarding consent grants after endpoint validation. Seeded records use stable fixture IDs/reference date; freshly onboarded companies use UUID4/current UTC business date. `seed_demo(db, *, demo_mode: bool) -> None` from `app.seed` is idempotent, refuses false, and creates the published synthetic credentials and default client-owned fixtures. It does not reset existing data/passwords.

Implemented routes: auth register/login/logout/me; GET consent documents for onboarding/application; companies list/create/read; GET precheck; POST precheck/retry; GET `/demo/fixtures` (demo-only, client-only, safe summary excluding oracle); GET `/health` (DB ping and demo mode). Empty lists use `{items,total}`. Officer client routes return 403; there is no placeholder application/catalog API.

The retry command locks the owned Company, looks up `IdempotencyRecord` on `(actor_id,method,path,key)`, compares canonical request SHA-256, returns the saved JSON before revision validation on an exact replay, then checks version, applies immutable fixture recovery, appends precheck and increments company version exactly once in the same transaction. PostgreSQL lock and uniqueness constraints serialize concurrent calls. Future application commands should use that same ordering but lock the application row and scope ownership through Company. Replay response/status fields and resource ID are available on the shared model; do not reuse an idempotency key across different bodies.

## Validation and errors

`app.schemas.StrictModel` rejects unknown keys; extend it for every JSON body, including empty command objects. `CompanyInput` validates string-only ASCII INN/checksums and both literal JSON-true consent entries at `demo-consent-v1`. `VersionInput` requires a strict positive integer.

`app.errors.ApiError(status: int, code: str, message: str, *, fields: dict|None=None, details: dict|None=None)` renders `{error:{code,message,fields?,details?}}`. Raise it for domain/auth failures; Russian human messages, English codes. Validation errors use 422 `VALIDATION_ERROR` with paths but never echo input/secrets. DB uniqueness races map to 409 `RESOURCE_CONFLICT`; domain duplicate checks use `EMAIL_EXISTS`/`COMPANY_EXISTS`. Other errors include `ORIGIN_FORBIDDEN`, `AUTH_REQUIRED`, `CLIENT_REQUIRED`, `OFFICER_REQUIRED`, `REGISTRY_NOT_FOUND`, `COMPANY_NOT_FOUND`, `PRECHECK_NOT_FOUND`, `VERSION_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `INVALID_CREDENTIALS`, `LOGIN_RATE_LIMIT` (429). Unknown routes use standardized 404. Unexpected errors use a generic 500 without stack traces in the response.

## Frontend

`frontend/src/api.ts` exports `request<T>(path: string, options?: {method?: string; body?: unknown; idempotencyKey?: string; signal?: AbortSignal}) -> Promise<T>`, where path is relative to `/api/v1`. Uses `credentials:'same-origin'`, JSON, optional key; 204 resolves undefined. `ApiError` has `status`, `code`, `message`, `fields`, `details`; network errors use status 0 and code `NETWORK_ERROR`. Aborted requests retain AbortError. No local/session storage or auth-token JSON.

Typed `User`, `Company`, `Precheck`, `CompanyResult`, `Fixture`, `ConsentDocument` and `api` helpers are exported. Extend these for later vertical slices. App session restoration uses `/auth/me`; selected company/intent appears in URL query for deep links and reload. React stores only transient form/view copies. Consent acceptance is explicit for each required server-delivered text. Read helpers `me(signal?)`, `companies(signal?)`, `company(id, signal?)`, `fixtures(signal?)`, and `consents(signal?)` accept an optional AbortSignal. The workspace cancels obsolete reads and checks a session/view generation before every asynchronous success/error/loading cleanup. Navigation invalidates the view; logout/account replacement also clears all account-bound state and invalidates the session. Initial `/auth/me` restoration has a separate controller and session-only lifetime, so company history traversal cannot cancel boot. Mutations are allowed to finish server-side, but obsolete results cannot replace the current view. Retry retains its key **and original body revision per company** across navigation or a transient network failure, and removes that attempt only after a confirmed response in the same session. The UI displays source labels, inactive/read-only status and missing information without inventing financial limits or approval claims.

## Verification and boundaries

Run `.venv/bin/pytest` from backend; set `TEST_DATABASE_URL=.../credit_route_test` to exercise PostgreSQL rather than SQLite. Test setup refuses non-`_test` PostgreSQL DBs and recreates its tables. Browser flows use an already-running stack and synthetic random accounts. Startup/migration/seed commands are in root README and scripts. The PostgreSQL+host API/Vite runtime is the verified baseline; Dockerfiles provide an optional full container path. Future migrations must not mutate research or fixture answer keys.
