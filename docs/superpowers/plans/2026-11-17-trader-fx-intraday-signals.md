# trader-fx : signaux en séance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Le serveur d'alertes détecte en séance cinq familles de signaux sur barres de 15 min et envoie sur Telegram jusqu'à 10 alertes par jour, avec un plan saisissable à la main dans MT5.

**Architecture:** Trois modules nouveaux à fonctions pures (`intraday_signals.py` : détection ; `intraday_plan.py` : plan, score, sélection ; `intraday_run.py` : orchestration d'un lancement) branchés dans `alerts_run.py` après les idées du briefing. Le contexte journalier (ATR, tendance) vient du briefing déjà relancé à chaque lancement (nouvelle clé `daily_context`), pas d'une requête de plus. L'état de déduplication étend `alert_state.py`.

**Tech Stack:** Python 3 standard, `unittest`, Yahoo (barres 15 min), Telegram, GitHub Actions (déjà en place).

**Spec:** `docs/superpowers/specs/2026-11-17-trader-fx-intraday-signals-design.md`

## Global Constraints

- Python 3 standard seulement, aucune dépendance ; tests `unittest` sans réseau (faux Telegram, fausses barres, faux calendrier, heure injectée).
- Barres : tuples `(ts_utc_secondes, open, high, low, close)` de `data.Series.bars`, début de barre ; une barre est clôturée quand `ts + 900 <= now`. Aucune lecture d'une barre non clôturée.
- Cron inchangé (`7,22,37,52 7-21 * * 1-5` UTC) ; un lancement reste sous `timeout-minutes: 10`.
- Plafonds : 3 alertes de signal par lancement, 10 par jour UTC (limite dure). Les alertes d'idées du briefing gardent leur plafond de 3.
- Plan caduc 30 minutes après la **clôture** de la barre du signal. Zone de validité : entrée ± 0,25 R dans le sens du trade.
- Vocabulaire : « haussier » / « baissier » ; jamais achat, acheter, vente, vendre, buy, sell, « à prendre », prévision, gagnant, profit. Chaque message dit « Plan mécanique à valider, pas un conseil. Prix Yahoo, retardé. » et tient sous 4 096 caractères.
- Taille jamais inventée : non calculable = « Taille à confirmer chez le courtier. » Le risque en USD est affiché (messages Telegram privés) ; aucun fichier commité ne contient de capital.
- Aucun ordre, aucune liaison avec MT5 : l'utilisateur saisit chaque ordre à la main (règle FundedNext).
- Chaque famille de signal est une fonction pure `(bars, i, …)` réutilisable par le futur rejeu historique.
- Les messages de commit se terminent par la ligne `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Tests : `python3 -m unittest discover -s .claude/skills/trader-fx/tests -p "<fichier>" -v` depuis la racine du dépôt ; suite complète sans `-p` (704 tests verts au départ).

## Review Focus

1. Série courte ou trouée (moins de barres que la période, doublons, horodatages non croissants) : aucune exception, aucun signal. → Tâches 3, 5, 6.
2. Série plate (écart-type 0, ATR 0, RSI 100) : aucun signal, aucune division par zéro. → Tâches 3, 5, 8.
3. Changement d'heure : plages de Londres et de New York correctes en été, en hiver et la semaine où l'Europe et les États-Unis ne changent pas le même jour. → Tâches 3, 4.
4. Instrument hors forex (or, indice) : alerte envoyée avec « Taille à confirmer » ; indice dont la séance est fermée (dernière barre vieille de plus de 30 min) : aucune alerte. → Tâches 8, 12.
5. Lancement en retard ou rejoué (échec Telegram, même barre vue deux fois) : jamais de doublon après envoi, renvoi tant que le plan n'est pas caduc, rien après. → Tâches 12, 13.

---

### Task 1: Section `intraday` de la configuration

**Files:**
- Modify: `.claude/skills/trader-fx/config.py`
- Test: `.claude/skills/trader-fx/tests/test_config.py`

**Interfaces:**
- Produces: `config.INTRADAY_FAMILIES = ("session_break", "bb_return", "fractal_break", "engulfing", "rsi_exit")` (ordre de priorité) ; `config.validate(...)["intraday"]` : dict avec les clés et défauts ci-dessous. `DEFAULTS["intraday"]` les porte.

| clé | défaut | bornes |
| --- | --- | --- |
| `enabled` | `True` | booléen |
| `symbols` | `[]` | liste de str ; vide = tout le contexte du briefing |
| `mt5_symbols` | `{}` | dict str vers str non vide |
| `families` | les cinq | sous-ensemble non vide de `INTRADAY_FAMILIES` |
| `range_minutes` | `30` | entier, multiple de 15, 15 à 120 |
| `break_window_hours` | `3` | nombre, 1 à 6 |
| `bb_period` / `bb_std` | `20` / `2.0` | entier 5 à 100 / nombre 1 à 4 |
| `rsi_period` / `rsi_low` / `rsi_high` | `14` / `30` / `70` | entier 5 à 50 / nombre 5 à 50 / nombre 50 à 95 |
| `engulfing_min_prior` | `3` | entier 1 à 6 |
| `min_stop_pct` | `0.05` | nombre, > 0 et <= 1 |
| `max_stop_daily_atr` | `1.0` | nombre, > 0 et <= 5 |
| `min_rr` | `1.0` | nombre, 0,5 à 5 |
| `score_per_signal` / `score_trend` / `window_bars` | `2` / `1` / `4` | entier 1 à 5 / entier 0 à 3 / entier 1 à 12 |
| `max_age_minutes` | `30` | entier 15 à 120 |
| `validity_r` | `0.25` | nombre, > 0 et <= 1 |
| `max_per_run` / `max_per_day` / `max_per_exposure` | `3` / `10` / `2` | entier 1 à 10 / 1 à 50 / 1 à 5 |
| `cooldown_minutes` | `120` | entier 0 à 720 |
| `min_score` | `None` | `None` ou entier |

- [ ] **Step 1: Write the failing tests** in `test_config.py`: `test_intraday_defaults` (chaque valeur du tableau), `test_intraday_unknown_key_refused` (message « clé inconnue intraday.xxx »), `test_intraday_bounds` (une valeur hors bornes par clé numérique lève `ConfigError`), `test_intraday_families_must_be_known_and_non_empty`, `test_intraday_mt5_symbols_must_map_str_to_non_empty_str`, `test_intraday_min_score_accepts_none_and_int_but_not_float`, `test_intraday_enabled_must_be_bool`, `test_intraday_range_minutes_multiple_of_15`.
- [ ] **Step 2: Run** `-p "test_config.py"` : FAIL (clé `intraday` inconnue).
- [ ] **Step 3: Implement** dans `config.py` : `INTRADAY_FAMILIES`, `DEFAULTS["intraday"]`, et un bloc de validation dans `validate` avec `_section(cfg, "intraday")` puis `_num` pour les bornes ; messages d'erreur dans le style existant (une phrase française nommant la clé).
- [ ] **Step 4: Run** `-p "test_config.py"` : PASS ; puis la suite complète : verte.
- [ ] **Step 5: Commit** `feat(trader-fx): section intraday de la configuration`.

### Task 2: `daily_context` dans le briefing

**Files:**
- Modify: `.claude/skills/trader-fx/briefing.py` (fonction `build_briefing`, dict retourné)
- Test: `.claude/skills/trader-fx/tests/test_briefing.py`

**Interfaces:**
- Produces: `briefing["daily_context"]` : `{symbole: {"name": str, "last": float, "atr_pct": float, "trend": "up"|"down"|"mixed"|None}}` pour **chaque** analyse (pas seulement les symboles à règle).

- [ ] **Step 1: Write the failing test** `test_daily_context_covers_every_analysed_symbol` : avec la fixture existante, `set(b["daily_context"]) == {a["symbol"] for a in analyses}` et, pour EURUSD=X, `last`, `atr_pct`, `trend` égaux à ceux de `signals.analyze`.
- [ ] **Step 2: Run** `-p "test_briefing.py"` : FAIL (`KeyError: 'daily_context'`).
- [ ] **Step 3: Implement** : dans `build_briefing`, `"daily_context": {a["symbol"]: {k: a[k] for k in ("name", "last", "atr_pct", "trend")} for a in analyses}`.
- [ ] **Step 4: Run** la suite complète (la page, `briefing_run` et les tests de gabarit doivent rester verts ; sinon corriger le test fautif sans retirer la clé).
- [ ] **Step 5: Commit** `feat(trader-fx): contexte journalier de tous les symboles dans le briefing`.

### Task 3: Fondations des signaux et heures d'ouverture de session

**Files:**
- Modify: `.claude/skills/trader-fx/sessions.py`
- Create: `.claude/skills/trader-fx/intraday_signals.py`, `.claude/skills/trader-fx/tests/intraday_helpers.py`
- Test: `.claude/skills/trader-fx/tests/test_sessions.py`, `.claude/skills/trader-fx/tests/test_intraday_signals.py`

**Interfaces:**
- Produces: `sessions.open_utc(name: str, now_utc: datetime) -> datetime` (ouverture UTC de la session `name`, clé de `SESSIONS`, à la date locale de `now_utc` dans le fuseau de la session) ; `intraday_signals.BAR_S = 900` ; `FAMILIES` (= `config.INTRADAY_FAMILIES`) ; `closed_bars(bars, now_utc) -> list` (triées, sans doublon de `ts`, seulement `ts + BAR_S <= now`) ; `atr_bars(bars, i, n=14) -> float | None` (ATR de Wilder des vraies amplitudes jusqu'à la barre `i` incluse ; `None` sous `n + 1` barres) ; `bollinger(bars, i, period, std) -> (mid, upper, lower) | None` (écart-type de population des `period` dernières clôtures finissant en `i` ; `None` si série courte ou écart-type nul) ; `signal_params(config) -> dict` (= `config["intraday"]` plus `stop_atr_mult` et `target_r` de `config["plan"]`). Dans `tests/intraday_helpers.py` : `make_bars(start_utc: datetime, ohlc: list[tuple]) -> list` (barres consécutives de 900 s) et `utc(y, m, d, h, mi=0) -> datetime`.
- Un **signal** est un dict `{"family", "side" ("haussier"|"baissier"), "i", "stop_raw": float, "target_raw": float | None, "detail": str}` ; l'entrée est la clôture de la barre `i`.

- [ ] **Step 1: Write the failing tests.** `test_sessions.py` : `open_utc("London", 2026-11-16 12:00 UTC) == 2026-11-16 08:00 UTC` ; même appel en `2026-07-15` donne 07:00 UTC ; `open_utc("New York", 2026-11-16)` donne 13:00 UTC ; `open_utc("New York", 2026-10-28)` donne 12:00 UTC et `open_utc("London", 2026-10-28)` donne 08:00 UTC (semaine du décalage Europe/États-Unis). `test_intraday_signals.py` : `closed_bars` écarte la barre en cours (`ts + 900 > now`), trie des `ts` désordonnés, retire un doublon ; `atr_bars` renvoie `None` sous 15 barres et 0,0 sur une série plate ; `bollinger` renvoie `None` sous `period` barres et sur une série plate, et sinon `mid` égal à la moyenne des clôtures.
- [ ] **Step 2: Run** les deux fichiers : FAIL (fonctions absentes).
- [ ] **Step 3: Implement** les fonctions aux signatures ci-dessus (`open_utc` s'appuie sur `_local_at` et `SESSIONS`). `signal_params` ne valide rien : la configuration l'est déjà.
- [ ] **Step 4: Run** les deux fichiers : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): fondations des signaux en séance et ouverture de session en UTC`.

### Task 4: Plages de session et cassure (`session_break`)

**Files:**
- Modify: `.claude/skills/trader-fx/intraday_signals.py`
- Test: `.claude/skills/trader-fx/tests/test_intraday_signals.py`

**Interfaces:**
- Consumes: Task 3.
- Produces: `session_ranges(bars, now_utc, params) -> list[dict]`, un dict `{"name": "Asie"|"Londres"|"New York", "day": "AAAA-MM-JJ", "start": ts, "end": ts, "high": float, "low": float}` par plage ayant au moins une barre : Asie `[00:00, 07:00)` UTC du jour de `now_utc` ; Londres et New York `[open_utc, open_utc + range_minutes)`. `session_break(bars, i, ranges, params) -> dict | None`.

Règle : signal sur la barre `i` quand `ts_i >= end`, `ts_i + BAR_S <= end + break_window_hours * 3600`, la clôture est hors plage, et **aucune** barre entre `end` et `i - 1` n'a déjà clôturé de ce côté ; `stop_raw` = l'autre bord de la plage, `target_raw = None`, `detail` = nom de la plage.

- [ ] **Step 1: Write the failing tests** (Londres, 2026-11-16, plage 08:00-08:30 UTC, hauts 1.1010 et 1.1012, bas 1.0990 et 1.0995) : `test_london_range_values` (high 1.1012, low 1.0990) ; `test_break_up_on_first_close_outside` (barre 08:30 clôture 1.1020 : haussier, `stop_raw == 1.0990`, `detail == "Londres"`) ; `test_second_close_outside_gives_no_signal` (08:45 clôture 1.1025 : `None`) ; `test_close_inside_gives_none` ; `test_break_down_mirror` (baissier, `stop_raw == 1.1012`) ; `test_window_closes_after_three_hours` (la barre 11:15 signale, la barre 11:30 non) ; `test_asia_range_uses_00_to_07_utc` ; `test_ranges_follow_dst` (le même test en 2026-07-15 place la plage de Londres à 07:00-07:30 UTC ; le 2026-10-28 celle de New York à 12:00-12:30 UTC).
- [ ] **Step 2: Run** : FAIL.
- [ ] **Step 3: Implement** `session_ranges` et `session_break` ; une plage sans barre est omise, jamais une erreur.
- [ ] **Step 4: Run** : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): plages de session et signal session_break`.

### Task 5: `bb_return` et `rsi_exit`

**Files:**
- Modify: `.claude/skills/trader-fx/intraday_signals.py`
- Test: `.claude/skills/trader-fx/tests/test_intraday_signals.py`

**Interfaces:**
- Consumes: Task 3 (`bollinger`, `atr_bars`), `signals.rsi(closes, n)`.
- Produces: `bb_return(bars, i, params) -> dict | None` ; `rsi_exit(bars, i, params) -> dict | None`.

Règles : `bb_return` baissier si la clôture de `i - 1` est au-dessus de la bande haute calculée en `i - 1` et celle de `i` n'y est plus (bande calculée en `i`) ; haussier en miroir sous la bande basse ; `stop_raw` = plus haut (baissier) ou plus bas (haussier) de la barre `i - 1` ; `target_raw` = bande du milieu en `i`. `rsi_exit` haussier si RSI(`i - 1`) < `rsi_low` et RSI(`i`) >= `rsi_low` ; baissier si RSI(`i - 1`) > `rsi_high` et RSI(`i`) <= `rsi_high` ; `stop_raw` = clôture ∓ `stop_atr_mult` × `atr_bars(bars, i)`, `target_raw = None` ; `None` si l'ATR est indisponible ou nul.

- [ ] **Step 1: Write the failing tests** : `test_bb_return_bearish` (série où la barre `i - 1` clôture au-dessus de la bande haute à 20 périodes et 2 σ et la barre `i` y rentre : baissier, `stop_raw` = haut de `i - 1`, `target_raw == bollinger(bars, i, 20, 2.0)[0]`) ; `test_bb_return_bullish_mirror` ; `test_bb_still_outside_gives_none` (la barre `i` reste hors bande) ; `test_bb_short_or_flat_series_gives_none` ; `test_rsi_exit_bullish` (série baissière puis une barre de rebond : RSI passe de moins de 30 à 30 ou plus ; `stop_raw` = clôture − 1,5 ATR) ; `test_rsi_exit_bearish_mirror` ; `test_rsi_staying_in_zone_gives_none` ; `test_rsi_short_series_gives_none` (moins de `rsi_period + 2` clôtures) ; `test_rsi_flat_series_gives_none` (RSI 100 constant : pas de sortie de zone, pas de signal).
- [ ] **Step 2: Run** : FAIL.
- [ ] **Step 3: Implement** les deux fonctions.
- [ ] **Step 4: Run** : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): signaux bb_return et rsi_exit`.

