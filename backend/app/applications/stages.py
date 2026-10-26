"""The six saved questionnaire stages: field contract, server prefill, deep-merged partial saves, the stage-3
answer/source evidence and the submit-time requirements (R1 corrections, R3 gaps).

Answers are a flat object keyed by the field names below; only `collateral` is nested. Paths in `missing_fields`,
InfoRequest.requested_fields and error `fields` are those names (`collateral.<key>` for collateral details).

Stage 2 follows the chosen runtime product: its purposes (a single one preselected), its amount bounds, its term range
limited per purpose (no term field for a product without a term) and its collateral mode (the pledge is required,
optional or not asked). R3 asks for the pledge details whenever the application is secured.

Source-owned answers (SOURCE_OWNED) are the server's, never the client's: the tax regime and the employee count come from
the latest precheck's registry payload (the mock open sources), the representative's name and authority from the
company's Госуслуги verification. They are prefilled, described `read_only` with their source, written again from the
sources at submission, and never asked by R3 (with an unavailable registry the check waits for it: R4).
"""
from ..recommendations import catalog
from ..recommendations.service import eligibility_checks, rub

PURPOSES = {'working_capital': 'Пополнение оборотных средств', 'business_development': 'Развитие бизнеса',
            'investment': 'Инвестиции', 'refinancing': 'Рефинансирование'}
COLLATERAL_STATUSES = {'declared': 'Залог заявлен', 'none': 'Залога нет', 'unknown': 'Пока не знаю'}
COLLATERAL_TYPES = {'real_estate': 'Недвижимость', 'vehicle': 'Транспорт', 'equipment': 'Оборудование',
                    'inventory': 'Товары в обороте', 'deposit': 'Депозит'}


def options(labels: dict) -> list[dict]:
    return [{'value': value, 'label': label} for value, label in labels.items()]


def boolean(name: str, label: str, *, required: bool = True, must_be_true: bool = False) -> dict:
    field = {'name': name, 'label': label, 'type': 'boolean', 'required': required}
    if must_be_true:
        field['must_be_true'] = True
    return field


def number(name: str, label: str, *, required: bool = True, minimum: int = 0) -> dict:
    return {'name': name, 'label': label, 'type': 'integer', 'required': required, 'min': minimum}


def text(name: str, label: str, max_length: int, *, required: bool = True) -> dict:
    return {'name': name, 'label': label, 'type': 'text', 'required': required, 'max_length': max_length}


