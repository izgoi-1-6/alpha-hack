# Running and presenting «Кредитный маршрут»

«Кредитный маршрут» takes a small business (ИП or ООО) from its first visit to a final credit decision: the client adds a company (with a Госуслуги authority check), picks an amount, compares the bank's catalog products on explained cards, fills a six-stage questionnaire and submits it with consents. Scoring then gives a preliminary approval, a review by a credit officer or a refusal. After a preliminary approval the client uploads documents, the officer reviews them and takes the final decision, and an approved client is handed off to Alfa-Business.

Everything runs locally on synthetic data. The registry, turnover, ФНС/open sources, BKI, Госуслуги, notifications, document checks and Alfa-Business are local mocks, and no real call ever leaves the machine. What is executed and what is assumed is listed in [evidence.md](evidence.md).

## 1. Start-up

### Local (the development set-up)

Requires Python 3.12, Node 24 with npm, and Docker (for PostgreSQL only).

```sh
cp .env.example .env          # optional: the defaults below are the same
./scripts/setup.sh            # venv + npm ci + PostgreSQL container + migrations + seed (idempotent)
./scripts/run-api.sh          # API on http://127.0.0.1:8000 (auto-reload)
npm run dev --prefix frontend # in another terminal: UI on http://localhost:5173
```

Open **http://localhost:5173**, not 127.0.0.1. The API accepts commands only from the exact UI origin (`UI_ORIGIN`, default `http://localhost:5173`), and Vite proxies `/api` so the browser stays same-origin. OpenAPI is at http://127.0.0.1:8000/docs.

### Docker Compose (the whole stack in containers)

```sh
docker compose up --build -d   # db + api + web; UI on http://localhost:5173
docker compose logs -f api     # «Uvicorn running on http://0.0.0.0:8000»
docker compose stop api web    # stop the app, keep the database running
```

