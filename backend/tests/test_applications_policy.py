"""Pure post-submission scoring and R2-R11 decisions, compared with the independent oracle. No HTTP, no database.

Inputs sweep the spec's boundaries; expected values come from application_oracle (exact fractions and calendar
stepping) and the spec's rule table, never from the scoring module under test.
"""
from datetime import date, timedelta
from itertools import product as grid
import pytest
from app.applications import scoring
import application_oracle as oracle
from recommendation_oracle import PRODUCTS

TERM, LINE, SECURED = 'alfa_term_loan_unsecured', 'alfa_revolving_line_unsecured', 'alfa_term_loan_secured'
CLEAN = {'status': 'available', 'credit_history': 'clean', 'current_overdue_days': 0}
COLLATERAL = {'status': 'declared', 'type': 'equipment', 'declared_value_rub': 8_000_000, 'description': 'Демо',
              'owner_confirmed': True, 'encumbered': False}


def evidence(value, origin):
    """Stage-3 evidence as the application builds it: the scored `value` is the source value whenever one is known."""
    if origin == 'source':
        return {'answer': value, 'source': value, 'source_status': 'available', 'origin': 'source', 'value': value}
    if origin == 'declared':
        return {'answer': value, 'source': None, 'source_status': 'missing', 'origin': 'declared', 'value': value}
    return {'answer': value + 1, 'source': value, 'source_status': 'available', 'origin': 'override', 'value': value}


def check(product=TERM, *, revenue=800_000, previous=680_000, origin='source', age=48, debt=160_000, requested=1_000_000,
          registry='active', registry_source='available', turnover_source='available', missing=(), **answers):
    finance = {'monthly_revenue_rub': evidence(revenue, origin), 'previous_monthly_revenue_rub': evidence(previous, origin),
               'financial_period_end': evidence('2026-09-30', 'source')}
    collateral = COLLATERAL if PRODUCTS[product]['collateral_required'] else None
    return scoring.CheckInput(product=PRODUCTS[product], registry_status=registry, registry_source_status=registry_source,
                              turnover_source_status=turnover_source, age_months=age, finance=finance,
                              answers={'monthly_debt_payment_rub': debt, 'tax_debt_rub': 0, 'legal_proceedings': False,
                                       'requested_amount_rub': requested, 'collateral': collateral, **answers},
                              missing_answers=tuple(missing))


def decide(item, report=CLEAN, trusted=False):
    assert scoring.before_bki(item) is None
    return scoring.after_bki(item, report, trusted_source_review=trusted)


@pytest.mark.parametrize('total,band', [(0, 'high'), (49, 'high'), (50, 'medium'), (74, 'medium'), (75, 'low'), (100, 'low')])
def test_risk_bands_at_the_spec_thresholds(total, band):
    assert scoring.risk_of(total) == band == oracle.risk(total)


def test_completed_months_matches_calendar_stepping():
    starts = [date(2024, 1, 31), date(2024, 2, 29), date(2023, 3, 31), date(2026, 4, 24), date(2026, 4, 25), date(2024, 10, 24),
              date(2024, 10, 25), date(2025, 12, 31), date(2022, 10, 24)]
    for start in starts:
        for offset in range(0, 900, 7):
            end = start + timedelta(days=offset)
            assert scoring.completed_months(start, end) == oracle.completed_months(start, end), (start, end)


