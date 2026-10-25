"""Pure post-submission scoring and the R2-R11 decision. No I/O; integer arithmetic only.

Factors (spec "Scoring and state machine"): business age in completed calendar months, revenue growth (R-P)/P,
monthly debt burden debt/R and the BKI credit history, compared exactly by cross-multiplication. Rules run in the
spec table's order: `before_bki` covers R2 (known inactive), R3 (a client-answerable gap) and R4 (registry or turnover
unavailable), so none of them spends a BKI request; `after_bki` covers the report's R4/R2/R3, then the review flags
(R5), R6, R7 and R8-R11. A check that recovers trusted-source evidence (an open trusted_source request) ends in
MANUAL_REVIEW unless R2, R6 or R7 rejects. Score and limit stay null when they cannot be computed.
"""
import calendar
from dataclasses import dataclass
from datetime import date
from ..recommendations.service import rub

HISTORY_POINTS = {'clean': 25, 'minor_closed': 10, 'serious': 0}
LOW_RISK_MIN_SCORE, MEDIUM_RISK_MIN_SCORE = 75, 50
OVERDUE_STOP_DAYS = 30
BKI_CATEGORIES = ('credit_history', 'current_overdue_days')
REVENUE_FIELDS = ('monthly_revenue_rub', 'previous_monthly_revenue_rub')

REASONS = {
    'inactive': 'Компания не действует по данным демо-реестра.',
    'overdue': 'Текущая просрочка по данным демо-БКИ — 30 дней или более.',
    'client_gap': 'Для проверки не хватает обязательных сведений анкеты.',
    'bki_missing': 'Ответ демо-БКИ не содержит категорию кредитной истории. Нужен повторный запрос к источнику; '
                   'анкета эти сведения не принимает.',
    'registry_unavailable': 'Демо-реестр временно недоступен. Повторите проверку.',
    'turnover_unavailable': 'Демо-источник оборотов временно недоступен. Повторите проверку.',
    'bki_unavailable': 'Демо-БКИ временно недоступно. Повторите проверку: запрос выполнится по сохранённому согласию.',
    'high_risk': 'Высокий риск по результатам скоринга: менее 50 баллов.',
    'manual': 'Заявку проверит кредитный специалист.',
    'noncomputable': 'Балл и лимит нельзя рассчитать автоматически.',
    'trusted_review': 'Сведения получены повторным запросом к демо-БКИ; заявку проверит кредитный специалист.',
    'low': 'Низкий риск: запрошенная сумма укладывается в рассчитанный лимит. Это предварительное одобрение, '
           'не окончательное решение.',
    'medium': 'Средний риск: заявку рассмотрит кредитный специалист.',
}
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
    'bki': 'Демо-БКИ ответило без категории кредитной истории. Нажмите «Повторить проверку»: запрос выполнится '
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


def scored_limit(product: dict, risk: str, revenue: int | None, collateral: dict | None) -> int | None:
    """low: min(ceiling, low multiple x R); medium: min(ceiling, medium cap, medium multiple x R); high: none. A secured
    product is further capped by floor(declared value x LTV); without a declared value there is no limit."""
    if risk == 'high' or not is_count(revenue) or revenue == 0:
        return None
    if risk == 'low':
        limit = min(product['amount_max_rub'], product['low_risk_revenue_multiple'] * revenue)
    else:
        limit = min(product['amount_max_rub'], product['medium_risk_cap_rub'], product['medium_risk_revenue_multiple'] * revenue)
    if not product['collateral_required']:
        return limit
    collateral = collateral or {}
    value = collateral.get('declared_value_rub') if collateral.get('status') == 'declared' else None
    if not is_count(value) or value == 0:
        return None
    return min(limit, value * product['collateral_ltv_bps'] // 10000)


@dataclass(frozen=True)
class CheckInput:
    """What one check reads: the pinned product policy, persisted company/source state and the frozen answers.

    `finance` is stages.finance_evidence(): per stage-3 field the answer, the source value, the source status, the
    origin tag (source/declared/override) and the scored `value` (the source value whenever one is known)."""
    product: dict
    registry_status: str
    registry_source_status: str
    turnover_source_status: str
    age_months: int | None
    finance: dict
    answers: dict
    missing_answers: tuple[str, ...] = ()


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


def before_bki(check: CheckInput) -> Decision | None:
    """R2, R3 and R4 outcomes that need no BKI request; None means the BKI simulator may be called."""
    if check.registry_status == 'inactive':
        return Decision('R2', 'REJECTED', (REASONS['inactive'],))
    if check.missing_answers:
        return Decision('R3', 'NEED_INFO', (REASONS['client_gap'],), info_request={
            'kind': 'client_answers', 'source': None, 'requested_fields': list(check.missing_answers),
            'question': QUESTIONS['client_answers']})
    if check.registry_source_status == 'unavailable':
        return Decision('R4', 'WAIT_EXTERNAL', (REASONS['registry_unavailable'],))
    if check.turnover_source_status == 'unavailable':
        return Decision('R4', 'WAIT_EXTERNAL', (REASONS['turnover_unavailable'],))
    return None


def review_flags(check: CheckInput, report: dict) -> tuple[str, ...]:
    """R5 conditions: zero or malformed values, declared or overridden finance, unconfirmed collateral, tax/legal
    concerns and an unconfirmed registry status."""
    revenue, previous = (check.finance[name]['value'] for name in REVENUE_FIELDS)
    origins = {entry['origin'] for entry in check.finance.values()}
    flags = []
    if revenue == 0 or previous == 0:
        flags.append('zero_revenue')
    counts = (revenue, previous, check.answers.get('monthly_debt_payment_rub'), check.age_months, report.get('current_overdue_days'))
    if not all(is_count(value) for value in counts) or report.get('credit_history') not in HISTORY_POINTS:
        flags.append('invalid_source')
    if 'declared' in origins:
        flags.append('declared_finance')
    if 'override' in origins:
        flags.append('finance_override')
    if check.product['collateral_required']:
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
    flags = review_flags(check, report)
    revenue, previous = (check.finance[name]['value'] for name in REVENUE_FIELDS)
    score = risk = factors = limit = None
    if 'zero_revenue' not in flags and 'invalid_source' not in flags:
        score, factors = score_of(check.age_months, revenue, previous, check.answers['monthly_debt_payment_rub'], report['credit_history'])
        risk = risk_of(score)
        limit = scored_limit(check.product, risk, revenue, check.answers.get('collateral'))
    measured = {'score': score, 'risk': risk, 'factors': factors, 'scored_limit_rub': limit, 'flags': flags}
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
