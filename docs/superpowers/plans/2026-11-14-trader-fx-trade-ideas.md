# trader-fx : trades potentiels avec taille de position, plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** une section « Trades potentiels » (page, résumé terminal, `briefing.json`) qui range des idées haussières et baissières avec entrée, stop, cible, rapport gain/risque et taille de position pour un compte de 100 000 USD.

**Architecture:** quatre nouveaux modules purs dans le skill existant (`config.py`, `sizing.py`, `plan.py`, et `find_short_setups` dans `signals.py`), branchés dans `build_briefing` (clé `trade_ideas`), le résumé, `fx.py` (option `--config`) et le gabarit de page. Aucun réseau supplémentaire : les conversions de devises viennent des cours déjà analysés.

**Tech Stack:** Python 3 (bibliothèque standard seulement), `unittest`, gabarit HTML existant (charte 4884).

**Spec:** `docs/superpowers/specs/2026-11-14-trader-fx-trade-ideas-design.md` (complète `2026-11-13-trader-fx-briefing-design.md`).

## Global Constraints

- Python 3, bibliothèque standard seulement ; tests `unittest`, jamais de réseau dans un test.
- Commandes lancées depuis `C:/Users/m.poirat/TRADING`. Modules plats dans `.claude/skills/trader-fx/` ; chaque fichier de test commence par `import _path  # noqa`. Lancer : `python3 -m unittest discover -s .claude/skills/trader-fx/tests -v` (196 tests passent aujourd'hui, sortie sans avertissement).
- Le risque réel d'une idée ne dépasse jamais `risk.per_trade_pct` du capital ; une taille non calculable est `to_confirm`, jamais un chiffre inventé.
- Vocabulaire : « haussier » et « baissier » ; jamais achat, acheter, vente, vendre, buy, sell, gagnant, profit ; aucun chiffre de gain ou de perte potentiel (seulement risque au stop, rapport gain/risque, lots, levier, valeur du pip) ; les idées sont des « plans mécaniques à valider », pas des conseils.
- Configuration invalide : une seule ligne, code de sortie 1, aucun `briefing.json` écrit. `trader/fx/config.json` est exclu de git.
- Résumé terminal : 40 lignes au plus (pire cas testé). Briefing complet en moins de 90 s à froid.
- Chaque message de commit se termine par la ligne `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (ligne vide avant). Ne rien pousser, ne rien publier.

## Review Focus

1. Stop si serré que la taille atteint le plafond de levier : taille réduite, `limited_by = "levier"`, risque réel inférieur au risque fixé (Task 3).
2. Arrondi flottant au multiple exact (500 / 0,0056818… doit donner 88 000 unités, pas 87 000) (Task 3).
3. Symbole avec déclencheurs dans les deux sens, ou ATR nulle ou absente : pas d'idée, listé dans `skipped` (Task 4).
4. Cotation sans paire en dollar dans le briefing, ou instrument absent de la table `contracts` : `to_confirm`, aucun plantage (Task 3).
5. Clé de configuration inconnue, capital en texte, devise de compte non USD : une ligne et code 1, aucun fichier écrit ; un lancement un samedi produit quand même des idées, avec l'avertissement de week-end (Tasks 2 et 5).

---

### Task 1: règles baissières dans signals.py

**Files:**
- Modify: `.claude/skills/trader-fx/signals.py` (ajout de `find_short_setups`, extension de `analyze`)
- Test: `.claude/skills/trader-fx/tests/test_signals.py`

**Interfaces:**
- Produces:
  - `find_short_setups(closes: list[float]) -> tuple[list[str], dict]` : `closes` du plus ancien au plus récent, au moins 30 ; renvoie les clés parmi `breakdown_20d`, `bear_flag`, `lose_ma20`, `overbought`, `overbought_reject` et `{"rsi","rsi_prev","low20","ma20","run_pct","range5_pct"}`.
  - `analyze(...)` ajoute la clé `"setups_short": list[str]` (les autres clés et `find_setups` ne changent pas).

- [ ] **Step 1: Écrire les tests (échouent)** dans `test_signals.py` :
  - `test_breakdown_20d`, `test_bear_flag`, `test_lose_ma20`, `test_overbought`, `test_overbought_reject` : une série synthétique de 30 clôtures par règle, assertion que la clé est présente ; conditions exactes : `breakdown_20d` = dernière clôture sous le minimum des 20 précédentes ; `bear_flag` = `c[-6]/c[-16]-1 < -0.10` et `(max(c[-5:])-min(c[-5:]))/last < 0.05` ; `lose_ma20` = `c[-2] > ma20_prev` et `last < ma20` (`ma20_prev` = moyenne de `c[-21:-1]`) ; `overbought` = RSI 14 > 70 ; `overbought_reject` = RSI de `c[:-1]` > 70 et `last < c[-2]`.
  - `test_no_short_tags_on_a_steadily_rising_series_except_overbought` : une hausse régulière donne `overbought` seulement (ni `breakdown_20d`, ni `bear_flag`, ni `lose_ma20`).
  - `test_find_setups_is_unchanged` : la suite de parité avec `scan.py` existante reste verte (ne pas la modifier).
  - `test_analyze_carries_setups_short` : `analyze` sur une série baissière contient `"setups_short"` avec `breakdown_20d`.
- [ ] **Step 2: Lancer** `python3 -m unittest discover -s .claude/skills/trader-fx/tests -p "test_signals.py" -v` ; attendu : FAIL (`find_short_setups` absent).
- [ ] **Step 3: Implémenter `find_short_setups`** (même structure que `find_setups`, `signals.py:31-54`, conditions inversées ; utiliser `rsi` existant) et ajouter `setups_short` à `analyze`.
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : tout PASS.
- [ ] **Step 5: Commit** `git add .claude/skills/trader-fx && git commit -m "feat(trader-fx): règles baissières miroir (find_short_setups)"`

### Task 2: config.py et config.example.json

**Files:**
- Create: `.claude/skills/trader-fx/config.py`, `.claude/skills/trader-fx/config.example.json`, `.claude/skills/trader-fx/tests/test_config.py`
- Modify: `.gitignore` (ajouter `trader/fx/config.json`)

**Interfaces:**
- Produces:
  - `class ConfigError(Exception)` : le message est une phrase française prête à afficher.
  - `DEFAULTS: dict` : `{"account": {"currency": "USD", "capital": 100000}, "risk": {"per_trade_pct": 0.5, "max_total_pct": 2.0}, "leverage_max": 30, "plan": {"stop_atr_mult": 1.5, "target_r": 2.0}, "ideas": {"max_shown": 5, "max_per_exposure": 2}, "contracts": {}}`.
  - `defaults() -> dict` : copie profonde de `DEFAULTS`.
  - `validate(cfg: dict) -> dict` : fusionne `cfg` sur les valeurs par défaut (section par section) et renvoie une copie validée ; lève `ConfigError`.
  - `load_config(path: str | None) -> dict` : fichier absent ou `path` vide = `defaults()` ; fichier illisible, JSON invalide ou non-objet = `ConfigError`.

- [ ] **Step 1: Écrire les tests (échouent)** dans `test_config.py` :
  - `test_defaults_match_the_spec` : `defaults()` égal au dictionnaire ci-dessus ; muter la copie ne change pas `DEFAULTS`.
  - `test_missing_file_gives_defaults` et `test_partial_override_keeps_other_defaults` (seul `risk.per_trade_pct = 1` fourni : le reste vaut les défauts).
  - `test_rejects` (une assertion `ConfigError` par violation, message contenant le mot-clé) : devise `"EUR"` (« devise de compte »), `capital` 0 ou texte, `per_trade_pct` 0 et 2,5, `max_total_pct` inférieur à `per_trade_pct` et 11, `leverage_max` 0 et 501, `stop_atr_mult` 0,4 et 5,1, `target_r` 0,9 et 5,1, `max_shown` 0 et 11, `max_per_exposure` 0 et 6, clé inconnue (« clé inconnue ») au premier niveau et dans une section, entrée `contracts` sans `step` ou avec `usd_per_point` négatif ou `min` nul.
  - `test_accepts_a_valid_contract_table` : `{"^FCHI": {"usd_per_point": 1.1, "step": 0.1, "min": 0.1}}`.
  - `test_invalid_json_and_non_object_file_raise` (fichiers temporaires).
  - `test_example_file_is_valid` : `load_config("…/config.example.json")` passe et ne contient que des clés connues.
- [ ] **Step 2: Lancer** `… -p "test_config.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter `config.py`** (booléens refusés comme nombres ; bornes du spec §4.4 ; messages en français). `config.example.json` = les défauts plus `contracts` avec `^FCHI` et `GC=F` en valeurs d'exemple et une clé `"_note"` NON acceptée : mettre la mise en garde (« valeurs d'exemple, à vérifier chez le courtier ») dans `SKILL.md` (Task 7), pas dans le JSON.
- [ ] **Step 4: Relancer** ; attendu : PASS. Ajouter la ligne au `.gitignore`.
- [ ] **Step 5: Commit** `feat(trader-fx): config.py et config.example.json`

### Task 3: sizing.py

**Files:**
- Create: `.claude/skills/trader-fx/sizing.py`, `.claude/skills/trader-fx/tests/test_sizing.py`

**Interfaces:**
- Consumes: `strength.pair_currencies(symbol) -> tuple[str, str] | None`, `config.defaults()`.
- Produces (tous renvoient le même dictionnaire `size`, clés toujours présentes) :
  - `size = {"status": "ok"|"too_wide"|"to_confirm", "lots": float|None, "units": int|None, "size": float|None, "risk_usd": float|None, "leverage": float|None, "pip_value_usd_per_lot": float|None, "limited_by": "risque"|"levier"|None, "note": str|None}` (`lots` et `units` pour le forex, `size` pour les autres instruments).
  - `pip_size(quote: str) -> float` : 0,01 si `"JPY"`, sinon 0,0001.
  - `usd_rate(ccy: str, prices: dict[str, float]) -> float | None` : valeur en USD d'une unité de `ccy` : 1 pour USD ; `1 / prices["USD<ccy>=X"]` si présent ; sinon `prices["<ccy>USD=X"]` ; sinon `None`.
  - `size_forex(symbol, entry, stop, prices, capital, risk_pct, leverage_max) -> dict`.
  - `size_contract(symbol, entry, stop, contract, capital, risk_pct, leverage_max) -> dict` (`contract = {"usd_per_point","step","min"}`).
  - `size_idea(symbol, entry, stop, prices, config) -> dict` : forex si `pair_currencies(symbol)`, sinon `config["contracts"].get(symbol)` ou `to_confirm` (note : « taille à confirmer chez le courtier : renseigner contracts dans trader/fx/config.json »).

- [ ] **Step 1: Écrire les tests (échouent)** avec ces valeurs calculées à la main (capital 100 000, `risk_pct` 0,5 donc 500 USD, `leverage_max` 30) :
  - `test_eurusd_50_pips` : entrée 1,1000, stop 1,0950, prix `{"EURUSD=X": 1.10}` → `units == 100000`, `lots == 1.0`, `risk_usd == 500.0`, `leverage == 1.10`, `pip_value_usd_per_lot == 10.0`, `limited_by == "risque"`, `status == "ok"`.
  - `test_usdjpy` : entrée 150,00, stop 149,25, prix `{"USDJPY=X": 150.0}` → `lots == 1.0`, `pip_value_usd_per_lot` proche de 6,6667 (`assertAlmostEqual(…, 4)`), `leverage == 1.0`.
  - `test_cross_converted_through_a_dollar_pair_and_float_floor` : GBPCHF=X entrée 1,1000 stop 1,0950, prix `{"GBPCHF=X": 1.10, "USDCHF=X": 0.88, "GBPUSD=X": 1.30}` → `units == 88000`, `lots == 0.88` (Review Focus 2 : pas 87 000).
  - `test_leverage_cap_reduces_the_size` : EURUSD entrée 1,1000, stop 1,0999 (1 pip), même prix → `limited_by == "levier"`, `units == 2727000`, `risk_usd` ≈ 272,7 (inférieur à 500), `leverage` ≤ 30 (Review Focus 1).
  - `test_stop_too_wide` : EURUSD entrée 2,0, stop 1,0 → `status == "too_wide"`, `lots is None`.
  - `test_rounds_down_never_up` : une taille brute de 99 999 unités donne 99 000.
  - `test_unknown_conversion_is_to_confirm` : GBPZAR=X sans `USDZAR=X` ni `ZARUSD=X` dans les prix → `status == "to_confirm"` (Review Focus 4).
  - `test_contract_table` : `^FCHI`, entrée 8000, stop 7900, contrat `{"usd_per_point": 1.1, "step": 0.1, "min": 0.1}` → `size == 4.5`, `risk_usd == 495.0`, `leverage` ≈ 0,396 (`assertAlmostEqual(…, 3)`).
  - `test_contract_below_min_is_too_wide` et `test_symbol_without_contract_is_to_confirm` (note contenant « à confirmer chez le courtier »).
  - `test_real_risk_never_exceeds_the_budget` : balayage de 40 couples (entrée, stop) pseudo-aléatoires à graine fixe sur trois paires : `risk_usd <= 500.0` toujours.
- [ ] **Step 2: Lancer** `… -p "test_sizing.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter `sizing.py`** selon spec §4.3. Algorithme à ne pas déduire : `units = floor(round(risque_usd / perte_par_unité / 1000, 6)) * 1000` (le `round` à 6 décimales évite 87 999,999…) ; la même règle pour `size` avec `step` ; levier : `valeur = unités × b2u` ; si `valeur > leverage_max × capital`, `units = floor(round(leverage_max × capital / b2u / 1000, 6)) * 1000` ; arrondir les flottants de sortie (`risk_usd` 2 décimales, `leverage` 2, `pip_value_usd_per_lot` 4).
- [ ] **Step 4: Relancer** ; attendu : PASS. **Step 5: Commit** `feat(trader-fx): sizing.py (lots, levier, table de contrats)`

### Task 4: plan.py

**Files:**
- Create: `.claude/skills/trader-fx/plan.py`, `.claude/skills/trader-fx/tests/test_plan.py`

**Interfaces:**
- Consumes: analyses de `signals.analyze` (clés `symbol, name, last, rsi, atr_pct, trend, setups, setups_short`), `sizing.size_idea`, `strength.pair_currencies`, la configuration validée de `config.py`.
- Produces:
  - `LONG_TRIGGERS`, `SHORT_TRIGGERS` (tuples, spec §4.2).
  - `classify(analysis: dict) -> tuple[str | None, list[str], str | None]` : `(side, triggers, reason)` avec `side` `"haussier"`, `"baissier"` ou `None` ; `reason` = `"signaux contradictoires"` quand les deux sens déclenchent, `None` sinon.
  - `score(analysis: dict, side: str, triggers: list[str]) -> tuple[int, list[str]]` : points et lignes « pourquoi ».
  - `exposures(symbol: str, side: str) -> list[tuple[str, str]]` : forex `XXXYYY`, haussier `[("XXX","+"),("YYY","-")]`, baissier l'inverse ; autre instrument `[(symbol, "+" ou "-")]`.
  - `make_plan(analysis: dict, side: str, cfg: dict) -> dict | None` : `{"reference_price","stop","target","rr","atr"}` ; `None` si `atr_pct` absent ou ≤ 0.
  - `build_trade_ideas(analyses: list[dict], config: dict) -> dict` : l'objet `trade_ideas` du spec §4.5 (`reference: "last_close"`, `account`, `ideas`, `skipped`, `total_risk_usd`, `total_risk_pct`, `max_total_pct`, `over_cap`).

- [ ] **Step 1: Écrire les tests (échouent)** :
  - `test_classify` : un déclencheur haussier → `("haussier", [...], None)` ; un baissier → `"baissier"` ; les deux → `(None, [], "signaux contradictoires")` (Review Focus 3) ; `oversold` ou `overbought` seuls (états) → `(None, [], None)`.
  - `test_score_long_and_short` : idée haussière avec 1 déclencheur, tendance `up`, RSI 25 → 2 + 1 + 1 = 4 ; avec RSI 77 et tendance `down` → 2 − 1 − 1 = 0 ; idée baissière avec 2 déclencheurs, tendance `down`, RSI 75 → 4 + 1 + 1 = 6 ; tendance `mixed` ou `None` → 0 point. Lignes « pourquoi » exactes : `"+2 cassure du plus haut 20 j"`, `"+1 tendance haussière"`, `"−1 tendance haussière (à contre-sens)"` (pour une idée baissière sur tendance haussière), `"+1 RSI sous 30 (survente)"`, `"−1 RSI déjà au-dessus de 70"`, `"+1 RSI au-dessus de 70 (surachat)"`, `"−1 RSI déjà sous 30"` (le signe est U+2212).
  - `test_exposures` (EURUSD haussier : `+EUR −USD` ; USDJPY baissier : `−USD +JPY` ; `GC=F`).
  - `test_make_plan_both_sides` : entrée 100,00, `atr_pct` 1,0 (ATR 1,0), `stop_atr_mult` 1,5, `target_r` 2,0 → haussier : stop 98,50, cible 103,00, `rr == 2.0` ; baissier : stop 101,50, cible 97,00.
  - `test_forex_rounding_directions` : EURUSD haussier, le stop est arrondi vers le bas (s'éloigne de l'entrée) et la cible vers le bas (se rapproche), à 5 décimales (3 pour une cotation JPY) ; `test_non_forex_rounds_to_two_decimals`.
  - `test_atr_missing_or_zero_is_skipped` : `skipped` contient `{"symbol", "reason": "ATR indisponible"}` (Review Focus 3).
  - `test_ranking_order_and_tie_break` : égalité de score départagée par le nombre de déclencheurs puis par le symbole, ordre déterministe.
  - `test_diversification_caps_the_same_exposure` : trois idées haussières avec `+USD` (USDJPY, USDCHF, USDCAD) et `max_per_exposure = 2` → la troisième est écartée avec `"corrélée à <symbole de la première idée retenue portant cette exposition>"` ; `test_max_shown_limit` : raison `"au-delà des 5 idées affichées"`.
  - `test_total_risk_and_over_cap` : 5 idées en `ok` à 500 USD → `total_risk_usd == 2500.0`, `total_risk_pct == 2.5`, `over_cap is True` (plafond 2,0) ; une idée en `to_confirm` compte pour le risque prévu (500) ; 3 idées → `over_cap is False`.
  - `test_empty_input` : `ideas == []`, `skipped == []`, `total_risk_usd == 0.0`.
- [ ] **Step 2: Lancer** `… -p "test_plan.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter `plan.py`** selon spec §4.2. Algorithme d'arrondi : pour un symbole forex le pas est 1e-5 (1e-3 si la cotation est JPY), pour les autres 1e-2 ; idée haussière : stop (sous l'entrée, donc arrondi pour s'éloigner d'elle) et cible (au-dessus, arrondie pour s'en rapprocher) tous deux vers le bas (`floor`) ; idée baissière : stop et cible tous deux vers le haut (`ceil`) ; passer par `round(x / pas, 6)` avant `floor`/`ceil` pour éviter les erreurs flottantes. Les prix `prices` passés à `sizing.size_idea` sont `{a["symbol"]: a["last"]}` pour les analyses dont `strength.pair_currencies` n'est pas `None`.
- [ ] **Step 4: Relancer** ; attendu : PASS. **Step 5: Commit** `feat(trader-fx): plan.py (idées, score, diversification, entrée/stop/cible)`

### Task 5: briefing.py, fx.py et résumé

**Files:**
- Modify: `.claude/skills/trader-fx/briefing.py`, `.claude/skills/trader-fx/fx.py`
- Test: `.claude/skills/trader-fx/tests/test_briefing.py`

**Interfaces:**
- Consumes: `config.load_config`, `config.defaults`, `config.ConfigError`, `plan.build_trade_ideas`, `signals.analyze` (clé `setups_short`).
- Produces:
  - `briefing.has_setup(analysis: dict) -> bool` : `bool(a["setups"] or a["setups_short"])` ; remplace les deux tests `a["setups"]` (`briefing.py:108` et `fx.py:101`).
  - `_hit(a)` ajoute la clé `setups_short` ; `swing.hits` = analyses avec `has_setup`.
  - `build_briefing(universe, daily, failed, hourly, calendar, now_utc, extra_warnings=(), config=None)` : `config=None` donne les valeurs par défaut ; ajoute la clé `trade_ideas` (sortie de `plan.build_trade_ideas(analyses, cfg)`). Dans `briefing.py`, importer le module sous le nom `fxconfig` (`import config as fxconfig`) pour que le paramètre `config` ne le masque pas.
  - `fx.py brief` accepte `--config PATH` (défaut `trader/fx/config.json`) ; la configuration est chargée avant tout accès réseau ; une `ConfigError` donne `_fail(str(e))`, code 1, aucun fichier écrit.
  - `render_summary(b)` : ajoute un bloc d'idées (8 lignes au plus) après les lignes du calendrier.

- [ ] **Step 1: Écrire les tests (échouent)** :
  - `test_trade_ideas_key_and_shape` : `build_briefing(...)` contient `trade_ideas` avec les clés du spec §4.5 ; l'ensemble des clés de premier niveau devient `{"as_of","market_state","counts","data_age","calendar","strength","swing","day_plan","trade_ideas","warnings","disclaimer"}` (mettre à jour le test d'ensemble de clés existant).
  - `test_hits_include_short_only_setups` et `test_has_setup`.
  - `test_saturday_run_still_gives_ideas_with_the_weekend_warning` (`--now "2026-11-14 10:00"`, séries synthétiques) : `trade_ideas.reference == "last_close"`, `market_state == "closed_weekend"`, l'avertissement de week-end est présent (Review Focus 5).
  - `test_custom_config_changes_sizes` : `config` avec `risk.per_trade_pct = 1.0` double le risque d'une idée `ok`.
  - `test_main_config_error_returns_1_and_writes_nothing` : fichier de configuration avec une clé inconnue, puis capital en texte, puis devise `"EUR"` ; code 1, une seule ligne imprimée, `briefing.json` absent (Review Focus 5) ; `test_main_default_config_path_is_trader_fx_config_json`.
  - `test_summary_idea_block` : avec 3 idées, le résumé contient `Idées de trade (3), plan mécanique à valider :`, une ligne par idée avec le sens, `entrée`, `stop`, `cible`, les lots ou « taille à confirmer » ou « stop trop large », et `Risque cumulé : <USD> USD (<pct> %) sur 2.0 % autorisés` (suffixe « : dépassé » si `over_cap`) ; zéro idée : `Idées de trade : aucune`.
  - `test_summary_worst_case_stays_within_40_lines` (étendre le test existant avec 6 idées, des échecs, des avertissements et 10 événements).
  - `test_summary_and_json_have_no_forbidden_words` : regex `(?i)\b(achat|acheter|vente|vendre|buy|sell|gagnant|profit)\b` sur le résumé ; aucune clé ni valeur de gain.
