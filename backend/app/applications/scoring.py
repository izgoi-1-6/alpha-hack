"""Pure post-submission scoring and the R2-R11 decision. No I/O; integer arithmetic only.

Factors (spec "Scoring and state machine"): business age in completed calendar months, revenue growth (R-P)/P,
monthly debt burden debt/R and the BKI credit history, compared exactly by cross-multiplication. Rules run in the
spec table's order: `before_bki` covers R2 (known inactive, or a machine eligibility fact of the pinned product that the
current company data fails — reached after a registry recovery, since R1 refuses it at submission), R3 (a
client-answerable gap) and R4 (registry or turnover unavailable), so none of them spends a BKI request; `after_bki` covers the report's R4/R2/R3, then the review flags
(R5), R6, R7 and R8-R11. A check that recovers trusted-source evidence (an open trusted_source request) ends in
MANUAL_REVIEW unless R2, R6 or R7 rejects. `after_response` re-checks revised answers after an information response
and always ends in MANUAL_REVIEW. Score and limit stay null when they cannot be computed.
"""
import calendar
from dataclasses import dataclass
from datetime import date
from ..products_config import limits
from ..recommendations.service import rub

HISTORY_POINTS = {'clean': 25, 'minor_closed': 10, 'serious': 0}
LOW_RISK_MIN_SCORE, MEDIUM_RISK_MIN_SCORE = 75, 50
OVERDUE_STOP_DAYS = 30
BKI_CATEGORIES = ('credit_history', 'current_overdue_days')
REVENUE_FIELDS = ('monthly_revenue_rub', 'previous_monthly_revenue_rub')

REASONS = {
    'inactive': 'Компания не действует по данным реестра.',
    'ineligible': 'По обновлённым данным реестра компания не подходит под условия продукта.',
    'overdue': 'Текущая просрочка по данным БКИ — 30 дней или более.',
    'client_gap': 'Для проверки не хватает обязательных сведений анкеты.',
    'bki_missing': 'Ответ БКИ не содержит категорию кредитной истории. Нужен повторный запрос к источнику; '
                   'анкета эти сведения не принимает.',
    'registry_unavailable': 'Реестр временно недоступен. Повторите проверку.',
    'turnover_unavailable': 'Источник оборотов временно недоступен. Повторите проверку.',
    'bki_unavailable': 'БКИ временно недоступно. Повторите проверку: запрос выполнится по сохранённому согласию.',
    'high_risk': 'Высокий риск по результатам скоринга: менее 50 баллов.',
    'manual': 'Заявку проверит кредитный специалист.',
    'noncomputable': 'Балл и лимит нельзя рассчитать автоматически.',
    'trusted_review': 'Сведения получены повторным запросом к БКИ; заявку проверит кредитный специалист.',
    'low': 'Низкий риск: запрошенная сумма укладывается в рассчитанный лимит. Это предварительное одобрение, '
           'не окончательное решение.',
    'medium': 'Средний риск: заявку рассмотрит кредитный специалист.',
    'answered': 'Клиент ответил на запрос сведений: расчёт обновлён по новым ответам и сохранённым данным источников; '
                'заявку проверит кредитный специалист.',
    'no_bki': 'Данных БКИ по заявке нет: балл и лимит не рассчитаны.',
}
# Flags of earlier evaluations that a re-check after an information response keeps: a declaration or a conflict with
# the source stays on record even when the revised answers no longer show it.
RETAINED_FLAGS = ('declared_finance', 'finance_override')
# R5 review flags, in the order they are reported.
FLAG_REASONS = {
    'zero_revenue': 'Нулевая выручка за текущий или предыдущий период: автоматический расчёт невозможен.',
    'invalid_source': 'Некорректные данные источника требуют проверки специалистом.',
    'declared_finance': 'Финансовые показатели заявлены клиентом и не подтверждены источником.',
    'finance_override': 'Финансовые показатели в анкете отличаются от данных источника; исходные значения сохранены.',
    'collateral_unconfirmed': 'Право собственности на залог не подтверждено или залог обременён.',
    'tax_debt': 'Указана налоговая задолженность.',
    'legal_proceedings': 'Указаны судебные разбирательства.',
    'registry_unconfirmed': 'Статус компании в реестре не подтверждён.',
}
QUESTIONS = {
    'bki': 'БКИ ответило без категории кредитной истории. Нажмите «Повторить проверку»: запрос выполнится '
           'по сохранённому согласию на БКИ. Эти сведения нельзя указать в анкете.',
    'client_answers': 'Дополните сведения анкеты, без которых проверку нельзя завершить.',
}


