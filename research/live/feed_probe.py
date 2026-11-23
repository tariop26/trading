#!/usr/bin/env python3
"""Sonde du fournisseur de prix Twelve Data (offre gratuite) : or, DAX40, Dow Jones.

    TWELVE_DATA_API_KEY=... python3 research/live/feed_probe.py

Pour chaque symbole candidat : demande les 3 dernières barres 1 minute et affiche le statut,
le dernier prix, l'âge de la dernière barre (en minutes, par rapport à l'heure UTC actuelle) et
les crédits restants. La clé ne s'affiche jamais. Bibliothèque standard seulement.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://api.twelvedata.com/time_series"
# (cible, symbole Twelve Data). Plusieurs noms possibles par cible : on ne sait pas lequel
# l'offre gratuite accepte. DIA = ETF qui suit le Dow Jones (prix / 100 environ), repli éventuel.
CANDIDATES = [
    ("or", "XAU/USD"),
    ("DAX40", "DAX"),
    ("DAX40", "GDAXI"),
    ("Dow Jones", "DJI"),
    ("Dow Jones", "DIA"),
]


def fetch(symbol, key):
    q = urllib.parse.urlencode({"symbol": symbol, "interval": "1min", "outputsize": 3,
                                "timezone": "UTC", "apikey": key})
    req = urllib.request.Request(BASE + "?" + q, headers={"User-Agent": "trader-fx-probe"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body, hdr, code = r.read().decode("utf-8"), r.headers, r.status
    except urllib.error.HTTPError as e:
        body, hdr, code = e.read().decode("utf-8", "replace"), e.headers, e.code
    except (urllib.error.URLError, TimeoutError) as e:
        return {"error": "réseau : %s" % type(e).__name__}
    try:
        doc = json.loads(body)
    except ValueError:
        return {"error": "réponse non JSON (HTTP %s)" % code}
    doc["_http"] = code
    doc["_ms"] = int((time.time() - t0) * 1000)
    doc["_left"] = hdr.get("api-credits-left")
    return doc


def main():
    key = os.environ.get("TWELVE_DATA_API_KEY", "").strip()
    if not key:
        print("TWELVE_DATA_API_KEY absente de l'environnement.")
        return 1
    now = datetime.now(timezone.utc)
    print("Sonde Twelve Data, %s UTC" % now.strftime("%Y-%m-%d %H:%M:%S"))
    for target, symbol in CANDIDATES:
        doc = fetch(symbol, key)
        if "error" in doc:
            print("%-10s %-8s ERREUR %s" % (target, symbol, doc["error"]))
            continue
        if doc.get("status") != "ok" or not doc.get("values"):
            # le message d'erreur du fournisseur ne contient pas la clé
            print("%-10s %-8s REFUSÉ  code=%s : %s" % (
                target, symbol, doc.get("code", doc["_http"]), str(doc.get("message", ""))[:160]))
            continue
        last = doc["values"][0]
        try:
            bar = datetime.strptime(last["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            age = "%.1f min" % ((now - bar).total_seconds() / 60)
        except (KeyError, ValueError):
            age = "?"
        print("%-10s %-8s OK      dernière barre %s UTC, âge %s, close %s, %d ms, crédits restants %s"
              % (target, symbol, last.get("datetime"), age, last.get("close"), doc["_ms"], doc["_left"]))
        meta = doc.get("meta", {})
        print("           type=%s, bourse=%s, devise=%s" % (
            meta.get("type"), meta.get("exchange"), meta.get("currency")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