- [ ] **Step 2: Lancer** `… -p "test_briefing.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** : le bloc d'idées du résumé réserve `IDEA_LINES = 8` ; chaque idée tient sur une ligne ≤ 150 caractères (`_cut`) ; au-delà de 6 idées, ajouter `  ... et N autres (voir briefing.json)` ; le budget des setups swing (`_hit_lines`) diminue d'autant.
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): trade_ideas dans le briefing, option --config, bloc du résumé`

### Task 6: section « Trades potentiels » dans la page

**Files:**
- Modify: `.claude/skills/trader-fx/report_template.html`, `.claude/skills/trader-fx/tests/test_page.py`, `.claude/skills/trader-fx/tests/fixtures/briefing_sample.json`

**Interfaces:**
- Consumes: `briefing.json` avec `trade_ideas` et `swing.hits[].setups_short`.
- Produces: section `id="s-ideas"` (titre « Trades potentiels ») placée entre l'en-tête et « Résumé » ; fonction `renderIdeas(b)` dans le script ; libellés `breakdown_20d` « Cassure du plus bas 20 j », `bear_flag` « Drapeau baissier », `lose_ma20` « Perte de la moyenne 20 j », `overbought` « Surachat », `overbought_reject` « Rejet depuis le surachat ». Le tableau « Setups swing » affiche `setups` et `setups_short` ensemble.

