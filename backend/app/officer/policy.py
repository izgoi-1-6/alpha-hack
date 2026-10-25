"""What the session officer may do with an application: claimable states, the reject phase per state, the actions to
offer, the preapproval terms judged by the latest evaluation's computed values, never by its rule label (R5
precedes R6/R7, and trusted-source recovery records a rule such as R8 with outcome MANUAL_REVIEW), and the final
approval terms judged by the accepted document evidence."""
from ..applications import scoring
from ..applications.models import Application, Evaluation
from ..documents.models import Document
from ..documents.service import current_documents
from ..models import Company
from ..recommendations.service import rub

CLAIMABLE = frozenset({'MANUAL_REVIEW', 'NEED_INFO', 'PREAPPROVED', 'DOCS_UPLOADED', 'DOCS_REWORK'})
REJECT_PHASE = {'MANUAL_REVIEW': 'preliminary', 'PREAPPROVED': 'final', 'DOCS_UPLOADED': 'final', 'DOCS_REWORK': 'final'}


def mandatory_stop(evaluation: Evaluation | None, company: Company, product: dict) -> str | None:
    """An R2/R6/R7 condition no officer can override: a known inactive company (now or when evaluated), a stored BKI
    current overdue of 30 days or more, a computed score below 50, a scored limit below the product minimum.
    Returns its reason, or None."""
    evaluated = evaluation.input_snapshot.get('company', {}) if evaluation is not None else {}
    if company.registry_status == 'inactive' or evaluated.get('registry_status') == 'inactive':
        return scoring.REASONS['inactive']
    if evaluation is None:
        return None
    overdue = (evaluation.sources.get('bki') or {}).get('current_overdue_days')
    if scoring.is_count(overdue) and overdue >= scoring.OVERDUE_STOP_DAYS:
        return scoring.REASONS['overdue']
    rejection = scoring.mandatory_rejection(evaluation.score, evaluation.scored_limit_rub, product['amount_min_rub'])
    return rejection[2][0] if rejection else None


def preapproval_terms(application: Application, company: Company, evaluation: Evaluation | None,
                      product: dict) -> tuple[tuple[int, int] | None, tuple[str, str] | None]:
    """((amount_min_rub, amount_max_rub), None) when an officer may preapprove a reviewed application — product
    minimum <= amount <= min(request, scored limit) — or (None, (code, message)) when it is refused."""
    stop = mandatory_stop(evaluation, company, product)
    if stop:
        return None, ('MANDATORY_STOP', f'Предварительное одобрение невозможно. {stop} Возможен только отказ с причиной.')
    limit = None if evaluation is None else evaluation.scored_limit_rub
    if limit is None:
        return None, ('LIMIT_NOT_COMPUTABLE', 'Лимит не рассчитан: запросите сведения, которые позволят его рассчитать, '
                                              'или откажите с причиной.')
    return (product['amount_min_rub'], min(application.requested_amount_rub, limit)), None


def amount_error_message(low: int, high: int, *, final: bool = False) -> str:
    return f'Сумма {"окончательного" if final else "предварительного"} одобрения — от {rub(low)} до {rub(high)}.'


def final_terms(application: Application, documents: list[Document], evaluation: Evaluation | None, product: dict) -> dict:
    """The final approval bounds from persisted evidence: every required document's current revision ACCEPTED, then
    product minimum <= final <= min(preapproved amount, the limit recomputed with the scoring rule — the evaluation's
    risk and scored revenue and, for a secured product, the accepted valuation's verified value under the LTV cap,
    never the client's declaration or a value sent with the approval). A bound below the product minimum refuses
    approval (only a reasoned final rejection remains). Returns {amount_min_rub, amount_max_rub, verified_limit_rub,
    blocked_by: null | {code, message}}; bounds are null when blocked."""
    def blocked(code: str, message: str, limit: int | None = None) -> dict:
        return {'amount_min_rub': None, 'amount_max_rub': None, 'verified_limit_rub': limit,
                'blocked_by': {'code': code, 'message': message}}

    current = current_documents(documents)
    if any(kind not in current or current[kind].status != 'ACCEPTED' for kind in product['required_documents']):
        return blocked('DOCUMENTS_NOT_ACCEPTED', 'Окончательное одобрение возможно, когда приняты все обязательные документы.')
    collateral = None
    if product['collateral_required']:
        collateral = {'status': 'declared', 'declared_value_rub': current['COLLATERAL_VALUATION'].verified_value_rub}
    revenue = ((evaluation.input_snapshot.get('finance') or {}).get('monthly_revenue_rub') or {}).get('value') if evaluation else None
    limit = None if evaluation is None or evaluation.risk is None else scoring.scored_limit(product, evaluation.risk, revenue, collateral)
    if limit is None:
        return blocked('LIMIT_NOT_COMPUTABLE', 'Лимит по проверенным данным не рассчитывается: возможен только отказ с причиной.')
    low, high = product['amount_min_rub'], min(application.preapproved_amount_rub, limit)
    if high < low:
        source = 'по проверенной стоимости залога' if product['collateral_required'] else 'по проверенным данным'
        return blocked('COLLATERAL_INSUFFICIENT' if product['collateral_required'] else 'LIMIT_BELOW_MINIMUM',
                       f'Лимит {source} — {rub(limit)}, ниже минимальной суммы продукта {rub(low)}: окончательное '
                       'одобрение невозможно, возможен только отказ с причиной.', limit)
    return {'amount_min_rub': low, 'amount_max_rub': high, 'verified_limit_rub': limit, 'blocked_by': None}


def staff_actions(application: Application, officer_id: str, *, preapprovable: bool, reviewable: bool = False,
                  approvable: bool = False) -> list[str]:
    """Commands the session officer can run now: claim an unassigned case; the assignee requests information or
    preapproves in review, reviews pending documents and approves in DOCS_UPLOADED (when the final terms allow), and
    rejects in review or the document phase."""
    status, assignee, actions = application.status, application.assignee_id, []
    if status in CLAIMABLE and assignee is None:
        actions.append('claim')
    if assignee == officer_id:
        if status == 'MANUAL_REVIEW':
            actions.append('request_info')
            if preapprovable:
                actions.append('preapprove')
        if status == 'DOCS_UPLOADED':
            if reviewable:
                actions.append('review_document')
            if approvable:
                actions.append('approve')
        if status in REJECT_PHASE:
            actions.append('reject')
    return actions
