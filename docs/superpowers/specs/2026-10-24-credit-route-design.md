# Кредитный маршрут — canonical MVP contract

Version `demo-spec-v1`, 2026-10-24. This document and `data/demo-*.json` bind implementation. All money fields below are integer RUB; basis points are integers (2350 = 23.50%). Unknown is `null`, never zero. English identifiers, Russian UI. No calibrated approval probability exists; show fit, reasons and uncertainty instead.

## Scope and provenance

React/TypeScript/Vite, FastAPI, PostgreSQL 17, SQLAlchemy 2/Alembic. Modules follow the plan's file boundaries. Exactly three products accept applications. Registry, turnover, BKI, notifications, document verification and Alfa-Business are labeled local mocks. No real PII, external bank calls, real signatures, real SMS or disbursement. No OTP stage; an explicit demo confirmation replaces source SMS signing. Staff final approval is a demo decision.

Preserved original sources, relative to original checkout `/Users/ren1kron/Developer/hakatons/alpha-hack`:

- `drafts&notes/credit-route_files/a_Sxsi.html`: real analyst content, six-stage questionnaire and preapproval → documents → final approval. The outer `credit-route.html` is a wrapper.
- `drafts&notes/credit_catalog.json`: nine research items; archived in `data/catalog.research.json` with source SHA-256 and `can_apply=false`. Its rates, key rate, program/legal claims and limits are unverified historical research, never demo calculation inputs.
- `scoring/alfa_scoring_simple.ipynb`: original score factors and R1–R12. The 100k–3m/6–36-month single product is historical, not today's three-product policy.
- `drafts&notes/synthetic_tests_client_flow_v2/{README.md,fixtures_T1_T20_flow_v2.json,validate_fixtures.py}`: old synthetic oracle and flow scenarios, not executed application evidence.
- `drafts&notes/functional-requirements.md`: missing-source recovery, read-only inactive profiles and useful empty results.

The original HTML contradicts itself about unknown collateral and gives secured catalog ceilings as personal capacity. This contract resolves both: unknown collateral means `needs_info` and null secured indicative limit; every personal limit is constrained by turnover. Founder ownership never implies guarantor consent. The MVP does not collect guarantors or run their BKI; production surety rules remain out of scope. Every demo product is explicitly a simplified product, not an implementation of real bank policy.

## Authentication and common HTTP contract

All endpoints start `/api/v1`. UUID strings identify entities; `product_id` and fixture IDs are the stable strings in data. Dates ISO-8601; timestamps UTC `Z`. API reads return objects, lists `{items:[...],total:N}`. Error shape `{error:{code,message,fields?,details?}}`; message is Russian. `fields` maps field paths to messages; never include stack traces or secrets. Unknown request keys are rejected (422), including role/status/owner injection. Use 401 unauthenticated, 403 wrong role/origin, 404 absent or other customer's resource, 409 state/version/duplicate/idempotency conflict, 422 invalid data, 413 oversized file, 415 unacceptable media.

Server-owned opaque random session cookie `credit_route_session`, HttpOnly, SameSite=Lax, Path=/, Secure in HTTPS (false only documented localhost development). Store only a hash of the token, never return token JSON; no browser auth storage. Sessions expire 12h after login (no sliding refresh), revoke on logout, new login creates a new session. Hash passwords with a maintained password library. Email trim/lowercase, unique; password 10–128 characters. Registration creates CLIENT only. Officer seeding only via demo tooling; no role picker in public registration. Authenticated mutating requests require Origin matching configured exact UI origin; absent/foreign Origin fails 403 (integration drivers send it). CORS permits only configured development origin with credentials; Vite/production proxy presents same origin to browser.

| Method/path | Input | Success |
|---|---|---|
| POST `/auth/register` | `{email,password,display_name}` (name 1–100 chars) | 201 `{user}` + cookie |
| POST `/auth/login` | `{email,password}` | 200 `{user}` + cookie; invalid credentials 401 |
| POST `/auth/logout` | `{}` | 204, revoked cookie/session; may be safely repeated |
| GET `/auth/me` | — | `{user}`; 401 after expiry |
| GET `/consents/documents?stage=onboarding\|application` | — | `{items:[{code,version,text}]}` |

`user` contains only `{id,email,display_name,role}`. Apply Origin check to registration/login too. Limit login attempts in demo reasonably; do not claim production abuse protection. Demo-only seed creates `client@demo.local`, `other@demo.local`, `officer@demo.local`, password `DemoCredit2026!` (published synthetic local credentials, never production secrets). IDs in fixture actors are stable seed IDs. Both clients get no cross-access; default fixture companies belong to the first client. Seed is idempotent, gated by demo mode; production refuses demo seed/reset.

