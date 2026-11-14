# trader-fx : journal de trading et statistiques, plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** un journal local des trades réellement pris (entrée, taille, stop, cible, clôture) avec résultat en USD et en R, cinq familles de statistiques, un fichier d'alertes pour le futur serveur, et une page « Journal de trading ».

**Architecture:** un module de données (`journal.py`, fonctions pures et stockage atomique), un module de statistiques pur (`jstats.py`), deux fonctions de risque et de résultat ajoutées à `sizing.py`, une fonction de session ajoutée à `sessions.py`, une ligne de commande (`journal.py` en script), un gabarit de page (`journal_template.html`) rendu par `page.py` étendu.

**Tech Stack:** Python 3 (bibliothèque standard seulement), `unittest`, gabarit HTML (charte 4884 existante).

**Spec:** `docs/superpowers/specs/2026-11-14-trader-fx-journal-design.md`.

## Global Constraints

- Python 3, bibliothèque standard seulement ; tests `unittest`, jamais de réseau dans un test (la récupération d'un taux Yahoo est injectée et simulée).
- Commandes lancées depuis `C:/Users/m.poirat/TRADING`. Modules plats dans `.claude/skills/trader-fx/` ; chaque fichier de test commence par `import _path  # noqa`. Lancer : `python3 -m unittest discover -s .claude/skills/trader-fx/tests -v` (384 tests passent aujourd'hui, sortie sans avertissement, aussi sous `-W error`).
- Heures stockées en UTC (ISO 8601), saisies et affichées en heure de Paris (`--time "YYYY-MM-DD HH:MM"`, défaut : maintenant).
- Écriture atomique du journal (fichier temporaire puis `os.replace`), copie `trader/fx/journal.json.bak` (exclue de git) ; une erreur ne modifie jamais le fichier existant.
- Une erreur = une seule ligne française, code de sortie 1, aucun fichier modifié.
- Vocabulaire : « haussier » et « baissier » ; interdits comme mots entiers : achat, acheter, vente, vendre, buy, sell ; aucun conseil, aucune prévision. Les résultats positifs/négatifs, les montants en USD et en R sont des faits permis dans le journal. Un résultat estimé est toujours marqué « estimé, hors frais ».
- `alerts.json` ne contient aucun résultat, capital ou taille.
- Chaque message de commit se termine par une ligne vide puis `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Ne rien pousser, ne rien publier.

## Review Focus

1. Clôture exactement au stop (R = −1,00) ou à l'entrée (R = 0), et trade dont le risque est inconnu (`r` nul) : les statistiques ne plantent pas, `n` les compte, les moyennes de R les excluent (Tasks 2 et 3).
2. Paire croisée sans taux de conversion hors ligne : une ligne qui demande `--pnl` ou `--quote-usd-rate`, aucun trade à moitié écrit (Tasks 2 et 4).
3. Stop déplacé après l'entrée : `risk_usd` (initial) inchangé, le R utilise le risque initial, un stop de suivi du bon côté de l'entrée est accepté (Task 2).
4. `journal.json` tronqué, illisible ou d'une autre version : une ligne, rien n'est écrasé ; une sauvegarde interrompue garde l'ancien fichier (Tasks 2 et 4).
5. Sessions et jours autour de l'heure d'été et de minuit (entrée à 23:30 UTC = lendemain à Paris) : les regroupements par jour et par session utilisent l'heure de Paris de façon cohérente (Task 3).

---

### Task 1: risque et résultat en USD dans sizing.py

**Files:**
- Modify: `.claude/skills/trader-fx/sizing.py`
- Test: `.claude/skills/trader-fx/tests/test_sizing.py`

**Interfaces:**
- Consumes: `sizing.usd_rate(ccy, prices)`, `sizing.usd_cents(x)`, `strength.pair_currencies(symbol)`, `sizing.pip_size` (existants).
- Produces:
  - `risk_at(symbol: str, entry: float, stop: float, qty: float, prices: dict, contracts: dict) -> float | None` : perte en USD si le stop est touché, arrondie par `usd_cents`. `qty` = unités (forex) ou taille (contrat). Forex base USD (cotation non USD) : `qty × |entry − stop| / stop` ; cotation USD : `qty × |entry − stop|` ; croisée : `qty × |entry − stop| × usd_rate(quote)` ; contrat : `qty × |entry − stop| × usd_per_point`. `None` si une conversion ou un contrat manque, ou si `qty`, `entry` ou `stop` n'est pas un nombre positif.
  - `pnl_at(symbol: str, side: str, entry: float, exit_price: float, qty: float, prices: dict, contracts: dict) -> float | None` : résultat signé en USD, haussier `exit − entry`, baissier `entry − exit`. Cotation USD : `qty × diff` ; base USD : `qty × diff / exit_price` ; croisée : `qty × diff × usd_rate(quote)` ; contrat : `qty × diff × usd_per_point`. Arrondi `usd_cents` (demi vers le haut en valeur absolue). `None` si indéterminé.

- [ ] **Step 1: Écrire les tests (échouent)** dans `test_sizing.py`, valeurs calculées à la main :
  - `risk_at` : EURUSD entrée 1,1000 stop 1,0950, 100 000 unités, `{"EURUSD=X": 1.10}` → 500.0 ; USDJPY entrée 150,00 stop 149,25, 99 000 unités → 497.49 ; GBPCHF entrée 1,1000 stop 1,0950, 88 000 unités, `{"USDCHF=X": 0.88}` → 500.0 ; `^FCHI` entrée 8000 stop 7900 taille 4,5, contrats `{"^FCHI": {"usd_per_point": 1.1, "step": 0.1, "min": 0.1}}` → 495.0.
  - `pnl_at` : EURUSD haussier 1,1000 → 1,1050, 100 000 unités → 500.0 ; même entrée et sortie baissier → −500.0 ; USDJPY haussier 150,00 → 151,50, 100 000 unités → 990.10 ; USDJPY baissier 150,00 → 148,50, 100 000 unités → 1010.10 ; EURJPY baissier 176,70 → 175,10, 45 000 unités, `{"USDJPY=X": 159.875}` → 450.35 ; `^FCHI` haussier 8000 → 8050 taille 4,5 → 247.5.
  - `test_unknown_conversion_gives_none` : GBPZAR sans `USDZAR=X` ni `ZARUSD=X` → `None` pour les deux fonctions ; contrat absent → `None` ; `qty` 0 ou négative, prix nul ou texte → `None` (aucune exception).
  - `test_risk_at_matches_size_idea` : pour un échantillon de 200 couples (graine fixe) sur EURUSD, USDJPY, GBPCHF, `risk_at(units de size_idea) <= risk_usd attendu + 0.01` (cohérence avec le calcul de taille).
- [ ] **Step 2: Lancer** `python3 -m unittest discover -s .claude/skills/trader-fx/tests -p "test_sizing.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** en réutilisant `usd_rate`, `usd_cents` et le calcul de perte par unité existant ; aucun doublon de la formule : si possible factoriser la partie « perte par unité en USD » partagée avec `size_forex` sans changer son comportement.
- [ ] **Step 4: Lancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `git add .claude/skills/trader-fx && git commit -m "feat(trader-fx): risk_at et pnl_at (risque et résultat en USD)"`

### Task 2: couche de données du journal (journal.py)

**Files:**
- Create: `.claude/skills/trader-fx/journal.py`, `.claude/skills/trader-fx/tests/test_journal.py`
- Modify: `.gitignore` (ajouter `trader/fx/journal.json.bak`)

**Interfaces:**
- Consumes: `sizing.risk_at`, `sizing.pnl_at`, `strength.pair_currencies`, `sizing.LOT_UNITS`.
- Produces (fonctions de module ; le script en ligne de commande arrive en Task 4) :
  - `class JournalError(Exception)` : message d'une ligne, en français.
  - `VERSION = 1`, `empty_journal() -> dict` (`{"v": 1, "trades": []}`).
  - `load_journal(path: str) -> dict` : fichier absent → journal vide ; JSON invalide, non-objet, version différente, ou `trades` non liste → `JournalError`.
  - `save_journal(path: str, journal: dict) -> None` : écrit dans un fichier temporaire du même dossier puis `os.replace` ; copie l'ancien fichier en `path + ".bak"` avant ; crée le dossier ; ne laisse jamais de fichier partiel.
  - `find_trade(journal, trade_id) -> dict` (`JournalError` si inconnu).
  - `new_trade_id(journal, symbol: str, when_utc: datetime) -> str` : `"<AAAA-MM-JJ UTC>-<symbole sans '=X'>-<n>"`, `n` = 1 + nombre d'identifiants déjà présents avec le même préfixe.
  - `open_trade(journal, *, symbol, name, side, price, when_utc, lots=None, size=None, stop=None, target=None, idea=None, risk_usd=None, prices=None, contracts=None) -> dict` : valide, construit le trade du spec §4.1 (statut `open`, `initial_stop`, `stop`, `history` avec l'événement `ouverture`), l'ajoute à `journal["trades"]` et le renvoie. Paire forex : `lots` obligatoire, `units = round(lots × 100000)`, `size = None` ; autre instrument : `size` obligatoire. Si `idea` est fourni, `stop` et `target` valent par défaut ceux de l'idée et `source = "idee"` ; sinon `stop` est obligatoire et `source = "hors_plan"`. `risk_usd` = argument, sinon `risk_at(...)` (peut être `None`).
  - `amend_trade(journal, trade_id, *, when_utc, stop=None, target=None) -> dict` : trade ouvert seulement ; événements `stop_deplace` / `cible_deplacee` ; ajoute l'étiquette `stop_deplace` si le nouveau stop est plus éloigné du prix d'entrée que le précédent (haussier : plus bas ; baissier : plus haut) ; `risk_usd` et `initial_stop` ne changent jamais.
  - `close_trade(journal, trade_id, *, price, when_utc, reason="manuel", pnl_usd=None, prices=None, contracts=None, tags=(), note="") -> dict` : trade ouvert seulement ; `when_utc` doit être ≥ l'heure d'entrée ; `result.pnl_usd` = `pnl_usd` donné (`source "courtier"`) sinon `pnl_at(...)` (`source "estime"`) ; sinon `JournalError("Résultat inestimable : donne --pnl ou --quote-usd-rate.")` sans modifier le trade ; `result.r = round(pnl_usd / risk_usd, 2)` ou `None` si `risk_usd` est nul ou absent ; fusionne les étiquettes sans doublon ; événement `cloture`.
  - Validation commune (`JournalError`, une ligne) : sens inconnu ; prix, stop, cible non nombres positifs ; haussier exige `stop < price` et, si la cible existe, `price < cible` ; baissier l'inverse ; quantité nulle ou négative ; trade déjà clôturé.
  - Toutes ces fonctions écrivent des heures en ISO UTC (`datetime` avec fuseau obligatoire, sinon `ValueError`).

- [ ] **Step 1: Écrire les tests (échouent)** dans `test_journal.py` :
  - `test_load_missing_gives_empty`, `test_load_rejects_bad_json_non_object_wrong_version_and_bad_trades` (chaque cas : `JournalError` d'une ligne), `test_load_tolerates_a_bom`.
  - `test_save_is_atomic_and_keeps_a_backup` : après deux sauvegardes `.bak` contient la première version ; une sauvegarde dont `os.replace` est simulée en échec laisse l'ancien fichier intact et supprime le temporaire (Review Focus 4).
  - `test_new_trade_id_increments_per_day_and_symbol` (`"2026-11-16-EURJPY-1"` puis `-2`, nouvelle date → `-1`).
  - `test_open_from_idea_and_off_plan` : idée EURJPY baissier (stop 178,408, cible 173,161), 0,45 lot à 176,70 → `units == 45000`, `source == "idee"`, stop et cible de l'idée, `risk_usd` calculé par `risk_at` avec `{"USDJPY=X": 159.875}` (valeur attendue calculée à la main : `45000 × |176.70 − 178.408| / 159.875` = 76 860 / 159,875 = 480.75) ; hors plan sans stop → `JournalError` ; hors plan avec stop → `source == "hors_plan"`.
  - `test_open_validations` : haussier avec stop au-dessus du prix, baissier avec cible au-dessus, lots nuls, ni lots ni taille, taille donnée pour une paire forex, sens inconnu, prix texte.
  - `test_open_with_unknown_risk_keeps_r_none` : croisée sans taux → `risk_usd is None` (pas d'erreur à l'ouverture) ; puis `close_trade` avec `--pnl` donne `result.r is None` (Review Focus 1).
  - `test_amend_moves_stop_and_tags_only_when_farther_and_keeps_initial_risk` : stop éloigné → étiquette `stop_deplace` ; stop rapproché → pas d'étiquette ; `risk_usd` et `initial_stop` identiques ; un stop de suivi au-dessus de l'entrée sur un haussier est accepté tant qu'il reste sous la cible (Review Focus 3) ; amender un trade clôturé → erreur.
  - `test_close_with_broker_pnl_and_estimated` : clôture EURJPY baissier à 175,10 avec `pnl_usd=450.35` → `source "courtier"`, `r == round(450.35 / 480.75, 2) == 0.94` ; sans `pnl_usd` avec `{"USDJPY=X": 159.875}` → `source "estime"`, même résultat ; sans taux ni `pnl_usd` → `JournalError` et le trade reste ouvert (Review Focus 2).
  - `test_close_exactly_at_stop_and_at_entry` : clôture au stop → `r == -1.0` (au centime près) ; clôture à l'entrée → `pnl_usd == 0.0` et `r == 0.0` (Review Focus 1).
  - `test_close_validations` : déjà clôturé, heure avant l'entrée, prix négatif, raison inconnue.
  - `test_history_events_in_order`.
- [ ] **Step 2: Lancer** `… -p "test_journal.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter `journal.py`** (fonctions pures sur le dictionnaire du journal ; aucun accès disque hors `load_journal`/`save_journal` ; aucun réseau). Algorithme à ne pas déduire : `r = round(pnl_usd / risk_usd, 2)` avec `usd_cents` pour les montants ; l'étiquette de stop éloigné compare `|prix_entrée − nouveau_stop|` à `|prix_entrée − stop_en_vigueur|`.
- [ ] **Step 4: Relancer** ; attendu : PASS. **Step 5: Commit** `feat(trader-fx): journal.py (couche de données, écriture atomique)`

### Task 3: sessions d'entrée et statistiques (sessions.py, jstats.py)

**Files:**
- Modify: `.claude/skills/trader-fx/sessions.py`, `.claude/skills/trader-fx/tests/test_sessions.py`
- Create: `.claude/skills/trader-fx/jstats.py`, `.claude/skills/trader-fx/tests/test_jstats.py`

**Interfaces:**
- Consumes: `sessions.SESSIONS`, `sessions._local_at`, `sessions.PARIS`, `plan.LONG_TRIGGERS`, `plan.SHORT_TRIGGERS`.
- Produces:
  - `sessions.entry_session(when_utc: datetime, sessions: dict = SESSIONS) -> str` : parmi les sessions de `SESSIONS` actives à `when_utc` (même calcul que `session_table`), celle dont l'ouverture est la plus récente (`"Sydney"`, `"Tokyo"`, `"London"`, `"New York"`) ; `"hors session"` si aucune. `ValueError` si `when_utc` n'a pas de fuseau.
  - `jstats.R_FLAT = 0.05`, `jstats.MIN_TRADES = 30`, `jstats.FEW = 5`.
  - `jstats.classify(trade: dict) -> str | None` : `"positif"`, `"negatif"` ou `"equilibre"` pour un trade clôturé (par `r` s'il existe, `|r| < R_FLAT` = équilibre ; sinon par le signe de `pnl_usd`) ; `None` pour un trade ouvert.
  - `jstats.compute_stats(journal: dict, capital: float = 100000.0, cap_pct: float = 2.0) -> dict` : objet `stats` ci-dessous. Seuls les trades `closed` comptent ; les `open` sont comptés dans `n_open`.

  ```
  stats = {"n_closed", "n_open", "sample_warning": str|None,
           "overall": {"n","positive","negative","flat","win_rate","avg_r_positive","avg_r_negative",
                       "expectancy_r","total_r","pnl_usd","n_estimated","n_no_r"},
           "by_rule": [G], "by_side": [G], "by_symbol": [G], "by_session": [G], "by_weekday": [G],
           "errors": [{"tag","n","avg_r","total_r"}],
           "equity": {"start","end","points":[{"time","trade_id","equity"}],
                      "max_drawdown_usd","max_drawdown_pct","worst_streak":{"n","r"},"cap_pct"}}
  G = {"key","n","win_rate","avg_r","total_r","pnl_usd","few"}
  ```
  `win_rate = positifs / n` (arrondi 4 décimales, `None` si `n == 0`) ; `avg_r` et les moyennes de R excluent les trades à `r` nul (`n_no_r` les compte) et valent `None` s'il n'en reste aucun ; `total_r` somme les `r` non nuls ; `pnl_usd` somme tous les résultats (arrondi centimes) ; `few = n < FEW`. `sample_warning = "échantillon trop petit pour conclure"` si `n_closed < MIN_TRADES`, sinon `None`. `by_rule` : un trade compte dans chacune de ses règles déclencheuses (`idea.setups` ∩ déclencheurs), `"hors plan"` pour `source == "hors_plan"` ; `by_symbol` par `symbol` ; `by_side` par `side` ; `by_session` par `sessions.entry_session(entry.time)` dans l'ordre Sydney, Tokyo, London, New York, hors session ; `by_weekday` par jour de la semaine de l'entrée en heure de Paris (lundi à dimanche, noms français) ; autres groupes triés par `n` décroissant puis clé. `errors` : une ligne par étiquette (sur les trades clôturés). `equity` : trades triés par heure de clôture, `equity = capital + somme cumulée des pnl_usd`, `max_drawdown_usd` = plus grand écart pic-à-creux (le départ compte comme pic), `max_drawdown_pct` rapport au pic (4 décimales, en %), `worst_streak` = plus longue suite de trades classés `negatif` consécutifs (`n`) et la somme de leurs `r` non nuls (`r`).

- [ ] **Step 1: Écrire les tests (échouent)** :
  - `test_sessions.py::test_entry_session` (valeurs calculées à la main avec les heures de `SESSIONS`) : 2026-11-13 12:00 UTC (hiver : Londres 08:00–17:00 UTC actif, New York pas encore ouvert) → `"London"` ; 2026-11-13 14:00 UTC (Londres et New York actifs, New York a ouvert le plus récemment à 13:00 UTC) → `"New York"` ; 2026-11-13 22:30 UTC (Sydney ouvert depuis 20:00 UTC, New York fermé depuis 22:00 UTC) → `"Sydney"` ; 2026-11-13 06:00 UTC (Tokyo 00:00–09:00 UTC actif, Sydney fermé depuis 05:00 UTC) → `"Tokyo"` ; été 2026-07-15 07:30 UTC (Londres BST ouvert depuis 07:00 UTC, Tokyo ouvert depuis 00:00 UTC) → `"London"` ; `"hors session"` testé avec le paramètre `sessions` : un dictionnaire avec la seule session Londres à 20:00 UTC ; `ValueError` sans fuseau (Review Focus 5).
  - `test_jstats.py` avec un journal inventé de 8 trades clôturés (fonction de construction dans le test) : 2 règles différentes dont un trade à deux règles, 2 sens, 3 symboles, 2 étiquettes d'erreur, un trade `hors_plan`, un trade au stop (R −1), un trade à l'équilibre (R 0), un trade à `r` nul, un ouvert. Vérifier à la main et figer : `overall.n`, `positive`, `negative`, `flat`, `win_rate`, `avg_r_positive`, `avg_r_negative`, `expectancy_r`, `total_r`, `pnl_usd`, `n_estimated`, `n_no_r` ; chaque groupe (valeurs de `n`, `avg_r`, `total_r`, `few`) ; l'ordre des groupes ; le trade à deux règles compté dans les deux lignes ; `errors` ; `equity.points` ordonnés par clôture, `max_drawdown_usd` et `%`, `worst_streak` ; `sample_warning` présent (8 < 30) et absent pour un journal de 30 trades générés.
  - `test_empty_journal` : `n_closed == 0`, tous les groupes vides, aucune division par zéro, `win_rate is None`.
  - `test_weekday_uses_paris_time` : un trade ouvert le vendredi à 23:30 UTC tombe sous « samedi » à Paris, en hiver (00:30) comme en été (01:30) ; un trade ouvert à 22:30 UTC en été tombe le lendemain à Paris (00:30) (Review Focus 5).
  - `test_classify` : `r` 0,04 et −0,04 → équilibre ; `r` 0,05 → positif et `r` −0,05 → négatif (borne exacte : seul `|r| < 0.05` est un équilibre) ; `r` nul avec `pnl` positif → positif, négatif → négatif, nul → équilibre ; trade ouvert → `None`.
  - `test_stats_do_not_mutate_the_journal`.
- [ ] **Step 2: Lancer** `… -p "test_sessions.py" -v` puis `-p "test_jstats.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter.** `entry_session` réutilise `SESSIONS` et `_local_at` ; `compute_stats` est pure (aucune lecture de fichier).
- [ ] **Step 4: Relancer** (les deux fichiers puis la suite) ; attendu : PASS. **Step 5: Commit** `feat(trader-fx): entry_session et jstats (statistiques du journal)`

### Task 4: ligne de commande, alertes et liste

**Files:**
- Modify: `.claude/skills/trader-fx/journal.py` (ajout de la ligne de commande), `.claude/skills/trader-fx/tests/test_journal.py`

**Interfaces:**
- Consumes: Tasks 1 à 3, `config.load_config`, `config.ConfigError`, `plan` (réutiliser `price_decimals` pour l'affichage), `sessions.PARIS`.
- Produces:
  - `main(argv: list[str] | None = None, deps: dict | None = None) -> int` ; `deps` accepte `now` (callable sans argument, renvoie un `datetime` UTC avec fuseau) et `fetch_rate` (callable `(symbole_yahoo: str) -> float | None`, dernier cours ; par défaut une requête Yahoo v8 minimale via `data.fetch_bars`, échec = `None`).
  - Options communes : `--journal PATH` (défaut `trader/fx/journal.json`), `--config PATH` (défaut `trader/fx/config.json`, absent = valeurs par défaut).
  - Sous-commandes : `open`, `amend`, `close`, `list [--open|--closed]`, `stats [--json]`, `alerts [--out PATH]` (défaut `trader/fx/alerts.json`), `page [--out PATH]` (défaut `trader/fx/journal.html`, rendue en Task 5).
  - `open` : `--symbol S --side haussier|baissier --price P (--lots L | --size Z) [--stop X] [--target Y] [--time T] [--risk-usd R] [--quote-usd-rate Q] [--briefing PATH]` (défaut `trader/fx/briefing.json`). Si le briefing existe et contient, dans `trade_ideas.ideas`, une idée de même symbole ET de même sens, l'idée (copie des champs du spec §4.1) est jointe et fournit stop et cible par défaut ; sinon hors plan (`--stop` obligatoire). Le symbole est mis en majuscules. Taux de conversion : `--quote-usd-rate Q` (valeur en USD d'une unité de la devise de cotation) devient `prices["<COTATION>USD=X"] = Q` ; sans lui, si le risque est incalculable et qu'une paire `USD<cotation>=X` est utile, `deps["fetch_rate"]` est appelé une fois ; son échec n'est pas une erreur (risque inconnu, message d'avertissement d'une ligne, R non calculable).
  - `close` : mêmes règles de taux au cours de clôture ; `--pnl USD` = résultat du courtier.
  - `alerts` écrit `{"v": 1, "updated": ISO UTC, "rules": [...]}` : pour chaque trade `open`, deux règles `{"id": "<id>-stop"|"<id>-cible", "trade_id", "symbol", "type": "stop"|"cible", "side", "level", "decimals"}` (la cible seulement si elle existe) ; `decimals` = `plan.price_decimals(symbol, level)` ; écriture atomique ; aucun champ de résultat, de capital, de taille, de risque ou de note.
  - Messages : confirmation d'une ligne pour `open`/`amend`/`close` (identifiant, symbole, sens, niveaux, risque prévu ou « risque prévu inconnu », résultat et R ou « estimé, hors frais ») ; `list` : une ligne par trade ; `stats` : résumé terminal (`Journal : N trades clôturés, M ouverts`, l'avertissement d'échantillon quand il existe, la ligne globale, une ligne par groupe avec son `n`) ; `stats --json` imprime l'objet `stats` ; toute `JournalError`/`ConfigError`/erreur d'argument : une ligne, code 1, aucun fichier écrit.

- [ ] **Step 1: Écrire les tests (échouent)** (appels de `main` avec des fichiers temporaires, `deps` simulés, sortie capturée) :
  - `test_open_from_briefing_idea_attaches_it` et `test_open_when_side_differs_is_off_plan` ; `test_open_off_plan_needs_stop`.
  - `test_open_cross_without_rate_warns_and_leaves_risk_unknown` (fetch simulé renvoyant `None`) puis `test_open_cross_uses_quote_usd_rate` et `test_open_cross_uses_fetch_rate_once` (compteur d'appels = 1).
  - `test_close_prints_r_and_estimated_flag`, `test_close_without_rate_or_pnl_is_one_line_error_and_file_untouched` (octets du fichier identiques avant et après ; Review Focus 2), `test_close_unknown_trade`.
  - `test_amend_then_close_keeps_initial_risk` (de bout en bout via `main`).
  - `test_corrupt_journal_is_one_line_error_and_untouched` : fichier tronqué, autre version, JSON non-objet (Review Focus 4).
  - `test_list_open_and_closed` ; `test_stats_text_and_json` (`échantillon trop petit pour conclure` présent pour moins de 30 trades ; `--json` = `stats` complet) ; `test_stats_on_empty_journal`.
  - `test_alerts_rules_for_open_trades_only_and_no_financial_fields` : un trade ouvert avec stop et cible → 2 règles ; un clôturé → aucune ; une cible absente → 1 règle ; l'ensemble des clés de chaque règle est exactement `{"id","trade_id","symbol","type","side","level","decimals"}` et aucun champ de premier niveau hors `v`, `updated`, `rules` ; la chaîne JSON ne contient ni `pnl`, ni `risk`, ni `capital`, ni `lots`.
  - `test_time_is_paris_and_stored_utc` (`--time "2026-11-16 09:30"` en hiver → `08:30` UTC ; un même texte en été → `07:30` UTC).
  - `test_config_error_is_one_line` (clé inconnue dans `--config`) ; `test_default_paths_are_relative_to_cwd`.
  - `test_vocabulary_of_all_outputs` : regex en RAW string `\b(achat|acheter|vente|vendre|buy|sell)\b` insensible à la casse sur toutes les sorties, avec contrôle négatif (« survente » ne correspond pas, « un achat » correspond) ; vérifier avec `grep -c $'\x08'` qu'aucun fichier de test ne contient de caractère retour arrière.
- [ ] **Step 2: Lancer** `… -p "test_journal.py" -v` ; attendu : FAIL (nouveaux tests).
- [ ] **Step 3: Implémenter** `main` avec `argparse` (sous-commandes), en réutilisant les fonctions de la Task 2 ; `if __name__ == "__main__": sys.exit(main())` ; reconfigurer stdout et stderr en UTF-8 au début de `main` (comme `fx.py`).
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): ligne de commande du journal, alertes et liste`

### Task 5: page « Journal de trading »

**Files:**
- Create: `.claude/skills/trader-fx/journal_template.html`, `.claude/skills/trader-fx/tests/test_journal_page.py`
- Modify: `.claude/skills/trader-fx/page.py`, `.claude/skills/trader-fx/journal.py` (sous-commande `page`), `.claude/skills/trader-fx/tests/test_page.py` (un test), `.claude/skills/trader-fx/tests/test_journal.py`

**Interfaces:**
- Produces:
  - `page.embed_json(doc, script_id="briefing")` et `page.render_page(doc, template_path, script_id="briefing")` : le comportement actuel est inchangé quand `script_id` est omis (tests existants verts) ; le marqueur reste `<!--BRIEFING_JSON-->` ; `script_id` ne contient que `[a-z-]`, sinon `ValueError`.
  - `journal.py page` : écrit `trader/fx/journal.html` avec `doc = {"as_of": {"iso","paris"}, "journal": <journal>, "stats": <compute_stats>}` et `script_id="journal"`.
  - Gabarit : un seul `<title>` (« Journal de trading »), pas de balises `<html>/<head>/<body>`, mêmes jetons de charte que `report_template.html` (mêmes valeurs dans `:root`, les deux blocs sombres, `color-scheme: dark`, `body` avec fond explicite, marge latérale `max(16px, env(safe-area-inset-*))`, balise `claude:viewport-fit-sides`), le seul lien externe autorisé est la feuille Google Fonts de la charte, aucune requête réseau, valeurs insérées par `textContent` uniquement. Sections (titres en français) : « Résumé » (trades ouverts et clôturés, R total, résultat en USD, avertissement d'échantillon), « Trades ouverts » (symbole, sens, entrée, stop et cible en vigueur, taille, risque prévu, ouverture en heure de Paris), « Statistiques » (cinq familles dans cet ordre : « Réussite et R », « Par règle et par sens », « Par paire, session et jour », « Erreurs », « Capital et drawdown » avec une courbe de capital en SVG simple, `n` à chaque ligne, mention « peu de trades » quand `few`), « Trades clôturés » (entrée, sortie, résultat en USD et en R, étiquette « estimé, hors frais » ou « courtier », étiquettes d'erreur). Zéro trade : message explicite. Le disclaimer de page : « Journal de faits : résultats passés, ni conseil ni prévision. ».

- [ ] **Step 1: Écrire les tests (échouent)** :
  - `test_page.py::test_embed_json_script_id_defaults_to_briefing_and_validates` ; les tests existants restent inchangés.
  - `test_journal_page.py` (exécutions node du script avec le même simulateur DOM que `test_page.py`) : la section « Résumé » avec chiffres exacts d'un journal inventé ; la ligne d'un trade ouvert ; le tableau des cinq familles avec `n` ; `few` affiche « peu de trades » ; l'avertissement d'échantillon ; un résultat estimé porte « estimé, hors frais » et un résultat du courtier « courtier » ; la courbe de capital produit un `svg` avec autant de points que de trades clôturés plus le départ ; zéro trade et `stats` absent ne plantent pas ; texte hostile (`<img onerror=…>`, `</script>`) dans symbole, note, étiquette : aucun élément créé ; les jetons de charte du gabarit sont identiques à ceux de `report_template.html` (comparaison des blocs `:root` et des deux blocs sombres) ; aucune couleur brute hors des blocs de jetons ; contraste ≥ 4,5:1 (texte) et 3:1 (graphique) pour chaque paire utilisée dans les deux thèmes (même assistant WCAG que `test_page.py`) ; aucun emoji, aucune bordure latérale, aucune ombre ; regex de vocabulaire en RAW string `\b(achat|acheter|vente|vendre|buy|sell)\b` avec contrôle négatif et `grep -c $'\x08'` = 0 ; le test réseau (seul `<link>` autorisé : Google Fonts).
  - `test_journal.py::test_page_command_writes_the_page_and_is_one_line_on_error`.
- [ ] **Step 2: Lancer** `… -p "test_journal_page.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** gabarit, `page.py` et la sous-commande. Reprendre le style de `report_template.html` (charte 4884 déjà appliquée) ; ne pas charger de skill de design supplémentaire. Aucun navigateur n'est disponible : vérifier par les tests node et le tableau de contrastes, et le dire dans le rapport.
- [ ] **Step 4: Relancer** la suite complète (aussi sous `python3 -W error`) ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): page Journal de trading`

### Task 6: SKILL.md, essai de bout en bout, vérifications

**Files:**
- Modify: `.claude/skills/trader-fx/SKILL.md`

- [ ] **Step 1: Mettre à jour `SKILL.md`** (français, exact par rapport au code) : section « Journal » (déclarer un trade en une phrase et la commande correspondante ; « donne le résultat du courtier à la clôture » ; stop déplacé ; `list`, `stats`, `alerts`, `page`) ; la liste des fichiers lus et écrits (`journal.json`, `journal.json.bak`, `alerts.json`, `journal.html`) ; le vocabulaire factuel du journal ; les limites (résultat estimé hors frais, swap et glissement ; un seul compte USD ; pas d'import du courtier ; échantillon inférieur à 30 trades) ; la phrase que `alerts.json` ne contient aucun résultat ; la description du frontmatter ajoute « journal de trading », « statistiques de trades », « j'ai pris l'idée », "trading journal", "trade stats".
- [ ] **Step 2: Essai de bout en bout sur un trade fictif** dans un dossier temporaire (jamais sur le vrai journal) : ouvrir un trade depuis une idée du dernier `briefing.json`, `amend` (stop éloigné), `close` avec `--pnl`, `stats`, `alerts`, `page` ; consigner les sorties et vérifier à la main le R et le résultat d'un trade (`pnl_at` contre le calcul manuel). Vérifier que `alerts.json` ne contient aucun champ financier.
- [ ] **Step 3: Générer la page de l'essai** et vérifier la présence des cinq titres de statistiques. Ne pas publier.
- [ ] **Step 4: Suite complète** `python3 -m unittest discover -s .claude/skills/trader-fx/tests -v` (aussi `-W error`) ; attendu : tout PASS, sortie sans avertissement.
- [ ] **Step 5: Commit** `feat(trader-fx): SKILL.md du journal`