- [ ] **Step 1: Mettre à jour la fixture** `briefing_sample.json` (générée par un `build_briefing` à données synthétiques, comme les autres fixtures) avec 3 idées (une `ok`, une `to_confirm`, une `too_wide`), un `skipped`, `over_cap` faux puis une variante vraie en test.
- [ ] **Step 2: Écrire les tests (échouent)** dans `test_page.py` (exécutions node du script, comme les tests existants) :
  - `test_ideas_section_is_between_header_and_resume` (ordre dans le HTML) et `test_ideas_heading_and_note` : texte exact « Idées de plan mécaniques, issues des règles ci-dessous. À valider, pas des conseils. Prix de référence : dernière clôture. ».
  - `test_idea_card_shows_the_four_numbers_and_why` : symbole, « Haussier »/« Baissier », entrée, stop, cible, taille (lots et unités), risque maximal en USD, `1:2`, levier, valeur du pip, lignes « pourquoi ».
  - `test_to_confirm_and_too_wide_messages` : « Taille à confirmer chez le courtier » et « Stop trop large pour le risque fixé ».
  - `test_total_risk_line_and_over_cap_banner` : « Risque cumulé » ; bandeau présent seulement si `over_cap`.
  - `test_skipped_ideas_listed_with_reason`.
  - `test_zero_ideas_message` : « Aucune idée de trade sur cette analyse. » et absence de plantage quand `trade_ideas` est absent (anciens `briefing.json`).
  - `test_hostile_text_in_idea_fields_is_not_executed` (titre ou raison contenant `<img onerror=…>` et `</script>` : aucun élément créé).
  - `test_new_setup_labels_in_swing_table` et `test_template_has_no_forbidden_words` (regex `(?i)\b(achat|acheter|vente|vendre|buy|sell|gagnant|profit)\b` sur le gabarit et le rendu de la fixture) ; le test réseau reste inchangé et vert.