For application edits and stateful commands body `version` is the current integer revision (starts 1); successful changes increment it once. No need to use ETag/If-Match as well. Stateful POST commands require `Idempotency-Key` (1–128 characters); scope `(actor_id,method,path,key)` with body digest, persisted status/body and resource ID. Exact replay returns the original result without new evaluation/history/BKI call; same key + different body → 409 `IDEMPOTENCY_CONFLICT`. Replay lookup precedes version/state validation but follows authentication/ownership checks. Keys survive for the lifetime of the demo database. Commands serialize on application row/conditional version update; DB uniqueness also guards active submissions. Upload uses version and key form fields/header; downloads/reads never change revision except lazy expiry.

## Persisted entities and data ownership

Fields with `?` are nullable; all other fields are required. JSON snapshots are immutable once used for submission. All resources are owner-scoped through company, with explicit officer-only reads/commands. A logged-in client cannot read another client's identifiers, snapshots, files, timeline or events. User role/owner IDs come from session, never request bodies.

| Entity | Fields |
|---|---|
| User | id, email, password_hash, display_name, role (`CLIENT`,`CREDIT_OFFICER`), created_at |
| Session | id, user_id, token_hash, expires_at, revoked_at?, created_at |
| Company | id, owner_user_id, inn (string), entity_type (`IP`,`LLC`), name?, registered_at?, registry_status (`active`,`inactive`,`unknown`), okved?, region?, legal_address?, fixture_id?, business_reference_date?, version, created_at, updated_at |
| Precheck | id, company_id, registry_source_status, turnover_source_status (`available`,`missing`,`unavailable`), registry_payload, turnover_payload, monthly_revenue_rub?, previous_monthly_revenue_rub?, financial_period_end?, source_version, checked_at, synthetic=true |
| Consent | id, user_id, company_id, application_id?, code (`ONBOARDING_PROCESSING`,`REGISTRY_LOOKUP`,`APPLICATION_PROCESSING`,`BKI`), text_version (`demo-consent-v1`), granted_at; append-only |
| RecommendationSnapshot | id, company_id, precheck_id, need (below), input_snapshot, result, catalog_version, rules_version, created_at |
| Application | id, company_id, product_id, recommendation_snapshot_id, status, answers, current_stage (1–6), version, submitted_at?, assignee_id?, requested_amount_rub?, indicative_limit_rub?, scored_limit_rub?, preapproved_amount_rub?, final_amount_rub?, preapproved_at?, preapproval_expires_at?, catalog_version, rules_version, submitted_input_snapshot?, created_at, updated_at |
| Evaluation | id, application_id, input_snapshot, score?, risk? (`low`,`medium`,`high`), factors?, rule (`R1`–`R12`), scored_limit_rub?, outcome, reasons[], sources, created_at |
| InfoRequest | id, application_id, officer_id? (null=system), kind (`client_answers`,`trusted_source`), source? (`registry`,`turnover`,`bki`), requested_fields[], question, response?, responded_at?, resolved_at?, created_at |
| StatusHistory | id, application_id, from_status?, to_status, actor_id? (null=system), reason_code, reason_text, application_version, created_at |
| OfficerDecision | id, application_id, officer_id, phase (`preliminary`,`final`), action (`preapprove`,`approve`,`reject`,`request_info`), amount_rub?, reason, evaluation_id?, created_at |
| Document | id, application_id, document_type, revision, original_name, media_type, size_bytes, sha256 (actual bytes), storage_key (private), status (`UPLOADED`,`ACCEPTED`,`REJECTED`,`SUPERSEDED`,`DELETED`), review_reason?, reviewer_id?, verified_value_rub? (integer RUB), created_at, reviewed_at? |
| Notification | id, application_id, event_code, channel (`demo_in_app`), message, created_at; no external dispatch |
| IdempotencyRecord | id, actor_id, method, path, key, request_hash, response_status, response_body, resource_id?, created_at |
| AnalyticsRun | id, user_id, task_id, mode (`baseline`,`guided`), cohort_id, fixture_version, answer_key_version, is_synthetic, started_at, completed_at? |
| AnalyticsEvent | id, run_id, user_id, application_id?, name, payload, recorded_at (server), client_event_id (unique per user) |

