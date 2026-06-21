"""Pricing engine for Fatima Bazaar Price Updater.

Core formulas (kept in one place so the rules are easy to audit / change):

  1. Per-unit cost:
        - sold by QUANTITY  -> cost per item = line_cost / units
        - sold by WEIGHT    -> cost per lb   = line_cost / weight_lbs
     (If the user enters the unit cost directly, units/weight = 1.)

  2. State markup applied to the cost:
        - California          -> cost * 1.05   (add 5%)
        - Any other state     -> cost * 1.10   (add 10%)

  3. Sell price:
        sell = adjusted_cost / 0.625
"""

import math

CALIFORNIA_MARKUP = 0.05      # +5%
OUT_OF_STATE_MARKUP = 0.10    # +10%
SELL_DIVISOR = 0.625          # sell price = cost / 0.625


def charm_round_up(price: float) -> float:
    """Round a price UP to the next 'charm' ending of .49 or .99.

    e.g. 1.85 -> 1.99, 2.02 -> 2.49, 13.15 -> 13.49, 0.60 -> 0.99, 3.00 -> 3.49.
    """
    eps = 1e-9
    base = math.floor(price + eps)
    frac = price - base
    if frac <= 0.49 + eps:
        return round(base + 0.49, 2)
    if frac <= 0.99 + eps:
        return round(base + 0.99, 2)
    return round(base + 1.49, 2)


def state_multiplier(state_choice: str) -> float:
    """Return the cost multiplier for the invoice's origin state.

    `state_choice` is "california" or anything else (treated as out of state).
    """
    if (state_choice or "").strip().lower() in ("california", "ca", "cali"):
        return 1.0 + CALIFORNIA_MARKUP
    return 1.0 + OUT_OF_STATE_MARKUP


def unit_cost(line_cost: float, divisor: float) -> float:
    """Cost per item or per lb. `divisor` is units or weight in lbs."""
    divisor = float(divisor) if divisor else 1.0
    if divisor == 0:
        divisor = 1.0
    return float(line_cost) / divisor


def compute_prices(line_cost, divisor, state_choice):
    """Return a dict with the full price breakdown for one item.

    line_cost : the cost figure pulled from the invoice for this line
    divisor   : units (if by quantity) or weight in lbs (if by weight)
    state_choice : "california" or other
    """
    base_unit_cost = unit_cost(line_cost, divisor)
    mult = state_multiplier(state_choice)
    adjusted_cost = base_unit_cost * mult
    raw_sell = adjusted_cost / SELL_DIVISOR
    return {
        "base_unit_cost": round(base_unit_cost, 4),
        "state_multiplier": mult,
        "adjusted_cost": round(adjusted_cost, 4),
        "raw_sell_price": round(raw_sell, 2),
        "sell_price": charm_round_up(raw_sell),
    }
