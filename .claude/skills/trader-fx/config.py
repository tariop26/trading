"""Configuration of the trade ideas (capital, risk, leverage, contract table).

Python 3 standard library only. `load_config` reads `trader/fx/config.json`
(optional); a missing file gives the defaults. Any problem raises `ConfigError`
whose message is ONE French sentence, ready to print, naming the offending key.
"""
import copy
import json
import math
import os

DEFAULTS = {
    "account": {"currency": "USD", "capital": 100000},
    "risk": {"per_trade_pct": 0.5, "max_total_pct": 2.0},
    "leverage_max": 30,
    "plan": {"stop_atr_mult": 1.5, "target_r": 2.0},
    "ideas": {"max_shown": 5, "max_per_exposure": 2},
    "contracts": {},
    "alerts": {"auto_push": False},
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