STAGES = (
    (1, 'Компания', (
        boolean('company_confirmed', 'Сведения о компании из реестра верны', must_be_true=True),
        text('actual_address', 'Фактический адрес', 300),
        text('actual_activity', 'Фактическая деятельность', 300),
    )),
    (2, 'Параметры', (
        {'name': 'purpose', 'label': 'Цель финансирования', 'type': 'enum', 'required': True},
        {'name': 'requested_amount_rub', 'label': 'Сумма, ₽', 'type': 'integer', 'required': True},
        {'name': 'term_months', 'label': 'Срок, мес.', 'type': 'integer', 'required': True},
        {'name': 'collateral', 'label': 'Залог', 'type': 'collateral', 'statuses': options(COLLATERAL_STATUSES),
         'types': options(COLLATERAL_TYPES), 'description_max_length': 500},
    )),
    (3, 'Бизнес и финансы', (
        number('monthly_revenue_rub', 'Среднемесячная выручка за текущий период, ₽'),
        number('previous_monthly_revenue_rub', 'Среднемесячная выручка за предыдущий период, ₽'),
        {'name': 'financial_period_end', 'label': 'Дата окончания отчётного периода', 'type': 'date', 'required': True},
        {'name': 'tax_regime', 'label': 'Налоговый режим', 'type': 'enum', 'required': True,
         'options': options({'OSN': 'ОСН', 'USN': 'УСН', 'PSN': 'ПСН', 'OTHER': 'Другой режим'})},
        number('employees', 'Число сотрудников'),
        boolean('seasonal', 'Выручка зависит от сезона', required=False),
    )),
    (4, 'Обязательства', (
        number('monthly_debt_payment_rub', 'Ежемесячные платежи по действующим кредитам и лизингу, ₽'),
        number('tax_debt_rub', 'Налоговая задолженность, ₽'),
        boolean('legal_proceedings', 'Есть судебные разбирательства'),
        text('obligations_note', 'Комментарий к обязательствам', 1000, required=False),
    )),
    (5, 'Руководитель и владельцы', (
        text('representative_name', 'ФИО представителя', 100),
        boolean('representative_authority_confirmed', 'Полномочия представителя подтверждены через Госуслуги', must_be_true=True),
        boolean('beneficial_owners_confirmed', 'Сведения о владельцах указаны верно (это не согласие поручителя)', must_be_true=True),
    )),
    (6, 'Проверка и согласия', (
        boolean('accuracy_confirmed', 'Подтверждаю, что сведения анкеты верны', must_be_true=True),
    )),
)
ANSWER_FIELDS = tuple(field['name'] for _, _, fields in STAGES for field in fields)
STAGE_OF = {field['name']: number for number, _, fields in STAGES for field in fields}
FINANCE_FIELDS = ('monthly_revenue_rub', 'previous_monthly_revenue_rub', 'financial_period_end')
REGISTRY_FIELDS = ('tax_regime', 'employees')
AUTHORITY_FIELDS = ('representative_name', 'representative_authority_confirmed')
SOURCE_OWNED = REGISTRY_FIELDS + AUTHORITY_FIELDS
SOURCE_OWNED_MESSAGE = ('Налоговый режим и число сотрудников приходят из открытых источников, сведения о представителе — '
                        'из подтверждения через Госуслуги: в анкете их не меняют и у клиента не запрашивают.')


def source_owned_message(name: str) -> str:
    return ('Значение приходит из открытых источников и в анкете не меняется.' if name in REGISTRY_FIELDS else
            'Значение приходит из подтверждения через Госуслуги и в анкете не меняется.')


def owned_sources(precheck, verification) -> dict:
    """Each source-owned answer's source: the registry payload of the latest precheck (its status as recorded) and the
    company's Госуслуги verification (`missing` for a company added before the check existed)."""
    registry = precheck.registry_payload or {}
    status = 'available' if verification is not None else 'missing'
    return {**{name: {'name': 'registry', 'status': precheck.registry_source_status, 'value': registry.get(name)}
               for name in REGISTRY_FIELDS},
            'representative_name': {'name': 'gosuslugi', 'status': status,
                                    'value': verification.person_name if verification is not None else None},
            'representative_authority_confirmed': {'name': 'gosuslugi', 'status': status,
                                                   'value': True if verification is not None else None}}


def source_answers(precheck, verification) -> dict:
    """The source-owned answers as the sources give them now."""
    return {name: entry['value'] for name, entry in owned_sources(precheck, verification).items()}


def source_finance(precheck) -> dict:
    period = precheck.financial_period_end
    return {'monthly_revenue_rub': precheck.monthly_revenue_rub,
            'previous_monthly_revenue_rub': precheck.previous_monthly_revenue_rub,
            'financial_period_end': period.isoformat() if period else None}


def has_term(product: dict) -> bool:
    return product['term_min_months'] is not None


def term_bounds(product: dict, purpose) -> tuple[int, int]:
    """The product's term range, its maximum lowered by a per-purpose maximum for the chosen purpose."""
    return product['term_min_months'], product['term_max_months_by_purpose'].get(purpose, product['term_max_months'])


