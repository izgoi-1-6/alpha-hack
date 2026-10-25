"""What the session officer may do with an application: claimable states, the reject phase per state, the actions to
offer, and the preapproval terms judged by the latest evaluation's computed values, never by its rule label (R5
precedes R6/R7, and trusted-source recovery records a rule such as R8 with outcome MANUAL_REVIEW)."""
from ..applications import scoring
from ..applications.models import Application, Evaluation
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


def amount_error_message(low: int, high: int) -> str:
    return f'Сумма предварительного одобрения — от {rub(low)} до {rub(high)}.'


def staff_actions(application: Application, officer_id: str, *, preapprovable: bool) -> list[str]:
    """Commands the session officer can run now: claim an unassigned case; the assignee requests information or
    preapproves in review, and rejects in review or the document phase."""
    status, assignee, actions = application.status, application.assignee_id, []
    if status in CLAIMABLE and assignee is None:
        actions.append('claim')
    if assignee == officer_id:
        if status == 'MANUAL_REVIEW':
            actions.append('request_info')
            if preapprovable:
                actions.append('preapprove')
        if status in REJECT_PHASE:
            actions.append('reject')
    return actions