### Task 6: `engulfing`, `fractal_break` et `detect_all`

**Files:**
- Modify: `.claude/skills/trader-fx/intraday_signals.py`
- Test: `.claude/skills/trader-fx/tests/test_intraday_signals.py`

**Interfaces:**
- Consumes: Tâches 3 et 4.
- Produces: `engulfing(bars, i, params) -> dict | None` ; `fractal_break(bars, i, params) -> dict | None` ; `detect_all(bars, i, ranges, params) -> list[dict]` (les signaux de chaque famille de `params["families"]` en `i`, dans l'ordre de `FAMILIES`).

Règles : `engulfing` haussier si la barre `i` est haussière (clôture > ouverture), la barre `i - 1` baissière, le corps de `i` contient celui de `i - 1`, et les `engulfing_min_prior` barres `i - k .. i - 1` sont toutes baissières ; `stop_raw` = plus bas de `i` ; miroir pour baissier (`stop_raw` = plus haut de `i`) ; `target_raw = None`. `fractal_break` : fractale de Williams haute en `k` si `high_k` dépasse strictement les hauts de `k - 2, k - 1, k + 1, k + 2` ; **confirmée** quand `k + 2 <= i - 1` ; cherchée sur les 50 dernières barres ; haussier si la clôture `i` dépasse le plus récent haut de fractale confirmé et qu'aucune clôture de `k + 3` à `i - 1` ne l'avait déjà dépassé ; `stop_raw` = bas de la dernière fractale basse confirmée si elle est sous la clôture, sinon clôture − `stop_atr_mult` × ATR ; miroir pour baissier ; `target_raw = None`.

- [ ] **Step 1: Write the failing tests** : `test_engulfing_bullish`, `test_engulfing_bearish`, `test_engulfing_needs_three_prior_opposite_bars` (deux barres seulement : `None`), `test_engulfing_body_must_contain_previous_body`, `test_fractal_break_up` (fractale haute à `k`, barres de confirmation, puis clôture au-dessus : haussier, `stop_raw` = dernière fractale basse), `test_fractal_unconfirmed_is_ignored` (clôture au-dessus d'un sommet vieux de moins de 2 barres : `None`), `test_fractal_already_broken_gives_none`, `test_fractal_without_opposite_fractal_uses_atr_stop`, `test_fractal_mirror_down`, `test_short_series_give_none_for_both`, `test_detect_all_orders_by_family_priority_and_honours_params_families`.
- [ ] **Step 2: Run** : FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run** : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): signaux engulfing et fractal_break, detect_all`.

### Task 7: Du signal au plan

**Files:**
- Create: `.claude/skills/trader-fx/intraday_plan.py`
- Test: `.claude/skills/trader-fx/tests/test_intraday_plan.py`

**Interfaces:**
- Consumes: `plan.price_decimals`, `plan._round_dir`, `plan._sides_ok`, `plan.LONG`, `plan.SHORT`.
- Produces: `make_signal_plan(symbol, side, close, stop_raw, target_raw, daily_atr, params) -> tuple[dict | None, str | None]`. Succès : `({"reference_price", "stop", "target", "rr", "decimals", "limit_price"}, None)` ; échec : `(None, raison)`. Raisons exactes : `"plan impossible"`, `"stop trop proche"`, `"stop trop large"`, `"rapport 1:R sous le minimum"`, `"ATR journalier indisponible"`.

Règles : `decimals = plan.price_decimals(symbol, close)` ; entrée = `round(close, decimals)` ; stop arrondi en s'éloignant de l'entrée ; `dist = |entrée − stop|` arrondie ; cible = `target_raw` arrondie en se rapprochant de l'entrée, ou, si `None`, entrée ± `target_r` × `dist` arrondie en se rapprochant ; `rr = round(|cible − entrée| / dist, 2)` ; `limit_price` = entrée ± `validity_r` × `dist`, arrondi en se rapprochant de l'entrée (plus haut pour haussier). Gardes dans l'ordre : `_sides_ok` ; `dist / entrée × 100 < min_stop_pct` ; `dist > max_stop_daily_atr × daily_atr` ; `rr < min_rr` ; `daily_atr` absent ou nul : `"ATR journalier indisponible"` en premier.

- [ ] **Step 1: Write the failing tests** (EURUSD=X, `min_stop_pct` 0.05, `max_stop_daily_atr` 1.0, `min_rr` 1.0, `target_r` 2.0, `validity_r` 0.25) : `test_long_with_range_stop_and_2r_target` (close 1.10200, stop_raw 1.09900, `daily_atr` 0.0070 : entrée 1.10200, stop 1.09900, cible 1.10800, `rr` 2.0, `limit_price` 1.10275) ; `test_short_mirror` ; `test_target_raw_is_used_and_rounded_toward_entry` (cible 1.10560 : `rr` 1.2) ; `test_jpy_pair_uses_three_decimals` ; `test_stop_too_close_rejected` (stop à 0,03 %) ; `test_stop_too_wide_rejected` (stop à 1,5 ATR journalier) ; `test_rr_below_minimum_rejected` (cible_raw à 0,5 R) ; `test_wrong_side_target_is_impossible` (cible du mauvais côté) ; `test_missing_or_zero_daily_atr` ; `test_gold_and_index_use_magnitude_decimals` (`GC=F`, `^FCHI`).
- [ ] **Step 2: Run** : FAIL.
- [ ] **Step 3: Implement** `make_signal_plan` en réutilisant les helpers de `plan.py` (pas de recopie des arrondis).
- [ ] **Step 4: Run** : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): plan d'un signal en séance (arrondis, gardes, zone de validité)`.

### Task 8: Score et candidat par symbole

**Files:**
- Modify: `.claude/skills/trader-fx/intraday_plan.py`
- Test: `.claude/skills/trader-fx/tests/test_intraday_plan.py`

**Interfaces:**
- Consumes: Tâches 3 à 7, `sizing.size_idea`, `plan.exposures`, `strength.pair_currencies`.
- Produces: `scan_symbol(symbol, name, bars, ranges, ctx, config, prices, now_utc) -> tuple[dict | None, str | None]`. `ctx` = `daily_context[symbol]` ; `prices` = `{paire forex: dernière clôture journalière}` (pour la conversion USD de la taille). Candidat : `{"symbol", "display_name", "side", "score", "why": [str], "families": [str], "primary": str, "detail": str, "bar_ts": int, "bar_iso": str, "plan": dict, "size": dict, "exposures": list}`. `display_name` = `config["intraday"]["mt5_symbols"].get(symbol)` sinon `name`. Raison de refus sinon (`"signaux contradictoires"`, la raison de `make_signal_plan`, `"aucun signal récent"`, `"plan caduc"`).

Règles : `bars = closed_bars(...)` ; `daily_atr = ctx["last"] * ctx["atr_pct"] / 100` (`None` si `atr_pct` est `None`), passé à `make_signal_plan` ; `ranges` est calculé par l'appelant (`session_ranges` sur les barres clôturées) ; signaux de chaque famille sur les `window_bars` dernières barres clôturées ; barre du signal le plus récent `j` : `now − (ts_j + 900) <= max_age_minutes × 60`, sinon `"plan caduc"` ; deux sens présents dans la fenêtre : `"signaux contradictoires"` ; signal primaire = celui de la barre `j` de plus haute priorité ; score = `score_per_signal` par famille concordante distincte de la fenêtre, plus `score_trend` si `ctx["trend"]` va dans le sens (`up` pour haussier), moins `score_trend` à contre-sens, 0 si `mixed` ou `None` ; `why` en lignes `"+2 session_break (Londres)"` et `"+1 tendance haussière"`.

- [ ] **Step 1: Write the failing tests** : `test_single_signal_scores_2_plus_trend` (+1 avec tendance, −1 à contre-sens, 0 si `mixed`) ; `test_two_concordant_families_score_4_and_list_both` ; `test_opposite_signal_in_window_cancels` ; `test_signal_older_than_30_minutes_is_stale` (la barre `j` close depuis 31 min : `(None, "plan caduc")`) ; `test_no_signal_returns_no_recent_signal` ; `test_plan_rejection_reason_is_propagated` ; `test_flat_series_gives_no_candidate_without_error` (ATR nul) ; `test_gold_without_contract_keeps_candidate_with_to_confirm_size` ; `test_display_name_uses_mt5_table`.
- [ ] **Step 2: Run** : FAIL.
- [ ] **Step 3: Implement** `scan_symbol` ; une exception arithmétique sur un symbole le refuse seul (`"calcul impossible (<type>)"`).
- [ ] **Step 4: Run** : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): score et candidat d'alerte par symbole`.

