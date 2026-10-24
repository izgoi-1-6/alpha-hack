"""Pure, deterministic preliminary recommendations.

Inputs are the persisted registry/turnover precheck, the client's stated need and the versioned product
policies. Credit history, scoring and approval odds are deliberately out of scope: an estimate is an upper
bound by turnover (and declared collateral), never a preapproval. Every number comes from the policy dicts.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext

STATUS_ORDER = {'fits': 0, 'needs_info': 1, 'does_not_fit': 2}
ENTITY_NAMES = {'IP': 'ИП', 'LLC': 'ООО'}
# Checks that must pass before an application may be started; capacity and data gaps do not block a draft.
APPLICATION_GATES = ('company_active', 'entity_type', 'purpose', 'term', 'amount_min', 'catalog_max')
# The payment is shown unless the product plainly cannot be offered; an unconfirmed registry only blocks applying.
PAYMENT_GATES = ('entity_type', 'purpose', 'term', 'amount_min', 'catalog_max')
NOTICE = 'Предварительная оценка по обороту, не предодобрение. БКИ не запрашивалось.'
FITS_NOTE = 'Цель, срок и сумма соответствуют предварительным условиям. Решение принимается после отправки заявки.'
GUARANTOR_NOTE = 'Доля учредителя не означает согласия на поручительство. Поручители в этом демо не оцениваются.'


def rub(value: int) -> str:
    return f'{value:,}'.replace(',', ' ') + ' ₽'


def check(code: str, result: str, text: str) -> dict:
    return {'code': code, 'result': result, 'text': text}


def monthly_payment(product: dict, amount: int, months: int) -> int:
    """Indicative RUB payment: term-loan annuity (half up), or a revolving line's full-utilization interest (up)."""
    if product['instrument_type'] == 'revolving_credit_line':
        # ceil(A * bps / 120000) in integers: a rounded monthly rate could push an exact total up by a ruble.
        return -(-amount * product['annual_rate_bps'] // 120000)
    with localcontext() as ctx:
        ctx.prec = 40
        rate = Decimal(product['annual_rate_bps']) / Decimal(120000)
        annuity = Decimal(amount) * rate / (1 - (1 + rate) ** -months)
        return int(annuity.to_integral_value(rounding=ROUND_HALF_UP))


def payment_assumptions(product: dict, amount: int, months: int) -> str:
    note = f'Расчёт на сумму {rub(amount)}, срок {months} мес. '
    if product['instrument_type'] == 'revolving_credit_line':
        line = product['revolving_assumptions']
        renewal = 'с автопродлением' if line['auto_renewal'] else 'без автопродления'
        note += ('Проценты за месяц при полном использовании лимита; основной долг возвращается в конце срока. '
                 f"Минимальная выборка {rub(line['minimum_draw_rub'])}, {renewal}. Комиссии не включены.")
    else:
        note += 'Аннуитетный платёж по учебной фиксированной ставке, комиссии не включены.'
    if product['collateral_required']:
        note += ' Залог и его стоимость требуют проверки документов.'
    return note


def personal_limit(product: dict, revenue: int | None, collateral: dict) -> int | None:
    """Upper indicative capacity: a multiple of monthly turnover capped by the product ceiling and, for secured
    products, by the declared collateral. Unknown or non-positive turnover and unknown collateral give no limit
    (zero turnover is a finance anomaly, not a zero limit)."""
    if revenue is None or revenue <= 0:
        return None
    limit = min(product['amount_max_rub'], product['low_risk_revenue_multiple'] * revenue)
    if not product['collateral_required']:
        return limit
    if collateral['status'] != 'declared':
        return None
    return min(limit, collateral['declared_value_rub'] * product['collateral_ltv_bps'] // 10000)


def registry_check(registry_status: str) -> dict:
    if registry_status == 'active':
        return check('company_active', 'passed', 'Действующий статус компании подтверждён демо-реестром.')
    if registry_status == 'unknown':
        return check('company_active', 'unknown', 'Нужно подтвердить статус в реестре.')
    return check('company_active', 'failed', 'Деятельность компании прекращена; доступен только просмотр.')


def turnover_check(product: dict, revenue: int | None) -> dict:
    if revenue is not None and revenue > 0:
        return check('turnover', 'passed', f"Предварительная оценка не выше {product['low_risk_revenue_multiple']} × среднемесячного оборота.")
    text = ('Нужны положительные сведения об обороте; нулевой оборот требует уточнения.' if revenue == 0
            else 'Оборот неизвестен. Финансовые сведения можно дополнить в анкете.')
    return check('turnover', 'unknown', text)


def collateral_check(product: dict, collateral: dict) -> dict:
    if not product['collateral_required']:
        return check('collateral', 'passed', 'Залог не требуется.')
    # Ownership is self-declared; an encumbered or unconfirmed pledge needs review rather than a pass.
    confirmed = (collateral['status'] == 'declared' and collateral.get('owner_confirmed') is True
                 and collateral.get('encumbered') is False)
    if confirmed:
        return check('collateral', 'passed', 'Стоимость и право собственности заявлены клиентом; понадобятся документы.')
    return check('collateral', 'unknown', 'Нужен заявленный залог с подтверждением собственности и отсутствия обременения. Данные требуют проверки.')


def capacity_check(product: dict, requested: int, limit: int | None) -> dict:
    if limit is None:
        return check('amount_capacity', 'unknown', 'Личный лимит пока неизвестен.')
    if requested <= limit:
        return check('amount_capacity', 'passed', 'Сумма укладывается в предварительную оценку.')
    if limit < product['amount_min_rub']:
        return check('amount_capacity', 'failed', 'Предварительная оценка ниже минимальной суммы продукта.')
    return check('amount_capacity', 'failed', 'Запрошенная сумма выше предварительной оценки. Возможно рассмотрение меньшей суммы.')


def build_checks(company: dict, product: dict, need: dict, revenue: int | None, collateral: dict, limit: int | None) -> list[dict]:
    """The ten criteria of the contract, in contract order."""
    purpose_ok = need['purpose'] in product['purposes']
    pattern_ok = need['funding_pattern'] == product['preferred_funding_pattern']
    entity_names = ' и '.join(ENTITY_NAMES[kind] for kind in product['entity_types'])
    return [
        registry_check(company['registry_status']),
        check('entity_type', 'passed' if company['entity_type'] in product['entity_types'] else 'failed', f'Продукт доступен {entity_names}.'),
        check('purpose', 'passed' if purpose_ok else 'failed',
              'Цель поддерживается.' if purpose_ok else 'Выбранная цель не поддерживается этим продуктом.'),
        # A different funding pattern is advisory: a revolving line can serve a single purchase.
        check('funding_pattern', 'passed' if pattern_ok else 'unknown',
              'Формат финансирования соответствует потребности.' if pattern_ok else
              'Другой формат: линия удобнее для повторных расходов, кредит одной суммой — для разовой задачи. Это не запрет подачи заявки.'),
        check('term', 'passed' if product['term_min_months'] <= need['term_months'] <= product['term_max_months'] else 'failed',
              f"Срок продукта: {product['term_min_months']}–{product['term_max_months']} мес."),
        check('amount_min', 'passed' if need['requested_amount_rub'] >= product['amount_min_rub'] else 'failed',
              f"Минимальная сумма: {rub(product['amount_min_rub'])}."),
        check('catalog_max', 'passed' if need['requested_amount_rub'] <= product['amount_max_rub'] else 'failed',
              f"Максимум продукта: {rub(product['amount_max_rub'])}. Это не личный лимит."),
        turnover_check(product, revenue),
        collateral_check(product, collateral),
        capacity_check(product, need['requested_amount_rub'], limit),
    ]


def status_of(checks: list[dict]) -> str:
    if any(c['result'] == 'failed' for c in checks):
        return 'does_not_fit'
    # The funding pattern is never a data prerequisite, so only other unknowns ask for more information.
    if any(c['result'] == 'unknown' and c['code'] != 'funding_pattern' for c in checks):
        return 'needs_info'
    return 'fits'


def missing_phrase(turnover_known: bool, collateral_missing: bool) -> str:
    """Names the gaps that keep the personal limit unknown."""
    if not turnover_known:
        return 'об обороте и залоге' if collateral_missing else 'об обороте'
    return 'о залоге'


def reasons_of(product: dict, checks: list[dict], status: str) -> list[str]:
    reasons = [FITS_NOTE] if status == 'fits' else []
    reasons += [c['text'] for c in checks if c['result'] != 'passed']
    reasons.append(NOTICE)
    if product['collateral_required']:
        reasons.append(GUARANTOR_NOTE)
    return reasons


def alternatives_of(company: dict, product: dict, need: dict, results: dict, limit: int | None, missing: str, status: str) -> list[str]:
    if company['registry_status'] == 'inactive':
        return ['Заявка недоступна для неактивной компании: выберите действующую компанию.']
    requested = need['requested_amount_rub']
    options = []
    if company['registry_status'] == 'unknown':
        options.append('Повторите проверку реестра в профиле компании.')
    if limit is None:
        options.append(f'Дополните сведения {missing}.')
    elif limit < product['amount_min_rub']:
        basis = 'об обороте или залоге' if product['collateral_required'] else 'об обороте'
        options.append(f'Предварительная оценка ниже минимальной суммы продукта; уточните сведения {basis} или измените потребность.')
    elif requested > limit:
        options.append(f'Рассмотрите сумму до {rub(limit)} по предварительной оценке.')
    if results['term'] == 'failed':
        options.append(f"Выберите срок {product['term_min_months']}–{product['term_max_months']} мес.")
    if results['purpose'] == 'failed':
        options.append('Измените цель или сравните другой продукт.')
    if results['amount_min'] == 'failed' or results['catalog_max'] == 'failed':
        options.append(f"Выберите сумму в диапазоне {rub(product['amount_min_rub'])}–{rub(product['amount_max_rub'])}.")
    if not options and status != 'fits':
        options.append('Уточните сведения компании или измените параметры потребности.')
    return options


def payment_of(product: dict, need: dict, results: dict, limit: int | None, missing: str) -> tuple[int | None, str]:
    """Indicative payment on min(requested, personal limit), or a null payment with the reason."""
    if results['company_active'] == 'failed':
        return None, 'Платёж не рассчитан: компания не действует.'
    if any(results[code] != 'passed' for code in PAYMENT_GATES):
        return None, 'Платёж не рассчитан: параметры потребности не соответствуют условиям продукта.'
    if limit is None:
        return None, f'Платёж не рассчитан: личный лимит пока неизвестен — нужны сведения {missing}.'
    amount = min(need['requested_amount_rub'], limit)
    if amount < product['amount_min_rub']:
        return None, 'Платёж не рассчитан: предварительная оценка ниже минимальной суммы продукта.'
    return monthly_payment(product, amount, need['term_months']), payment_assumptions(product, amount, need['term_months'])


def evaluate_product(company: dict, product: dict, need: dict, revenue: int | None, collateral: dict) -> tuple[tuple, dict]:
    requested = need['requested_amount_rub']
    limit = personal_limit(product, revenue, collateral)
    checks = build_checks(company, product, need, revenue, collateral, limit)
    results = {c['code']: c['result'] for c in checks}
    status = status_of(checks)
    missing = missing_phrase(revenue is not None and revenue > 0, product['collateral_required'] and collateral['status'] != 'declared')
    estimated, payment_note = payment_of(product, need, results, limit, missing)
    item = {'product_id': product['id'], 'rank': 0, 'status': status,
            'can_apply': product['can_apply'] and all(results[code] == 'passed' for code in APPLICATION_GATES),
            'indicative_limit_rub': limit, 'catalog_max_rub': product['amount_max_rub'], 'requested_amount_rub': requested,
            'checks': checks, 'reasons': reasons_of(product, checks, status),
            'alternatives': alternatives_of(company, product, need, results, limit, missing, status),
            'estimated_payment_rub': estimated, 'payment_note': payment_note}
    # Contract order: status, purpose mismatch, preferred-pattern mismatch, amount shortfall (unknown capacity counts
    # as the whole request), collateral requirement, rate, id. Price comes after suitability by design.
    shortfall = max(0, requested - limit) if limit is not None else requested
    key = (STATUS_ORDER[status], results['purpose'] != 'passed', results['funding_pattern'] != 'passed', shortfall,
           product['collateral_required'], product['annual_rate_bps'], product['id'])
    return key, item


def recommend(company: dict, precheck: dict, need: dict, products: list[dict]) -> list[dict]:
    """Ranked recommendation items for the supplied (supported) product policies."""
    revenue = precheck.get('monthly_revenue_rub')
    collateral = need.get('collateral') or {'status': 'unknown'}
    ranked = sorted((evaluate_product(company, product, need, revenue, collateral) for product in products),
                    key=lambda pair: pair[0])
    items = [item for _, item in ranked]
    for rank, item in enumerate(items, 1):
        item['rank'] = rank
    return items