def prefill(need: dict, precheck, product: dict, verification) -> dict:
    """Initial draft answers: stage 2's amount from the saved need (the need is the amount alone), the product's purpose
    when it has only one (term and collateral start empty), stage 3 finances from the persisted source, the
    source-owned answers from their sources; the rest empty."""
    answers = dict.fromkeys(ANSWER_FIELDS)
    answers['requested_amount_rub'] = need['requested_amount_rub']
    if len(product['purposes']) == 1:
        answers['purpose'] = product['purposes'][0]
    answers.update(source_finance(precheck))
    answers.update(source_answers(precheck, verification))
    return answers


def merge(answers: dict, patch: dict) -> dict:
    """A partial save: top-level fields are replaced, collateral details are merged key by key; null clears."""
    merged = dict(answers)
    for name, value in patch.items():
        if name == 'collateral' and isinstance(value, dict) and isinstance(merged.get('collateral'), dict):
            merged['collateral'] = {**merged['collateral'], **value}
        else:
            merged[name] = value
    return merged


def finance_evidence(answers: dict, precheck) -> dict:
    """Stage-3 answers next to the persisted turnover source. A known source value (present, from a source that is
    not unavailable; a 'missing' turnover source still reports its period end) stays authoritative and is the one
    scored: an equal answer is tagged 'source', a different one 'override' (both values kept); without a source
    value the answer is 'declared'. Originals are never overwritten."""
    sources = source_finance(precheck)
    evidence = {}
    for name in FINANCE_FIELDS:
        answer, source = answers.get(name), sources[name]
        known = source is not None and precheck.turnover_source_status != 'unavailable'
        if answer is None:
            origin = None
        elif known:
            origin = 'source' if answer == source else 'override'
        else:
            origin = 'declared'
        evidence[name] = {'answer': answer, 'source': source, 'source_status': precheck.turnover_source_status,
                          'origin': origin, 'value': source if known else answer}
    return evidence


def collateral_gaps(collateral) -> dict:
    if not isinstance(collateral, dict) or collateral.get('status') != 'declared':
        return {'collateral': 'Для кредита с залогом заявите залог: тип, стоимость и описание.'}
    gaps = {}
    if not collateral.get('type'):
        gaps['collateral.type'] = 'Укажите тип залога'
    if not collateral.get('declared_value_rub'):
        gaps['collateral.declared_value_rub'] = 'Укажите стоимость залога'
    if not (collateral.get('description') or '').strip():
        gaps['collateral.description'] = 'Опишите залог'
    return gaps


def missing(answers: dict, product: dict, secured: bool) -> dict:
    """R3: answers required at submit that are absent, or confirmations not given, in stage order. A product without a
    term asks none; the pledge and its details are asked when the application is secured (`secured`: derived from the
    answers before submission, pinned after it). Source-owned answers are never client gaps: the client cannot give
    them (submission re-checks the verification; an unavailable registry is R4)."""
    gaps = {}
    for _, _, fields in STAGES:
        for field in fields:
            name, value = field['name'], answers.get(field['name'])
            if name in SOURCE_OWNED:
                continue
            if name == 'collateral':
                if secured:
                    gaps.update(collateral_gaps(value))
            elif name == 'term_months' and not has_term(product):
                continue
            elif field.get('must_be_true'):
                if value is not True:
                    gaps[name] = 'Требуется подтверждение'
            elif field['required'] and (value is None or (isinstance(value, str) and not value.strip())):
                gaps[name] = 'Заполните поле'
    return gaps


