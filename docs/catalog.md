# Product catalog and demo policy

The app's loan products come from two files, validated together when the API starts:

| File | Holds | Version |
|---|---|---|
| `data/credit_catalog.json` | Product facts: amounts, terms, rates, purposes, eligibility, display texts. A copy of the user's `credit_catalog_updated.json` with the planned additions. | `catalog_version` (`2026-10-25.1`) |
| `data/demo-policy.json` | Demo decision rules and fallbacks for catalog nulls; ranking, payment models, slider, badges. | `rules_version` (`demo-rules-v2`) |

The catalog is authoritative. The policy fills a catalog `null` and may tighten a stated value, never weaken it. `data/catalog.research.json` is history only; nothing reads it. The paths can be overridden with `CREDIT_CATALOG_PATH` and `DEMO_POLICY_PATH`.

## Validate an edit

```sh
cd backend
.venv/bin/python -m app.products_config check                      # the files the app loads
.venv/bin/python -m app.products_config check --catalog /tmp/c.json --policy ../data/demo-policy.json
```

It prints `OK: catalog 2026-10-25.1+<sha8>, rules demo-rules-v2+<sha8>, 11 products, 1 overlay`, or every problem with its path and exit code 1, for example:

```
Config errors (2) in ../data/credit_catalog.json / ../data/demo-policy.json:
  items[psk_invest_subsidy].rate.periods[0].rate_percent: 11.0 does not equal KEY_RATE - 3.5 = 10.5
  items[alfa_factoring].amount.max: null, no policy fallback
```

The API refuses to start with the same messages. After a valid edit, restart the API (it loads the files once). Versions are stamped with a content hash (`catalog_version+sha8`, `rules_version+sha8`), so any edit, even without a version bump, makes saved recommendations and drafts stale: creating or submitting from them returns 409 `RECOMMENDATION_STALE` and the client recalculates. Submitted applications keep the product they pinned. Bump `catalog_version` or `rules_version` when the change is meaningful to readers.

## How the runtime products are built

