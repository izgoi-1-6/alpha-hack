# Acceptance and evidence contract

Policy: [canonical spec](../superpowers/specs/2026-10-24-credit-route-design.md). Inputs in `data/demo-companies.json` are frozen at business date 2026-10-24; app wall time is injectable/current. The expectations below predate application implementation. They are test specifications, not claims that backend/browser tests ran.

## Fixture outcomes

All fixtures owned by `client@demo.local`; use `other@demo.local` for unauthorized reads. Officer is `officer@demo.local`. Synthetic password `DemoCredit2026!`; never use these accounts outside local demo.

| Fixture | Facts and need | Expected after valid submission |
|---|---|---|
| strong | LLC, age48, R800k/P680k/debt160k, clean, 2m one-time/12m | score100, low, R8 PREAPPROVED 2m; indicative/scored unsecured limit2.4m |
| medium | IP, age18, R600k/P600k/debt240k, clean, repeated500k/12m | score65, medium, R10 MANUAL_REVIEW; upper estimate1.8m, scored limit600k; line first |
| high_risk | IP, age4, R300k/P375k/debt180k, minor_closed, 300k | score10, R6 REJECTED; pre-estimate does not know BKI risk |
| inactive | LLC inactive, otherwise strong | precheck read-only; server R2 REJECTED if draft submitted after status changes; no BKI |
| missing_turnover | IP, current/previous turnover null | estimates null, can draft; raw submit 422 missing required fields; discovered submitted source gap R3 NEED_INFO; declared values → MANUAL_REVIEW |
| registry_unavailable | registry unknown/unavailable | no fits, submission check R4 WAIT_EXTERNAL; retry recovers active → CHECKING→PREAPPROVED |
| secured_investment | LLC, R1.5m/P1.25m/debt300k, collateral8m, investment4m/36m | score100, secured indicative/scored min(6m,4.5m,5.6m)=4.5m; R8 PREAPPROVED4m |
| bki_missing | IP otherwise strong, successful BKI payload omits history category | R3 NEED_INFO, system trusted_source request; retry uses stored consent and recovered clean history→score100/limit2.4m→MANUAL_REVIEW, same application/assignee; client cannot supply BKI fields |
| bki_unavailable | IP otherwise strong; BKI unavailable | no BKI in recommendations; submit WAIT_EXTERNAL; retry one call recovers → PREAPPROVED1m |

`expected_check_outcome` fields are oracle labels. For missing_turnover/inactive/registry_unavailable, they describe defensive check outcomes when the check is reached, not bypassing UI/submit validation. Drivers must test both UI gating and internal check outcomes separately.

## Exact numerical boundaries

Independent verifier must use integer/Decimal arithmetic, not application helpers. Age completed calendar months: 2026-04-24→6 on fixture date, 2026-04-25→5; 2024-10-24→24, 2024-10-25→23. Age points: 5→0,6→10,23→10,24→20. With P100,000: R89,999→0 growth points;90,000→15;110,000→15;110,001→25. With R100,000: debt30,000→30 points;30,001→15;50,000→15;50,001→0. History clean25/minor_closed10/serious0. Score49→high,50→medium,74→medium,75→low; attainable examples scores45,50,70,75 verify real factor combinations. BKI current overdue29 is not the R2 stop;30 is. Zero R/P or imported negative debt→R5 with no division/automatic limit.

Each product boundary is inclusive: amount_min−1 invalid, min valid, max valid, max+1 invalid; term_min−1 invalid, min/max valid, max+1 invalid. Unsecured R800k low limit2.4m: request2,399,999 and2.4m R8;2,400,001 R9 with2.4m. Medium R600k:600k R10;600,001 R11. Low R99,999 capacity299,997 is below unsecured min300k→R7;R100k capacity300k is exact minimum. Secured declared value1m gives collateral cap700k; low R800k limit700k. Collateral value714,285→499,999 cap (<500k),714,286→500,000 (min). Unknown/none collateral→needs_info, null secured limit and payment. Unknown turnover→null for every product. Secured fixture company limit4.5m must remain below catalog6m even though declared LTV cap5.6m. Final verified collateral5m cap3.5m: cannot approve original4m, may approve≤3.5m with reason. No final amount may exceed preapproved/request/turnover/collateral bounds.

Term-loan payment at 1m/12m/23.50% rounds to94,318 RUB; revolving full-utilization monthly interest at1m/24% is20,000 RUB, plus principal at maturity. All comparisons preserve original requested amount even when preapproved lower. Deadline preapproved2026-10-24T12:00:00Z→expires2026-11-07T12:00:00Z; final approval at11:59:59 allowed if complete,12:00:00 denied/EXPIRED. Upload/rework never extends deadline.

## Genuine implementation acceptance scenarios (execute later)

