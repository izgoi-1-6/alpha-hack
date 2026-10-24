# Synthetic demo data

- `demo-products.json`: the only calculation/application catalog (`demo-2026-10-24-v1`, `demo-rules-v1`), exactly three supported products. All prices/limits are explicit demo assumptions.
- `demo-companies.json`: nine synthetic IP/LLC profiles, checksum-valid generated mock INNs, deterministic actor/company UUIDs, recoveries, and frozen product-choice answer keys. Business age reference date 2026-10-24; do not freeze app time. `expected_check_outcome` labels describe the internal evaluation path if reached; UI precheck/required-field gating is separate (`expected_ui_action`). Never load expectations into recommendation/scoring logic.
- `catalog.research.json`: nine archived source claims, `can_apply=false` throughout, source path/hash in provenance. Not validated current banking terms and never merged into executable demo policy.

Only local mocks consume these INNs; generated checksums do not imply unassigned real numbers. No real customer data. Seed credentials are published synthetic local accounts in the canonical spec. No real secrets or personal information belong here.

Held-out task answer keys are authored before recommendation engine results. Keep them server-side, pin the Task 1 data commit as answer_key_version, and report synthetic trials separately from any real participant study. Do not regenerate expected choices with the engine being evaluated.