`source_version=demo-fixtures-v1`; catalog/rules versions come from `data/demo-products.json`. Current app clock is UTC/injectable. Only business age for seeded companies is computed at fixture `business_reference_date=2026-10-24`, using completed calendar months; newly registered company snapshots use current business date. Do not freeze session, analytics or expiry time to fixture date. Registry/turnover lookup uses only synthetic whitelist INNs. A checksum-valid INN outside the demo whitelist produces 422 `REGISTRY_NOT_FOUND` on onboarding with an instruction to correct the INN/select a demo fixture; persist no unusable company and make no real registry call. The whitelisted registry-unavailable fixture is saved with unknown status and recovers through retry.

## Company onboarding and precheck

INNs must be strings of ASCII digits, length 10 LLC / 12 IP, valid standard Russian checksums. Ten digits: weights `[2,4,10,3,5,9,4,6,8]`, mod11 mod10. Twelve digits: digit11 uses `[7,2,4,10,3,5,9,4,6,8]`; digit12 uses `[3,7,2,4,10,3,5,9,4,6,8]` including digit11. Reject all-identical-digit and all-zero numbers even if checksum holds. Infer type from length. An INN may be onboarded by separate synthetic users but is unique per owner. Whitelisted fixtures are immutable source data, separate from application answers.

| Method/path | Input | Success |
|---|---|---|
| GET `/companies` | — | owned companies |
| POST `/companies` | `{inn,consents:[{code,version,accepted:true}]}`; both onboarding codes required | 201 `{company,precheck}`; existing owned INN 409 `COMPANY_EXISTS` |
| GET `/companies/{id}` | — | `{company,precheck}` |
| GET `/companies/{id}/precheck` | — | latest `{company,precheck}` |
| POST `/companies/{id}/precheck/retry` | `{version}` + key | updated `{company,precheck}`; no BKI |

Inactive fixture: read-only recommendations with failure reason; UI disables application submission. Server still rejects a submitted draft through R2 if status became inactive after creation. Missing turnover: show cards, null limits, explicit data request; do not fail the whole page. Unavailable registry: show unknown eligibility and retry. Retry of unavailable seeded mock transitions to recovery data in fixture `recovery`; retry `GET` never consumes a mock response. Repeated retries after recovery return available result; no timed sleeps. Application answers may supply missing financial values; source conflicts cannot be silently overwritten and go to review.

## Product policy and recommendations

Authoritative config `data/demo-products.json`, version `demo-2026-10-24-v1`. Common eligibility: IP/LLC, active company; no extra industry or business-age hard stop. Informational research items cannot create applications, even by direct API. Product ceiling ≠ indicative personal limit ≠ preapproved amount ≠ final amount.

| Product ID | Purposes | Min–max RUB | Months | Demo annual rate | Pattern |
|---|---|---|---|---|---|
| `alfa_term_loan_unsecured` | working_capital, business_development, refinancing | 300,000–3,000,000 | 6–36 | 23.50% | one_time |
| `alfa_revolving_line_unsecured` | working_capital | 300,000–3,000,000 | 6–18 | 24.00% | repeated |
| `alfa_term_loan_secured` | working_capital, business_development, investment, refinancing | 500,000–6,000,000 | 12–60 | 21.50% | one_time |

Need is `{purpose,funding_pattern,requested_amount_rub,term_months,collateral?}`. Purpose enum is union above; funding pattern `one_time|repeated`. Amount positive integer ≤150,000,000; months integer 1–120 at comparison input (a product may not support it). Collateral is `{status:"unknown"|"none"|"declared",type?:"real_estate"|"vehicle"|"equipment"|"inventory"|"deposit",declared_value_rub?:int,description?:string,owner_confirmed?:bool,encumbered?:bool}`. Declared requires positive value, type, description 1–500 chars, owner_confirmed=true and encumbered=false for automatic preapproval. It remains client-declared until officer acceptance of ownership/valuation documents. Encumbered/unconfirmed ownership is `needs_info` in estimates and manual review after submission. Unknown/none cannot submit secured questionnaire until changed to declared; server returns R3/422 without BKI. Ownership is self-declared, not bank verification.

Pre-submission recommendations MUST NOT call BKI, use credit_history, compute final score or state approval probability. With positive known revenue R: upper indicative capacity `min(product.amount_max_rub,3*R)`. Secured also bounded by `floor(declared_value_rub*7000/10000)`; unknown/absent collateral gives indicative limit null. Missing/zero revenue gives limit null (zero is a finance anomaly). This upper estimate is labeled «Предварительная оценка по обороту, не предодобрение». Registry unknown prevents a `fits` result even if turnover is known. `scored_limit_rub` after submission: low=min(product ceiling,3R), medium=min(product ceiling,1m,R), high=null; apply same secured LTV constraint. No product bypasses turnover. Less than product minimum is R7 rejection after scoring.