### Task 9: État : déduplication, repos, compteur du jour

**Files:**
- Modify: `.claude/skills/trader-fx/alert_state.py`
- Test: `.claude/skills/trader-fx/tests/test_alert_state.py`

**Interfaces:**
- Produces: clés d'état `signals_sent: list[str]` (entrées `"SYMBOLE|sens|barre_iso|score|envoi_iso|fam1+fam2"`), `signals_count: int`, `signals_cap_day: str | None` ; `empty_state` les contient ; `load_state` complète un état ancien sans ces clés (`setdefault`, jamais invalide) et les remet à zéro au changement de jour ; `last_signal(state, symbol, side, now_utc, cooldown_minutes) -> dict | None` (`{"score", "families": list, "sent_iso"}` du dernier envoi encore dans le repos) ; `signal_sent_for_bar(state, symbol, side, bar_iso) -> bool` ; `mark_signal(state, candidate: dict, now_utc) -> None` (ajoute l'entrée et incrémente `signals_count`).

- [ ] **Step 1: Write the failing tests** : `test_old_state_without_signal_keys_loads_with_defaults` ; `test_signal_keys_reset_on_new_day` ; `test_wrong_type_signal_key_gives_empty_state` ; `test_mark_signal_then_signal_sent_for_bar` ; `test_last_signal_inside_and_outside_cooldown` (`cooldown_minutes=120`, `0` = jamais de repos) ; `test_mark_signal_increments_count` ; `test_prune_keeps_signal_keys`.
- [ ] **Step 2: Run** : FAIL.
- [ ] **Step 3: Implement** ; `_valid` n'exige pas les nouvelles clés mais refuse un mauvais type quand elles sont présentes ; `STATE_VERSION` reste 1.
- [ ] **Step 4: Run** : PASS ; suite d'état et `test_alerts_run.py` verts.
- [ ] **Step 5: Commit** `feat(trader-fx): état des alertes de signal (déduplication, repos, compteur)`.

