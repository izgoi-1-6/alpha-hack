"""Exports the API description of «Кредитный маршрут» from the FastAPI app.

    backend/.venv/bin/python scripts/export-api-docs.py           # writes the files below
    backend/.venv/bin/python scripts/export-api-docs.py --check   # exits 1 if a file is out of date

Writes, deterministically (no timestamps):
  docs/api/openapi.yaml             app.openapi() with Russian tags, summaries and descriptions, the cookie session,
                                    the Origin header, the multipart upload and the common error shape;
  docs/api/postman_collection.json  a Postman v2.1 collection: one request per operation, grouped by area, plus the
                                    ordered folder «Сквозной сценарий»;
  docs/api/samples/*.pdf            two small synthetic PDFs the collection uploads.

No dependency beyond the backend's own: the YAML is written by `to_yaml` (block style, double-quoted strings) and
read back by `from_yaml` (the same subset) before anything is saved.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.main import app  # noqa: E402  (the backend package is on the path only now)

PREFIX = '/api/v1'
OPENAPI_PATH = ROOT / 'docs/api/openapi.yaml'
POSTMAN_PATH = ROOT / 'docs/api/postman_collection.json'
SAMPLES = {'bank-statement.pdf': b'Synthetic bank statement', 'financial-report.pdf': b'Synthetic financial report'}
SAMPLE_DIR = ROOT / 'docs/api/samples'
MUTATING = {'post', 'put', 'patch', 'delete'}
PUBLIC = {('post', '/auth/register'), ('post', '/auth/login'), ('post', '/auth/logout'),
          ('get', '/consents/documents'), ('get', '/catalog'), ('get', '/health')}

TAGS = [
    ('Аутентификация', 'Регистрация клиента, вход, выход и текущий пользователь. Сессия — cookie `credit_route_session`.'),
    ('Госуслуги', 'Заглушка подтверждения полномочий представителя компании.'),
    ('Компании', 'Компании клиента, проверка источников (реестр и обороты), тексты согласий.'),
    ('Каталог и подбор', 'Каталог продуктов и неизменяемые снимки подбора на сумму.'),
    ('Заявки клиента', 'Черновик, анкета из шести этапов, отправка, повторная проверка, ответ на запрос, отмена, история.'),
    ('Документы', 'Перечень документов, загрузка, скачивание, удаление и отправка комплекта.'),
    ('Кредитный специалист', 'Очередь, карточка заявки со скорингом, решения и проверка документов (роль CREDIT_OFFICER).'),
    ('Интеграции', 'Локальная страница перехода в Альфа-Бизнес.'),
    ('Служебные', 'Проверка работоспособности.'),
]

# (method, path without /api/v1) -> (tag, summary, description)
OPERATIONS = {
    ('post', '/auth/register'): ('Аутентификация', 'Регистрация клиента',
        'Создаёт пользователя с ролью CLIENT и сразу открывает сессию (cookie `credit_route_session`). Почта '
        'приводится к нижнему регистру, пароль — 10–128 символов, имя — 1–100. 201 `{user}`; 409 `EMAIL_EXISTS`.'),
    ('post', '/auth/login'): ('Аутентификация', 'Вход',
        'Открывает новую сессию на 12 часов. 200 `{user}`; 401 `INVALID_CREDENTIALS`; 429 `LOGIN_RATE_LIMIT` после '
        '10 неудачных попыток за 15 минут для пары «почта + адрес клиента».'),
    ('post', '/auth/logout'): ('Аутентификация', 'Выход',
        'Тело — пустой объект `{}`. Отзывает текущую сессию и удаляет cookie; повтор безопасен. 204.'),
    ('get', '/auth/me'): ('Аутентификация', 'Текущий пользователь',
        '`{user: {id, email, display_name, role}}`; 401 `AUTH_REQUIRED` без действующей сессии.'),
    ('post', '/identity/gosuslugi/verify'): ('Госуслуги', 'Подтверждение полномочий через Госуслуги (заглушка)',
        'Только CLIENT. Для ИНН из синтетического справочника всегда подтверждает представителя: ФИО директора из '
        'фикстуры, роль «Генеральный директор» (ООО) или «Индивидуальный предприниматель» (ИП). 201 `{verification_id, '
        'inn, person_name, role, verified_at, expires_at}`; подтверждение действует 30 минут и добавляет одну '
        'компанию. ИНН вне справочника — 422 `REGISTRY_NOT_FOUND`. Реальные ЕСИА/Госуслуги не вызываются.'),
    ('get', '/consents/documents'): ('Компании', 'Тексты согласий',
        '`stage=onboarding` — ONBOARDING_PROCESSING и REGISTRY_LOOKUP, `stage=application` — APPLICATION_PROCESSING и '
        'BKI. Версия текстов `consent-v2`. Доступно без входа.'),
    ('get', '/demo/fixtures'): ('Компании', 'Синтетические компании для выбора',
        'Только CLIENT. ИНН, название, тип и состояние источников каждой синтетической компании; при '
        '`DEMO_MODE=false` — 404.'),
    ('get', '/companies'): ('Компании', 'Компании клиента', '`{items, total}` в порядке добавления.'),
    ('post', '/companies'): ('Компании', 'Добавление компании',
        'Тело: `inn`, оба согласия этапа onboarding версии `consent-v2` с `accepted: true` и '
        '`authority_verification_id`. Порядок отказов: 422 `REGISTRY_NOT_FOUND` → 403 `AUTHORITY_NOT_VERIFIED` (нет, '
        'чужое, другого ИНН, использованное или просроченное подтверждение) → 409 `COMPANY_EXISTS`. 201 '
        '`{company, precheck}`: данные реестра и оборотов из синтетических источников.'),
    ('get', '/companies/{company_id}'): ('Компании', 'Компания и последняя проверка источников',
        '`{company, precheck}`. Чужая или несуществующая компания — 404 `COMPANY_NOT_FOUND`.'),
    ('get', '/companies/{company_id}/precheck'): ('Компании', 'Последняя проверка источников',
        'То же, что `GET /companies/{company_id}`.'),
    ('post', '/companies/{company_id}/precheck/retry'): ('Компании', 'Повторная проверка источников',
        'Тело `{version}` — текущая версия компании. Добавляет новую проверку по сценарию восстановления фикстуры '
        '(реестр или обороты), версия компании +1. БКИ не запрашивается. 409 `VERSION_CONFLICT`.'),
    ('get', '/catalog'): ('Каталог и подбор', 'Каталог продуктов',
        'Версии каталога и правил, ключевая ставка, шкала суммы, 11 продуктов-карточек с действующими условиями и '
        'надстройка-бейдж. Доступно без входа.'),
    ('post', '/companies/{company_id}/recommendations'): ('Каталог и подбор', 'Подбор продуктов на сумму',
        'Тело `{requested_amount_rub}` — целое число от 1 до 2 000 000 000. 201 — неизменяемый снимок `{snapshot_id, '
        'catalog_version, rules_version, items, created_at}`: все продукты по рангу со статусом `fits`, `needs_info` '
        'или `does_not_fit`, проверками, личной предварительной оценкой и платежом. БКИ не запрашивается, скоринг '
        'не считается. Без `Idempotency-Key`: каждый вызов — новый снимок.'),
    ('get', '/companies/{company_id}/recommendations/{snapshot_id}'): ('Каталог и подбор', 'Сохранённый снимок подбора',
        'Тот же снимок без пересчёта. 404 `RECOMMENDATION_NOT_FOUND`.'),
    ('post', '/applications'): ('Заявки клиента', 'Создание черновика заявки',
        'Тело `{company_id, product_id, recommendation_snapshot_id}`; продукт должен входить в снимок этой компании. '
        '201 — заявка в статусе DRAFT, версия 1. 422 `PRODUCT_NOT_SUPPORTED`, 409 `RECOMMENDATION_STALE` (каталог '
        'или правила изменились после подбора).'),
    ('get', '/applications'): ('Заявки клиента', 'Заявки клиента',
        'Фильтры `status` и `company_id`; новые первыми. Перед фильтром применяется ленивое истечение срока.'),
    ('get', '/applications/{application_id}'): ('Заявки клиента', 'Заявка',
        '`{application}`: ответы, суммы, `allowed_actions`, `missing_fields`, открытый запрос сведений, сводка '
        'документов. Скоринга нет: ни балла, ни риска, ни факторов, ни рассчитанного лимита.'),
    ('get', '/applications/{application_id}/dialog'): ('Заявки клиента', 'Анкета из шести этапов',
        'Описания полей с границами выбранного продукта, ответы, незаполненные поля и `field_issues` черновика. Поля '
        'из источников (`tax_regime`, `employees`, `representative_name`, `representative_authority_confirmed`) '
        'помечены `read_only`.'),
    ('get', '/applications/{application_id}/history'): ('Заявки клиента', 'История заявки',
        'Переходы статусов с ролью участника (`client`, `officer`, `system`) и уведомлением в кабинете. Результат '
        'автоматической проверки по скорингу показан кодом `CHECK_RESULT` и нейтральным текстом.'),
    ('patch', '/applications/{application_id}/answers'): ('Заявки клиента', 'Сохранение ответов анкеты',
        'Только DRAFT. Тело `{version, current_stage, answers}`: частичное сохранение, `collateral` объединяется по '
        'ключам. Без `Idempotency-Key` — повтор защищает версия. 422 `SOURCE_OWNED_FIELDS` (поле из источника), '
        '409 `VERSION_CONFLICT`, 409 `INVALID_STATUS`.'),
    ('post', '/applications/{application_id}/submit'): ('Заявки клиента', 'Отправка заявки',
        'Тело `{version, consents}` — согласия APPLICATION_PROCESSING и BKI версии `consent-v2`. Порядок отказов: 409 '
        '`VERSION_CONFLICT`, 409 `INVALID_STATUS`, 403 `AUTHORITY_NOT_VERIFIED`, 409 `RECOMMENDATION_STALE`, 409 '
        '`DUPLICATE_ACTIVE_APPLICATION`, 422 `CORRECTION_REQUIRED` (R1), 422 `NEED_INFO` (согласия, затем R3). Затем '
        'проверка выполняется синхронно — не больше одного запроса в БКИ — и ответ содержит итоговый статус.'),
    ('post', '/applications/{application_id}/retry-check'): ('Заявки клиента', 'Повторная проверка',
        'Из WAIT_EXTERNAL или из NEED_INFO с открытым запросом к источнику; использует сохранённое согласие на БКИ. '
        '409 `INVALID_STATUS`, 409 `CONSENT_REQUIRED`.'),
    ('post', '/applications/{application_id}/respond-info'): ('Заявки клиента', 'Ответ на запрос сведений',
        'NEED_INFO с запросом `client_answers`. Тело `{version, response, answers}` — только запрошенные поля. Заявка '
        'возвращается в MANUAL_REVIEW без нового запроса в БКИ. 409 `TRUSTED_SOURCE_REQUIRED`; 422 '
        '`NEED_FIELDS_LOCKED`, `SOURCE_OWNED_FIELDS`, `ANSWER_NOT_REQUESTED`, `NEED_INFO`.'),
    ('post', '/applications/{application_id}/cancel'): ('Заявки клиента', 'Отмена заявки',
        'Тело `{version, reason}` (причина 1–2000 символов). Доступно в DRAFT, WAIT_EXTERNAL, NEED_INFO, '
        'MANUAL_REVIEW, PREAPPROVED, DOCS_UPLOADED и DOCS_REWORK.'),
    ('get', '/applications/{application_id}/documents'): ('Документы', 'Перечень документов',
        '`{notice, requirements, items}`: обязательные документы заявки с текущим файлом и все версии файлов.'),
    ('post', '/applications/{application_id}/documents'): ('Документы', 'Загрузка документа',
        'multipart/form-data: `file`, `document_type`, `version`. PDF, JPEG или PNG до 20 МиБ: расширение, MIME-тип, '
        'сигнатура и структура файла должны совпадать. Только в PREAPPROVED и DOCS_REWORK. 201 `{document, '
        'application}`; 413 `FILE_TOO_LARGE`, 415 `MEDIA_NOT_ALLOWED`, 422 `FILE_INVALID`, 422 '
        '`DOCUMENT_TYPE_NOT_ALLOWED`, 409 `DOCUMENT_ACCEPTED`.'),
    ('get', '/applications/{application_id}/documents/{document_id}/download'): ('Документы', 'Скачивание файла',
        'Владелец заявки или кредитный специалист. `Content-Disposition: attachment`, `Cache-Control: private, '
        "no-store`, `Content-Security-Policy: default-src 'none'; sandbox`. 404 `DOCUMENT_NOT_FOUND`."),
    ('delete', '/applications/{application_id}/documents/{document_id}'): ('Документы', 'Удаление файла',
        'Тело `{version}`. Текущий непринятый файл в PREAPPROVED или DOCS_REWORK. 409 `DOCUMENT_ACCEPTED`, 409 '
        '`DOCUMENT_NOT_CURRENT`.'),
    ('post', '/applications/{application_id}/documents/complete'): ('Документы', 'Отправка комплекта документов',
        'PREAPPROVED или DOCS_REWORK → DOCS_UPLOADED, когда загружены все обязательные документы и нет отклонённых. '
        '409 `DOCUMENTS_INCOMPLETE` (`details: {missing, rejected}`).'),
    ('get', '/officer/applications'): ('Кредитный специалист', 'Очередь заявок',
        'Только CREDIT_OFFICER. Отправленные заявки, давние первыми; фильтры `status`, `assignee=me|unassigned`, '
        '`company_id`; `status=DRAFT` показывает черновики.'),
    ('get', '/officer/applications/{application_id}'): ('Кредитный специалист', 'Карточка заявки для специалиста',
        'Полный скоринг (балл, риск, факторы, рассчитанный лимит, правило), все оценки, данные источников, решения, '
        'запросы сведений, история с именами, все версии документов и `requestable_fields`.'),
    ('post', '/officer/applications/{application_id}/claim'): ('Кредитный специалист', 'Взять заявку в работу',
        'Тело `{version}`. Статус не меняется. 409 `ALREADY_ASSIGNED`, 409 `INVALID_STATUS`.'),
    ('post', '/officer/applications/{application_id}/request-info'): ('Кредитный специалист', 'Запрос сведений у клиента',
        'Назначенный специалист, MANUAL_REVIEW → NEED_INFO. Тело `{version, reason, requested_fields}`. 409 '
        '`ASSIGNMENT_REQUIRED`, 409 `INFO_REQUEST_OPEN`; 422 `NEED_FIELDS_LOCKED`, `FIELD_NOT_REQUESTABLE`.'),
    ('post', '/officer/applications/{application_id}/preapprove'): ('Кредитный специалист', 'Предварительное одобрение (R12)',
        'Назначенный специалист, MANUAL_REVIEW → PREAPPROVED. Сумма — от минимума продукта до min(запрошенная '
        'сумма, рассчитанный лимит). 409 `MANDATORY_STOP`, 409 `LIMIT_NOT_COMPUTABLE`; 422 `AMOUNT_OUT_OF_BOUNDS`.'),
    ('post', '/officer/applications/{application_id}/reject'): ('Кредитный специалист', 'Отказ',
        'Назначенный специалист. Из MANUAL_REVIEW — предварительный отказ (R12), из PREAPPROVED, DOCS_UPLOADED или '
        'DOCS_REWORK — окончательный. Причина 1–2000 символов.'),
    ('post', '/officer/applications/{application_id}/documents/{document_id}/review'): ('Кредитный специалист', 'Проверка документа',
        'Назначенный специалист, DOCS_UPLOADED. Тело `{version, decision: accept|reject, reason, verified_value_rub?}`; '
        'принять отчёт об оценке залога можно только с `verified_value_rub`. Первое отклонение переводит заявку в '
        'DOCS_REWORK. 409 `DOCUMENT_NOT_REVIEWABLE`; 422 `VERIFIED_VALUE_REQUIRED`, `VERIFIED_VALUE_NOT_ALLOWED`.'),
    ('post', '/officer/applications/{application_id}/approve'): ('Кредитный специалист', 'Окончательное одобрение',
        'Назначенный специалист, DOCS_UPLOADED → APPROVED, когда все обязательные документы приняты. Сумма — от '
        'минимума продукта до min(предварительно одобренная сумма, лимит по проверенным данным). 409 '
        '`DOCUMENTS_NOT_ACCEPTED`, `LIMIT_NOT_COMPUTABLE`, `COLLATERAL_INSUFFICIENT` (с залогом) или `LIMIT_BELOW_MINIMUM` (без '
        'залога); 422 `AMOUNT_OUT_OF_BOUNDS`. Деньги '
        'не перечисляются, договор не подписывается.'),
    ('post', '/integrations/alfa-business/link'): ('Интеграции', 'Ссылка на переход в Альфа-Бизнес',
        'Владелец заявки в статусе APPROVED: `{url: "/alfa-business/{id}", simulated: true}`. Ничего не меняет и '
        'никуда не обращается. 409 `INVALID_STATUS` до окончательного одобрения.'),
    ('get', '/health'): ('Служебные', 'Проверка работоспособности',
        '`{status: "ok", demo_mode}`; выполняет запрос к базе данных.'),
}

DESCRIPTION = """\
API «Кредитного маршрута»: путь клиента малого бизнеса от добавления компании до окончательного решения и работа \
кредитного специалиста. Все пути начинаются с `/api/v1`. Документ сгенерирован из кода \
(`scripts/export-api-docs.py`); интерактивная версия — http://127.0.0.1:8000/docs.