Recommendation item fields: `{product_id,rank,status,can_apply,indicative_limit_rub,catalog_max_rub,requested_amount_rub,checks,reasons,alternatives,estimated_payment_rub,payment_note}`. `status` is `fits|needs_info|does_not_fit`. Checks are `{code,result:"passed"|"failed"|"unknown",text}` for company_active, entity_type, purpose, funding_pattern, term, amount_min, catalog_max, turnover, collateral, amount_capacity. Funding mismatch is a warning/check unknown, not a hard prohibition (a line may serve a single purchase). Failed company/purpose/term/min/catalog-max/known-capacity → does_not_fit; otherwise unknown source/collateral → needs_info; otherwise fits. `can_apply` is true for supported active products with matching purpose/term/catalog range even if data/capacity needs review; inactive/unknown registry or unsupported purpose/term disables it. Missing turnover can create a DRAFT and be completed there. Secured collateral may be declared in the wizard. Above personal estimate but within catalog range can apply and may get a smaller amount. Explain `can_apply` separately from fit.

Sort deterministically ascending tuple: (status: fits=0, needs_info=1, does_not_fit=2; purpose mismatch 0/1; preferred pattern mismatch 0/1; amount shortfall RUB, unknown capacity treated as requested amount; collateral requirement false=0/true=1; annual_rate_bps; product_id). Known amount shortfall=max(0,requested-limit). Rank supported items only, 1-based. All research cards remain informational after them; no rank that implies recommendation. Purpose/pattern/amount precede price; unsecured is preferred when both fulfill a one-time need without extra collateral. Return reasons even if none fits, show supported alternative amount or editable need; no empty error screen.

Indicative term-loan annuity: Decimal `A*r/(1-(1+r)^(-n))`, monthly r=annual_bps/120000, round half up to RUB; calculate on `min(requested,limit)` only when positive limit is known and amount ≥product minimum. No fees included. Revolving shows monthly interest at full utilization `ceil(A*annual_bps/120000)` and principal due at maturity, not a fake annuity or guaranteed repayment plan. Minimum draw 50k, no auto-renewal; this demo is deliberately bounded. Secured payment remains indicative pending collateral review. Return null payment when unknown/incompatible.

| Method/path | Input | Success |
|---|---|---|
| GET `/catalog` | — | `{catalog_version,rules_version,products:[demo config],research_items:[archive items]}` |
| POST `/companies/{id}/recommendations` | need | 201 `{snapshot_id,catalog_version,rules_version,items:[recommendation item],created_at}` |
| GET `/companies/{id}/recommendations/{snapshot_id}` | — | same immutable snapshot |

Creating an application copies its owned snapshot (no TTL on draft creation); submission rechecks current source data and pins fresh product/rule/input snapshots so old estimates do not promise capacity. Product withdrawn or policy changed → 409 `RECOMMENDATION_STALE`, regenerate recommendation; never silently migrate submitted decisions to a later policy. Draft creation may retain a supported snapshot with incomplete data; `can_apply` gates the ordinary UI action, while direct submission still enforces R1–R4.

## Six saved questionnaire stages

The server declares stage fields, completion and allowed actions. `GET /applications/{id}/dialog` returns `{current_stage,steps_total:6,stages:[{number,title,fields,complete}],answers,missing_fields}`. A fixed six-stage schema is sufficient; no LLM or complex tour engine required. Partial saves are allowed, final validation happens on submit. Synthetic personal names only, no passports or actual tax-resident identifiers.

| Stage | Fields saved under answers | Required at submit |
|---|---|---|
| 1 Компания | `company_confirmed`, `actual_address`, `actual_activity` | true, nonempty address/activity (1–300 chars); company snapshot is server-owned |
| 2 Параметры | `purpose`, `funding_pattern`, `requested_amount_rub`, `term_months`, `collateral` | compatible purpose and catalog min/max/months; secured declaration as above |
| 3 Бизнес и финансы | `monthly_revenue_rub`, `previous_monthly_revenue_rub`, `financial_period_end`, `tax_regime`, `employees`, optional `seasonal` | both revenue values present, date, tax regime `OSN|USN|PSN|OTHER`, employees integer ≥0 |
| 4 Обязательства | `monthly_debt_payment_rub`, `tax_debt_rub`, `legal_proceedings`, optional `obligations_note` | amounts ≥0, boolean proceedings; current overdue/history are BKI-owned and never client-set |
| 5 Руководитель и владельцы | `representative_name`, `representative_authority_confirmed`, `beneficial_owners_confirmed` | name 1–100 chars; both true; synthetic confirmation, not verification of guarantor consent |
| 6 Проверка и согласия | `accuracy_confirmed`; submission consents passed to submit | true; BKI and APPLICATION_PROCESSING checked explicitly, default unchecked, exact current versions |