def is_count(value) -> bool:
    """A non-negative integer (booleans excluded): what every scored amount, age and day count must be."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def completed_months(start: date, end: date) -> int:
    """Whole calendar months from start to end; a month ending on a shorter month's last day counts as completed."""
    months = (end.year - start.year) * 12 + end.month - start.month
    anniversary = min(start.day, calendar.monthrange(end.year, end.month)[1])
    return months - (1 if end.day < anniversary else 0)


def age_points(months: int) -> int:
    return 20 if months >= 24 else 10 if months >= 6 else 0


def growth_points(revenue: int, previous: int) -> int:
    """(R-P)/P above +10% is 25, from -10% to +10% inclusive 15, below -10% 0; requires P > 0."""
    change = 10 * (revenue - previous)
    return 25 if change > previous else 15 if change >= -previous else 0


def burden_points(debt: int, revenue: int) -> int:
    """debt/R up to 30% is 30, above 30% through 50% 15, above 50% 0; requires R > 0."""
    return 30 if 10 * debt <= 3 * revenue else 15 if 2 * debt <= revenue else 0


def score_of(age_months: int, revenue: int, previous: int, debt: int, credit_history: str) -> tuple[int, dict]:
    factors = {'age_months': age_months, 'age_points': age_points(age_months),
               'revenue_growth_points': growth_points(revenue, previous), 'debt_burden_points': burden_points(debt, revenue),
               'credit_history': credit_history, 'credit_history_points': HISTORY_POINTS[credit_history]}
    return sum(value for key, value in factors.items() if key.endswith('_points')), factors


def risk_of(score: int) -> str:
    return 'low' if score >= LOW_RISK_MIN_SCORE else 'medium' if score >= MEDIUM_RISK_MIN_SCORE else 'high'


def declared_value(collateral: dict | None) -> int | None:
    collateral = collateral or {}
    return collateral.get('declared_value_rub') if collateral.get('status') == 'declared' else None


def scored_limit(product: dict, risk: str, revenue: int | None, secured: bool, collateral: dict | None) -> int | None:
    """The personal limit (products_config.limits) at the scored risk: a secured application adds the collateral cap
    of the declared value to the product's unsecured cap, and has no limit without a declared value. (Final approval
    uses the verified value instead: officer.policy.)"""
    return limits.personal_limit(product, risk, revenue, secured=secured, collateral_value=declared_value(collateral))


def indicative_limit(product: dict, revenue: int | None, secured: bool, collateral: dict | None) -> int | None:
    """The post-submission upper estimate: the low-risk personal limit on the stage-3 scored revenue — the turnover
    source value when the source knows it, otherwise the client's declared answer, which keeps its 'declared' tag in the
    evaluation evidence. It is not a scored limit and promises no capacity."""
    return scored_limit(product, 'low', revenue, secured, collateral)


@dataclass(frozen=True)
class CheckInput:
    """What one check reads: the pinned product terms and secured flag, persisted company/source state and the frozen
    answers.

    `finance` is stages.finance_evidence(): per stage-3 field the answer, the source value, the source status, the
    origin tag (source/declared/override) and the scored `value` (the source value whenever one is known)."""
    product: dict
    secured: bool
    registry_status: str
    registry_source_status: str
    turnover_source_status: str
    age_months: int | None
    finance: dict
    answers: dict
    missing_answers: tuple[str, ...] = ()
    eligibility_failures: tuple[str, ...] = ()  # texts of the pinned product's eligibility checks the company now fails


@dataclass(frozen=True)
class Decision:
    rule: str
    outcome: str
    reasons: tuple[str, ...]
    score: int | None = None
    risk: str | None = None
    factors: dict | None = None
    scored_limit_rub: int | None = None
    preapproved_amount_rub: int | None = None
    flags: tuple[str, ...] = ()
    info_request: dict | None = None  # {kind, source, requested_fields, question} for a system-detected gap
    reason_code: str | None = None  # the history row's reason code when it is not the rule (ELIGIBILITY_FAILED)


def before_bki(check: CheckInput) -> Decision | None:
    """R2, R3 and R4 outcomes that need no BKI request; None means the BKI simulator may be called."""
    if check.registry_status == 'inactive':
        return Decision('R2', 'REJECTED', (REASONS['inactive'],))
    if check.eligibility_failures:
        return Decision('R2', 'REJECTED', (REASONS['ineligible'] + ' ' + ' '.join(check.eligibility_failures),),
                        reason_code='ELIGIBILITY_FAILED')
    if check.missing_answers:
        return Decision('R3', 'NEED_INFO', (REASONS['client_gap'],), info_request={
            'kind': 'client_answers', 'source': None, 'requested_fields': list(check.missing_answers),
            'question': QUESTIONS['client_answers']})
    if check.registry_source_status == 'unavailable':
        return Decision('R4', 'WAIT_EXTERNAL', (REASONS['registry_unavailable'],))
    if check.turnover_source_status == 'unavailable':
        return Decision('R4', 'WAIT_EXTERNAL', (REASONS['turnover_unavailable'],))
    return None


