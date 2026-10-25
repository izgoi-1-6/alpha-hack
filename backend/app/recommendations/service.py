"""Pure, deterministic preliminary recommendations over every catalog card product.

Inputs are the persisted company and registry/turnover precheck, the client's requested amount and the runtime
product configuration. Only machine-checkable eligibility applies (entity type, SME register, region, main OKVED
class, an open program); requirements, categories and unparsed OKVED text are conditions to confirm, never a block.
Credit history, scoring and approval odds are out of scope: an estimate is an upper bound by turnover, never a
preapproval. Every number comes from the configuration.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from ..products_config.rules import okved_class

STATUS_ORDER = {'fits': 0, 'needs_info': 1, 'does_not_fit': 2}
ENTITY_NAMES = {'IP': 'ИП', 'LLC': 'ООО'}
CHECK_CODES = ('company_active', 'entity_type', 'msp_registry', 'region', 'okved', 'program_status', 'amount_min',
               'catalog_max', 'turnover', 'collateral', 'amount_capacity')
# What must pass before an application may be started; capacity, turnover and collateral gaps do not block a draft.
APPLICATION_GATES = CHECK_CODES[:8]
# Product conditions whose failure means the product plainly cannot be offered, so no payment is shown.
PRODUCT_CONDITIONS = APPLICATION_GATES[1:]
ELIGIBILITY = ('entity_type', 'msp_registry', 'region', 'okved', 'program_status')
NOTICE = 'Предварительная оценка по обороту, не предодобрение. БКИ не запрашивалось.'
FITS_NOTE = 'Сумма укладывается в предварительные условия продукта. Решение принимается после отправки заявки.'
GUARANTOR_NOTE = 'Доля учредителя не означает согласия на поручительство. Поручители на этом этапе не оцениваются.'


def rub(value: int) -> str:
    return f'{value:,}'.replace(',', ' ') + ' ₽'


def percent(bps: int) -> str:
    whole, part = divmod(bps, 100)
    return f'{whole},{part:02d}'.rstrip('0') if part else str(whole)


def check(code: str, result: str, text: str) -> dict:
    return {'code': code, 'result': result, 'text': text}


def annuity(amount: int, bps: int, months: int) -> int:
    """Indicative term-loan payment: Decimal annuity rounded half up (an interest-free rate repays A/n a month)."""
    with localcontext() as ctx:
        ctx.prec = 40
        rate = Decimal(bps) / Decimal(120000)
        payment = Decimal(amount) / months if bps == 0 else Decimal(amount) * rate / (1 - (1 + rate) ** -months)
        return int(payment.to_integral_value(rounding=ROUND_HALF_UP))


def full_utilization_interest(amount: int, bps: int) -> int:
    # ceil(A * bps / 120000) in integers: a rounded monthly rate could push an exact total up by a ruble.
    return -(-amount * bps // 120000)


def estimate_months(product: dict, config) -> int:
    """The policy's estimate term, inside the product's own term range."""
    return max(product['term_min_months'], min(product['term_max_months'], config.payment_estimate_term_months))


def personal_limit(product: dict, revenue: int | None) -> int | None:
    """min(product maximum, low multiple × monthly turnover, unsecured cap). The need states no collateral, so a
    product that requires it has no limit yet; unknown or non-positive turnover gives none (zero is an anomaly)."""
    if revenue is None or revenue <= 0 or product['collateral_mode'] == 'required':
        return None
    return min(product['amount_max_rub'], product['low_risk_revenue_multiple'] * revenue, product['unsecured_cap_rub'])


def registry_check(registry_status: str) -> dict:
    if registry_status == 'active':
        return check('company_active', 'passed', 'Действующий статус компании подтверждён реестром.')
    if registry_status == 'unknown':
        return check('company_active', 'unknown', 'Нужно подтвердить статус в реестре.')
    return check('company_active', 'failed', 'Деятельность компании прекращена; доступен только просмотр.')


def msp_check(product: dict, flag: bool | None) -> dict:
    if not product['eligibility']['msp_registry_required']:
        return check('msp_registry', 'passed', 'Включение в реестр МСП не требуется.')
    if flag is True:
        return check('msp_registry', 'passed', 'Компания включена в реестр МСП.')
    if flag is False:
        return check('msp_registry', 'failed', 'Продукт доступен только компаниям и ИП из реестра МСП.')
    return check('msp_registry', 'unknown', 'Нужно подтвердить включение в реестр МСП.')


def region_check(product: dict, region: str | None, config) -> dict:
    allowed = product['eligibility']['regions_allow']
    if not allowed:
        return check('region', 'passed', 'Ограничений по региону нет.')
    if region is None:
        return check('region', 'unknown', 'Нужно подтвердить регион регистрации компании.')
    if config.region_in(region, allowed):
        return check('region', 'passed', f'Регион регистрации подходит: {region.strip()}.')
    return check('region', 'failed', f"Продукт доступен в регионах: {', '.join(allowed)}.")


def okved_check(product: dict, okved: str | None) -> dict:
    denied = product['eligibility']['okved_denied_classes']
    if not denied:
        return check('okved', 'passed', 'Ограничений по основному ОКВЭД нет.')
    found = okved_class(okved)
    if found is None:
        return check('okved', 'unknown', 'Нужно подтвердить основной ОКВЭД компании.')
    if found in denied:
        return check('okved', 'failed', f'Основной ОКВЭД {okved.strip()} входит в ограничения продукта.')
    return check('okved', 'passed', 'Основной ОКВЭД не входит в ограничения продукта.')


def program_check(product: dict) -> dict:
    if product['applyable']:
        return check('program_status', 'passed', 'Продукт действует, приём заявок открыт.')
    return check('program_status', 'failed', 'Приём заявок по продукту сейчас закрыт.')


def turnover_check(product: dict, revenue: int | None) -> dict:
    if revenue is not None and revenue > 0:
        return check('turnover', 'passed', f"Предварительная оценка не выше {product['low_risk_revenue_multiple']} × среднемесячного оборота.")
    text = ('Нужны положительные сведения об обороте; нулевой оборот требует уточнения.' if revenue == 0
            else 'Оборот неизвестен. Финансовые сведения можно дополнить в анкете.')
    return check('turnover', 'unknown', text)


def collateral_check(product: dict) -> dict:
    mode = product['collateral_mode']
    if mode == 'none':
        return check('collateral', 'passed', 'Залог не требуется.')
    if mode == 'optional':
        return check('collateral', 'passed', 'Залог не обязателен; его можно указать в анкете.')
    return check('collateral', 'unknown', 'Нужен залог: тип и стоимость укажете в анкете, документы проверит банк.')


def capacity_check(product: dict, requested: int, limit: int | None) -> dict:
    if limit is None:
        return check('amount_capacity', 'unknown', 'Личный лимит пока неизвестен.')
    if requested <= limit:
        return check('amount_capacity', 'passed', 'Сумма укладывается в предварительную оценку.')
    if limit < product['amount_min_rub']:
        return check('amount_capacity', 'failed', 'Предварительная оценка ниже минимальной суммы продукта.')
    return check('amount_capacity', 'failed', 'Запрошенная сумма выше предварительной оценки. Возможно рассмотрение меньшей суммы.')


def build_checks(company: dict, product: dict, requested: int, revenue: int | None, limit: int | None, config) -> list[dict]:
    """The eleven criteria of the contract, in contract order."""
    entity_names = ' и '.join(ENTITY_NAMES[kind] for kind in product['entity_types'])
    return [
        registry_check(company['registry_status']),
        check('entity_type', 'passed' if company['entity_type'] in product['entity_types'] else 'failed', f'Продукт доступен {entity_names}.'),
        msp_check(product, company.get('msp_registry')),
        region_check(product, company.get('region'), config),
        okved_check(product, company.get('okved')),
        program_check(product),
        check('amount_min', 'passed' if requested >= product['amount_min_rub'] else 'failed',
              f"Минимальная сумма: {rub(product['amount_min_rub'])}."),
        check('catalog_max', 'passed' if requested <= product['amount_max_rub'] else 'failed',
              f"Максимум продукта: {rub(product['amount_max_rub'])}. Это не личный лимит."),
        turnover_check(product, revenue),
        collateral_check(product),
        capacity_check(product, requested, limit),
    ]


def status_of(checks: list[dict]) -> str:
    if any(c['result'] == 'failed' for c in checks):
        return 'does_not_fit'
    if any(c['result'] == 'unknown' for c in checks):
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
    if product['collateral_mode'] == 'required':
        reasons.append(GUARANTOR_NOTE)
    return reasons


def alternatives_of(company: dict, product: dict, requested: int, results: dict, limit: int | None, missing: str,
                    status: str) -> list[str]:
    if company['registry_status'] == 'inactive':
        return ['Заявка недоступна для неактивной компании: выберите действующую компанию.']
    options = []
    if company['registry_status'] == 'unknown':
        options.append('Повторите проверку реестра в профиле компании.')
    if any(results[code] == 'failed' for code in ELIGIBILITY):
        options.append('Компания не подходит под условия этого продукта: сравните другие продукты.')
    elif results['amount_min'] == 'failed' or results['catalog_max'] == 'failed':
        options.append(f"Выберите сумму в диапазоне {rub(product['amount_min_rub'])}–{rub(product['amount_max_rub'])}.")
    elif limit is None:
        options.append(f'Дополните сведения {missing} в анкете: от них зависит личный лимит.')
    elif limit < product['amount_min_rub']:
        options.append('Предварительная оценка ниже минимальной суммы продукта; уточните сведения об обороте или выберите другой продукт.')
    elif requested > limit:
        options.append(f'Рассмотрите сумму до {rub(limit)} по предварительной оценке.')
    if not options and status != 'fits':
        options.append('Уточните сведения компании или измените сумму.')
    return options


def payment_of(product: dict, requested: int, results: dict, limit: int | None, missing: str,
               config) -> tuple[int | None, str, str | None]:
    """(indicative payment on min(requested, personal limit), its note, its label), or a null payment with the
    reason. A preferential rate labels the payment with its period."""
    if results['company_active'] == 'failed':
        return None, 'Платёж не рассчитан: компания не действует.', None
    if any(results[code] == 'failed' for code in PRODUCT_CONDITIONS):
        return None, 'Платёж не рассчитан: сумма или компания не соответствуют условиям продукта.', None
    if product['payment_model'] == 'none':
        return None, 'Ежемесячный платёж не рассчитывается: задолженность погашает заказчик из оплаты поставки.', None
    if product['rate_certainty'] == 'undisclosed':
        return None, 'Ставка уточняется: банк её не публикует, поэтому платёж не рассчитан.', None
    if limit is None:
        return None, f'Платёж не рассчитан: личный лимит пока неизвестен — нужны сведения {missing}.', None
    amount = min(requested, limit)
    if amount < product['amount_min_rub']:
        return None, 'Платёж не рассчитан: предварительная оценка ниже минимальной суммы продукта.', None
    bps, preferential = product['annual_rate_bps'], product['rate_preferential_months']
    rate = f'{percent(bps)}% годовых' + (f' — льготная ставка на первые {preferential} мес.' if preferential else '')
    if product['payment_model'] == 'annuity':
        months = estimate_months(product, config)
        payment = annuity(amount, bps, months)
        note = f'Расчёт на сумму {rub(amount)}, срок {months} мес. Аннуитетный платёж по ставке {rate}, комиссии не включены.'
    else:
        payment = full_utilization_interest(amount, bps)
        note = (f'Расчёт на сумму {rub(amount)}. Проценты за месяц при полном использовании лимита по ставке {rate}; '
                'основной долг возвращается в конце срока. Комиссии не включены.')
        if product['tranche_min_rub']:
            note += f" Минимальный транш {rub(product['tranche_min_rub'])}."
    if preferential:
        note += ' После льготного периода ставка и платёж могут измениться.'
    return payment, note, f'в льготный период {preferential} мес.' if preferential else None


def badges_of(company: dict, product: dict, config) -> list[dict]:
    """Overlays shown on the card: the overlay lists the product, the company meets its machine-checkable conditions
    (SME register, entity type, region) and its main OKVED is known and not denied, unless the policy exempts the
    product. A card that requires collateral gets the softer text."""
    badges = []
    for overlay in config.overlays:
        eligibility = overlay['eligibility']
        if product['id'] not in overlay['applies_to'] or overlay['status'] != 'active' or overlay['limit_status'] != 'open':
            continue
        if eligibility['msp_registry_required'] and company.get('msp_registry') is not True:
            continue
        if company['entity_type'] not in overlay['entity_types']:
            continue
        region = company.get('region')
        if eligibility['regions_allow'] and (region is None or not config.region_in(region, eligibility['regions_allow'])):
            continue
        okved = okved_class(company.get('okved'))
        if eligibility['okved_denied_classes'] and product['id'] not in overlay['okved_exempt_products'] \
                and (okved is None or okved in eligibility['okved_denied_classes']):
            continue
        text = overlay['badge_text_collateral_required'] if product['collateral_mode'] == 'required' else overlay['badge_text']
        badges.append({'overlay_id': overlay['id'], 'name': overlay['name'], 'text': text})
    return badges


def evaluate_product(company: dict, product: dict, requested: int, revenue: int | None, config) -> tuple[tuple, dict]:
    limit = personal_limit(product, revenue)
    checks = build_checks(company, product, requested, revenue, limit, config)
    results = {c['code']: c['result'] for c in checks}
    status = status_of(checks)
    missing = missing_phrase(revenue is not None and revenue > 0, product['collateral_mode'] == 'required')
    payment, note, label = payment_of(product, requested, results, limit, missing, config)
    item = {'product_id': product['id'], 'rank': 0, 'status': status,
            'can_apply': all(results[code] == 'passed' for code in APPLICATION_GATES),
            'indicative_limit_rub': limit, 'catalog_max_rub': product['amount_max_rub'], 'requested_amount_rub': requested,
            'checks': checks, 'reasons': reasons_of(product, checks, status),
            'alternatives': alternatives_of(company, product, requested, results, limit, missing, status),
            'estimated_payment_rub': payment, 'payment_note': note, 'payment_label': label,
            'badges': badges_of(company, product, config),
            'conditions_to_confirm': [dict(entry) for entry in product['conditions_to_confirm']]}
    # Contract order: status, known shortfall (unknown capacity counts as the whole request), collateral burden, rate
    # certainty, rate (an undisclosed rate counts as 0 within its certainty), policy priority, id. A preferential or
    # undisclosed rate never outranks a stated full-term rate.
    shortfall = max(0, requested - limit) if limit is not None else requested
    key = (STATUS_ORDER[status], shortfall, config.ranking['collateral_burden'][product['collateral_mode']],
           config.ranking['rate_certainty'][product['rate_certainty']], product['annual_rate_bps'] or 0,
           product['priority'], product['id'])
    return key, item


def recommend(company: dict, precheck: dict, need: dict, config) -> list[dict]:
    """Ranked recommendation items for every card product of the configuration."""
    revenue = precheck.get('monthly_revenue_rub')
    requested = need['requested_amount_rub']
    ranked = sorted((evaluate_product(company, product, requested, revenue, config) for product in config.products),
                    key=lambda pair: pair[0])
    items = [item for _, item in ranked]
    for rank, item in enumerate(items, 1):
        item['rank'] = rank
    return items