Wizard prefills source finances/need; user confirms or edits. Overrides of known source finances or nonzero tax debt/legal proceedings route R5 manual review; flag sources and original values, never erase originals. Unknown source finances may be supplied as declared (source tag retained), yielding MANUAL_REVIEW even if score is low until officer checks evidence. Zero previous/current revenue is allowed as saved data but routes R5 (no division, no auto-limit). Negative numbers are invalid input, yet malformed imported internal data is R5. Requested amount above personal capacity is allowed within product ceiling; R9/R11 handles it.

## Scoring and state machine

Original factors (RUB values compare with exact integer arithmetic): business age ≥24 months 20, 6–23 10, <6 0. Revenue growth `(R-P)/P`: >10% 25; −10% through +10% inclusive 15; <−10% 0. Monthly debt/R ≤30% 30, >30% through50% 15, >50% 0. BKI history `clean`25, `minor_closed`10, `serious`0. Total≥75 low, ≥50 medium, otherwise high. `serious` historical is not itself a hard stop: current overdue≥30 days or inactive company is R2 regardless of points. No hypothetical diagnostic score is persisted as an executed evaluation. External BKI data is trusted only from configured mock; questionnaire cannot set it.

| Rule in order | Trigger | New behavior |
|---|---|---|
| R1 | unsupported purpose/amount/term or invalid input | 422 `CORRECTION_REQUIRED`, keep DRAFT; no BKI/evaluation |
| R2 | known inactive or BKI current overdue≥30d | REJECTED, score may remain null; bypass later rules |
| R3 | required values/collateral/submission consents absent | submit 422 `NEED_INFO`, keep DRAFT and no BKI for missing consent; if gap discovered in submitted check → NEED_INFO |
| R4 | registry/turnover/BKI unavailable (not simply missing) | WAIT_EXTERNAL; retry explicit, no hidden loops |
| R5 | zeros/contradictory finance, imported invalid values, declared-only finance, encumbered collateral, tax/legal concern | MANUAL_REVIEW with evidence; score/limit null if noncomputable |
| R6 | computed score<50 | REJECTED |
| R7 | scored limit<product minimum | REJECTED |
| R8 | low risk and request≤scored limit | PREAPPROVED, preapproved amount=request |
| R9 | low risk and request>scored limit | PREAPPROVED, preapproved amount=scored limit; explain smaller amount |
| R10 | medium risk and request≤scored limit | MANUAL_REVIEW |
| R11 | medium risk and request>scored limit | MANUAL_REVIEW, show lower possible amount |
| R12 | assigned officer preliminary preapprove/reject | PREAPPROVED/REJECTED; never final APPROVED |

R1, known registry R2 and required consent/input R3 are checked before any BKI. Registry unavailable uses R4 (it is not missing client input); known inactive overrides missing finance. After successful submission, persist consent → CHECKING/history → call BKI once → store evaluation and result within transaction/guarded service. A missing BKI result category is NEED_INFO with a system-created trusted_source InfoRequest (`officer_id=null`, `source=bki`, `requested_fields=[]`, generated retry explanation); unavailable service is WAIT_EXTERNAL. A client-answerable gap creates kind=client_answers with requested answer paths; an officer request always has kind=client_answers and nonnull officer_id. For trusted_source, source is required, officer_id is null and requested_fields is empty; client_answers uses source=null and nonempty requested answer paths. System requests may be unassigned. Source-owned gaps cannot be filled through questionnaire answers; their allowed_actions exposes retry_check, not respond_info. Retry/answers create a new immutable evaluation; preserve prior source payloads/evaluations. No real source network calls.

Allowed states, exact spelling: `DRAFT`, `CHECKING`, `WAIT_EXTERNAL`, `MANUAL_REVIEW`, `NEED_INFO`, `PREAPPROVED`, `DOCS_UPLOADED`, `DOCS_REWORK`, `APPROVED`, `REJECTED`, `CANCELLED`, `EXPIRED`.

