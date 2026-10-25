# Demo decisions — 2026-10-24

Authority: [canonical contract](superpowers/specs/2026-10-24-credit-route-design.md), `demo-spec-v1`. These are bounded MVP choices, not verified bank policy.

| Ruling | Reason and consequence |
|---|---|
| FastAPI + React/TypeScript/Vite + PostgreSQL; no Spring implementation | User-selected stack; obsolete README placeholders replaced. |
| Exactly three application products; archive all nine research entries separately | A full catalog is retained without pretending unsupported products have executable rules. Demo JSON alone drives calculations. |
| Unsecured term 300k–3m, 6–36m, 23.50%; revolving 300k–3m, 6–18m, 24%; secured 500k–6m, 12–60m, 21.50% | Explicit demonstration rates/ceilings. Historical 100k single product and research catalog ceilings do not govern new applications. Revolving has no renewal; interest at full utilization, principal at maturity. |
| Low-risk capacity min(product ceiling,3R); medium min(product ceiling,1m,R); secured additionally 70% declared/verified collateral | Prevents catalog maxima being sold as personal capacity. Unknown turnover/collateral yields null, never a promise. Secured limit is declared until document review. |
| Purpose, pattern and amount suitability precede indicative price; avoid collateral when unnecessary | A cheaper secured rate must not outrank an adequate unsecured product merely on price. Deterministic ties use product ID. |
| No score/BKI before explicit submitted consent | Recommendations use turnover upper bound, never a claimed likelihood of approval. Founder majority is not guarantor consent; simplified demo omits sureties rather than fake their verification. |
| Original factors and R1–R12 retained; OFFERED becomes PREAPPROVED | Preliminary approval requires documents/officer final decision. Low-risk smaller amount R9 retained. Product-specific R1/R7 replace historical minimum/term checks. |
| Missing declared data recoverable, unavailable source WAIT_EXTERNAL, finance anomalies manual | Retry uses controlled fixture recovery, not real services. Client-answerable NEED_INFO retains application/assignee and returns MANUAL_REVIEW. Trusted-source gaps create system-authored requests (nullable officer) and retry the named mock with stored consent, returning review with fresh trusted evidence. Missing consent blocks submit with 422 without BKI. |
| Six guided stages, synthetic representative confirmation instead of passport/OTP/signature | Preserves usable analyst journey without collecting real PII or implying legally effective signing. |
| Opaque 12-hour server sessions; body integer revision; command Idempotency-Key | One simple concurrency/auth contract, no parallel ETag convention or browser token storage. Row locks and partial active uniqueness guard races. |
| Preapproval expires after 14 exact days, including documents/rework | Immutable deadline; expired cases cannot get final approval. Final APPROVED is terminal. |
| BANK_STATEMENT + FINANCIAL_REPORT, secured adds ownership + valuation | Small deterministic checklist; accept is a visibly simulated officer review. Valuation acceptance persists verified value on the accepted current document revision; final LTV reads that immutable evidence. Rejection does not require accepted/complete documents. |
| Fixture business date 2026-10-24; current UTC clock for sessions/expiry/events | Stable age/scoring without creating already-expired live demo cases. Nine generated-checksum INNs are mocks, not asserted unassigned numbers. |
| Optional controlled comparison has server-side frozen answer key, synthetic cohort by default | Key committed before engine outcomes. Counts/denominators are technical observations, not proof of real-user or revenue uplift. Financial benefit is a separate editable formula. |

Production pricing, banking/legal conditions, real data permissions, calibrated risk and abuse/file security operations remain future work; no implementation task should silently widen the demo to those integrations.

## Task 3 rulings (recommendations)

Reversible implementation choices made while building the preliminary calculator; the canonical contract above still governs.

| Ruling | Reason and consequence |
|---|---|
| An unconfirmed registry blocks `can_apply` and any `fits`, but the indicative limit and payment stay visible | The contract nulls a payment only when it is unknown or incompatible, and says turnover may be known while the registry is unknown. An inactive company is incompatible and gets no payment. |
| A missing payment always carries its reason in `payment_note` | Null alone reads as an error; the note names the gap (inactive company, incompatible parameters, unknown turnover or collateral, estimate below the product minimum). |
| Every economic number is read from the product policy (revenue multiple, collateral LTV, minimum draw, rates) | A policy change in a new catalog version must change estimates without a code edit; snapshots keep the versions they were computed under. |
| Revolving interest uses integer ceiling arithmetic, term-loan annuities use Decimal half up | A rounded monthly rate can push an exact whole-ruble interest total up by one; the annuity has no exact-integer boundary. |
| «Обычный каталог» is the baseline: the same server figures in fixed catalog order, with no rank, status, reasons, alternatives or criteria | The later comparison needs identical data with guidance removed; the display mode is local UI state until Task 7 assigns it per run. |
| The UI archive list hides the three research entries that reuse a supported product id | They share an id with a live demo product but carry different unverified parameters; the API still returns all nine with `can_apply=false`. |
| One snapshot is saved per calculator edit (after a 300 ms debounce) | The contract wants a saved snapshot id for each estimate; there is no pruning or rate limit in the demo. |

## Task 4a rulings (applications backend)

Reversible choices made while building the questionnaire, submission and scoring API; the controller's binding decisions (lazy expiry placement, respond-info in Task 5, allowed actions, debt as a client answer, attempt-indexed BKI recovery, check order) are in the SDD ledger and the canonical contract.

