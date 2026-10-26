"""What a client is told about a check result: never the scoring (user request after hand-over).

Evaluations and history keep the staff reasons unchanged; the customer serializers map them here. A source wait or an
information request (R3, R4), a known inactive company and a failed eligibility fact keep their own texts. Every other
check outcome — the score-derived ones (R5–R11, the forced review after a trusted-source recovery, the re-check after an
information response), the BKI overdue stop and anything not recognised — gets a neutral text by outcome, and its
history row the reason code CHECK_RESULT instead of the rule.
"""
from ..recommendations.service import rub
from .scoring import REASONS

CHECK_RESULT = 'CHECK_RESULT'
PREAPPROVED = 'Заявка предварительно одобрена. Это не окончательное решение.'
REVIEW = 'Заявку рассмотрит кредитный специалист.'
REJECTED = 'К сожалению, сейчас мы не можем одобрить заявку.'
REJECTION = 'По заявке принят отказ. '
REJECTION_NOTICE = REJECTION + REJECTED
OWN_TEXT_OUTCOMES = frozenset({'WAIT_EXTERNAL', 'NEED_INFO'})


def disclosed(outcome: str, text: str) -> bool:
    """Whether a check outcome's own text may reach the client: a wait or an information request, a known inactive
    company, a failed eligibility fact. A text that is not recognised stays hidden."""
    if outcome in OWN_TEXT_OUTCOMES:
        return True
    return outcome == 'REJECTED' and (text == REASONS['inactive'] or text.startswith(REASONS['ineligible']))


def neutral_text(outcome: str, rule: str, preapproved_amount_rub: int | None) -> str:
    """The client's text for a hidden outcome: R9 names the smaller preapproved amount, never a limit calculation."""
    if outcome == 'PREAPPROVED':
        if rule == 'R9' and preapproved_amount_rub is not None:
            return (f'Заявка предварительно одобрена. Предварительно одобрена сумма {rub(preapproved_amount_rub)} — меньше '
                    'запрошенной; исходная сумма заявки сохранена. Это не окончательное решение.')
        return PREAPPROVED
    return REVIEW if outcome == 'MANUAL_REVIEW' else REJECTED


def customer_reasons(outcome: str, rule: str, reasons: list[str], preapproved_amount_rub: int | None) -> list[str]:
    """An evaluation's reasons as the client reads them."""
    if reasons and disclosed(outcome, reasons[0]):
        return list(reasons)
    return [neutral_text(outcome, rule, preapproved_amount_rub)]


def rejection_notice(reason: str) -> str:
    """The notification of a check's rejection, as the client is sent it."""
    return REJECTION + reason if disclosed('REJECTED', reason) else REJECTION_NOTICE