def corrections(answers: dict, product: dict, company: dict, *, registry_unavailable: bool) -> dict:
    """R1: what the selected product cannot accept. The company's current data must pass the product's machine-checked
    eligibility: a failed fact always blocks; an unknown one blocks like a failed one (as for `can_apply`) unless the
    registry source is unavailable — then the fact is unknown only because the source is down, the check waits (R4) and
    re-checks eligibility after the recovery (scoring.before_bki). Present answers must fit the purposes, the amount
    bounds and the term range (its per-purpose maximum included); a product without a term takes no term and one
    without collateral no declared pledge."""
    issues = {}
    blocking = ('failed',) if registry_unavailable else ('failed', 'unknown')
    blocked = [entry['text'] for entry in eligibility_checks(company, product, catalog.config()) if entry['result'] in blocking]
    if blocked:
        issues['product_id'] = ' '.join(blocked)
    purpose, amount, term = (answers.get(name) for name in ('purpose', 'requested_amount_rub', 'term_months'))
    if purpose is not None and purpose not in product['purposes']:
        issues['purpose'] = 'Цель не поддерживается выбранным продуктом.'
    if amount is not None and not product['amount_min_rub'] <= amount <= product['amount_max_rub']:
        issues['requested_amount_rub'] = f"Сумма продукта: от {rub(product['amount_min_rub'])} до {rub(product['amount_max_rub'])}."
    if term is not None and not has_term(product):
        issues['term_months'] = 'Срок для этого продукта не указывается: он действует без фиксированного срока.'
    elif term is not None:
        low, high = term_bounds(product, purpose)
        if not low <= term <= high:
            scope = f"для цели «{PURPOSES[purpose]}»" if high != product['term_max_months'] else 'продукта'
            issues['term_months'] = f'Срок {scope}: {low}–{high} мес.'
    collateral = answers.get('collateral')
    if product['collateral_mode'] == 'none' and isinstance(collateral, dict) and collateral.get('status') == 'declared':
        issues['collateral'] = 'Продукт выдаётся без залога: уберите заявленный залог.'
    return issues


def issues(answers: dict, product: dict, company: dict, secured: bool, *, registry_unavailable: bool) -> dict:
    """Everything blocking submission (R1 and R3), ordered by stage and field."""
    found = {**corrections(answers, product, company, registry_unavailable=registry_unavailable),
             **missing(answers, product, secured)}
    order = {name: index for index, name in enumerate(ANSWER_FIELDS)}
    return dict(sorted(found.items(), key=lambda item: order.get(item[0].split('.')[0], -1)))


def describe(field: dict, product: dict, evidence: dict, answers: dict, owned: dict) -> dict | None:
    """A field descriptor for the dialog, or None for a stage-2 field the product does not ask. A source-owned field is
    `read_only` with its source (name, status, value), `required: false` and no `must_be_true`: the client gives
    nothing for it."""
    described = dict(field)
    name = field['name']
    if name == 'purpose':
        described['options'] = [{'value': value, 'label': PURPOSES[value]} for value in product['purposes']]
    elif name == 'requested_amount_rub':
        described.update(min=product['amount_min_rub'], max=product['amount_max_rub'])
    elif name == 'term_months':
        if not has_term(product):
            return None
        low, high = term_bounds(product, answers.get('purpose'))
        described.update(min=low, max=high, max_by_purpose=dict(product['term_max_months_by_purpose']))
    elif name == 'collateral':
        if product['collateral_mode'] == 'none':
            return None
        described['required'] = product['collateral_mode'] == 'required'
    if name in evidence:
        entry = evidence[name]
        described['source'] = {'name': 'turnover', 'status': entry['source_status'], 'value': entry['source']}
        described['origin'] = entry['origin']
    if name in owned:
        # Nothing is asked of the client (R3 skips it): no requirement flags, only the source's value.
        described.update(read_only=True, source=owned[name], required=False)
        described.pop('must_be_true', None)
    return described


def stage_contract(answers: dict, product: dict, precheck, verification, blocking: dict) -> list[dict]:
    """Stage descriptors for the dialog; a stage is complete when none of its fields blocks submission."""
    evidence = finance_evidence(answers, precheck)
    owned = owned_sources(precheck, verification)
    blocked = {STAGE_OF.get(path.split('.')[0]) for path in blocking}
    return [{'number': number, 'title': title,
             'fields': [entry for entry in (describe(field, product, evidence, answers, owned) for field in fields)
                        if entry is not None],
             'complete': number not in blocked} for number, title, fields in STAGES]