- [ ] **Step 3: Lancer** `… -p "test_page.py" -v` ; attendu : FAIL.
- [ ] **Step 4: Implémenter** gabarit et script : cartes dans la charte 4884 déjà en place (jetons existants, pas d'emoji, pas de bordure latérale, or en accent seulement ; le sens se lit par le mot, pas par la couleur seule) ; toutes les valeurs insérées par `textContent` ; chaque rendu de section reste dans son `try/catch`. Charger le skill `artifact-design` avant d'écrire le HTML.
- [ ] **Step 5: Relancer** la suite complète ; attendu : PASS (et sans avertissement). **Step 6: Commit** `feat(trader-fx): section Trades potentiels dans la page`

### Task 7: SKILL.md, essai en direct et vérifications

**Files:**
- Modify: `.claude/skills/trader-fx/SKILL.md`

- [ ] **Step 1: Mettre à jour `SKILL.md`** (français) : section « Trades potentiels » (règles haussières et baissières, classement, diversification, plan, taille) ; section « Configuration » (`trader/fx/config.json`, valeurs par défaut, `--config`, exemple de table `contracts` avec la mise en garde « valeurs d'exemple, à vérifier chez le courtier ») ; limites (cours Yahoo retardés, prix de référence = dernière clôture à revalider, lot de 100 000 unités et valeur du pip à vérifier chez le courtier, pas de swap ni de spread, devise de compte USD seulement) ; la description (frontmatter) ajoute les déclencheurs « trades potentiels », « taille de position », « idées de trade », "trade ideas", "position size".
- [ ] **Step 2: Essai en direct à froid** (sans fichier de configuration, valeurs par défaut) : `rm -rf trader/fx/cache && time python3 .claude/skills/trader-fx/fx.py brief` ; attendu : code 0, au plus 40 lignes, bloc « Idées de trade », moins de 90 s ; consigner le nombre d'idées, leur sens, leurs statuts et le risque cumulé.
- [ ] **Step 3: Vérifier la conversion** (spec §7) : dans `briefing.json`, lister les idées forex en `to_confirm` et la cause ; vérifier à la main, sur une idée `ok`, `risk_usd <= 500`, `lots` multiple de 0,01, et que le levier annoncé est ≤ 30 ; signaler toute paire sans conversion.
- [ ] **Step 4: Générer la page** `python3 .claude/skills/trader-fx/fx.py page` ; vérifier la présence de la section et du titre « Trades potentiels ». Ne pas publier.
- [ ] **Step 5: Suite complète** `python3 -m unittest discover -s .claude/skills/trader-fx/tests -v` ; attendu : tout PASS, sortie sans avertissement.
- [ ] **Step 6: Commit** `feat(trader-fx): SKILL.md des trades potentiels` (ne pas committer `trader/fx/briefing.*` ni `config.json`, déjà ignorés).