def review_flags(check: CheckInput, report: dict | None) -> tuple[str, ...]:
    """R5 conditions: zero or malformed values, declared or overridden finance, an unconfirmed pledge of a secured
    application, tax/legal concerns and an unconfirmed registry status. Without a BKI report only the non-BKI values
    are checked."""
    revenue, previous = (check.finance[name]['value'] for name in REVENUE_FIELDS)
    origins = {entry['origin'] for entry in check.finance.values()}
    flags = []
    if revenue == 0 or previous == 0:
        flags.append('zero_revenue')
    counts = [revenue, previous, check.answers.get('monthly_debt_payment_rub'), check.age_months]
    if report is not None:
        counts.append(report.get('current_overdue_days'))
    if not all(is_count(value) for value in counts) or (report is not None and report.get('credit_history') not in HISTORY_POINTS):
        flags.append('invalid_source')
    if 'declared' in origins:
        flags.append('declared_finance')
    if 'override' in origins:
        flags.append('finance_override')
    if check.secured:
        collateral = check.answers.get('collateral') or {}
        if collateral.get('owner_confirmed') is not True or collateral.get('encumbered') is not False:
            flags.append('collateral_unconfirmed')
    tax_debt = check.answers.get('tax_debt_rub')
    if is_count(tax_debt) and tax_debt > 0:
        flags.append('tax_debt')
    if check.answers.get('legal_proceedings') is True:
        flags.append('legal_proceedings')
    if check.registry_status != 'active':
        flags.append('registry_unconfirmed')
    return tuple(flags)


def amount_rule(risk: str, requested: int, limit: int) -> str:
    if risk == 'low':
        return 'R8' if requested <= limit else 'R9'
    return 'R10' if requested <= limit else 'R11'


def mandatory_rejection(score: int | None, limit: int | None, minimum: int) -> tuple[str, str, tuple[str, ...]] | None:
    """R6 and R7: rejections no review or officer can override."""
    if score is not None and score < MEDIUM_RISK_MIN_SCORE:
        return 'R6', 'REJECTED', (REASONS['high_risk'],)
    if limit is not None and limit < minimum:
        return 'R7', 'REJECTED', (f'Рассчитанный лимит {rub(limit)} ниже минимальной суммы продукта {rub(minimum)}.',)
    return None


def capacity_note(requested: int, limit: int | None) -> tuple[str, ...]:
    if limit is None or requested <= limit:
        return ()
    return (f'Запрошенная сумма выше рассчитанного лимита. Возможная сумма — до {rub(limit)}; исходная сумма заявки сохранена.',)


def measure(check: CheckInput, report: dict) -> dict:
    """The R5 review flags, then score, risk, factors and scored limit whenever they can be computed (no zero or
    malformed value): the measured part of a Decision."""
    flags = review_flags(check, report)
    revenue, previous = (check.finance[name]['value'] for name in REVENUE_FIELDS)
    score = risk = factors = limit = None
    if 'zero_revenue' not in flags and 'invalid_source' not in flags:
        score, factors = score_of(check.age_months, revenue, previous, check.answers['monthly_debt_payment_rub'], report['credit_history'])
        risk = risk_of(score)
        limit = scored_limit(check.product, risk, revenue, check.secured, check.answers.get('collateral'))
    return {'score': score, 'risk': risk, 'factors': factors, 'scored_limit_rub': limit, 'flags': flags}


