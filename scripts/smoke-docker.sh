#!/usr/bin/env bash
# Smoke check of a running stack through its web entry point (nginx in Docker Compose, or Vite locally):
#   ./scripts/smoke-docker.sh [base-url]      # default http://localhost:5173
#
# Checks: API health; an officer login with the Origin header and the session cookie; a refused command without Origin;
# a fresh synthetic client's registration; the Госуслуги check and adding «Сильный бизнес»; a questionnaire submitted
# to a preliminary approval; a small synthetic PDF uploaded and downloaded byte for byte; the SPA served at
# /alfa-business/<id>; nginx's security headers. Needs bash, curl and python3. Creates one synthetic client and one
# application in the configured database; nothing else is changed.
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="${1:-http://localhost:5173}"
ORIGIN="${ORIGIN:-http://localhost:5173}"
API="$BASE/api/v1"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
: > "$WORK/officer"
: > "$WORK/client"
FAILURES=0

json() { python3 -c 'import json, sys
value = json.load(open(sys.argv[1]))
for key in sys.argv[2].split("."):
    value = value[int(key)] if isinstance(value, list) else value[key]
print(value)' "$WORK/body" "$1"; }
key() { python3 -c 'import uuid; print(uuid.uuid4())'; }
pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; FAILURES=$((FAILURES + 1)); }
expect() { if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1 (expected $3, got $2)"; fi; }

# call <jar> <method> <path> [json body] [extra curl args...] -> HTTP status; body in $WORK/body, headers in $WORK/headers
call() {
  local jar="$1" method="$2" path="$3" body="${4:-}"
  shift 4 || shift $#
  local args=(-sS -o "$WORK/body" -D "$WORK/headers" -w '%{http_code}' -b "$WORK/$jar" -c "$WORK/$jar" -X "$method")
  if [[ "$method" != GET ]]; then args+=(-H "Origin: $ORIGIN"); fi
  if [[ -n "$body" ]]; then args+=(-H 'Content-Type: application/json' --data "$body"); fi
  curl "${args[@]}" "$@" "$API$path"
}

echo "Smoke check against $BASE"

# The API may still be applying migrations right after `docker compose up -d`: wait up to 60 s for its health.
for _ in $(seq 1 60); do
  status=$(curl -s -o "$WORK/body" -w '%{http_code}' "$API/health" || true)
  if [[ "$status" == 200 ]]; then break; fi
  sleep 1
done
expect "health: $(cat "$WORK/body")" "$status" 200

status=$(call officer POST /auth/login '{"email":"officer@demo.local","password":"DemoCredit2026!"}')
expect "officer login" "$status" 200
expect "officer role" "$(json user.role)" CREDIT_OFFICER
if grep -qi '^set-cookie: credit_route_session=.*HttpOnly' "$WORK/headers" && grep -qi 'SameSite=lax' "$WORK/headers"; then
  pass "session cookie is HttpOnly, SameSite=Lax"
else
  fail "session cookie flags"
fi
status=$(call officer GET /auth/me)
expect "the cookie restores the officer session" "$status" 200

status=$(curl -sS -o "$WORK/body" -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  --data '{"email":"officer@demo.local","password":"DemoCredit2026!"}' "$API/auth/login")
expect "a command without Origin is refused" "$status" 403
expect "refusal code" "$(json error.code)" ORIGIN_FORBIDDEN

email="smoke-$(date +%s)-$RANDOM@example.test"
status=$(call client POST /auth/register "{\"email\":\"$email\",\"password\":\"Synthetic-Pass-2026\",\"display_name\":\"Синтетический клиент\"}")
expect "fresh client registration ($email)" "$status" 201

status=$(call client POST /identity/gosuslugi/verify '{"inn":"9900000017"}' -H "Idempotency-Key: $(key)")
expect "Госуслуги check" "$status" 201
verification=$(json verification_id)
echo "     confirmed: $(json person_name), $(json role)"

status=$(call client POST /companies "{\"inn\":\"9900000017\",\"consents\":[{\"code\":\"ONBOARDING_PROCESSING\",\"version\":\"consent-v2\",\"accepted\":true},{\"code\":\"REGISTRY_LOOKUP\",\"version\":\"consent-v2\",\"accepted\":true}],\"authority_verification_id\":\"$verification\"}")
expect "company added" "$status" 201
company=$(json company.id)
expect "registry source" "$(json precheck.registry_source_status)" available

status=$(call client POST "/companies/$company/recommendations" '{"requested_amount_rub":2000000}')
expect "recommendations for 2 000 000 ₽" "$status" 201
snapshot=$(json snapshot_id)

status=$(call client POST /applications "{\"company_id\":\"$company\",\"product_id\":\"alfa_term_loan_unsecured\",\"recommendation_snapshot_id\":\"$snapshot\"}" -H "Idempotency-Key: $(key)")
expect "draft created" "$status" 201
application=$(json application.id)
version=$(json application.version)

answers='{"company_confirmed":true,"actual_address":"г. Москва, ул. Складская, д. 1","actual_activity":"Оптовая торговля","purpose":"working_capital","term_months":12,"monthly_debt_payment_rub":160000,"tax_debt_rub":0,"legal_proceedings":false,"beneficial_owners_confirmed":true,"accuracy_confirmed":true}'
status=$(call client PATCH "/applications/$application/answers" "{\"version\":$version,\"current_stage\":6,\"answers\":$answers}")
expect "questionnaire saved" "$status" 200
version=$(json application.version)

status=$(call client POST "/applications/$application/submit" "{\"version\":$version,\"consents\":[{\"code\":\"APPLICATION_PROCESSING\",\"version\":\"consent-v2\",\"accepted\":true},{\"code\":\"BKI\",\"version\":\"consent-v2\",\"accepted\":true}]}" -H "Idempotency-Key: $(key)")
expect "submitted" "$status" 200
expect "preliminary approval" "$(json application.status)" PREAPPROVED
version=$(json application.version)

sample=docs/api/samples/bank-statement.pdf
status=$(curl -sS -o "$WORK/body" -w '%{http_code}' -b "$WORK/client" -H "Origin: $ORIGIN" -H "Idempotency-Key: $(key)" \
  -F "file=@$sample;type=application/pdf" -F document_type=BANK_STATEMENT -F "version=$version" \
  "$API/applications/$application/documents")
expect "PDF uploaded through the proxy ($(wc -c < "$sample" | tr -d ' ') bytes)" "$status" 201
download=$(json document.download_url)
status=$(curl -sS -o "$WORK/download" -D "$WORK/headers" -w '%{http_code}' -b "$WORK/client" "$BASE$download")
expect "PDF downloaded" "$status" 200
if cmp -s "$sample" "$WORK/download"; then pass "downloaded bytes are identical"; else fail "downloaded bytes differ"; fi
if grep -qi '^content-disposition: attachment' "$WORK/headers"; then pass "download is an attachment"; else fail "download disposition"; fi

status=$(curl -sS -o "$WORK/page" -D "$WORK/headers" -w '%{http_code}' "$BASE/alfa-business/$application")
expect "SPA served at /alfa-business/<id>" "$status" 200
if grep -qi '^content-type: text/html' "$WORK/headers" && grep -q '<div id="root">' "$WORK/page"; then
  pass "the page is the app's index.html"
else
  fail "the hand-off path does not serve the app"
fi
if grep -qi '^x-content-type-options: nosniff' "$WORK/headers"; then pass "X-Content-Type-Options: nosniff"; else fail "nosniff header"; fi

if [[ "$FAILURES" -eq 0 ]]; then
  echo "All smoke checks passed"
else
  echo "$FAILURES smoke check(s) failed"
  exit 1
fi
