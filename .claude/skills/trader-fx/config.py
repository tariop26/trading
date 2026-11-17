"""Configuration of the trade ideas (capital, risk, leverage, contract table).

Python 3 standard library only. `load_config` reads `trader/fx/config.json`
(optional); a missing file gives the defaults. Any problem raises `ConfigError`
whose message is ONE French sentence, ready to print, naming the offending key.
"""
import copy
import json
import math
import os

# Intraday signal families, in priority order.
INTRADAY_FAMILIES = ("session_break", "bb_return", "fractal_break", "engulfing", "rsi_exit")

DEFAULTS = {
    "account": {"currency": "USD", "capital": 100000},
    "risk": {"per_trade_pct": 0.5, "max_total_pct": 2.0},
    "leverage_max": 30,
    "plan": {"stop_atr_mult": 1.5, "target_r": 2.0},
    "ideas": {"max_shown": 5, "max_per_exposure": 2},
    "contracts": {},
    "alerts": {"auto_push": False},
    "intraday": {
        "enabled": False,
        "symbols": [],
        "mt5_symbols": {},
        "families": list(INTRADAY_FAMILIES),
        "range_minutes": 30,
        "break_window_hours": 3,
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_low": 30,
        "rsi_high": 70,
        "engulfing_min_prior": 3,
        "min_stop_pct": 0.05,
        "max_stop_daily_atr": 1.0,
        "min_rr": 1.0,
        "score_per_signal": 2,
        "score_trend": 1,
        "window_bars": 4,
        "max_age_minutes": 30,
        "validity_r": 0.25,
        "max_per_run": 3,
        "max_per_day": 10,
        "max_per_exposure": 2,
        "cooldown_minutes": 120,
        "min_score": None,
    },
}

CONTRACT_KEYS = ("usd_per_point", "step", "min")


class ConfigError(Exception):
    """Invalid configuration; str() is a single French sentence."""


def defaults():
    return copy.deepcopy(DEFAULTS)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def _num(path, v, lo=None, hi=None, lo_open=False, integer=False):
    """Check that v is a real number (optionally integer) within bounds."""
    if not _is_number(v):
        raise ConfigError(f"La valeur de {path} doit être un nombre.")
    if integer and (isinstance(v, float) and not v.is_integer()):
        raise ConfigError(f"La valeur de {path} doit être un nombre entier.")
    if lo is not None and (v <= lo if lo_open else v < lo):
        sign = ">" if lo_open else ">="
        raise ConfigError(f"La valeur de {path} doit être {sign} {lo} (reçu {v}).")
    if hi is not None and v > hi:
        raise ConfigError(f"La valeur de {path} doit être <= {hi} (reçu {v}).")
    return int(v) if integer else v


def _check_keys(path, got, allowed):
    for key in got:
        if key not in allowed:
            full = f"{path}.{key}" if path else str(key)
            raise ConfigError(f"Configuration invalide : clé inconnue {full}.")


def _section(cfg, name):
    value = cfg.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"La section {name} doit être un objet JSON.")
    _check_keys(name, value, DEFAULTS[name])
    merged = copy.deepcopy(DEFAULTS[name])
    merged.update(copy.deepcopy(value))
    return merged


def _contracts(value):
    if not isinstance(value, dict):
        raise ConfigError("La section contracts doit être un objet JSON.")
    out = {}
    for symbol, entry in value.items():
        base = f"contracts.{symbol}"
        if not isinstance(entry, dict):
            raise ConfigError(f"L'entrée {base} doit être un objet JSON.")
        _check_keys(base, entry, CONTRACT_KEYS)
        for key in CONTRACT_KEYS:
            if key not in entry:
                raise ConfigError(f"Il manque la clé {base}.{key}.")
        out[symbol] = {key: _num(f"{base}.{key}", entry[key], lo=0, lo_open=True)
                       for key in CONTRACT_KEYS}
    return out


# key -> (lo, hi, lo_open, integer) for the plain numeric intraday keys.
INTRADAY_BOUNDS = {
    "break_window_hours": (1, 6, False, False),
    "bb_period": (5, 100, False, True),
    "bb_std": (1, 4, False, False),
    "rsi_period": (5, 50, False, True),
    "rsi_low": (5, 50, False, False),
    "rsi_high": (50, 95, False, False),
    "engulfing_min_prior": (1, 6, False, True),
    "min_stop_pct": (0, 1, True, False),
    "max_stop_daily_atr": (0, 5, True, False),
    "min_rr": (0.5, 5, False, False),
    "score_per_signal": (1, 5, False, True),
    "score_trend": (0, 3, False, True),
    "window_bars": (1, 12, False, True),
    "max_age_minutes": (15, 120, False, True),
    "validity_r": (0, 1, True, False),
    "max_per_run": (1, 10, False, True),
    "max_per_day": (1, 50, False, True),
    "max_per_exposure": (1, 5, False, True),
    "cooldown_minutes": (0, 720, False, True),
}


