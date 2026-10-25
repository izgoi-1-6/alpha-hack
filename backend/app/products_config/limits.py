"""The one personal-limit formula over a runtime product's effective terms. The pre-submission estimate
(recommendations, low risk), the scored and indicative limits (applications.scoring) and the officer's final bounds
(officer.policy) all call `personal_limit`, so a limit is computed the same way everywhere:

    min(effective max, turnover limit T, secured ? unsecured cap + ⌊LTV·V⌋ : unsecured cap)

T is min(max, low multiple × R) at low risk and min(max, medium cap, medium multiple × R) at medium risk; high risk, or
no positive whole monthly turnover R, gives no limit. The unsecured cap is the product's `unsecured_cap_rub`: 0 when
collateral is required, the catalog's `max_unsecured` for the universal limit, the maximum otherwise. A secured limit
needs a positive whole pledge value V (declared before the document review, verified at final approval); without one
there is none. Integer arithmetic only.
"""


def positive(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def turnover_limit(product: dict, risk: str | None, revenue) -> int | None:
    if risk not in ('low', 'medium') or not positive(revenue):
        return None
    if risk == 'low':
        return min(product['amount_max_rub'], product['low_risk_revenue_multiple'] * revenue)
    return min(product['amount_max_rub'], product['medium_risk_cap_rub'], product['medium_risk_revenue_multiple'] * revenue)


def collateral_cap(product: dict, value: int) -> int:
    """The most a pledge of this value secures: ⌊value × LTV⌋."""
    return value * product['collateral_ltv_bps'] // 10000


def personal_limit(product: dict, risk: str | None, revenue, *, secured: bool, collateral_value) -> int | None:
    limit = turnover_limit(product, risk, revenue)
    if limit is None:
        return None
    if not secured:
        return min(limit, product['unsecured_cap_rub'])
    if not positive(collateral_value):
        return None
    return min(limit, product['unsecured_cap_rub'] + collateral_cap(product, collateral_value))