**Сессия.** `POST /auth/register` или `POST /auth/login` ставят cookie `credit_route_session` (HttpOnly, \
SameSite=Lax, срок 12 часов, `Secure` при `COOKIE_SECURE=true`). Без действующей сессии — 401 `AUTH_REQUIRED`. Роли: \
клиент (`CLIENT`) и кредитный специалист (`CREDIT_OFFICER`); чужая роль — 403 `CLIENT_REQUIRED` или \
`OFFICER_REQUIRED`, чужой или несуществующий ресурс — 404.

**Origin.** Каждый запрос POST, PATCH и DELETE должен нести заголовок `Origin`, точно равный адресу интерфейса \
(`UI_ORIGIN`, по умолчанию `http://localhost:5173`), иначе 403 `ORIGIN_FORBIDDEN`.

**Idempotency-Key.** Команды, меняющие состояние, требуют заголовок `Idempotency-Key` (1–128 символов). Повтор с тем \
же ключом и телом возвращает сохранённый ответ и ничего не выполняет снова; тот же ключ с другим телом — 409 \
`IDEMPOTENCY_CONFLICT`. Ключ не нужен для регистрации, входа и выхода, `POST /companies`, подбора \
(`POST /companies/{company_id}/recommendations`) и `PATCH /applications/{application_id}/answers`.