| ID | Driver and assertions |
|---|---|
| A01 | HTTP+DB: register/login/logout/session expiry, reject role injection, Origin mismatch/absence, invalid/all-zero/checksum INNs, valid non-demo INN422 REGISTRY_NOT_FOUND with correction path; no browser storage token; reload retains session. |
| A02 | HTTP+DB: company list/read/retry scoped to owner; other client gets404 for company, snapshot, application, history, file; client gets403 for every staff mutation/aggregate. |
| A03 | Service+HTTP: all product bounds, stable ranking for one-time/repeated/investment, missing collateral/turnover/registry; zero BKI calls before submission; all six informational research IDs refuse application creation. |
| A04 | HTTP+DB: saved stage answers survive reload; missing consent/field422, no BKI; high/low/medium and R2/R5/R7/R9 match exact inputs; one submit call/evaluation when replayed; changed body same key409. |
| A05 | Concurrent HTTP+PostgreSQL: two drafts race to submit same company/product→one success, one409 existing ID; two officers race claim→one assignee; stale revision409; terminal history permits new submission. |
| A06 | HTTP+DB+browser: medium submit→claim→request-info→same ID owner response→MANUAL_REVIEW same officer→preapprove≤600k, requiring reason; insufficient/null finance cannot be preapproved; no arbitrary state PATCH. |
| A07 | HTTP+DB: registry/BKI unavailable→WAIT_EXTERNAL; retries consume one recovery response and preserve history, do not duplicate decision; missing finance response returns review, known conflict visible. |
| A08 | Real upload bytes+private storage: reject >20MiB, wrong magic/MIME/extension, HTML/SVG/disguised/truncated file, traversal names; no files outside private store; unauthorized download404; SHA is actual byte hash; rollback cleanup. |
| A09 | Browser+HTTP: strong preapproval→two required uploads→complete→officer rejects file→DOCS_REWORK→replacement→complete→all accept→final APPROVED→local simulated handoff; original rejected file remains audit evidence. |
| A10 | HTTP+clock: incomplete/unaccepted docs deny approve, secured requires four and verified value; all preapproved doc states expire exactly once at deadline; no expiry on approved; final file replacement denied. |
| A11 | HTTP+DB: idempotent officer replay one decision, stale or competing officer forbidden; preapproved/final amounts independently bounded; cancellation terminal; clients cannot manufacture BKI/history/score. |
| A12 | HTTP+browser: baseline/guided see same fixture/catalog; events allowlisted/≤4KiB, unknown fields rejected, run/application ownership checked, server timestamps/cohort, replay dedup, held-out answers hidden; empty summary nulls. |
| A13 | Controlled synthetic trials run three held-out tasks in both modes; compute correct/N completed, completion/N started, median server duration/N; label synthetic. No claim of human behavior or revenue uplift. |
| A14 | HTTP+DB+process restart: submit bki_missing→system NEED_INFO with null officer_id/kind=trusted_source/source=bki/empty requested_fields; respond-info409 TRUSTED_SOURCE_REQUIRED; retry with stored consent→fresh mock clean evidence→MANUAL_REVIEW same ID/assignee, score100/limit2.4m, old evidence retained; replay no second source call/evaluation. Secured valuation review persists positive verified_value_rub on accepted current revision; restart and approve still enforce3.5m cap from verified5m, never original8m declaration. Missing/rejected/superseded valuation cannot approve. Assigned officer can reject PREAPPROVED/DOCS_UPLOADED/DOCS_REWORK with incomplete/unaccepted docs and reason; same conditions deny approve. |

Use genuine PostgreSQL constraints/transactions for concurrency tests, backend for HTTP integration, and browser against live frontend/backend for UI acceptance. A test using SQLite alone is not evidence of PostgreSQL race correctness. Fixture validator only checks its own oracle, not these scenarios.

## Mapping historical oracle/flow tests

Original notebook/fixture requirements were 100k–3m,6–36m and OFFERED→SIGNING→ISSUED. Do not copy them unchanged or claim they passed new endpoints.

| Old IDs | New lifecycle/expectation |
|---|---|
| T1,T2,T8,T18 | R8/R9 preserved; OFFERED→PREAPPROVED. T18 exact capacity is inclusive. No final approval without docs. |
| T3,T4,T9,T11 | R10/R11 MANUAL_REVIEW, preserve score/limit; T9 requested250k must become300k to fit new unsecured minimum. |
| T5,T10 | R6 retained; requested200k must become300k to reach score rule with new minimum. |
| T6,T12 | R2 retained; diagnostic scores not asserted as executed score; inactive UI blocks, test defensive R2 through changed registry/internal check. |
| T7A/B | Missing finance: UI blocks submit, backend422; if missing discovered after submission NEED_INFO; same application response→MANUAL_REVIEW. |
| T13A/B | Old term48 was invalid; still invalid unsecured36 max, valid secured if other parameters meet policy. Test against selected product, not global max. |
| T14,T20 | R5 anomaly retained. Negative debt API input422; R5 applies corrupt imported negative data. |
| T15 | R4 WAIT_EXTERNAL; explicit retry recovery replaces old 5/15s retry schedule. |
| T16A/B | Unchecked BKI consent blocks UI/backend422, no BKI; does not create a submitted NEED_INFO case. |
| T17 | Old request100k changed to300k to test R7 rather than R1; low turnover limit still below product min. |
| T19 | R12 staff preliminary decision600k→PREAPPROVED, then separate document/final flow. |
| NF (14 source cases) | Retain onboarding/estimates/recovery intent; after preapproval collect docs. Old document-before-score/signing/issued expectations replaced by A06–A10 and simulated handoff. |
| D (10 source cases) | Retain replay, idempotency, ownership, concurrency intent; adapt tokens/ETags to cookie/session and body version; partial active uniqueness excludes DRAFT/terminal. |

At source research time, the original validator checked 26 core variants for internal consistency; NF14/D10 only had structural checks. Those counts are not backend passes. Task 1's preserved verification independently checks new data/math/doc coverage. Genuine integration/browser results must be added later with exact executed commands, environment, counts, failures and limits.

## Frozen held-out comparison protocol

Task IDs `comparison-working-capital`, `comparison-single`, `comparison-investment` contain human-authored expected choices and criteria in JSON before engine implementation. Task1 commit SHA freezes answer_key_version. Do not compute answer keys by calling recommendation code. Counterbalance synthetic run order baseline/guided to exercise instrumentation, never present speed of automation as human task speed. A real consenting participant study, if separately run, must label cohort, participant count, order, duration measurement, missing observations and avoid conflating repeated trials with people. Model financial assumptions separately; no observed signing/funding/revenue exists.
