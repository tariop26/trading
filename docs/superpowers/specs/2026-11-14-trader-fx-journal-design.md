# trader-fx : journal de trading et statistiques (sous-projet 4)

Date : 2026-11-14. Statut : en attente de relecture.
S'appuie sur `2026-11-13-trader-fx-briefing-design.md` et `2026-11-14-trader-fx-trade-ideas-design.md`. Le sous-projet 3 (alertes sur serveur GitHub, avec Telegram) aura son propre spec et lira le fichier d'alertes produit ici.

## 1. Contexte et objectif

Le briefing propose des idées de trade, mais rien ne garde la trace de ce que l'utilisateur prend réellement ni de ce qui en sort. Sans cette trace, impossible de savoir quelles règles marchent, quelles erreurs coûtent cher, ni de surveiller le stop et la cible d'un trade ouvert.

Objectif : un journal local des trades réellement pris (entrée, taille, stop, cible, clôture), qui calcule le résultat en USD et en R, produit des statistiques honnêtes sur ce qui marche, et génère les règles de stop et de cible que le serveur d'alertes surveillera.

Ce que l'utilisateur a dit : le journal est la source de vérité des trades pris ; il déclare un trade en le disant à Claude (« j'ai pris l'idée EURJPY baissier à 176,70, 0,45 lot ») ; toutes les familles de statistiques sont voulues (réussite et R, par règle et par sens, par paire/session/jour, erreurs, capital et drawdown) ; un format qui permettra plus tard une déclaration depuis Telegram ; le quota Claude doit être ménagé (calculs en Python pur).
Hypothèses (à corriger à la relecture) : le journal est versionné dans le dépôt privé `tariop26/trading` (sauvegarde) ; le résultat réel en USD du courtier est préféré et saisi à la clôture, sinon il est estimé et marqué comme tel ; un seul compte, en USD.

## 2. Hors périmètre

- Aucun ordre, aucune connexion à un courtier, aucun import automatique d'historique.
- La déclaration par Telegram (le format la prévoit, la commande viendra plus tard).
- Le serveur d'alertes, Telegram et GitHub Actions (sous-projet 3).
- Plusieurs comptes ou devises, fiscalité, calcul exact du swap, du spread ou des commissions (le résultat du courtier les inclut ; l'estimation les ignore et le dit).
- Toute prévision ou conseil : le journal rapporte des faits.

## 3. Critères de succès

1. `open`, `amend`, `close`, `list`, `stats`, `alerts` et `page` fonctionnent sur un journal vide ou rempli, sans plantage, avec des messages d'une ligne en cas d'erreur.
2. Le R et le résultat estimé d'exemples calculés à la main (forex cotée en USD, base USD, croisée, instrument à contrat) sont exacts.
3. Chaque statistique est exacte sur un petit journal inventé à la main, et chaque ligne affiche le nombre de trades qui la fonde.
4. Un journal abîmé ou une écriture interrompue ne détruit jamais l'ancien fichier (écriture atomique, copie `.bak`).
5. `trader/fx/alerts.json` ne contient aucun résultat financier ni identifiant de compte : seulement les niveaux de stop et de cible des trades ouverts.
6. Tous les tests passent sans réseau.

## 4. Architecture

Nouvelles unités dans `.claude/skills/trader-fx/` (Python 3, bibliothèque standard seulement).

| Fichier | Rôle | Dépend de |
| --- | --- | --- |
| `journal.py` | ligne de commande et stockage (`open`, `amend`, `close`, `list`, `stats`, `alerts`, `page`) | `jstats`, `sizing`, `config` |
| `jstats.py` | statistiques, fonctions pures | `sessions` |
| `sizing.py` (étendu) | `risk_at` et `pnl_at` : risque et résultat en USD | `strength` |
| `journal_template.html` | page « Journal de trading » (charte 4884) | `journal.json` et statistiques intégrés |
| `page.py` (étendu) | `render_page(doc, template_path, script_id="briefing")` | rien de nouveau |

### 4.1 Fichier `trader/fx/journal.json`

```
{"v": 1, "trades": [Trade, ...]}
Trade = {
  "id": "2026-11-16-EURJPY-1",          # date UTC d'ouverture, symbole sans "=X", numéro du jour
  "symbol": "EURJPY=X", "name": "EUR/JPY",
  "side": "haussier" | "baissier",
  "status": "open" | "closed",
  "source": "idee" | "hors_plan",
  "idea": null | {"as_of", "rank", "score", "setups": [...], "reference_price", "stop", "target",
                  "rr", "last_bar_date", "decimals", "size": {...}},   # copie de trade_ideas
  "entry": {"time": ISO UTC, "price": float, "lots": float|null, "units": int|null, "size": float|null},
  "initial_stop": float, "initial_target": float|null,
  "stop": float, "target": float|null,   # niveaux en vigueur
  "risk_usd": float|null,                # risque prévu au stop, calculé à l'ouverture, jamais modifié
  "exit": null | {"time": ISO UTC, "price": float, "reason": "stop"|"cible"|"manuel"},
  "result": null | {"pnl_usd": float, "r": float|null, "source": "courtier"|"estime"},
  "tags": [str], "note": str,
  "history": [{"time": ISO UTC, "event": "ouverture"|"stop_deplace"|"cible_deplacee"|"cloture", "detail": str}]
}
```

- Heures stockées en UTC ; l'utilisateur les saisit et les lit en heure de Paris (`--time "YYYY-MM-DD HH:MM"`, défaut : maintenant).
- **R** = `pnl_usd / risk_usd`, avec `risk_usd` fixé à l'ouverture à partir du stop initial : déplacer le stop ne change jamais l'unité de mesure. `r` vaut `null` si `risk_usd` est inconnu.
- Écriture atomique : fichier temporaire puis `os.replace` ; l'ancienne version est copiée en `journal.json.bak` (exclu de git). Un fichier absent donne un journal vide ; un fichier illisible ou d'une autre version : une ligne d'erreur, rien n'est écrit.

### 4.2 sizing.py : risque et résultat en USD

Mêmes conventions que le calcul de taille existant.

- `risk_at(symbol, entry, stop, qty, prices, contracts) -> float | None` : perte en USD si le stop est touché, pour `qty` (unités forex ou taille de contrat). Forex : base USD (cotation non USD) `qty × |entry − stop| / stop` ; cotation USD `qty × |entry − stop|` ; croisée `qty × |entry − stop| × q2u` au cours d'entrée. Instrument à contrat : `qty × |entry − stop| × usd_per_point`. `None` si une conversion ou un contrat manque.
- `pnl_at(symbol, side, entry, exit, qty, prices, contracts) -> float | None` : résultat en USD (signé, haussier `exit − entry`, baissier `entry − exit`). Forex : cotation USD `qty × diff` ; base USD `qty × diff / exit` ; croisée `qty × diff × q2u` au cours de clôture ; contrat `qty × diff × usd_per_point`. `None` si indéterminé. Hors frais, swap et glissement.
- `prices` = derniers cours de paires forex (`"EURUSD=X"`…), comme pour le calcul de taille.
- Quand une conversion manque, le journal peut faire une requête Yahoo pour la paire nécessaire (`USD<cotation>=X`) ; hors ligne, l'utilisateur passe `--quote-usd-rate X` (valeur en USD d'une unité de la cotation) ou `--risk-usd` / `--pnl`.