### Task 10: Filtres d'annonces et de trade ouvert

**Files:**
- Modify: `.claude/skills/trader-fx/alert_checks.py`
- Test: `.claude/skills/trader-fx/tests/test_alert_checks.py`

**Interfaces:**
- Produces: `news_blocked(symbol, events, now_utc, window_minutes=30) -> bool` (vrai si une annonce « High » d'une devise de `trade_currencies(symbol)` tombe dans `(now, now + window]`) ; `is_held(symbol, side, open_rules) -> bool`.

- [ ] **Step 1: Write the failing tests** : `test_news_blocked_inside_window_for_a_pair_currency`, `test_news_not_blocked_for_other_currency_or_low_impact_or_past_or_beyond_30_min`, `test_news_blocked_uses_usd_for_non_forex`, `test_news_ignores_malformed_events`, `test_is_held_matches_symbol_and_side_only`, `test_is_held_ignores_invalid_rules`.
- [ ] **Step 2: Run** : FAIL.
- [ ] **Step 3: Implement** en réutilisant `_aware`, `_valid_rule` et `trade_currencies`.
- [ ] **Step 4: Run** : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): filtres annonce et trade ouvert pour les signaux`.

### Task 11: Messages des alertes de signal

**Files:**
- Modify: `.claude/skills/trader-fx/alert_messages.py`
- Test: `.claude/skills/trader-fx/tests/test_alert_messages.py`

**Interfaces:**
- Consumes: candidat de la Tâche 8 ; `account` = `briefing["trade_ideas"]["account"]` ; `_size_line`, `_price`, `DISCLAIMER`.
- Produces: `signal_message(candidate, account, previous=None) -> str` ; `cap_message(max_per_day) -> str`. `previous` = `last_signal(...)` pour un signal renforcé, `None` pour une alerte normale.

Forme (heure de Paris) : ligne 1 `Signal en séance, non confirmé par le courtier : <display_name> <sens>.` (`Signal en séance renforcé, non confirmé par le courtier : …` si `previous`) ; `Signaux : session_break (Londres), rsi_exit. Barre 15 min de 09:15 Paris.` ; `Entrée 176.700 (zone valable jusqu'à 176.640), stop 177.100, cible 175.900 (1:2).` ; la ligne de taille de `_size_line` ; `Taille calculée sur le capital par défaut.` si `account["source"] == "default"` ; `Déjà alerté à HH:MM Paris : fam1, fam2.` si `previous` ; `DISCLAIMER`. `cap_message` : `Plafond de 10 alertes de signal atteint pour aujourd'hui : les suivantes ne sont pas envoyées.`

- [ ] **Step 1: Write the failing tests** : `test_signal_message_exact_text` (un candidat EURJPY baissier : chaque ligne exacte, décimales du plan, `1:2`) ; `test_reinforced_message_mentions_previous_families_and_time` ; `test_default_capital_line` ; `test_to_confirm_and_too_wide_sizes_never_invent_a_figure` ; `test_no_forbidden_word_and_under_telegram_limit` (regex `achat|acheter|vente|vendre|buy|sell|gagnant|profit|à prendre|prévision`) ; `test_cap_message_text` ; `test_display_name_is_clipped_and_shown`.
- [ ] **Step 2: Run** : FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run** : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): messages Telegram des signaux en séance`.

### Task 12: Sélection et orchestration (`intraday_run`)

**Files:**
- Modify: `.claude/skills/trader-fx/data.py` (ajouter `INTRADAY_15 = ("15m", "5d")`)
- Modify: `.claude/skills/trader-fx/intraday_plan.py` (`select`)
- Create: `.claude/skills/trader-fx/intraday_run.py`
- Test: `.claude/skills/trader-fx/tests/test_intraday_plan.py`, `.claude/skills/trader-fx/tests/test_intraday_run.py`

**Interfaces:**
- Consumes: Tâches 2, 8, 9, 10, 11.
- Produces: `intraday_plan.select(candidates, state, config, now_utc) -> tuple[list, bool]` (candidats retenus dans l'ordre d'envoi, et « plafond atteint avec des candidats restants ») ; `intraday_run.collect(now, document, get_events, open_rules, state, config, fetch_bars, workers=3) -> tuple[list[tuple[str, callable]], list[str]]` où `get_events` est un appelable `() -> list` (événements du calendrier), appelé **au plus une fois et seulement s'il existe au moins un candidat** (le calendrier n'est donc jamais demandé pour rien) ; retour : éléments `(texte, mark)` (comme la file de `alerts_run`) et lignes de journal.