| Ruling | Reason and consequence |
|---|---|
| A known BKI overdue of 30 days or more rejects (R2) even when the history category is missing | R2 precedes R3 in the spec's rule table, and a retry for the missing history could not change a mandatory stop. The fixtures never combine both. |
| A known turnover source value stays authoritative and is the scored value; a client override is kept beside it and routes R5 | "Persisted company/source fields are authoritative": an inflated override cannot raise the scored limit an officer works within. A value the source lacks is scored as declared and routes R5. A missing turnover source still reports its period end, so that prefill is tagged `source`. |
| A known inactive company's submission persists both consents and goes DRAFT→CHECKING→REJECTED | The submission was accepted for processing with valid consents; no BKI request is made. Missing answers do not block it (known inactive overrides missing finance). |
| Drafts can be created for any supported product in an owned snapshot, whatever `can_apply` says | The contract makes `can_apply` a UI gate and has an unconfirmed-registry case reach the R4 check on submission. `allowed_actions` omits `submit` for a known inactive company. |
| Submit checks conflicts before input: version, draft, current policy, duplicate active application, then R1, consents, R3 | A state conflict cannot be fixed by editing answers. Lazy expiry of the other applications runs inside the duplicate check. |
| One command increments the version once; the check result is a system history step | DRAFT→CHECKING (client) and CHECKING→outcome (system, actor null) share one revision, matching "successful changes increment it once". |
| A command that is the first touch after the preapproval deadline returns a committed 409 `APPLICATION_EXPIRED` | A raised error would roll the lazily recorded expiry back; the refusal now persists exactly one EXPIRED row. |
| Trusted-source recovery records the computed rule (for example R8) with outcome MANUAL_REVIEW | The evaluation shows what scoring alone would decide while the forced review is explicit in its outcome and reasons; R2/R6/R7 still reject. |
| `indicative_limit_rub` is recomputed at submission from current sources (the low-risk upper-estimate formula) | Old estimates must not promise capacity; the draft keeps the snapshot's figure until then. |
| Retry-check evaluates under the product policy pinned at submission | Submitted decisions are never silently migrated to a later policy. |
| Open info requests are shown only while the application is in progress | A terminal application has nothing to answer; the rows stay unresolved as audit evidence. |
| The client-answers NEED_INFO of a submitted check is reachable only through an internal check | Submission already blocks missing answers with 422, so the defensive path is exercised by a service-level test, as the acceptance note on missing_turnover asks. |

## Task 4b rulings (customer applications UI)

Reversible presentation and interaction choices made while building the questionnaire, consent, status and list screens; the controller's 4b rulings and the canonical contract govern.

| Ruling | Reason and consequence |
|---|---|
| The card keeps its line «Можно начать анкету: …» and adds one «Начать анкету» button under it, only where `can_apply`, in both display modes | The line already explains availability; the button is the card's single action. The plain catalog baseline can also submit, as the comparison requires. |
| An application command reuses its idempotency key only when repeated with an identical body after an unknown outcome (network error or 5xx); success or a 4xx releases it | Unlike the company retry, which re-sends its original body, a changed body (a newer version the UI has learned) gets a new key, so no repeat can be refused as `IDEMPOTENCY_CONFLICT` and none can act twice. |
| Every stage change saves the open stage and the stage pointer (a PATCH even with no changed answers); there is no per-keystroke autosave | Resume must land on the server's `current_stage`; each save costs a PATCH and a dialog reload. The wizard's «← Мои заявки» link saves the open stage first and reloading or closing the tab asks while edits are unsaved; leaving through the sidebar or browser history does not save the open stage's edits. |
| Only type errors block a partial save; product-bound corrections and missing answers block submission | Partial saves are allowed by contract. Corrections show next to saved values at once, gaps once the customer has left the stage, and the review lists every blocker with a link to its stage. |
| A stale-version reply reloads the dialog and keeps the customer's unsaved edits on top of it | "Nothing is lost silently": the newer saved answers appear, the edits stay visible, and the next save carries the new version. |
| The two submission consents live only in the review view: unchecked on every arrival at stage 6 | Never pre-checked or stored between visits; leaving the review (for example to change an answer) asks for them again. `accuracy_confirmed` is an ordinary saved answer. |
| Status amounts: requested, preliminary estimate (hidden after a rejection), preliminary approval, final when present; the demo score and scored limit appear only inside «Результат проверки» | Each figure has its own label and caveat; a rejected application does not show an estimate that reads like available capacity. |
| Timeline actors: own id → «Вы», null → «Система · демо-проверка», any other → «Сотрудник банка» | The customer history still returns raw actor ids until Task 5a maps roles; no id is displayed. |
| An open info request shows its question; a client-answers request adds that answering arrives at a later demo stage | Respond-info is Task 5; the customer is told rather than shown a dead form. |
| Server-written texts get non-breaking spaces inside digit groups and before «₽» on the client | The backend's ASCII grouping (a ledgered Task 3 minor) would otherwise let amounts wrap mid-number; backend behaviour is unchanged. |
| The applications feature has its own stylesheet; the extracted card's action styles sit beside the card rules in `styles.css` | `styles.css` is already over 2,000 lines; the new screens are one responsibility. |
| The stale-recommendation paths are tested by answering single requests with the documented 409 | The live catalog only becomes stale when the policy file changes, which this task must not do; every other browser assertion runs against the real API. |
