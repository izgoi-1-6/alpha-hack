"""Local BKI simulator: the only place the application flow obtains credit history.

It reads the company's whitelisted synthetic source and returns only the BKI categories (availability, credit history,
current overdue days), never the whole fixture; questionnaire answers cannot supply them. Recovery is indexed by
attempt: attempt 1 answers with the fixture's `bki_source_status`; later attempts use its `recovery.retry_*` values
when the fixture has them. Callers derive the attempt from persisted evaluations (see checks.bki_attempts), so recovery
survives an API restart.

`CALLS` is an observable in-process log of requests for tests and diagnostics; it never influences a response.
"""
from .. import companies

PROVIDER = 'demo_bki_mock'
CALLS: list[dict] = []


def request_report(inn: str, attempt: int) -> dict:
    """One simulated BKI request for a whitelisted INN. Status is 'available', 'missing' (a category is absent) or
    'unavailable' (no categories)."""
    CALLS.append({'inn': inn, 'attempt': attempt})
    source = companies.SOURCES[inn]
    recovery = source.get('recovery') or {}
    if attempt > 1 and recovery.get('retry_bki_source_status'):
        status = recovery['retry_bki_source_status']
        history = recovery.get('retry_credit_history', source.get('credit_history'))
        overdue = recovery.get('retry_current_overdue_days', source.get('current_overdue_days'))
    else:
        status, history, overdue = source['bki_source_status'], source.get('credit_history'), source.get('current_overdue_days')
    if status == 'unavailable':
        history = overdue = None
    elif status == 'missing':
        history = None  # a successful response that omits the credit history category
    return {'provider': PROVIDER, 'synthetic': True, 'attempt': attempt, 'status': status,
            'credit_history': history, 'current_overdue_days': overdue}