def _is_text(v):
    return isinstance(v, str) and bool(v.strip())


def _intraday(cfg):
    intra = _section(cfg, "intraday")
    if not isinstance(intra["enabled"], bool):
        raise ConfigError("La valeur de intraday.enabled doit être true ou false.")

    symbols = intra["symbols"]
    if not isinstance(symbols, list) or not all(_is_text(s) for s in symbols):
        raise ConfigError("La valeur de intraday.symbols doit être une liste de symboles "
                          "(textes non vides).")

    mt5 = intra["mt5_symbols"]
    if (not isinstance(mt5, dict)
            or not all(_is_text(k) and _is_text(v) for k, v in mt5.items())):
        raise ConfigError("La valeur de intraday.mt5_symbols doit être un objet associant "
                          "un symbole à un nom MT5 (textes non vides).")

    families = intra["families"]
    if (not isinstance(families, list) or not families
            or not all(isinstance(f, str) and f in INTRADAY_FAMILIES for f in families)
            or len(set(families)) != len(families)):
        raise ConfigError("La valeur de intraday.families doit être une liste non vide, sans "
                          "doublon, de familles parmi " + ", ".join(INTRADAY_FAMILIES) + ".")

    minutes = _num("intraday.range_minutes", intra["range_minutes"], lo=15, hi=120, integer=True)
    if minutes % 15:
        raise ConfigError("La valeur de intraday.range_minutes doit être un multiple de 15 "
                          f"(reçu {minutes}).")
    intra["range_minutes"] = minutes

    for key, (lo, hi, lo_open, integer) in INTRADAY_BOUNDS.items():
        intra[key] = _num(f"intraday.{key}", intra[key], lo=lo, hi=hi,
                          lo_open=lo_open, integer=integer)

    score = intra["min_score"]
    if score is not None and (isinstance(score, bool) or not isinstance(score, int)):
        raise ConfigError("La valeur de intraday.min_score doit être un nombre entier ou null.")
    return intra


def validate(cfg):
    """Merge cfg over the defaults (section by section) and return a validated copy."""
    if not isinstance(cfg, dict):
        raise ConfigError("La configuration doit être un objet JSON.")
    _check_keys("", cfg, DEFAULTS)

    out = {}
    account = _section(cfg, "account")
    if account["currency"] != "USD":
        raise ConfigError("Configuration invalide : devise de compte non gérée : USD seulement "
                          "(account.currency).")
    account["capital"] = _num("account.capital", account["capital"], lo=0, lo_open=True)
    out["account"] = account

    risk = _section(cfg, "risk")
    risk["per_trade_pct"] = _num("risk.per_trade_pct", risk["per_trade_pct"],
                                 lo=0, hi=2, lo_open=True)
    risk["max_total_pct"] = _num("risk.max_total_pct", risk["max_total_pct"], hi=10)
    if risk["max_total_pct"] < risk["per_trade_pct"]:
        raise ConfigError("La valeur de risk.max_total_pct doit être >= risk.per_trade_pct "
                          f"(reçu {risk['max_total_pct']} contre {risk['per_trade_pct']}).")
    out["risk"] = risk

    out["leverage_max"] = _num("leverage_max", cfg.get("leverage_max", DEFAULTS["leverage_max"]),
                               lo=1, hi=500)

    plan = _section(cfg, "plan")
    plan["stop_atr_mult"] = _num("plan.stop_atr_mult", plan["stop_atr_mult"], lo=0.5, hi=5)
    plan["target_r"] = _num("plan.target_r", plan["target_r"], lo=1, hi=5)
    out["plan"] = plan

    ideas = _section(cfg, "ideas")
    ideas["max_shown"] = _num("ideas.max_shown", ideas["max_shown"], lo=1, hi=10, integer=True)
    ideas["max_per_exposure"] = _num("ideas.max_per_exposure", ideas["max_per_exposure"],
                                     lo=1, hi=5, integer=True)
    out["ideas"] = ideas

    out["contracts"] = _contracts(cfg.get("contracts", {}))

    alerts = _section(cfg, "alerts")
    if not isinstance(alerts["auto_push"], bool):
        raise ConfigError("La valeur de alerts.auto_push doit être true ou false.")
    out["alerts"] = alerts

    out["intraday"] = _intraday(cfg)
    return out


def load_config(path):
    """Load and validate the config file; missing file or empty path = defaults."""
    if not path or not os.path.exists(path):
        return defaults()
    try:
        with open(path, encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Le fichier de configuration {path} n'est pas du JSON valide "
                          f"(ligne {exc.lineno}, colonne {exc.colno}).") from None
    except (OSError, UnicodeDecodeError) as exc:
        reason = " ".join(str(exc).split())
        raise ConfigError(f"Le fichier de configuration {path} est illisible ({reason}).") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"Le fichier de configuration {path} doit contenir un objet JSON.")
    return validate(raw)