### 4.3 Commandes (`journal.py`)

- `open --symbol S --side haussier|baissier --price P (--lots L | --size Z) [--stop X] [--target Y] [--time T] [--risk-usd R] [--quote-usd-rate Q] [--briefing PATH]` : si `S` figure parmi les idées de `trader/fx/briefing.json` (défaut du chemin), la copie de l'idée est jointe (`source = "idee"`) et son stop et sa cible servent de défaut ; sinon `--stop` est obligatoire (`source = "hors_plan"`). Validation : haussier exige `stop < prix` et, si la cible est donnée, `prix < cible` ; baissier l'inverse ; quantité positive. Calcule `risk_usd` avec `risk_at` (ou `--risk-usd`). Pour le forex, `units = round(lots × 100000)`. Affiche l'identifiant et une ligne de confirmation.
- `amend ID [--stop X] [--target Y] [--time T]` : met à jour les niveaux en vigueur ; ajoute l'événement `stop_deplace` ou `cible_deplacee`, et l'étiquette `stop_deplace` si le stop a été éloigné du prix (augmente le risque).
- `close ID --price P [--reason stop|cible|manuel] [--pnl USD] [--tags a,b] [--note TEXTE] [--time T] [--quote-usd-rate Q]` : `pnl_usd` = `--pnl` s'il est donné (`source = "courtier"`), sinon `pnl_at` (`source = "estime"`) ; si ni l'un ni l'autre n'est possible : une ligne qui dit quoi fournir. Calcule `r`.
- `list [--open|--closed]` : une ligne par trade.
- `stats [--json]` : résumé terminal (4.4).
- `alerts [--out PATH]` : écrit `trader/fx/alerts.json` (4.5).
- `page [--out PATH]` : écrit `trader/fx/journal.html`.

### 4.4 jstats.py : statistiques

Seuls les trades clôturés comptent (les trades ouverts sont listés à part). Un trade à `|r| < 0.05` est « à l'équilibre » (ni positif ni négatif). `r` nul : le trade est compté dans `n` mais exclu des moyennes de R (et signalé).