def test_factor_points_match_exact_fractions_around_every_boundary():
    previous_values = [100_000, 680_000, 1]
    for previous, age in grid(previous_values, [0, 5, 6, 23, 24, 48]):
        revenues = [previous * 9 // 10 - 1, previous * 9 // 10, previous * 9 // 10 + 1, previous, previous * 11 // 10 - 1,
                    previous * 11 // 10, previous * 11 // 10 + 1, 3 * previous]
        for revenue in (r for r in revenues if r > 0):
            for debt in {0, revenue * 3 // 10, revenue * 3 // 10 + 1, revenue // 2, revenue // 2 + 1, revenue, 2 * revenue}:
                for history in ('clean', 'minor_closed', 'serious'):
                    total, factors = scoring.score_of(age, revenue, previous, debt, history)
                    assert total == oracle.score(age, revenue, previous, debt, history), (age, revenue, previous, debt, history)
                    assert total == sum(value for key, value in factors.items() if key.endswith('_points'))


@pytest.mark.parametrize('product', [TERM, LINE, SECURED])
def test_scored_limits_follow_the_spec_formulas(product):
    for band, revenue, declared in grid(('low', 'medium', 'high'), (1, 99_999, 100_000, 333_334, 600_001, 2_000_000, 50_000_000),
                                        (714_285, 714_286, 1_000_000, 8_000_000)):
        collateral = {**COLLATERAL, 'declared_value_rub': declared}
        expected = oracle.scored_limit(product, band, revenue, declared if PRODUCTS[product]['collateral_required'] else None)
        assert scoring.scored_limit(PRODUCTS[product], band, revenue, collateral) == expected, (band, revenue, declared)


def test_rule_order_without_review_flags_matches_the_oracle():
    for age, revenue, previous, debt, history, requested in grid(
            (4, 18, 48), (99_999, 100_000, 300_000, 800_000), (100_000, 680_000), (0, 160_000, 240_000, 600_000),
            ('clean', 'minor_closed', 'serious'), (300_000, 1_000_000, 2_400_000, 2_400_001)):
        decision = decide(check(age=age, revenue=revenue, previous=previous, debt=debt, requested=requested),
                          {**CLEAN, 'credit_history': history})
        total = oracle.score(age, revenue, previous, debt, history)
        limit = oracle.scored_limit(TERM, oracle.risk(total), revenue)
        rule, status, amount = oracle.outcome(TERM, total, limit, requested)
        assert (decision.rule, decision.outcome, decision.preapproved_amount_rub) == (rule, status, amount)
        assert (decision.score, decision.risk) == (total, oracle.risk(total))
        assert decision.scored_limit_rub == limit and decision.reasons


def test_bki_unavailable_waits_and_overdue_precedes_a_missing_history_category():
    assert decide(check(), {'status': 'unavailable', 'credit_history': None, 'current_overdue_days': None}).rule == 'R4'
    stop = decide(check(), {'status': 'missing', 'credit_history': None, 'current_overdue_days': 30})
    assert (stop.rule, stop.outcome, stop.score) == ('R2', 'REJECTED', None)  # R2 is earlier in the rule order than R3
    gap = decide(check(), {'status': 'missing', 'credit_history': None, 'current_overdue_days': 0})
    assert (gap.rule, gap.outcome, gap.score) == ('R3', 'NEED_INFO', None)
    assert {key: gap.info_request[key] for key in ('kind', 'source', 'requested_fields')} == {'kind': 'trusted_source', 'source': 'bki', 'requested_fields': []}
    assert gap.info_request['question']
    assert decide(check(), {**CLEAN, 'current_overdue_days': 29}).rule == 'R8'


def test_review_flags_precede_rejection_on_a_normal_check():
    declared = decide(check(origin='declared', age=4, revenue=300_000, previous=375_000, debt=180_000), {**CLEAN, 'credit_history': 'minor_closed'})
    assert (declared.rule, declared.outcome, declared.score, declared.risk, declared.scored_limit_rub) == ('R5', 'MANUAL_REVIEW', 10, 'high', None)
    assert 'declared_finance' in declared.flags
    override = decide(check(origin='override'))
    assert (override.rule, override.outcome, override.score) == ('R5', 'MANUAL_REVIEW', 100) and 'finance_override' in override.flags
    for answers, flag in (({'tax_debt_rub': 1}, 'tax_debt'), ({'legal_proceedings': True}, 'legal_proceedings')):
        decision = decide(check(**answers))
        assert (decision.rule, decision.outcome, decision.score) == ('R5', 'MANUAL_REVIEW', 100) and flag in decision.flags
    for change in ({'encumbered': True}, {'owner_confirmed': False}, {'owner_confirmed': None}):
        decision = decide(check(SECURED, requested=4_000_000, collateral={**COLLATERAL, **change}))
        assert (decision.rule, decision.outcome) == ('R5', 'MANUAL_REVIEW') and 'collateral_unconfirmed' in decision.flags
        assert decision.scored_limit_rub == 2_400_000  # still calculable from the declared value for the officer


@pytest.mark.parametrize('changes', [{'revenue': 0}, {'previous': 0}])
def test_zero_revenue_routes_review_without_division(changes):
    decision = decide(check(**changes))
    assert (decision.rule, decision.outcome, decision.score, decision.risk, decision.scored_limit_rub) == ('R5', 'MANUAL_REVIEW', None, None, None)
    assert 'zero_revenue' in decision.flags


@pytest.mark.parametrize('item,report', [
    (check(revenue=-1), CLEAN), (check(previous=-5), CLEAN), (check(age=-1), CLEAN), (check(age=None), CLEAN),
    (check(), {**CLEAN, 'current_overdue_days': -3}), (check(), {**CLEAN, 'credit_history': 'excellent'}),
])
def test_malformed_imported_values_route_review_without_a_score(item, report):
    decision = decide(item, report)
    assert (decision.rule, decision.outcome, decision.score) == ('R5', 'MANUAL_REVIEW', None)
    assert 'invalid_source' in decision.flags


def test_trusted_source_recovery_reviews_unless_a_mandatory_rejection_applies():
    review = decide(check(), trusted=True)
    assert (review.rule, review.outcome, review.score, review.scored_limit_rub, review.preapproved_amount_rub) == ('R8', 'MANUAL_REVIEW', 100, 2_400_000, None)
    medium = decide(check(age=18, revenue=600_000, previous=600_000, debt=240_000, requested=500_000), trusted=True)
    assert (medium.rule, medium.outcome) == ('R10', 'MANUAL_REVIEW')
    high = decide(check(age=4, revenue=300_000, previous=375_000, debt=180_000), {**CLEAN, 'credit_history': 'minor_closed'}, trusted=True)
    assert (high.rule, high.outcome) == ('R6', 'REJECTED')
    small = decide(check(revenue=99_999, previous=99_999, debt=0, requested=300_000), trusted=True)
    assert (small.rule, small.outcome) == ('R7', 'REJECTED')
    overdue = decide(check(), {**CLEAN, 'current_overdue_days': 30}, trusted=True)
    assert (overdue.rule, overdue.outcome) == ('R2', 'REJECTED')
    flagged = decide(check(tax_debt_rub=5), trusted=True)
    assert (flagged.rule, flagged.outcome, flagged.score) == ('R5', 'MANUAL_REVIEW', 100)
    # Mandatory rejections still apply in recovery even when review flags exist (spec: R2/R6/R7 cannot be overridden).
    flagged_high = decide(check(origin='declared', age=4, revenue=300_000, previous=375_000, debt=180_000),
                          {**CLEAN, 'credit_history': 'minor_closed'}, trusted=True)
    assert (flagged_high.rule, flagged_high.outcome) == ('R6', 'REJECTED')


def test_checks_before_bki_follow_the_rule_order():
    inactive = scoring.before_bki(check(registry='inactive', missing=('monthly_revenue_rub',)))
    assert (inactive.rule, inactive.outcome, inactive.score) == ('R2', 'REJECTED', None)  # known inactive overrides gaps
    gap = scoring.before_bki(check(missing=('monthly_revenue_rub', 'previous_monthly_revenue_rub')))
    assert (gap.rule, gap.outcome) == ('R3', 'NEED_INFO')
    assert {key: gap.info_request[key] for key in ('kind', 'source', 'requested_fields')} == \
           {'kind': 'client_answers', 'source': None, 'requested_fields': ['monthly_revenue_rub', 'previous_monthly_revenue_rub']}
    for changes in ({'registry_source': 'unavailable', 'registry': 'unknown'}, {'turnover_source': 'unavailable'}):
        waiting = scoring.before_bki(check(**changes))
        assert (waiting.rule, waiting.outcome) == ('R4', 'WAIT_EXTERNAL')
    unconfirmed = decide(check(registry='unknown'))
    assert (unconfirmed.rule, unconfirmed.outcome) == ('R5', 'MANUAL_REVIEW') and 'registry_unconfirmed' in unconfirmed.flags