- **Card products** are catalog items whose `kind` is one of the policy's `applyable_kinds` (`product`, `gov_program`) and `display.as` is `card`. All are shown and evaluated; a product accepts applications (`applyable`) when `status` is `active` and `limit_status` is `open`.
- **Overlays** (`kind: overlay`, `display.as: badge_on_card`) become badges on the cards in their `display.applies_to`.
- **Effective terms.** Each of amount min/max and term min/max is the policy's per-product setting (`products.<id>`) if present, else the catalog value, else the policy default (`defaults.amount_min_rub`, `amount_max_rub_if_null`, `term_min_months`, `term_max_months`). A per-product setting for a stated catalog value must tighten it (a higher minimum, a lower maximum). `term.unlimited: true` means no term. `amount.max_unsecured` caps lending without collateral (the universal limit's 20,000,000); `term.max_months_by_purpose` caps one purpose's term inside the range. The runtime product lists the fields the policy filled in `fallbacks`.
- **Collateral mode.** `collateral.required: true` → `required` (the policy cannot weaken it); `false` → `none` unless the policy sets `optional` (or `required`); `null` needs a policy `collateral_mode`.
- **Rates.** One rate period from month 1. `rate_formula` is `KEY_RATE`, `KEY_RATE + n`, `KEY_RATE - n` or a number, read from `params.key_rate.value_percent` without `eval`; the result must equal `rate_percent` and be whole basis points. A period whose `to_month` ends before the product's longest term is a preferential rate (the payment says «в льготный период N мес.»). `type: undisclosed` has no percent and no payment («Ставка уточняется»).
- **Eligibility** is machine-checked only for the entity type (via the policy's `entity_types` map), `msp_registry_required`, `regions_allow` (normalised by the policy's `region_normalization`) and `okved_deny_main` entries that start with a two-digit class `NN` or a range `NN–NN` (compared on the company's main OKVED class). Everything else — free-text OKVED restrictions, an entry that starts with a subclass such as `47.11` (it names only part of a class), `categories`, `requirements` — becomes `conditions_to_confirm` on the card and never blocks.
- **Explanation texts.** Every card product needs `display.summary`, 3–5 `display.features` and `display.best_for`, drafted only from the item's own facts (no new claims, no «демо» wording).

## Policy settings

| Key | Meaning |
|---|---|
| `entity_types` | Catalog entity names to company types (`ИП`→`IP`, `ЮЛ`→`LLC`). |
| `applyable_kinds` | Catalog kinds shown as products. |
| `defaults` | Fallbacks for nulls, revenue multiples and the medium-risk cap, LTV (bps), base and collateral documents (from the four document types), default priority. |
| `payment_models` | Per instrument type: `annuity`, `interest_full_utilization` or `none`. Every card product's instrument type needs one. |
| `payment_estimate_term_months` | The term the card's indicative annuity uses, clamped to each product's term range (36). |
| `products.<id>` | `amount_min_rub`, `amount_max_rub`, `term_min_months`, `term_max_months` (fallbacks, or tightenings), `collateral_mode`, `priority` (lower ranks first; it only breaks exact ties). |
| `ranking` | Collateral burden per mode and rate-certainty order used by the ranking key. |
| `amount_slider` | Log-scale slider bounds, default, snapping bands (`up_to_rub`/`step_rub`, the last band ending at `max_rub`) and presets. Bounds, default, presets and every product minimum must land exactly on a step. |
| `okved_rule` | The supported OKVED reading (`leading_code_or_range`, compared on the main class, the rest a condition to confirm). |
| `overlay_badges.<overlay>` | The softer badge text for collateral-required cards and the products exempt from the overlay's OKVED restriction. |
| `region_normalization` | Steps applied to both sides of a region comparison: `casefold`, `yo_to_ye`, `collapse_spaces`. |

## What the checker enforces

- **Shapes and types.** Every section has its JSON type (objects, lists); each item is an object with an id; amounts and terms (catalog values, per-product settings and the default fallbacks) are positive whole numbers, so `"30000000"`, `30000000.5`, `0` or `-5` are refused; `max_unsecured`, tranches and a rate period's `to_month` are positive whole numbers or `null`; rates and the key rate are JSON numbers, not texts; flags (`term.unlimited`, `collateral.required`, `msp_registry_required`) are booleans (`required` may be `null`); names, notes and eligibility lists are texts. A mistyped section is reported, never a crash.
- **Vocabulary.** Known enum values (the catalog's `enums`, plus purposes the questionnaire can ask, at least one per card), `status` `active` or `inactive`, `display.as` `card` or `badge_on_card`, unique ids; `guarantee_overlay` and overlay `applies_to` naming existing items; at least one applyable kind and at least one card product.
- **Rules.** Each formula equal to its percent; whole-basis-point rates and key rate, none negative; an annuity payment model only on a product with a term; a fallback for every null a card product needs; policy settings that only tighten; minimum ≤ maximum for amounts and terms, per-purpose caps inside the term range; explanation texts on every card product and badge text on every overlay; payment models for every card instrument type; complete ranking tables; supported OKVED and region rules; the slider reaching every product minimum.
- **Documents.** Types among the four the app checks, each listed once; at least one base document; the collateral documents include `COLLATERAL_VALUATION`, whose verified value bounds a secured final approval.

Each problem is reported with its path (`items[<id>]…` for the catalog, `policy.…` for the policy). The test suite also replaces each value of the policy and of representative catalog items with mistyped ones and checks that every edit the checker accepts still serialises and recommends.

## Recommendations in brief

The client gives only an amount. For each card product the server runs the checks `company_active`, `entity_type`, `msp_registry`, `region`, `okved`, `program_status`, `amount_min`, `catalog_max`, `turnover`, `collateral`, `amount_capacity`: any failure is «Не соответствует», any unknown «Нужны сведения», else «Соответствует». The personal estimate is `min(maximum, 3 × monthly turnover, unsecured cap)`; a product that requires collateral has none until the questionnaire. The same formula (`app/products_config/limits.py`) gives the scored limit after submission — at the scored risk, with the declared pledge added to the unsecured cap for a secured application — and the officer's final bound with the verified pledge. Cards rank by status, shortfall, collateral burden, rate certainty, rate, policy priority and id. The spec's «Product policy and recommendations» section is the full contract.

## Common edits

- **Key rate changed.** Update `params.key_rate.value_percent` and every formula item's `rate_percent` (the checker names each one that no longer matches).
- **A product's terms changed.** Edit its `amount`/`term`/`rate` in the catalog; if a value becomes `null`, check the policy has a fallback.
- **A new product.** Add a catalog item with the same schema, its display texts, and if its instrument type is new, a `payment_models` entry; optionally a `products.<id>.priority`.
- **Close a program.** Set `limit_status` to `exhausted` or `closed`: the card stays visible, `program_status` fails and «Начать анкету» is not offered (`can_apply` false); a draft created by a direct API call is refused at submission (R1 on `product_id`). An application already submitted keeps the terms pinned at its submission.