- **Réussite et R** : `n`, trades positifs, négatifs, à l'équilibre, taux de trades positifs, R moyen des positifs et des négatifs, espérance (`R moyen`), R total, résultat total en USD avec le nombre de résultats estimés.
- **Par règle et par sens** : un trade compte dans chacune de ses règles déclencheuses (une idée à deux règles figure dans les deux lignes ; le tableau le dit) ; par sens haussier et baissier ; les trades hors plan figurent sous « hors plan ».
- **Par paire, session et jour** : par symbole ; session d'entrée = parmi les sessions actives à l'heure d'entrée, celle qui a ouvert le plus récemment (Tokyo, Londres, New York, Sydney), « hors session » sinon (`sessions.session_table`) ; jour de la semaine de l'entrée en heure de Paris.
- **Erreurs** : par étiquette, nombre de trades, R moyen et R total (le « coût » de l'erreur est son R total).
- **Capital et drawdown** : capital de départ (`account.capital` de la configuration), courbe après chaque trade clôturé (ordre d'heure de clôture), pire drawdown en USD et en pourcentage du pic, pire série de trades négatifs (nombre et R cumulé) ; le drawdown est comparé au plafond de risque cumulé de la configuration.
- **Chaque ligne affiche son `n`.** Moins de 30 trades clôturés au total : avertissement « échantillon trop petit pour conclure » en tête ; une ligne de groupe à moins de 5 trades porte la mention « peu de trades ».

### 4.5 alerts.json

```
{"v": 1, "updated": ISO UTC,
 "rules": [{"id": "<trade id>-stop", "trade_id": "...", "symbol": "EURJPY=X", "type": "stop",
            "side": "baissier", "level": 178.4, "decimals": 3},
           {"id": "<trade id>-cible", ... "type": "cible" ...}]}
```

Une règle par stop et par cible de trade ouvert (`stop` et `target` en vigueur). Aucun résultat, aucun capital, aucune taille. Le format est celui que le sous-projet 3 lira.

### 4.6 Page

`page.render_page(doc, template_path, script_id="briefing")` insère le JSON dans le gabarit comme aujourd'hui ; pour le journal, `doc = {"journal": ..., "stats": ..., "as_of": ...}` et `script_id = "journal"`. Sections : résumé (trades ouverts et clôturés, R total, résultat), trades ouverts, statistiques (les cinq familles, avec `n` et avertissements), liste des trades clôturés. Charte 4884, deux thèmes, aucun appel réseau, valeurs insérées en texte seulement. Le journal contient des résultats : la page se publie en Artifact privé.

## 5. Gestion des erreurs et vocabulaire

- Une ligne claire par erreur, code de sortie 1, aucun fichier modifié : trade inconnu ou déjà clôturé, prix du mauvais côté du stop, quantité nulle, résultat inestimable sans `--pnl`, option manquante, fichier illisible.
- Le journal rapporte des faits : « résultat positif/négatif », montants en USD et en R sont permis. Interdits : achat, acheter, vente, vendre, buy, sell, tout conseil et toute prévision. « Haussier » et « baissier » désignent le sens.
- Les résultats estimés sont toujours marqués « estimé, hors frais » ; un résultat du courtier est marqué « courtier ».

## 6. Tests

`unittest`, sans réseau.
- `sizing.risk_at` / `pnl_at` : exemples chiffrés à la main (EURUSD, USDJPY haussier et baissier, une croisée convertie, un instrument à contrat, conversion manquante donnant `None`).
- `journal` : ouverture depuis une idée et hors plan, validations, identifiants du jour, `amend` (étiquette `stop_deplace`, `risk_usd` inchangé), `close` avec résultat du courtier et estimé, trade déjà clôturé, écriture atomique (échec simulé : l'ancien fichier subsiste), version inconnue, journal vide.
- `jstats` : journal de 8 à 10 trades inventés avec toutes les statistiques vérifiées à la main ; trade à l'équilibre ; `r` nul ; règle multiple ; sessions et jours (heures d'été et d'hiver) ; drawdown et séries ; avertissements d'échantillon.
- `alerts` : règles de stop et de cible des trades ouverts seulement ; aucun champ financier.
- Page : rendu avec trades, sans trade, valeurs hostiles non exécutées, vocabulaire interdit, test réseau inchangé.
- Essai manuel en direct, à part, sur un trade fictif (ouverture, déplacement du stop, clôture).

## 7. Points à traiter pendant l'implémentation

- Vérifier le calcul du résultat estimé d'une croisée avec un taux saisi à la main.
- Décider du nom du fichier de page publié (`journal.html`) et de son lien d'Artifact (un second Artifact, privé).
- Ajouter à `SKILL.md` la section « Journal » : comment déclarer un trade en une phrase, et la règle « donne le résultat du courtier à la clôture ».

## 8. Suite

Sous-projet 3 (alertes) : lit `alerts.json`, lance un script sur GitHub Actions, envoie Telegram ; ajoute l'annonce à fort impact 30 minutes avant. Son spec dépend du verdict du test de faisabilité.