- Create→DRAFT. Submit DRAFT→CHECKING→WAIT_EXTERNAL/NEED_INFO/MANUAL_REVIEW/PREAPPROVED/REJECTED. CHECKING is a real history step; synchronous response can return final resulting state.
- WAIT_EXTERNAL→CHECKING on retry. NEED_INFO with an open trusted_source request also permits retry-check→CHECKING using stored submission BKI consent for BKI, attempting the named mock once. Missing again→NEED_INFO; unavailable→WAIT_EXTERNAL with the request unresolved; valid fresh trusted-source evidence resolves the request (`resolved_at=now`) and creates a new evaluation, then MANUAL_REVIEW even if low risk (R2/R6/R7 mandatory rejections still apply). Preserve application ID/assignee and old evidence. Later retries from WAIT_EXTERNAL retain this return-to-review rule while that request is unresolved. No maximum-retry rejection or hidden timed loops.
- MANUAL_REVIEW→NEED_INFO on officer request; NEED_INFO with kind=client_answers→MANUAL_REVIEW when client responds, recording responded_at/resolved_at and retaining ID, previous evidence and assignee. No automatic low-risk shortcut after a requested answer; officer reviews it. `missing_fields` and `open_info_request` make recovery concrete. System-generated NEED_INFO may have no assignee, queue it on response.
- MANUAL_REVIEW→PREAPPROVED/REJECTED by assigned officer. A null/noncomputable limit forbids preliminary approval until supplied finance yields a calculable limit; rerun scoring after responses when needed. After an information response, recompute calculable score/limit from the revised answers and latest trusted source evidence, preserving original snapshots, retain all conflict/declaration flags and MANUAL_REVIEW; officer reason records resolution. Medium risk is allowed by officer; R2/R6/R7 cannot be overridden. Officer amounts satisfy product_min≤amount≤min(request,scored_limit); original requested amount is never rewritten.
- PREAPPROVED→DOCS_UPLOADED on complete checklist. DOCS_UPLOADED→DOCS_REWORK on rejected required document; DOCS_REWORK→DOCS_UPLOADED on all required documents replaced/present. Uploads do not auto-complete the packet.
- DOCS_UPLOADED→APPROVED by assigned officer only after all current required docs accepted. Final amount must satisfy product_min≤final≤preapproved and remain within verified collateral/turnover bounds. Incomplete/unaccepted docs make approval409. PREAPPROVED/DOCS_UPLOADED/DOCS_REWORK→REJECTED by assigned officer with reason; rejection does not require complete or accepted documents.
- DRAFT, WAIT_EXTERNAL, MANUAL_REVIEW, NEED_INFO, PREAPPROVED, DOCS_UPLOADED, DOCS_REWORK→CANCELLED by owner. CHECKING cancellation serializes until check transaction ends. APPROVED/REJECTED/CANCELLED/EXPIRED terminal; no edits/actions except authorized reads/downloads and approved handoff.
- PREAPPROVED, DOCS_UPLOADED and DOCS_REWORK→EXPIRED once `now >= preapproved_at+14*24h`. Deadline never extends with uploads/rework/claim. Enforce on every relevant read/command (lazy expiry plus optional scheduled sweep), append exactly one history/notification. APPROVED never subsequently expires. New application required after expiry; no revive command.

One active submitted application per company/product in CHECKING, WAIT_EXTERNAL, MANUAL_REVIEW, NEED_INFO, PREAPPROVED, DOCS_UPLOADED, DOCS_REWORK. Multiple DRAFT allowed; submission conflict 409 `DUPLICATE_ACTIVE_APPLICATION` with existing ID for same owner. DB constraint/lock enforces races, not just UI. Lazy expiry runs before duplicate check. Each state change records actor, UTC time, reason, revision and simulated notification; same-state edits/claim can increment version without inventing a status transition. No arbitrary status PATCH endpoint.

## Customer and officer command APIs

`application` returns public fields, answers, latest evaluation, allowed_actions[], missing_fields[], open_info_request?, document_summary, product summary; never storage key or internal secrets. `GET /applications/{id}/history` returns ordered history. Staff detail additionally returns source snapshots, factors, decisions, claim owner and documents. Persisted company/source fields are authoritative; client only submits questionnaire fields.