**version.** Команды над заявкой передают в теле `version` — текущую целую ревизию заявки (для \
`POST /companies/{company_id}/precheck/retry` — ревизию компании). Несовпадение — 409 `VERSION_CONFLICT`; успешная \
команда увеличивает ревизию на 1.

**Ошибки.** Тело ошибки — `{"error": {"code": "…", "message": "…", "fields": {…}, "details": {…}}}`: `code` — \
английский код, `message` — текст на русском, `fields` — сообщения по полям, `details` — данные для интерфейса. \
Неизвестные ключи в теле запроса — 422 `VALIDATION_ERROR`.

**Скоринг.** Маршруты клиента не возвращают балл, категорию риска, факторы, флаги проверки и рассчитанный лимит. \
Маршруты `/officer/*` возвращают их полностью.

Суммы — целые рубли, время — UTC в ISO 8601 с `Z`. Все данные синтетические; внешние сервисы (реестр, обороты, БКИ, \
Госуслуги, уведомления, Альфа-Бизнес) — локальные заглушки."""

ERROR_SCHEMA = {
    'type': 'object', 'required': ['error'], 'additionalProperties': False,
    'properties': {'error': {
        'type': 'object', 'required': ['code', 'message'],
        'properties': {
            'code': {'type': 'string', 'description': 'Английский код ошибки', 'examples': ['VERSION_CONFLICT']},
            'message': {'type': 'string', 'description': 'Сообщение на русском языке'},
            'fields': {'type': 'object', 'additionalProperties': {'type': 'string'},
                       'description': 'Сообщения по полям запроса'},
            'details': {'type': 'object', 'description': 'Дополнительные данные (например, границы суммы)'},
        }}},
}
ORIGIN_PARAMETER = {'name': 'Origin', 'in': 'header', 'required': True,
                    'description': 'Адрес интерфейса, точно равный `UI_ORIGIN`', 'schema': {'type': 'string',
                                                                                            'example': 'http://localhost:5173'}}
UPLOAD_BODY = {'required': True, 'content': {'multipart/form-data': {'schema': {
    'type': 'object', 'required': ['file', 'document_type', 'version'],
    'properties': {
        'file': {'type': 'string', 'format': 'binary', 'description': 'PDF, JPEG или PNG до 20 МиБ'},
        'document_type': {'type': 'string', 'enum': ['BANK_STATEMENT', 'FINANCIAL_REPORT', 'COLLATERAL_OWNERSHIP',
                                                     'COLLATERAL_VALUATION']},
        'version': {'type': 'string', 'pattern': '^[1-9][0-9]{0,8}$', 'description': 'Текущая ревизия заявки'},
    }}}}}


def build_openapi() -> dict:
    spec = copy.deepcopy(app.openapi())
    spec['info'] = {'title': 'Кредитный маршрут — API', 'version': spec['info']['version'], 'description': DESCRIPTION}
    spec['servers'] = [{'url': 'http://localhost:5173', 'description': 'Интерфейс (Vite или nginx) с прокси на API: '
                                                                       'тот же адрес, что и Origin'}]
    spec['tags'] = [{'name': name, 'description': text} for name, text in TAGS]
    seen = set()
    for path, operations in spec['paths'].items():
        short = path.removeprefix(PREFIX)
        for method, operation in operations.items():
            key = (method, short)
            if key not in OPERATIONS:
                raise SystemExit(f'No Russian summary for {method.upper()} {path}: add it to OPERATIONS')
            seen.add(key)
            tag, summary, description = OPERATIONS[key]
            operation.update(tags=[tag], summary=summary, description=description)
            if key in PUBLIC:
                operation['security'] = []
            if method in MUTATING:
                operation.setdefault('parameters', []).insert(0, {'$ref': '#/components/parameters/Origin'})
            if key == ('post', '/applications/{application_id}/documents'):
                operation['requestBody'] = copy.deepcopy(UPLOAD_BODY)
            if key == ('get', '/applications/{application_id}/documents/{document_id}/download'):
                operation['responses']['200']['content'] = {
                    media: {'schema': {'type': 'string', 'format': 'binary'}}
                    for media in ('application/pdf', 'image/jpeg', 'image/png')}
            for code, response in operation['responses'].items():
                if code == '422':
                    response['description'] = 'Ошибка проверки данных'
                    response['content'] = {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}
                elif code.startswith('2'):
                    response['description'] = 'Успешный ответ'
            operation['responses']['default'] = {
                'description': 'Ошибка', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}}
    missing = set(OPERATIONS) - seen
    if missing:
        raise SystemExit(f'OPERATIONS lists operations the app does not have: {sorted(missing)}')
    schemas = spec['components']['schemas']
    for name in ('HTTPValidationError', 'ValidationError'):
        schemas.pop(name, None)
    schemas['Error'] = ERROR_SCHEMA
    spec['components']['parameters'] = {'Origin': ORIGIN_PARAMETER}
    spec['components']['securitySchemes'] = {'cookieAuth': {
        'type': 'apiKey', 'in': 'cookie', 'name': 'credit_route_session',
        'description': 'Сессия, которую ставят `POST /auth/register` и `POST /auth/login`'}}
    spec['security'] = [{'cookieAuth': []}]
    return spec


# --- block YAML: writer and reader of the same subset ---------------------------------------------------------------

PLAIN_KEY = re.compile(r'[A-Za-z_$/][A-Za-z0-9_$./{}+-]*')
RESERVED = {'true', 'false', 'null', 'yes', 'no', 'on', 'off', 'y', 'n', '~'}


def yaml_key(key: str) -> str:
    return key if PLAIN_KEY.fullmatch(key) and key.lower() not in RESERVED else json.dumps(key, ensure_ascii=False)


def yaml_scalar(value) -> str:
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f'unsupported YAML value {value!r}')


def yaml_lines(value, indent: int) -> list[str]:
    pad = ' ' * indent
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            head = f'{pad}{yaml_key(str(key))}:'
            if isinstance(item, (dict, list)) and item:
                lines += [head, *yaml_lines(item, indent + 2)]
            elif isinstance(item, str) and '\n' in item:
                lines += [f'{head} |-', *[(' ' * (indent + 2) + line) if line else '' for line in item.split('\n')]]
            else:
                lines.append(f'{head} {"{}" if item == {} else "[]" if item == [] else yaml_scalar(item)}')
    else:
        for item in value:
            if isinstance(item, (dict, list)) and item:
                lines += [f'{pad}-', *yaml_lines(item, indent + 2)]
            else:
                lines.append(f'{pad}- {"{}" if item == {} else "[]" if item == [] else yaml_scalar(item)}')
    return lines


def to_yaml(value: dict) -> str:
    return '\n'.join(yaml_lines(value, 0)) + '\n'


def parse_scalar(text: str):
    if text == '{}':
        return {}
    if text == '[]':
        return []
    if text in ('null', 'true', 'false') or re.fullmatch(r'-?\d+(\.\d+)?([eE][+-]?\d+)?', text):
        return json.loads(text)
    if text.startswith('"'):
        return json.loads(text)
    raise ValueError(f'unexpected scalar {text!r}')


def from_yaml(text: str):
    lines = text.split('\n')

    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(' '))

    def next_content(i: int) -> int:
        while i < len(lines) and not lines[i].strip():
            i += 1
        return i

    def split_key(content: str) -> tuple[str, str]:
        if content.startswith('"'):
            key, end = json.JSONDecoder().raw_decode(content)
        else:
            end = content.index(':')
            key = content[:end]
        if content[end] != ':':
            raise ValueError(f'expected ":" in {content!r}')
        return key, content[end + 1:].strip()

    def node(i: int, indent: int):
        i = next_content(i)
        content = lines[i].strip()
        if content == '-' or content.startswith('- '):
            items = []
            while i < len(lines) and indent_of(lines[i]) == indent and (lines[i].strip() == '-' or lines[i].strip().startswith('- ')):
                rest = lines[i].strip()[1:].strip()
                if rest:
                    items.append(parse_scalar(rest))
                    i = next_content(i + 1)
                else:
                    child = next_content(i + 1)
                    value, i = node(child, indent_of(lines[child]))
                    items.append(value)
                    i = next_content(i)
            return items, i
        mapping = {}
        while i < len(lines) and lines[i].strip() and indent_of(lines[i]) == indent:
            key, rest = split_key(lines[i].strip())
            if rest == '|-':
                block, j = [], i + 1
                while j < len(lines) and (not lines[j].strip() or indent_of(lines[j]) > indent):
                    block.append(lines[j][indent + 2:] if lines[j].strip() else '')
                    j += 1
                while block and block[-1] == '':
                    block.pop()
                mapping[key] = '\n'.join(block)
                i = next_content(j)
            elif rest:
                mapping[key] = parse_scalar(rest)
                i = next_content(i + 1)
            else:
                child = next_content(i + 1)
                mapping[key], i = node(child, indent_of(lines[child]))
                i = next_content(i)
        return mapping, i

    value, end = node(0, 0)
    if next_content(end) != len(lines):
        raise ValueError(f'unparsed YAML from line {end + 1}')
    return value


# --- Postman v2.1 ---------------------------------------------------------------------------------------------------

NAMESPACE = uuid.UUID('7c0c6c8e-4a0b-4d8e-9a54-2f6a0d1b6e71')
PATH_VARIABLES = {'company_id': 'companyId', 'application_id': 'applicationId', 'snapshot_id': 'snapshotId',
                  'document_id': 'documentId'}
VARIABLES = [
    ('baseUrl', 'http://localhost:5173/api/v1', 'Адрес API через интерфейс (Vite или nginx)'),
    ('origin', 'http://localhost:5173', 'Значение заголовка Origin = UI_ORIGIN'),
    ('clientEmail', '', 'Почта нового клиента: задаётся в первом запросе сценария'),
    ('clientPassword', 'Synthetic-Pass-2026', 'Пароль нового синтетического клиента'),
    ('officerEmail', 'officer@demo.local', 'Кредитный специалист из начальных данных'),
    ('officerPassword', 'DemoCredit2026!', 'Синтетический пароль начальных учётных записей'),
    ('inn', '990000000299', 'ИНН синтетической компании «Средний риск»'),
    ('productId', 'alfa_revolving_line_unsecured', 'Продукт сценария'),
    ('amount', '500000', 'Сумма потребности и решений сценария, ₽'),
    ('verificationId', '', ''), ('companyId', '', ''), ('snapshotId', '', ''), ('applicationId', '', ''),
    ('version', '', 'Текущая ревизия заявки'), ('documentId', '', 'Последний загруженный документ'),
    ('statementDocumentId', '', ''), ('reportDocumentId', '', ''),
]
# Raw JSON bodies keep these collection variables unquoted (numbers).
NUMERIC = ('{{version}}', '{{amount}}')
ONBOARDING_CONSENTS = [{'code': 'ONBOARDING_PROCESSING', 'version': 'consent-v2', 'accepted': True},
                       {'code': 'REGISTRY_LOOKUP', 'version': 'consent-v2', 'accepted': True}]
SUBMISSION_CONSENTS = [{'code': 'APPLICATION_PROCESSING', 'version': 'consent-v2', 'accepted': True},
                       {'code': 'BKI', 'version': 'consent-v2', 'accepted': True}]
ANSWERS = {'company_confirmed': True, 'actual_address': 'г. Санкт-Петербург, ул. Торговая, д. 2',
           'actual_activity': 'Оптовая торговля', 'purpose': 'working_capital', 'monthly_debt_payment_rub': 240000,
           'tax_debt_rub': 0, 'legal_proceedings': False, 'beneficial_owners_confirmed': True, 'accuracy_confirmed': True}
REASON = 'Сведения проверены, условия продукта выполнены.'

# Example bodies of the reference requests (variables from the scenario).
EXAMPLES = {
    ('post', '/auth/register'): {'email': '{{clientEmail}}', 'password': '{{clientPassword}}', 'display_name': 'Синтетический клиент'},
    ('post', '/auth/login'): {'email': '{{officerEmail}}', 'password': '{{officerPassword}}'},
    ('post', '/auth/logout'): {},
    ('post', '/identity/gosuslugi/verify'): {'inn': '{{inn}}'},
    ('post', '/companies'): {'inn': '{{inn}}', 'consents': ONBOARDING_CONSENTS, 'authority_verification_id': '{{verificationId}}'},
    ('post', '/companies/{company_id}/precheck/retry'): {'version': 1},
    ('post', '/companies/{company_id}/recommendations'): {'requested_amount_rub': '{{amount}}'},
    ('post', '/applications'): {'company_id': '{{companyId}}', 'product_id': '{{productId}}',
                                'recommendation_snapshot_id': '{{snapshotId}}'},
    ('patch', '/applications/{application_id}/answers'): {'version': '{{version}}', 'current_stage': 6, 'answers': ANSWERS},
    ('post', '/applications/{application_id}/submit'): {'version': '{{version}}', 'consents': SUBMISSION_CONSENTS},
    ('post', '/applications/{application_id}/retry-check'): {'version': '{{version}}'},
    ('post', '/applications/{application_id}/respond-info'): {'version': '{{version}}', 'response': 'Уточнили платежи по кредитам.',
                                                              'answers': {'monthly_debt_payment_rub': 240000}},
    ('post', '/applications/{application_id}/cancel'): {'version': '{{version}}', 'reason': 'Финансирование больше не нужно.'},
    ('delete', '/applications/{application_id}/documents/{document_id}'): {'version': '{{version}}'},
    ('post', '/applications/{application_id}/documents/complete'): {'version': '{{version}}'},
    ('post', '/officer/applications/{application_id}/claim'): {'version': '{{version}}'},
    ('post', '/officer/applications/{application_id}/request-info'): {
        'version': '{{version}}', 'reason': 'Уточните ежемесячные платежи по действующим кредитам.',
        'requested_fields': ['monthly_debt_payment_rub']},
    ('post', '/officer/applications/{application_id}/preapprove'): {'version': '{{version}}', 'amount_rub': '{{amount}}', 'reason': REASON},
    ('post', '/officer/applications/{application_id}/reject'): {'version': '{{version}}', 'reason': 'Условия продукта не выполнены.'},
    ('post', '/officer/applications/{application_id}/documents/{document_id}/review'): {
        'version': '{{version}}', 'decision': 'accept', 'reason': 'Документ читается и соответствует анкете.'},
    ('post', '/officer/applications/{application_id}/approve'): {'version': '{{version}}', 'amount_rub': '{{amount}}', 'reason': REASON},
    ('post', '/integrations/alfa-business/link'): {'application_id': '{{applicationId}}'},
}
QUERY = {('get', '/consents/documents'): [('stage', 'onboarding', False)],
         ('get', '/applications'): [('status', 'MANUAL_REVIEW', True), ('company_id', '{{companyId}}', True)],
         ('get', '/officer/applications'): [('status', 'MANUAL_REVIEW', True), ('assignee', 'unassigned', True),
                                            ('company_id', '{{companyId}}', True)]}


def raw_json(body) -> str:
    text = json.dumps(body, ensure_ascii=False, indent=2)
    for name in NUMERIC:
        text = text.replace(f'"{name}"', name)
    return text


def url_of(path: str, query=()) -> dict:
    segments = [PATH_VARIABLES.get(part[1:-1], part) if part.startswith('{') else part for part in path.strip('/').split('/')]
    segments = ['{{' + part + '}}' if part in PATH_VARIABLES.values() else part for part in segments]
    raw = '{{baseUrl}}/' + '/'.join(segments)
    url = {'raw': raw, 'host': ['{{baseUrl}}'], 'path': segments}
    if query:
        url['query'] = [{'key': key, 'value': value, **({'disabled': True} if disabled else {})} for key, value, disabled in query]
        enabled = [f'{key}={value}' for key, value, disabled in query if not disabled]
        if enabled:
            url['raw'] += '?' + '&'.join(enabled)
    return url


def request_item(name: str, method: str, path: str, *, body=None, form=None, idempotent: bool, description: str = '',
                 query=(), prerequest=(), tests=()) -> dict:
    headers = []
    if method in MUTATING:
        headers.append({'key': 'Origin', 'value': '{{origin}}'})
    if idempotent:
        headers.append({'key': 'Idempotency-Key', 'value': '{{$guid}}'})
    request = {'method': method.upper(), 'header': headers, 'url': url_of(path, query)}
    if body is not None:
        headers.append({'key': 'Content-Type', 'value': 'application/json'})
        request['body'] = {'mode': 'raw', 'raw': raw_json(body), 'options': {'raw': {'language': 'json'}}}
    if form is not None:
        request['body'] = {'mode': 'formdata', 'formdata': form}
    if description:
        request['description'] = description
    item = {'name': name, 'request': request}
    events = [(kind, lines) for kind, lines in (('prerequest', prerequest), ('test', tests)) if lines]
    if events:
        item['event'] = [{'listen': kind, 'script': {'type': 'text/javascript', 'exec': list(lines)}} for kind, lines in events]
    return item


def upload_form(document_type: str, sample: str) -> list[dict]:
    return [{'key': 'file', 'type': 'file', 'src': f'docs/api/samples/{sample}'},
            {'key': 'document_type', 'value': document_type, 'type': 'text'},
            {'key': 'version', 'value': '{{version}}', 'type': 'text'}]


def check(status: int, *more: str) -> list[str]:
    return [f'pm.test("HTTP {status}", function () {{ pm.response.to.have.status({status}); }});', *more]


def store_application(status: str | None = None) -> list[str]:
    lines = ['const body = pm.response.json();',
             'pm.collectionVariables.set("version", body.application.version);']
    if status:
        lines.append(f'pm.test("Статус {status}", function () {{ pm.expect(body.application.status).to.eql("{status}"); }});')
    return lines


def login(name: str, who: str) -> dict:
    return request_item(name, 'post', '/auth/login', idempotent=False,
                        body={'email': '{{' + who + 'Email}}', 'password': '{{' + who + 'Password}}'}, tests=check(200))


def scenario() -> list[dict]:
    return [
        request_item('1. Регистрация нового клиента', 'post', '/auth/register', idempotent=False,
                     body=EXAMPLES[('post', '/auth/register')],
                     prerequest=['pm.collectionVariables.set("clientEmail", "client-" + Date.now() + "@example.test");'],
                     tests=check(201)),
        request_item('2. Подтверждение полномочий через Госуслуги', 'post', '/identity/gosuslugi/verify', idempotent=True,
                     body={'inn': '{{inn}}'},
                     tests=check(201, 'pm.collectionVariables.set("verificationId", pm.response.json().verification_id);')),
        request_item('3. Добавление компании', 'post', '/companies', idempotent=False, body=EXAMPLES[('post', '/companies')],
                     tests=check(201, 'pm.collectionVariables.set("companyId", pm.response.json().company.id);')),
        request_item('4. Подбор продуктов на сумму', 'post', '/companies/{company_id}/recommendations', idempotent=False,
                     body={'requested_amount_rub': '{{amount}}'},
                     tests=check(201, 'const body = pm.response.json();',
                                 'pm.collectionVariables.set("snapshotId", body.snapshot_id);',
                                 'const item = body.items.find(function (entry) { return entry.product_id === pm.collectionVariables.get("productId"); });',
                                 'pm.test("Продукт можно выбрать", function () { pm.expect(item.can_apply).to.eql(true); });')),
        request_item('5. Создание черновика заявки', 'post', '/applications', idempotent=True,
                     body=EXAMPLES[('post', '/applications')],
                     tests=check(201, 'pm.collectionVariables.set("applicationId", pm.response.json().application.id);',
                                 *store_application('DRAFT'))),
        request_item('6. Ответы анкеты', 'patch', '/applications/{application_id}/answers', idempotent=False,
                     body=EXAMPLES[('patch', '/applications/{application_id}/answers')],
                     tests=check(200, *store_application(),
                                 'pm.test("Анкета заполнена", function () { pm.expect(body.application.missing_fields).to.eql([]); });')),
        request_item('7. Отправка заявки с согласиями', 'post', '/applications/{application_id}/submit', idempotent=True,
                     body=EXAMPLES[('post', '/applications/{application_id}/submit')],
                     tests=check(200, *store_application('MANUAL_REVIEW'),
                                 'pm.test("Клиент не видит скоринг", function () { pm.expect("scored_limit_rub" in body.application).to.eql(false); });')),
        login('8. Вход кредитного специалиста', 'officer'),
        request_item('9. Карточка заявки со скорингом', 'get', '/officer/applications/{application_id}', idempotent=False,
                     tests=check(200, 'const body = pm.response.json();',
                                 'pm.collectionVariables.set("version", body.application.version);',
                                 'pm.test("Специалист видит балл", function () { pm.expect(typeof body.application.latest_evaluation.score).to.eql("number"); });')),
        request_item('10. Взять заявку в работу', 'post', '/officer/applications/{application_id}/claim', idempotent=True,
                     body={'version': '{{version}}'}, tests=check(200, *store_application('MANUAL_REVIEW'))),
        request_item('11. Предварительное одобрение', 'post', '/officer/applications/{application_id}/preapprove', idempotent=True,
                     body=EXAMPLES[('post', '/officer/applications/{application_id}/preapprove')],
                     tests=check(200, *store_application('PREAPPROVED'))),
        login('12. Вход клиента', 'client'),
        request_item('13. Загрузка банковской выписки', 'post', '/applications/{application_id}/documents', idempotent=True,
                     form=upload_form('BANK_STATEMENT', 'bank-statement.pdf'),
                     tests=check(201, *store_application(),
                                 'pm.collectionVariables.set("statementDocumentId", body.document.id);',
                                 'pm.collectionVariables.set("documentId", body.document.id);')),
        request_item('14. Загрузка финансовой отчётности', 'post', '/applications/{application_id}/documents', idempotent=True,
                     form=upload_form('FINANCIAL_REPORT', 'financial-report.pdf'),
                     tests=check(201, *store_application(),
                                 'pm.collectionVariables.set("reportDocumentId", body.document.id);',
                                 'pm.collectionVariables.set("documentId", body.document.id);')),
        request_item('15. Отправка комплекта документов', 'post', '/applications/{application_id}/documents/complete',
                     idempotent=True, body={'version': '{{version}}'}, tests=check(200, *store_application('DOCS_UPLOADED'))),
        login('16. Вход кредитного специалиста', 'officer'),
        request_item('17. Принять выписку', 'post', '/officer/applications/{application_id}/documents/{{statementDocumentId}}/review',
                     idempotent=True, body=EXAMPLES[('post', '/officer/applications/{application_id}/documents/{document_id}/review')],
                     tests=check(200, *store_application('DOCS_UPLOADED'))),
        request_item('18. Принять отчётность', 'post', '/officer/applications/{application_id}/documents/{{reportDocumentId}}/review',
                     idempotent=True, body=EXAMPLES[('post', '/officer/applications/{application_id}/documents/{document_id}/review')],
                     tests=check(200, *store_application('DOCS_UPLOADED'))),
        request_item('19. Окончательное одобрение', 'post', '/officer/applications/{application_id}/approve', idempotent=True,
                     body=EXAMPLES[('post', '/officer/applications/{application_id}/approve')],
                     tests=check(200, *store_application('APPROVED'))),
        login('20. Вход клиента', 'client'),
        request_item('21. Ссылка на переход в Альфа-Бизнес', 'post', '/integrations/alfa-business/link', idempotent=True,
                     body={'application_id': '{{applicationId}}'},
                     tests=check(200, 'pm.test("Локальная страница перехода", function () { pm.expect(pm.response.json().simulated).to.eql(true); });')),
    ]


def build_postman(spec: dict) -> dict:
    folders: dict[str, list] = {name: [] for name, _ in TAGS}
    for path, operations in spec['paths'].items():
        short = path.removeprefix(PREFIX)
        for method, operation in operations.items():
            key = (method, short)
            idempotent = any(parameter.get('name') == 'Idempotency-Key' for parameter in operation.get('parameters', []))
            form = upload_form('BANK_STATEMENT', 'bank-statement.pdf') if key == ('post', '/applications/{application_id}/documents') else None
            body = EXAMPLES.get(key) if form is None and method in MUTATING else None
            folders[operation['tags'][0]].append(request_item(
                operation['summary'], method, short, body=body, form=form, idempotent=idempotent,
                description=operation['description'], query=QUERY.get(key, ())))
    intro = ('Запросы выполняются по порядку и сохраняют идентификаторы и ревизию в переменных коллекции. Новый клиент '
             'добавляет синтетическую компанию «Средний риск», заявка уходит специалисту (MANUAL_REVIEW), специалист '
             'берёт её в работу и предварительно одобряет, клиент загружает документы, специалист принимает их и '
             'окончательно одобряет, клиент получает ссылку на переход в Альфа-Бизнес. Сессии клиента и специалиста '
             'сменяются входом. Нужны запущенные API и интерфейс; рабочая папка Postman — корень репозитория (файлы '
             'загрузки лежат в docs/api/samples).')
    items = [{'name': 'Сквозной сценарий', 'description': intro, 'item': scenario()}]
    items += [{'name': name, 'description': text, 'item': folders[name]} for name, text in TAGS if folders[name]]
    return {
        'info': {'_postman_id': str(uuid.uuid5(NAMESPACE, 'credit-route-api')), 'name': 'Кредитный маршрут — API',
                 'description': 'Сгенерировано из кода командой `backend/.venv/bin/python scripts/export-api-docs.py`. '
                                'Описание API — docs/api/openapi.yaml.',
                 'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json'},
        'item': items,
        'variable': [{'key': key, 'value': value, 'type': 'string', **({'description': text} if text else {})}
                     for key, value, text in VARIABLES],
    }


def sample_pdf(text: bytes) -> bytes:
    """A one-page PDF 1.4 with a correct cross-reference table (no fonts embedded, no active content)."""
    content = b'BT /F1 12 Tf 20 100 Td (' + text + b') Tj ET\n'
    bodies = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
              b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R /Resources << >> >>',
              b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream']
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % number + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(bodies) + 1)
    out += b''.join(b'%010d 00000 n \n' % offset for offset in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(bodies) + 1, xref)
    return bytes(out)


def outputs() -> dict[Path, bytes]:
    spec = build_openapi()
    text = to_yaml(spec)
    if from_yaml(text) != json.loads(json.dumps(spec)):
        raise SystemExit('The YAML writer and reader disagree: openapi.yaml would not round-trip')
    files = {OPENAPI_PATH: text.encode(),
             POSTMAN_PATH: (json.dumps(build_postman(spec), ensure_ascii=False, indent=2) + '\n').encode()}
    files.update({SAMPLE_DIR / name: sample_pdf(content) for name, content in SAMPLES.items()})
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--check', action='store_true', help='compare with the files on disk instead of writing')
    args = parser.parse_args()
    stale = []
    for path, data in outputs().items():
        if args.check:
            if not path.is_file() or path.read_bytes() != data:
                stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print(f'wrote {path.relative_to(ROOT)} ({len(data)} bytes)')
    for path in stale:
        print(f'out of date: {path.relative_to(ROOT)}')
    return 1 if stale else 0


if __name__ == '__main__':
    sys.exit(main())