`select` : écarte une barre déjà annoncée (`signal_sent_for_bar`) ; en repos (`last_signal` non nul) ne garde un candidat que si son score est strictement supérieur à celui de la dernière alerte (renforcement : le candidat retenu reçoit alors la clé `"previous"` = ce `last_signal`, que `collect` passe à `signal_message`) ; applique `min_score` s'il est défini ; trie par score décroissant, puis nombre de familles, puis symbole ; diversifie à `max_per_exposure` par exposition de devise (réutiliser `plan._diversify` si son interface convient, sinon la même logique) ; coupe à `max_per_run` et à `max_per_day − signals_count`.

`collect` : rien si `enabled` est faux, si `sessions.market_state(now) == "closed_weekend"`, si `document` est `None` (ligne « briefing indisponible : signaux en séance sautés »), ou si `document["daily_context"]` est vide ; symboles = ceux du contexte, filtrés par `intraday.symbols` si non vide ; `fetch_bars(symbols, *data.INTRADAY_15, cache_dir=None, ttl_s=0, use_cache=False, workers=workers)` ; symboles en échec journalisés (type et nombre, jamais bloquants) ; symboles sans contexte ou sans ATR journalier sautés avec une ligne ; `prices` pour `scan_symbol` = `{symbole: ctx["last"]}` des paires forex du contexte ; trade ouvert (`is_held`) et annonce (`news_blocked`) filtrent avant la sélection ; `mark` d'un message appelle `alert_state.mark_signal`. Quand le plafond du jour est atteint avec des candidats restants et que `signals_cap_day != today` : un élément `cap_message` dont le mark fixe `signals_cap_day`.