| Method/path | Input and response |
|---|---|
| POST `/applications` | `{company_id,product_id,recommendation_snapshot_id}` + key →201 `{application}`; selected product must occur in owned snapshot, research IDs 422 |
| GET `/applications` | owned list; optional status/company_id filter |
| GET `/applications/{id}` | `{application}` |
| GET `/applications/{id}/dialog` | stage contract above |
| PATCH `/applications/{id}/answers` | `{version,current_stage,answers:{partial whitelist}}` → `{application}`; DRAFT only; deep-merge stage fields, forbid state/product/company/snapshot mutation |
| POST `/applications/{id}/submit` | `{version,consents:[{code,version,accepted:true}]}` + key → `{application}` |
| POST `/applications/{id}/retry-check` | `{version}` + key; WAIT_EXTERNAL or NEED_INFO with an open trusted_source request; stored submission BKI consent required for BKI retry → `{application}` following recovery transitions above |
| POST `/applications/{id}/respond-info` | `{version,response,answers:{requested fields only}}` + key; NEED_INFO with kind=client_answers only; trusted_source request returns409 `TRUSTED_SOURCE_REQUIRED`, never accepts client BKI fields; response 1–2000 chars → `{application}` in MANUAL_REVIEW |
| POST `/applications/{id}/cancel` | `{version,reason}` + key → `{application}` |
| GET `/applications/{id}/history` | `{items:[StatusHistory]}` |
| GET `/officer/applications` | filters status, assignee (`me\|unassigned`), company_id; `{items,total}` scoped by officer role |
| GET `/officer/applications/{id}` | `{application,evaluations,source_evidence,decisions,documents}` |
| POST `/officer/applications/{id}/claim` | `{version}` + key; unassigned or same officer; 409 `ALREADY_ASSIGNED` if other assignee; returns `{application}` |
| POST `/officer/applications/{id}/request-info` | `{version,reason,requested_fields:[answer paths]}` + key; MANUAL_REVIEW only; create InfoRequest/decision and NEED_INFO |
| POST `/officer/applications/{id}/preapprove` | `{version,amount_rub,reason}` + key; MANUAL_REVIEW only; R12 bounds above |
| POST `/officer/applications/{id}/reject` | `{version,reason}` + key; MANUAL_REVIEW (preliminary) or PREAPPROVED/DOCS_UPLOADED/DOCS_REWORK (final); no completeness/acceptance prerequisite; persist phase preliminary/final |
| POST `/officer/applications/{id}/approve` | `{version,amount_rub,reason}` + key; DOCS_UPLOADED only, final guards above |

All officer mutations except initial claim require assignee=session officer; reasons 1–2000 chars after trim. Auto-preapproved applications start unassigned and are claimable in document phase. Claims allowed MANUAL_REVIEW/NEED_INFO/PREAPPROVED/DOCS_UPLOADED/DOCS_REWORK. Claiming never changes status. Competing claim/decision uses row lock/version, replay cannot create second decision. No silent reassignment. Staff queue excludes DRAFT by default. Client cannot use staff routes; staff cannot use client commands to impersonate owner.

## Documents and final decision

Required all products: `BANK_STATEMENT`, `FINANCIAL_REPORT`. Secured adds `COLLATERAL_OWNERSHIP`, `COLLATERAL_VALUATION`. These are synthetic evidence, not real bank legal requirements. Current period end from questionnaire, no hidden recency rule; officer reviews declared period and content. Each requirement has one current document; replacements supersede old metadata/content access remains authorized, rejected required document must be replaced. Accepted documents cannot be silently replaced; allow replacement of UPLOADED/REJECTED only before final state. Upload/delete allowed PREAPPROVED or DOCS_REWORK; DOCS_UPLOADED freezes packet until review/rework. Missing optional document cannot block approval. All mandatory docs must exist at complete and all must be ACCEPTED at approve. Officer acceptance of COLLATERAL_VALUATION requires positive `verified_value_rub`, persisted atomically on that Document row with ACCEPTED status/reviewer/time. Other document types and rejected/unreviewed valuation revisions keep the field null. Final approval reads the persisted current ACCEPTED COLLATERAL_VALUATION document revision and recalculates the secured bound with the same LTV/turnover rule, never client declaration or a new approve-request value. That accepted revision/value is immutable and remains readable after process restart; replacement revisions start with null verified value and cannot inherit prior acceptance. If below minimum → final reject with reason, never fabricate support.

| Method/path | Input and result |
|---|---|
| GET `/applications/{id}/documents` | `{requirements:[{document_type,required,current_document?}],items:[public Document]}` |
| POST `/applications/{id}/documents` | multipart `file,document_type,version`; header key →201 `{document,application}` |
| GET `/applications/{id}/documents/{doc_id}/download` | authorized streaming attachment, nosniff; owner or officer; no public URL |
| DELETE `/applications/{id}/documents/{doc_id}` | `{version}` + key; unaccepted current file in allowed upload states → `{application}` |
| POST `/applications/{id}/documents/complete` | `{version}` + key; PREAPPROVED/DOCS_REWORK with required current nonrejected docs → `{application}` DOCS_UPLOADED |
| POST `/officer/applications/{id}/documents/{doc_id}/review` | `{version,decision:"accept"\|"reject",reason,verified_value_rub?}` + key → `{document,application}`; DOCS_UPLOADED only; reject moves DOCS_REWORK |
| POST `/integrations/alfa-business/link` | `{application_id}` + key → `{url:"/demo/alfa-business/{id}",simulated:true}`; APPROVED only, owner only |

