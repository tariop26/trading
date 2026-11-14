"""Position sizing in USD terms (forex lots, contract table, leverage cap).

Python 3 standard library only. Every public sizer returns the same `size`
dictionary with ALL nine keys always present; fields that do not apply are None.
A size that cannot be computed is `to_confirm`, never a made-up figure, and sizes
are always rounded down. The risk at the stop never exceeds
`risk_usd = capital * risk_pct / 100` for pairs quoted in USD and for USD-base
pairs (their loss is converted at the stop rate, `|entry - stop| / stop`); for
crosses the quote-to-USD rate at the stop is unknown, so the loss is converted at
the entry-day rate and can differ by roughly the stop distance in percent. Gaps and
slippage are never included.
"""
import math
from decimal import ROUND_HALF_UP, Decimal

import strength

LOT_UNITS = 100000
FOREX_STEP_UNITS = 1000          # 0.01 lot

NOTE_ZERO_DISTANCE = "distance au stop nulle"
NOTE_TOO_WIDE = "stop trop large pour le risque fixé"
NOTE_LEVERAGE_BEFORE_MIN = "levier maximum atteint avant la taille minimale"
NOTE_NO_CONTRACT = ("taille à confirmer chez le courtier : renseigner contracts "
                    "dans trader/fx/config.json")


def _result(status, note=None, **fields):
    out = {"status": status, "lots": None, "units": None, "size": None,
           "risk_usd": None, "leverage": None, "pip_value_usd_per_lot": None,
           "limited_by": None, "note": note}
    out.update(fields)
    return out


def _to_confirm(note):
    return _result("to_confirm", note)


def _too_wide(note):
    return _result("too_wide", note)


def _steps(amount, step):
    """Whole number of `step`s that fit in `amount`, rounded DOWN.

    The quotient is rounded to 6 decimals before the floor so that float noise
    (87 999.999999...) does not lose a whole step; it is never rounded up beyond
    that noise level.
    """
    return math.floor(round(amount / step, 6))