- [ ] **Step 1: Write the failing tests.** `test_intraday_plan.py` : `test_select_orders_by_score_then_families_then_symbol` ; `test_select_skips_bar_already_sent` ; `test_cooldown_blocks_same_score_but_lets_a_higher_score_through_as_reinforced` ; `test_per_run_cap_3` ; `test_per_day_cap_10_counts_previous_runs` ; `test_exposure_limit_2` ; `test_min_score_filters`. `test_intraday_run.py` (faux `fetch_bars`, document avec `daily_context` et `trade_ideas.account`) : `test_collect_returns_message_and_mark_updates_state` ; `test_no_bars_call_when_daily_context_is_missing` ; `test_skipped_on_closed_weekend` ; `test_skipped_when_document_is_none_with_log_line` ; `test_open_trade_same_symbol_and_side_is_skipped` ; `test_news_within_30_minutes_blocks_the_symbol` ; `test_symbol_failure_is_logged_not_fatal` ; `test_stale_index_series_gives_no_alert` (dernière barre vieille de 3 h) ; `test_cap_message_once_per_day` ; `test_symbols_filter_from_config`.
- [ ] **Step 2: Run** : FAIL.
- [ ] **Step 3: Implement** `INTRADAY_15`, `select`, `collect`. Une exception inattendue sur un symbole le saute seul.
- [ ] **Step 4: Run** : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): sélection, plafonds et orchestration des signaux en séance`.

### Task 13: Branchement dans `alerts_run.py`

**Files:**
- Modify: `.claude/skills/trader-fx/alerts_run.py`
- Test: `.claude/skills/trader-fx/tests/test_alerts_run.py`

**Interfaces:**
- Consumes: `intraday_run.collect`, `fxconfig.load_config` (garder son résultat, aujourd'hui jeté), `deps["fetch_bars"]`.

`get_events` passé à `collect` est une fermeture mémoïsée : elle réutilise `events` si le calendrier a déjà été lu (règles ouvertes), sinon appelle `fetch_calendar()` à la demande (`.get("events") or []`). Ordre de la file : stops et cibles, annonces, idées, puis signaux. Le code s'exécute après le bloc « 5. ideas » (il a besoin du `document`) et avant l'envoi ; il est protégé comme le briefing : une exception journalise son type seul et saute les signaux, jamais les stops ni les idées. `--dry-run` imprime les alertes sans état écrit ni envoi. Un échec d'envoi laisse l'alerte non marquée (elle repart au lancement suivant tant que le plan n'est pas caduc).

- [ ] **Step 1: Write the failing tests** (le `Harness` existant ; ajouter `daily_context` au document et des barres de 15 min au faux `fetch_bars`, qui reçoit déjà `interval` et `rng`) : `test_signal_alert_is_sent_after_ideas_and_marked` ; `test_second_run_sends_no_duplicate_for_the_same_bar` ; `test_failed_send_is_not_marked_and_is_resent_next_run_while_fresh_and_not_after_30_minutes` ; `test_exception_in_signals_does_not_silence_stops_or_ideas` (le message d'erreur ne fuit que le type) ; `test_dry_run_prints_signal_and_writes_no_state` ; `test_signal_cap_10_per_day_across_runs` ; `test_secret_config_capital_never_printed_in_logs` ; `test_calendar_is_fetched_only_when_a_signal_candidate_exists_and_without_open_rules` ; `test_missing_or_invalid_alerts_json_still_sends_signals` (la vérification des trades ouverts est sautée, la ligne existante du journal le dit) ; `test_existing_tests_still_see_no_15m_call_without_daily_context`.
- [ ] **Step 2: Run** `-p "test_alerts_run.py"` : FAIL.
- [ ] **Step 3: Implement** l'appel à `intraday_run.collect(now, document, events, rules or [], state, cfg, fetch_bars)` et l'ajout de ses éléments à `queue`.
- [ ] **Step 4: Run** `-p "test_alerts_run.py"` puis la suite complète : verts.
- [ ] **Step 5: Commit** `feat(trader-fx): alerts_run envoie les signaux en séance`.

### Task 14: Documentation et vérification réelle

**Files:**
- Modify: `.claude/skills/trader-fx/SKILL.md` (nouvelle section « Signaux en séance » ; mots déclencheurs « signaux en séance », « alertes intraday » dans `description`), `.github/workflows/alerts.yml` (commentaire d'en-tête seulement)

- [ ] **Step 1: Write the section** : les cinq familles et leurs règles (tableau de la spec 4.3), score, plafonds, repos et renforcement, zone de validité, clés `intraday` de la configuration (tableau de la Tâche 1), table `mt5_symbols`, limites (barres Yahoo retardées, signaux **non testés sur l'historique** tant que le rejeu n'existe pas, trade pris depuis une alerte = « hors plan » dans le journal, `--stop` obligatoire), rappel : aucun ordre, saisie manuelle dans MT5.
- [ ] **Step 2: Run** la suite complète : verte ; relever le nombre de tests.
- [ ] **Step 3: Vérification réelle** : `python3 .claude/skills/trader-fx/alerts_run.py --dry-run` depuis la racine, en séance. Attendu : le lancement se termine en code 0, des alertes de signal éventuelles s'affichent entre `---`, aucun mot interdit, et la durée totale est notée. Si elle dépasse 4 minutes, restreindre `intraday.symbols` et le dire à l'utilisateur ; ne rien envoyer sur Telegram.
- [ ] **Step 4: Commit** `docs(trader-fx): signaux en séance (SKILL.md)`.
- [ ] **Step 5:** lancer le workflow « Alerts » à la main avec `dry_run` coché depuis l'onglet Actions (action de l'utilisateur) et lui demander de confirmer que le journal du lancement montre les alertes de signal.