File constraints: single file ≤20 MiB, only PDF/JPEG/PNG, extension/MIME/magic/content agree; reject HTML/SVG/script/polyglot content, empty/invalid/truncated formats and executable archives. Use a maintained parser for structural validation; no claim of antivirus. Ignore upload paths; generate random private storage key outside webroot, sanitize attachment filename; cleanup failed/rolled-back uploads and handle deletion consistently. Stream with safe Content-Disposition. Maximum one current file per requirement. Retain SHA-256 of actual bytes; seeded structured oracle hashes are not file hashes. Review labels say «Демонстрационная проверка документов». Handoff is an authenticated local page confirming simulation, no bank redirect/signing/disbursement. APPROVED does not mean money issued.

## Analytics and honest evidence

A comparison run uses the same catalog and fixture data in both modes. Baseline shows ordinary fixed-order supported cards and calculator, guided uses ranked explanations; both can submit. No real study results exist at spec creation. Held-out task answer keys in `data/demo-companies.json:held_out_tasks` are predeclared product-choice criteria authored before recommendation engine outcomes, not generated from its output. They are an uncalibrated domain answer key, not statistical validation. Commit hash of this Task 1 dataset is answer_key_version; later tooling records it and cannot rewrite keys to match recommendations. Keep answer key server-side and omit it from experiment task payload until completion.

| Method/path | Input/result |
|---|---|
| POST `/analytics/runs` | `{task_id,mode}` →201 `{run_id,task,started_at,cohort_id,is_synthetic}`; task excludes answer; server versions/cohort |
| POST `/analytics/events` | `{run_id,client_event_id,name,application_id?,payload}` →201 `{event_id,recorded_at}`; replay event ID deduplicated; ownership enforced |
| GET `/officer/analytics/summary` | role-gated aggregates, by mode/cohort/task/is_synthetic; counts, denominators, null if no evidence |

Allowlist event names: `task_started` (empty payload), `product_selected` (`product_id`), `application_created` (empty), `application_submitted` (empty), `task_completed` (selected_product_id), `task_abandoned` (reason_code `explicit_exit|timeout_observed`). Payload size≤4096 UTF-8 bytes, no arbitrary nested free text/PII, all unknown keys rejected. `application_id`, when supplied, must be owned and its company match run fixture; event cannot manufacture business state (derive application_created/submitted success from backend or validate actual persisted state). Run owner is session client; officers only aggregate. Cohort derived by server from demo/experiment configuration; caller cannot claim real-user cohort. Default runs synthetic. Server-generated UTC timestamps, no caller duration/success fields. Task_started exactly once at creation (server event), repeated first-party event is idempotent; selected product supported; completed once, must match latest selection. Duration=completed_at−started_at on server, report median and N. Correctness compares selection against frozen answer key; report correct/N completed and completion/comparison started. Observed abandonment only explicit event; incomplete run is incomplete, not proof of abandonment. No event generation before consent to optional comparison participation (simple explicit start UI).

Summary separates executed technical tests, synthetic/automated task trials, any actual consenting human observations, and modeled business impact. Never mix cohorts/denominators or label bots as users. Empty data → no observations, null medians/rates. Business model shown independently with editable assumptions: `incremental_revenue = monthly_visitors * (guided_completion_rate - baseline_completion_rate) * approval_rate * funded_share * average_principal_rub * net_revenue_rate_bps / 10000`. Inputs displayed as assumptions with source `modeled` unless real evidence supplied. Negative differences remain negative; no forced uplift. Modeled revenue is not bank revenue measured by this demo; no final disbursement measurement exists.

## Verification boundaries and implementation gate

`docs/test-scenarios/acceptance.md` defines exact numerical boundaries, historical mapping and future end-to-end cases. Task 1 verification checks JSON syntax/consistency, checksums, fixture math and contract completeness only. It does not claim application integration passes. Downstream tests must execute real HTTP/DB/browser paths and assert mocks, authorization, revisions and file bytes, independently of stored expected labels. Reusing a policy function to generate its own expected answers is not an independent oracle. No production pricing/legal/compliance/approval validity is claimed.