def usd_cents(x):
    """`x` USD rounded to the cent, a half-cent tie going UP.

    Float `round` goes to even on an exact tie and shows 4971.875 as 4971.87; the
    product of floats also carries noise (4971.874999999993), so it is cleaned at 6
    decimals (the noise level used by `_steps`) before the decimal half-up round."""
    return float(Decimal(repr(round(x, 6))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) \
        and math.isfinite(x) and x > 0


def _distance(entry, stop):
    """|entry - stop| or None when it is missing, non-finite or not positive."""
    try:
        dist = abs(float(entry) - float(stop))
    except (TypeError, ValueError):
        return None
    return dist if math.isfinite(dist) and dist > 0 else None


def pip_size(quote):
    """0.01 for a JPY quote currency, 0.0001 otherwise."""
    return 0.01 if quote == "JPY" else 0.0001


def usd_rate(ccy, prices):
    """USD value of one unit of `ccy`, or None when it cannot be derived.

    1.0 for USD; 1 / prices["USD<ccy>=X"] if present; else prices["<ccy>USD=X"].
    A price that is zero or negative counts as missing.
    """
    if ccy == "USD":
        return 1.0
    prices = prices or {}
    inverse = prices.get(f"USD{ccy}=X")
    if _positive(inverse):
        return 1.0 / inverse
    direct = prices.get(f"{ccy}USD=X")
    if _positive(direct):
        return float(direct)
    return None


def size_forex(symbol, entry, stop, prices, capital, risk_pct, leverage_max):
    """Size a forex pair in lots of 100 000 units, in steps of 0.01 lot."""
    pair = strength.pair_currencies(symbol)
    if pair is None:
        return _to_confirm(NOTE_NO_CONTRACT)
    base, quote = pair
    dist = _distance(entry, stop)
    if dist is None:
        return _to_confirm(NOTE_ZERO_DISTANCE)

    q2u = usd_rate(quote, prices)
    b2u = usd_rate(base, prices)
    for ccy, rate in ((quote, q2u), (base, b2u)):
        if rate is None:
            return _to_confirm(
                f"conversion de devise impossible : taux en USD introuvable pour {ccy}")

    risk_usd = capital * risk_pct / 100.0
    if base == "USD" and quote != "USD":
        # the loss is in the quote currency and is realised AT THE STOP, where one unit
        # of quote is worth 1 / stop USD: exact for both directions
        loss_per_unit = dist / float(stop)
    else:
        # USD quote: exact (q2u = 1); cross: converted at the entry-day rate, the
        # quote-to-USD rate at the stop is unknown (documented residual)
        loss_per_unit = dist * q2u
    units = _steps(risk_usd / loss_per_unit, FOREX_STEP_UNITS) * FOREX_STEP_UNITS
    if units < FOREX_STEP_UNITS:
        return _too_wide(NOTE_TOO_WIDE)

    limited_by = "risque"
    if units * b2u > leverage_max * capital:
        units = _steps(leverage_max * capital / b2u, FOREX_STEP_UNITS) * FOREX_STEP_UNITS
        limited_by = "levier"
        if units < FOREX_STEP_UNITS:
            return _too_wide(NOTE_LEVERAGE_BEFORE_MIN)

    return _result(
        "ok",
        lots=round(units / LOT_UNITS, 2),
        units=int(units),
        risk_usd=usd_cents(units * loss_per_unit),
        leverage=round(units * b2u / capital, 2),
        pip_value_usd_per_lot=round(LOT_UNITS * pip_size(quote) * q2u, 4),
        limited_by=limited_by,
    )


def size_contract(symbol, entry, stop, contract, capital, risk_pct, leverage_max):
    """Size an index / commodity from its contract entry
    ({"usd_per_point", "step", "min"}), in steps of `step`."""
    if not isinstance(contract, dict) or not all(
            _positive(contract.get(k)) for k in ("usd_per_point", "step", "min")):
        return _to_confirm(NOTE_NO_CONTRACT)
    dist = _distance(entry, stop)
    if dist is None:
        return _to_confirm(NOTE_ZERO_DISTANCE)
    if not _positive(entry):
        return _to_confirm("prix d'entrée invalide")

    per_point = contract["usd_per_point"]
    step = contract["step"]
    minimum = contract["min"]
    risk_usd = capital * risk_pct / 100.0
    loss_per_size = dist * per_point
    size = round(_steps(risk_usd / loss_per_size, step) * step, 6)
    if size < round(minimum, 6):
        return _too_wide(NOTE_TOO_WIDE)

    limited_by = "risque"
    value_per_size = entry * per_point
    if size * value_per_size > leverage_max * capital:
        size = round(_steps(leverage_max * capital / value_per_size, step) * step, 6)
        limited_by = "levier"
        if size < round(minimum, 6):
            return _too_wide(NOTE_LEVERAGE_BEFORE_MIN)

    return _result(
        "ok",
        size=size,
        risk_usd=usd_cents(size * loss_per_size),
        # 3 decimals (not 2): the brief's worked value is 0.396, which 2 decimals would blur
        leverage=round(size * value_per_size / capital, 3),
        limited_by=limited_by,
    )


def size_idea(symbol, entry, stop, prices, config):
    """Size one idea from the config: forex pair or contract-table instrument."""
    capital = config["account"]["capital"]
    risk_pct = config["risk"]["per_trade_pct"]
    leverage_max = config["leverage_max"]
    if strength.pair_currencies(symbol) is not None:
        return size_forex(symbol, entry, stop, prices, capital, risk_pct, leverage_max)
    contract = (config.get("contracts") or {}).get(symbol)
    if contract is None:
        return _to_confirm(NOTE_NO_CONTRACT)
    return size_contract(symbol, entry, stop, contract, capital, risk_pct, leverage_max)