def after_bki(check: CheckInput, report: dict, *, trusted_source_review: bool) -> Decision:
    """The outcome once a BKI report exists (exactly one request per check)."""
    if report['status'] == 'unavailable':
        return Decision('R4', 'WAIT_EXTERNAL', (REASONS['bki_unavailable'],))
    overdue = report.get('current_overdue_days')
    if is_count(overdue) and overdue >= OVERDUE_STOP_DAYS:  # R2 precedes R3 in the rule order
        return Decision('R2', 'REJECTED', (REASONS['overdue'],))
    if any(report.get(category) is None for category in BKI_CATEGORIES):
        return Decision('R3', 'NEED_INFO', (REASONS['bki_missing'],), info_request={
            'kind': 'trusted_source', 'source': 'bki', 'requested_fields': [], 'question': QUESTIONS['bki']})
    measured = measure(check, report)
    flags, score, risk, limit = (measured[key] for key in ('flags', 'score', 'risk', 'scored_limit_rub'))
    requested = check.answers['requested_amount_rub']
    minimum = check.product['amount_min_rub']
    reviews = tuple(FLAG_REASONS[flag] for flag in flags)
    if trusted_source_review:
        rejection = mandatory_rejection(score, limit, minimum)
        if rejection:
            return Decision(*rejection, **measured)
        rule = 'R5' if flags or limit is None else amount_rule(risk, requested, limit)
        return Decision(rule, 'MANUAL_REVIEW', reviews + capacity_note(requested, limit) + (REASONS['trusted_review'],), **measured)
    if flags:
        return Decision('R5', 'MANUAL_REVIEW', reviews + ((REASONS['noncomputable'],) if score is None else ()) + (REASONS['manual'],), **measured)
    rejection = mandatory_rejection(score, limit, minimum)
    if rejection:
        return Decision(*rejection, **measured)
    if limit is None:  # defensive: a calculable score without a calculable limit is reviewed, never approved
        return Decision('R5', 'MANUAL_REVIEW', (REASONS['noncomputable'], REASONS['manual']), **measured)
    rule = amount_rule(risk, requested, limit)
    if rule == 'R8':
        return Decision(rule, 'PREAPPROVED', (REASONS['low'],), preapproved_amount_rub=requested, **measured)
    if rule == 'R9':
        return Decision(rule, 'PREAPPROVED', (f'Низкий риск: запрошенная сумма {rub(requested)} выше рассчитанного лимита. '
                                              f'Предварительно одобрено {rub(limit)}; исходная сумма заявки сохранена. '
                                              'Это не окончательное решение.',), preapproved_amount_rub=limit, **measured)
    if rule == 'R10':
        return Decision(rule, 'MANUAL_REVIEW', (REASONS['medium'],), **measured)
    return Decision(rule, 'MANUAL_REVIEW', (f'Средний риск: запрошенная сумма выше рассчитанного лимита. Возможная сумма — '
                                            f'до {rub(limit)}; заявку рассмотрит кредитный специалист.',), **measured)


def ordered_flags(flags) -> tuple[str, ...]:
    present = set(flags)
    return tuple(flag for flag in FLAG_REASONS if flag in present)


def after_response(check: CheckInput, report: dict | None, previous_flags=()) -> Decision:
    """A re-check after the client answered an information request: the revised answers with the latest trusted source
    evidence (the persisted precheck and the latest complete BKI report, which is not requested again). It always ends
    in MANUAL_REVIEW: the officer reviews the answer, so there is no automatic low-risk shortcut. The rule records what
    the rules alone would decide, R2/R6/R7 included (the officer can then only reject), and a declaration or source
    conflict flagged by an earlier evaluation stays flagged (RETAINED_FLAGS)."""
    retained = tuple(flag for flag in RETAINED_FLAGS if flag in previous_flags)
    if check.registry_status == 'inactive':
        return Decision('R2', 'MANUAL_REVIEW', (REASONS['inactive'], REASONS['answered']), flags=retained)
    if report is None:  # the gap was found before any BKI request (an internal check) and none is made now
        flags = ordered_flags(review_flags(check, None) + retained)
        return Decision('R5', 'MANUAL_REVIEW', tuple(FLAG_REASONS[flag] for flag in flags) + (REASONS['no_bki'], REASONS['answered']),
                        flags=flags)
    overdue = report.get('current_overdue_days')
    if is_count(overdue) and overdue >= OVERDUE_STOP_DAYS:
        return Decision('R2', 'MANUAL_REVIEW', (REASONS['overdue'], REASONS['answered']), flags=retained)
    measured = measure(check, report)
    measured['flags'] = flags = ordered_flags(measured['flags'] + retained)
    score, risk, limit = measured['score'], measured['risk'], measured['scored_limit_rub']
    requested = check.answers['requested_amount_rub']
    reviews = tuple(FLAG_REASONS[flag] for flag in flags)
    rejection = mandatory_rejection(score, limit, check.product['amount_min_rub'])
    if rejection:
        rule, _, reasons = rejection
        return Decision(rule, 'MANUAL_REVIEW', reviews + reasons + (REASONS['answered'],), **measured)
    rule = 'R5' if flags or limit is None else amount_rule(risk, requested, limit)
    noncomputable = (REASONS['noncomputable'],) if score is None else ()
    return Decision(rule, 'MANUAL_REVIEW', reviews + noncomputable + capacity_note(requested, limit) + (REASONS['answered'],),
                    **measured)