- `db` is PostgreSQL 17 on `127.0.0.1:5432`, with its data in the named volume `credit_route_data`.
- `api` runs the migrations and, with `DEMO_MODE=true`, the idempotent seed at every start, then Uvicorn on `127.0.0.1:8000`. Uploaded files go to the named volume `credit_route_documents`.
- `web` is nginx serving the production build on `127.0.0.1:5173`. It proxies `/api/` to the API and accepts bodies up to 21 MiB (the API's 20 MiB file limit plus the envelope).

The compose `db` is the same database the local set-up uses. Stop the local API and Vite before `docker compose up` (same ports 8000 and 5173), and start them again after `docker compose stop api web`. Never pass `-v` to `docker compose down`: it deletes the volumes and with them the data and the uploaded files. Files uploaded through the containers live in the `credit_route_documents` volume, not in `var/documents`.

## 2. Accounts

All seeded accounts use the synthetic password `DemoCredit2026!`. The login page has a quick-login button for each:

| Button | Account | Role | Starts with |
|---|---|---|---|
| «Войти как клиент» | `client@demo.local` | client | the ten fixture companies below (no applications) |
| «Новый клиент» | `other@demo.local` | client | no companies (a good account to show the walkthrough) |
| «Войти как специалист» | `officer@demo.local` | credit officer | the review queue |

«Регистрация» creates more clients (any synthetic e-mail; a password of at least 10 characters). Public registration only ever creates clients; credit officers come only from the seed. The walkthrough opens once per client and browser (its flag is kept in `localStorage`). «Как это работает» in the top bar restarts it.

## 3. Fixture companies

Adding a company means choosing one of these ten synthetic ИНН (`data/demo-companies.json`, `demo-fixtures-v2`). Each one exercises a path through the rules. The outcomes are those the browser journeys and backend tests produce. Business age is counted to the fixture date 2026-10-24.

| Company | ИНН | What it shows |
|---|---|---|
| ООО «Сильный бизнес» | 9900000017 | Low risk: 48 months, 800 000 ₽ a month, clean history. Personal estimate 2 400 000 ₽ (3 × turnover). Term loan 2 000 000 ₽ → score 100, R8 preliminary approval; 2 500 000 ₽ → R9, approved at the 2 400 000 ₽ limit. The main story. |
| ИП «Средний риск» | 990000000299 | Medium risk (65 points). The revolving line at 700 000 ₽ goes to an officer (R11, scored limit 600 000 ₽ = min(1 000 000, turnover)). The information-request story. |
| ИП «Высокий риск» | 990000000362 | Four months old, falling turnover, heavy debt: 10 points → automatic refusal (R6). With tax arrears the check goes to an officer instead (R5), where a preliminary approval is a mandatory stop. Main OKVED 47.11 falls under the guarantee's retail exclusion, so the «Зонтичное» badge shows only on the exempt border-territories program. |
| ООО «Неактивный бизнес» | 9900000049 | Closed business: read-only results, «Не рассчитывается» instead of an estimate, no «Начать анкету». |
| ИП «Неполные обороты» | 990000000500 | No turnover in the sources: estimates «Нужно уточнить». The client declares turnover in the questionnaire and a specialist reviews it (R5). A declared 0 makes the limit not computable for the officer. |
| ООО «Реестр недоступен» | 9900000063 | Registry did not answer: eligibility unknown, no application until «Повторить проверку» on the company profile recovers it. |
| ООО «Оборудование» | 9900000070 | Secured loan: 1 500 000 ₽ a month, an 8 000 000 ₽ pledge. Secured term loan 4 000 000 ₽ → R8 (limit 4 500 000 ₽), four documents. A verified valuation of 5 000 000 ₽ bounds the final amount at 3 500 000 ₽ (70 %). |
| ИП «БКИ недоступно» | 990000000820 | The credit bureau does not answer: «Ждём источник данных» (R4), then «Повторить проверку» → preliminary approval. |
| ИП «БКИ без категории» | 990000000901 | The bureau answers without a history category: a system request that only a source retry can close, then a specialist's review. |
| ООО «Курский производитель» | 9900000095 | Manufacturer in Курская область (OKVED 25.62) on the SME register: eligible for every card product. At 20 000 000 ₽ seven cards fit, the three secured ones wait for the pledge and the subsidy program starts at 25 000 000 ₽. «Кредит по ПСК для приграничных территорий» at 20 000 000 ₽ → score 100, R8 (limit 30 000 000 ₽). |

Any client can add any of these ИНН: the mock Госуслуги always confirms the fixture's director, so nothing needs setting up per account.

## 4. Editing the catalog and the policy

Products come from two files, both validated when the API starts:

- `data/credit_catalog.json`: the bank's products and their facts (amounts, terms, rates, purposes, eligibility, card texts). It is authoritative.
- `data/demo-policy.json`: the decision rules. It holds fallbacks for catalog nulls, payment models, ranking, the amount slider, badge texts and the OKVED/region rules. It may only tighten the catalog.

After editing either file, validate it before restarting the API:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.products_config check
# OK: catalog 2026-10-25.1+c0683aa1, rules rules-v2+e3e3ac59, 11 products, 1 overlay
```

A broken edit prints every problem with its path and exits 1, and the API refuses to start with the same messages. Restart the API after a valid edit (it reads the files once). Versions carry a content hash, so any edit makes saved recommendations and drafts stale (409 `RECOMMENDATION_STALE`; the client recalculates), while submitted applications keep the product they pinned. [catalog.md](catalog.md) explains every setting, what the checker enforces and the common edits (key rate, terms, a new product, closing a program).

## 5. Resetting to the seed

`scripts/reset-demo.sh` empties the configured database and reloads the seed: `alembic downgrade base`, `upgrade head`, then the seed. It deletes every user, company, application and document record; uploaded files stay on disk. Stop the API first, then:

```sh
./scripts/reset-demo.sh            # asks: type yes
./scripts/reset-demo.sh --yes      # no question
./scripts/reset-demo.sh --dry-run  # all checks, prints the steps, changes nothing
./scripts/run-api.sh               # start the API again
```

It refuses unless `DEMO_MODE` is true (as the app reads it), and it refuses a `DATABASE_URL` whose host is not `localhost`, `127.0.0.1` or `db`, or whose query sets a host (`host=`, `hostaddr=`), unless `--force-remote` is given. Values in the environment win over `.env`. With the Docker stack, run it from the host after `docker compose stop api` (the database port is published on 127.0.0.1:5432), then `docker compose start api`. There is no reset endpoint: `DEMO_MODE=false` also makes the seed refuse and hides the fixture list.

## 6. A short presentation script (about 12 minutes)

Use two browser windows: a normal one for the client, a private one for the officer. Start from a freshly reset database for clean lists.

**The client (about 6 minutes).**

1. On http://localhost:5173 choose «Регистрация» and create a client (or use «Новый клиент»). Say: the data is synthetic and every bank source is a local mock.
2. The walkthrough opens: «Начните с компании». Click «Добавить компанию» and follow it.
3. Choose «Сильный бизнес», then «Подтвердить через Госуслуги». The dialog shows the director (Соколов Андрей Викторович, Генеральный директор); click «Подтвердить». Tick both permissions and click «Добавить и проверить». Point out that the credit history is not requested yet.
4. The profile shows what the sources returned (registry, turnover 800 000 ₽). Click «Подобрать финансирование».
5. The amount is the only input (default 2 000 000 ₽). Show the eleven catalog products ranked on explained cards: what the product is, its features, who it suits. «Лучшее совпадение» is on the fitting first card. Keep the personal estimate (2 400 000 ₽) apart from the product maximum (30 000 000 ₽). The payment is 77 942 ₽ over the 36-month estimate term. Move to 3 000 000 ₽: the term loan offers «Рассчитать на 2 400 000 ₽». Come back to 2 000 000 ₽.
6. «Начать анкету» on «Кредит одной суммой без залога», then «Готово» on the last walkthrough step.
7. Go through the six stages:
   - confirm the company, give an address and an activity;
   - choose «Пополнение оборотных средств» and 12 months;
   - the turnover comes from the source, and the tax regime and staff are read-only;
   - debt payments 160 000 ₽, no tax arrears, no proceedings;
   - the representative comes from Госуслуги; confirm the owners;
   - give both consents and click «Отправить заявку».
8. «Заявка предварительно одобрена»: 100 points, scored limit 2 400 000 ₽, preliminary approval 2 000 000 ₽. Stress that it is not a final decision. Upload any small synthetic PDF as the bank statement and a PNG or JPEG as the financial report, then click «Отправить комплект».

**The officer (about 4 minutes).**

9. In the private window click «Войти как специалист». The queue lists the oldest submission first; filter «Статус» = «Документы на проверке» and open the application. Click «Взять в работу» and show the evidence: score factors, sources, amounts and the history.
10. Accept both documents with a comment. The final decision opens at 2 000 000 ₽ with its bounds. Give a reason, click «Одобрить окончательно», then «Да, одобрить».
11. In the client window reload the page: «Заявка одобрена», with the requested, preliminarily approved and final amounts on separate tiles. «Перейти в Альфа-Бизнес» opens the hand-off page: no money moves and nothing is signed here.

**Optional stories (2–3 minutes each).**

- *An information request*: as the client add «Средний риск» and apply for the revolving line at 700 000 ₽ («На рассмотрении», 65 points). The officer claims it, asks about the debt payments, the client answers on the same application, and the officer preliminarily approves up to 600 000 ₽. An amount above that is refused with the bounds.
- *A refusal*: «Высокий риск» at 300 000 ₽ is refused automatically (10 points). At the document stage the officer can refuse with a reason; the packet then stays as a read-only record.
- *A source outage*: «Реестр недоступен» shows unknown eligibility and no «Начать анкету» until «Повторить проверку» on the profile.
- *A gov program*: «Курский производитель» at 20 000 000 ₽ fits «Кредит по ПСК для приграничных территорий» (a preferential 14 % rate for 12 months).

## 7. Troubleshooting

- **«Нет связи с сервером» or «Сервер не смог выполнить запрос»**: the UI server or the API behind it is not running. The first means no answer at all; the second is a proxy or server failure. Start `./scripts/run-api.sh` (and Vite), or the compose `api` and `web`.
- **«Откройте приложение по разрешённому адресу»**: the UI was opened at another address (e.g. 127.0.0.1 instead of localhost), so the Origin check refuses commands; open http://localhost:5173 or set `UI_ORIGIN`.
- **The API does not start**: run the config check above, which names the broken catalog or policy value. Make sure PostgreSQL is up (`docker compose up -d --wait db`).
- **Port 5173 or 8000 busy**: a local API/Vite and the compose `api`/`web` cannot run at the same time.
- **«Условия продуктов изменились…» when starting or submitting**: the catalog or policy changed after the estimate; recalculate («Пересчитать оценку»).
- **The walkthrough does not open**: it opens once per client and browser. Use «Как это работает» or a private window.
