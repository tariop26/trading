# trader-fx : données et briefing, plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** une commande `python3 fx.py brief` qui produit `trader/fx/briefing.json`, un résumé terminal et une page HTML pour le forex, les matières premières et les indices.

**Architecture:** skill Python autonome `.claude/skills/trader-fx/`, un module par responsabilité (données, signaux, force des devises, calendrier, sessions, briefing, page). Python collecte et calcule, écrit le JSON ; la page n'est qu'un gabarit qui embarque ce JSON.

**Tech Stack:** Python 3 (bibliothèque standard seulement), `unittest`, Yahoo `v8/finance/chart`, flux calendrier `nfs.faireconomy.media`.

**Spec:** `docs/superpowers/specs/2026-11-13-trader-fx-briefing-design.md`

## Global Constraints

- Python 3, bibliothèque standard seulement ; tests `unittest`, jamais de réseau dans un test.
- Commandes lancées depuis `C:/Users/m.poirat/TRADING`. Modules plats dans `.claude/skills/trader-fx/` ; chaque fichier de test commence par `import _path  # noqa` (`tests/_path.py` ajoute le dossier du skill à `sys.path`). Lancer : `python3 -m unittest discover -s .claude/skills/trader-fx/tests -v`.
- Yahoo `v8/finance/chart` ; pause 0,3 s entre requêtes ; query2 puis query1 sur 429 ou 5xx ; une nouvelle tentative après 5 s sur 429 (comme `scan.py`).
- Cache dans `trader/fx/cache/` : 6 h pour le journalier, 10 min pour l'intraday.
- Moins de 30 séances journalières : symbole exclu et compté.
- Vocabulaire : « a matché une règle », jamais achat, vente, gagnant ; aucun chiffre de gain ou de perte ; données jamais présentées comme du temps réel.
- Heures affichées à Paris (Europe/Paris) et à New York (America/New_York).
- Disclaimer exact : « Liste de graphiques qui ont matché une règle. Pas un conseil. Données Yahoo, retardées. »
- Code de sortie 0 si le briefing est produit, 1 sinon avec une ligne d'explication ; aucun `briefing.json` écrit si aucun symbole n'est reçu.
- Résumé terminal : 40 lignes au plus. Briefing complet en moins de 90 s à froid.

## Review Focus

1. Yahoo renvoie la barre du jour en cours pour le forex : elle ne doit jamais compter comme clôture complète (Task 2).
2. Barres à valeurs nulles au milieu d'une série (jour férié des futures ou indices) : supprimées, pas de plantage (Task 1).
3. Lancement un samedi : `closed_weekend`, dernières clôtures du vendredi, bandeau week-end (Tasks 5 et 6).
4. Calendrier avec pays `All`, devise hors périmètre, `forecast` vide : filtrés ou affichés sans plantage (Task 4).
5. Fichier de cache vide ou corrompu : retéléchargé, pas de plantage (Task 1).

---

### Task 1: data.py (barres Yahoo et cache)

**Files:**
- Create: `.claude/skills/trader-fx/data.py`, `.claude/skills/trader-fx/tests/_path.py`, `.claude/skills/trader-fx/tests/test_data.py`
- Create (fixtures capturées en direct) : `tests/fixtures/eurusd_1d.json`, `eurusd_1h.json`, `gc_1d.json`, `fchi_1d.json`

**Interfaces:**
- Produces:
  - `Bar = tuple[int, float, float, float, float]` : `(ts_utc, open, high, low, close)`.
  - `@dataclass Series: bars: list[Bar]; gmtoffset: int; age_s: float | None` (`age_s` non nul seulement pour un cache périmé utilisé après échec).
  - `class DataError(Exception)`.
  - `parse_chart(text: str, sym: str) -> Series` : supprime toute barre dont un des 4 prix est nul ; lève `DataError` si Yahoo répond « no data ».
  - `fetch_bars(symbols: list[str], interval: str, rng: str, *, cache_dir: str | None, ttl_s: int, use_cache: bool = True, now: float | None = None, http_get=None, sleep=time.sleep) -> tuple[dict[str, Series], list[dict]]` ; le second élément est la liste `{"symbol", "reason"}` des échecs.
  - Constantes : `PAUSE = 0.3`, `BACKOFF = 5.0`, `TTL_DAILY = 21600`, `TTL_INTRADAY = 600`, `DAILY = ("1d", "6mo")`, `HOURLY = ("1h", "5d")`.

- [ ] **Step 1: Capturer 4 fixtures réelles et vérifier les highs/lows (point 8 du spec)**
  Un script jetable (scratchpad) télécharge `EURUSD=X` 1d/6mo, `EURUSD=X` 1h/5d, `GC=F` 1d/6mo, `^FCHI` 1d/6mo et sauve le JSON brut dans `tests/fixtures/`. Vérifier que open, high, low, close sont non nuls sur au moins 90 % des barres de chacun.
  Expected : trois lignes `ok`. Sinon, arrêter et signaler au partenaire humain.

- [ ] **Step 2: Écrire les tests (échouent)** dans `test_data.py`, avec `http_get` et `sleep` injectés :
  - `test_parse_chart_drops_bars_with_null_prices` : une barre avec `close=None` au milieu disparaît, les autres restent ordonnées (Review Focus 2).
  - `test_parse_chart_no_data_raises` : réponse `{"chart":{"result":null,"error":{...}}}` lève `DataError`.
  - `test_parse_chart_real_fixtures` : les 4 fixtures donnent chacune plus de 60 barres et `bars[i][2] >= bars[i][3]` (high ≥ low).
  - `test_fetch_falls_back_to_query1_on_500` puis `test_429_waits_backoff_once` (le `sleep` espion reçoit `5.0`, puis échec propre si 429 persiste).
  - `test_cache_hit_within_ttl_makes_no_request` et `test_cache_expired_refetches`.
  - `test_corrupt_or_empty_cache_file_refetches` : fichier vide, puis fichier `{`, la récupération réussit (Review Focus 5).
  - `test_stale_cache_used_after_network_failure_sets_age` : `Series.age_s > ttl_s`, symbole absent de `failed`.
  - `test_failure_without_cache_listed_in_failed` : `failed == [{"symbol": "XXX=X", "reason": "no data..."}]`.
  - `test_no_cache_flag_ignores_cache`.

- [ ] **Step 3: Lancer** `python3 -m unittest discover -s .claude/skills/trader-fx/tests -p "test_data.py" -v` ; attendu : échecs `ImportError`/`AttributeError`.

- [ ] **Step 4: Implémenter `data.py`.** Le nom de fichier de cache est `{symbole nettoyé}_{interval}_{rng}.json` (remplacer `^`, `=`, `/` par `_`) ; contenu `{"fetched_at", "gmtoffset", "bars"}`. La logique de relance reprend `yahoo_get` de `scan.py:235-267`, avec `http_get` injectable.

- [ ] **Step 5: Relancer le test** ; attendu : tous PASS.

- [ ] **Step 6: Commit** `git add .claude/skills/trader-fx && git commit -m "feat(trader-fx): data.py, barres Yahoo v8 avec cache"`

### Task 2: signals.py

**Files:**
- Create: `.claude/skills/trader-fx/signals.py`, `tests/test_signals.py`

**Interfaces:**
- Consumes: `data.Series`, `data.Bar`.
- Produces:
  - `MIN_DAILY = 30`
  - `rsi(closes: list[float], n: int = 14) -> float | None` et `find_setups(closes: list[float]) -> tuple[list[str], dict]` : mêmes définitions que `scan.py:485-539` (clés `breakout_20d`, `bull_flag`, `reclaim_ma20`, `oversold`, `oversold_bounce`).
  - `complete_daily(series: Series, now_utc: datetime) -> list[tuple[date, float, float, float, float]]` : `(date locale, o, h, l, c)`, une barre par date, la barre du jour supprimée (voir test).
  - `atr(daily: list, n: int = 14) -> float | None` (ATR de Wilder).
  - `trend(closes: list[float]) -> str | None` : `"up"`, `"down"` ou `"mixed"`.
  - `levels(daily: list) -> dict` : clés `prev_high, prev_low, week_high, week_low, high20, low20` (semaine = semaine ISO précédente).
  - `asia_range(hourly: Series, now_utc: datetime) -> dict | None` : clés `asia_high, asia_low, day_high, day_low` (barres 1 h entre 00:00 et 07:00 UTC du jour, `day_*` depuis 00:00 UTC).
  - `analyze(symbol: str, name: str, daily: Series, now_utc: datetime) -> dict | None` : `None` si moins de `MIN_DAILY` séances complètes ; sinon `{symbol, name, last, rsi, atr_pct, trend, setups, levels, last_bar_date}`.

- [ ] **Step 1: Écrire les tests (échouent)** :
  - `test_rsi_all_gains_is_100_and_short_series_is_none`.
  - `test_find_setups_matches_scan_py` : charge `scan.py` par `importlib.util.spec_from_file_location` et compare `(tags, nombres)` sur 4 séries synthétiques (cassure, drapeau, reclaim, survente puis rebond) ; c'est le seul couplage avec le scanner, limité aux tests.
  - `test_complete_daily_drops_todays_partial_bar` : maintenant = 2026-11-13 14:00 UTC, dernière barre datée 2026-11-13 ; elle est exclue, celle du 12 reste (Review Focus 1).
  - `test_complete_daily_keeps_last_bar_on_saturday` : maintenant = 2026-11-14 10:00 UTC, dernière barre datée du 13, conservée.
  - `test_atr_constant_range_series`, `test_trend_up_down_mixed`.
  - `test_levels_use_previous_iso_week` : haut/bas de la semaine précédente, pas de la semaine en cours.
  - `test_asia_range_uses_only_00_to_07_utc`.
  - `test_analyze_returns_none_under_30_sessions`.

- [ ] **Step 2: Lancer** `... -p "test_signals.py" -v` ; attendu : FAIL (module absent).
- [ ] **Step 3: Implémenter `signals.py`.** `complete_daily` calcule la date locale avec `ts + series.gmtoffset` ; une barre est incomplète si sa date locale vaut celle de `now_utc + gmtoffset`.
- [ ] **Step 4: Relancer** ; attendu : PASS.
- [ ] **Step 5: Commit** `git commit -am "feat(trader-fx): signals.py"` (après `git add` des nouveaux fichiers).

### Task 3: strength.py

**Files:**
- Create: `.claude/skills/trader-fx/strength.py`, `tests/test_strength.py`

**Interfaces:**
- Produces:
  - `CURRENCIES = ("USD","EUR","GBP","JPY","CHF","AUD","NZD","CAD")`
  - `pair_currencies(symbol: str) -> tuple[str, str] | None` : `"EURUSD=X" -> ("EUR","USD")`, `None` si le symbole n'est pas une paire forex `XXXYYY=X`.
  - `currency_strength(closes_by_symbol: dict[str, list[float]], windows: tuple[int, ...] = (1, 5, 20)) -> dict[str, list[dict]]` : clés `"1d"`, `"5d"`, `"20d"` ; chaque liste `[{"ccy","score"}]` triée du plus fort au plus faible ; score = moyenne, sur les paires de la devise, du rendement logarithmique ×100, signé `+` si la devise est la base, `-` si cotée. Seules les paires dont les deux devises sont dans `CURRENCIES` comptent ; une paire sans assez de clôtures pour la fenêtre est ignorée.
  - `clusters(hits: list[dict]) -> list[dict]` : sur les hits dont `pair_currencies(symbol)` n'est pas `None`, retourne `[{"ccy","count","of"}]` pour chaque devise avec `count >= 3` et `count / of >= 0.5`, triée par `count` décroissant (`of` = nombre de hits forex).

- [ ] **Step 1: Écrire les tests (échouent)** :
  - `test_pair_currencies_parses_pairs_and_rejects_others` (`GC=F`, `^FCHI` → `None`).
  - `test_rising_currency_ranks_first_and_falling_last` : EURUSD, EURGBP, EURJPY montent de 1 %, les autres plats ; EUR premier, USD, GBP, JPY derrière en 5 jours.
  - `test_signed_by_base_and_quote` : USDJPY +1 % donne USD `+` et JPY `-` de même amplitude.
  - `test_pair_with_too_few_closes_is_skipped_without_error`.
  - `test_clusters_flags_dominant_currency` : 5 hits dont 4 contiennent USD → `[{"ccy":"USD","count":4,"of":5}]`.
  - `test_clusters_empty_when_no_dominant_currency`.

- [ ] **Step 2: Lancer** `... -p "test_strength.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter `strength.py`.** Rendement sur `n` séances : `ln(c[-1] / c[-1-n])`.
- [ ] **Step 4: Relancer** ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): strength.py`.

### Task 4: economic_calendar.py

**Files:**
- Create: `.claude/skills/trader-fx/economic_calendar.py`, `tests/test_calendar.py`, `tests/fixtures/calendar_thisweek.json` (capture réelle du flux)

**Interfaces:**
- Produces:
  - `URL_THIS = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"`, `URL_NEXT = ".../ff_calendar_nextweek.json"`
  - `parse_events(doc: list[dict]) -> list[dict]` : `{utc: str ISO, time_paris, time_ny, currency, title, impact, forecast, previous}` ; `forecast` et `previous` valent `""` si absents.
  - `filter_events(events: list[dict], currencies: set[str], impacts: tuple[str, ...] = ("High",)) -> list[dict]` : supprime pays `All` et devises hors périmètre.
  - `within_hours(events: list[dict], start_utc: datetime, hours: int = 24) -> list[dict]`.
  - `fetch_calendar(*, http_get=None) -> dict` : `{"status": "ok"|"partial"|"unavailable", "events": [...]}` ; semaine en cours échouée → `unavailable` ; semaine suivante en 404 → `partial` ; les deux réussies → `ok`.
  - `focus_currencies(symbols: list[str]) -> set[str]` : devises des paires forex plus `"USD"`.

- [ ] **Step 1: Capturer** le flux de la semaine en cours dans `tests/fixtures/calendar_thisweek.json`.
- [ ] **Step 2: Écrire les tests (échouent)** :
  - `test_parse_events_converts_times` : un événement `2026-11-10T08:30:00-05:00` donne `time_ny == "08:30"` et `time_paris == "14:30"`.
  - `test_parse_real_fixture_has_high_impact_events`.
  - `test_filter_drops_all_country_and_unfocused_currency_and_medium` (Review Focus 4, avec un événement `country="All"` et un `CNY`).
  - `test_empty_forecast_is_empty_string`.
  - `test_within_hours_window_boundaries`.
  - `test_fetch_next_week_404_gives_partial`, `test_fetch_this_week_failure_gives_unavailable`, `test_fetch_both_ok`.
  - `test_focus_currencies_includes_usd_and_pair_codes`.
- [ ] **Step 3: Lancer** `... -p "test_calendar.py" -v` ; attendu : FAIL.
- [ ] **Step 4: Implémenter.** `fetch_calendar` utilise `urllib` avec `User-Agent` générique et délai de 20 s ; une 404 sur `URL_NEXT` n'est pas une erreur.
- [ ] **Step 5: Relancer** ; attendu : PASS. **Step 6: Commit** `feat(trader-fx): economic_calendar.py`.

### Task 5: sessions.py

**Files:**
- Create: `.claude/skills/trader-fx/sessions.py`, `tests/test_sessions.py`

**Interfaces:**
- Produces:
  - `SESSIONS = {"Sydney": ("Australia/Sydney", 7, 16), "Tokyo": ("Asia/Tokyo", 9, 18), "London": ("Europe/London", 8, 17), "New York": ("America/New_York", 8, 17)}`
  - `market_state(now_utc: datetime) -> str` : `"closed_weekend"` du vendredi 17:00 au dimanche 17:00 New York (bornes : fermé à 17:00 vendredi, ouvert à 17:00 dimanche), sinon `"open"`.
  - `session_table(now_utc: datetime) -> list[dict]` : une entrée par session pour sa date locale du jour : `{name, open_paris, close_paris, open_ny, close_ny, active}` (`"HH:MM"`, `active` si `open <= now < close`).

- [ ] **Step 1: Écrire les tests (échouent)** :
  - `test_market_state_boundaries` : vendredi 16:59 NY ouvert ; vendredi 17:00 NY fermé ; samedi fermé ; dimanche 16:59 NY fermé ; dimanche 17:00 NY ouvert (Review Focus 3).
  - `test_session_times_winter` : 2026-11-13, Londres 08:00 → Paris `09:00`, New York 08:00 → Paris `14:00`.
  - `test_session_times_us_dst_gap` : 2026-03-16 (heure d'été US, pas encore européenne), New York 08:00 → Paris `13:00`.
  - `test_active_flag_london_midday_utc`.
- [ ] **Step 2: Lancer** `... -p "test_sessions.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter avec `zoneinfo`.** Vérifier que `ZoneInfo("America/New_York")` se charge sous Windows ; sinon, signaler que `tzdata` est requis.
- [ ] **Step 4: Relancer** ; attendu : PASS. **Step 5: Commit** `feat(trader-fx): sessions.py`.

### Task 6: briefing.py et fx.py

**Files:**
- Create: `.claude/skills/trader-fx/briefing.py`, `.claude/skills/trader-fx/fx.py`, `tests/test_briefing.py`

**Interfaces:**
- Consumes : `data.fetch_bars`, `data.DAILY`, `data.HOURLY`, `data.TTL_DAILY`, `data.TTL_INTRADAY`, `signals.analyze`, `signals.asia_range`, `signals.complete_daily`, `strength.currency_strength`, `strength.clusters`, `economic_calendar.fetch_calendar`, `economic_calendar.filter_events`, `economic_calendar.within_hours`, `economic_calendar.focus_currencies`, `sessions.market_state`, `sessions.session_table`.
- Produces:
  - `read_list(path: str) -> list[tuple[str, str]]` : `(symbole, nom)` ; `#` commentaires, `|nom` optionnel.
  - `build_briefing(universe: list[tuple[str, str]], daily: dict[str, Series], failed: list[dict], hourly: dict[str, Series], calendar: dict, now_utc: datetime) -> dict` : fonction pure, clés exactes du spec §5.6 (`as_of, market_state, counts, data_age, calendar, strength, swing, day_plan, warnings, disclaimer`).
  - `alert_symbols(hits: list[dict]) -> list[str]` : symboles des hits plus les 7 majors (`EURUSD=X, GBPUSD=X, USDJPY=X, USDCHF=X, AUDUSD=X, USDCAD=X, NZDUSD=X`), sans doublon.
  - `render_summary(b: dict) -> str` : 40 lignes au plus.
  - `fx.main(argv: list[str] | None = None, deps: dict | None = None) -> int` : sous-commande `brief` ; options `--list FILE` (répétable, défaut les trois listes de `trader/lists/`), `--no-cache`, `--json`, `--now "YYYY-MM-DD HH:MM"` (heure de New York), `--out PATH` (défaut `trader/fx/briefing.json`). `deps` (tests) remplace `fetch_bars` et `fetch_calendar`.

- [ ] **Step 1: Écrire les tests (échouent)**, avec des `Series` synthétiques et les fixtures :
  - `test_read_list_skips_comments_and_names`.
  - `test_build_briefing_has_all_spec_keys` : `set(b) == {"as_of","market_state","counts","data_age","calendar","strength","swing","day_plan","warnings","disclaimer"}` et `b["disclaimer"]` égal au texte des contraintes globales.
  - `test_counts_say_partial` : 4 demandés, 3 reçus, 1 échec → `counts == {"requested":4,"fetched":3,"scanned":3,"failed":[{...}]}` et le résumé contient `Reçus : 3 sur 4 (1 en échec)`.
  - `test_under_30_sessions_counted_not_scanned` : `scanned` exclut le symbole et un avertissement le nomme.
  - `test_saturday_run_is_closed_weekend_and_warns` (`--now "2026-11-14 10:00"`) : `market_state == "closed_weekend"`, avertissement présent, dernières clôtures du vendredi.
  - `test_calendar_unavailable_adds_warning_and_runs` (Review Focus 3 et 4).
  - `test_stale_cache_sets_data_age_and_warning`.
  - `test_summary_under_41_lines_and_no_forbidden_words` : `assertNotRegex(summary, r"(?i)\b(achat|acheter|buy|gagnant|profit)\b")`.
  - `test_summary_mentions_usd_cluster_when_dominant`.
  - `test_main_writes_briefing_json_and_returns_0`, `test_main_returns_1_and_writes_nothing_when_no_symbol_fetched`, `test_main_json_flag_prints_json` (avec `deps` factices).
- [ ] **Step 2: Lancer** `... -p "test_briefing.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** `briefing.py` et `fx.py`. `fx.main` : lit les listes, `fetch_bars(... DAILY ...)` pour tous, calcule les hits, `fetch_bars(... HOURLY ...)` pour `alert_symbols`, calendrier, `build_briefing`, écriture JSON, impression du résumé. `day_plan.levels` combine `signals.levels` et `signals.asia_range`.
- [ ] **Step 4: Relancer toute la suite** `python3 -m unittest discover -s .claude/skills/trader-fx/tests -v` ; attendu : tous PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): briefing.py et fx.py (brief)`.

### Task 7: page HTML

**Files:**
- Create: `.claude/skills/trader-fx/report_template.html`, `.claude/skills/trader-fx/page.py`, `tests/test_page.py`
- Modify: `fx.py` (sous-commande `page`)

**Interfaces:**
- Consumes : `briefing.json` (clés du spec §5.6).
- Produces:
  - `render_page(briefing: dict, template_path: str) -> str` : insère le JSON échappé (`</` remplacé par `<\/`) dans le gabarit à `<!--BRIEFING_JSON-->`.
  - `fx.py page [--in PATH] [--out PATH]` : défauts `trader/fx/briefing.json` et `trader/fx/briefing.html` ; code 1 avec une ligne si le JSON manque.
  - Gabarit : page sans appel réseau ; sections « Résumé », « Force des devises » (barres), « Calendrier », « Setups swing », « Plan du jour », « Avertissements » et le disclaimer ; thème clair et sombre (variables CSS, `prefers-color-scheme` et `data-theme`), mise en page 400 px, tableaux dans des conteneurs `overflow-x:auto`, marge latérale d'au moins 16 px.

- [ ] **Step 1: Écrire les tests (échouent)** :
  - `test_render_page_embeds_json_and_escapes_script_close` : un titre contenant `</script>` ne ferme pas le bloc.
  - `test_template_has_all_sections_and_disclaimer`.
  - `test_template_makes_no_network_calls` : le gabarit ne contient ni `fetch(` ni `XMLHttpRequest` ni `http://` hors liens de texte.
  - `test_page_command_missing_json_returns_1`.
- [ ] **Step 2: Lancer** `... -p "test_page.py" -v` ; attendu : FAIL.
- [ ] **Step 3: Écrire le gabarit et `page.py`.** Charger le skill `artifact-design` avant d'écrire le HTML, puis appliquer ses règles (thèmes, mobile).
- [ ] **Step 4: Relancer** ; attendu : PASS. **Step 5: Commit** `feat(trader-fx): page HTML du briefing`.

### Task 8: SKILL.md, essai en direct, liste des indices, publication

**Files:**
- Create: `.claude/skills/trader-fx/SKILL.md`
- Modify: `trader/lists/indices.txt`

**Interfaces:** aucune nouvelle.

- [ ] **Step 1: Écrire `SKILL.md`** : en-tête (`name: trader-fx`, `description` avec déclencheurs « briefing forex », « scan forex », « force des devises », « calendrier économique », « matières premières », « indices »), commandes `brief` et `page`, tableau des fichiers lus et écrits, étapes pour Claude (lancer `brief`, résumer, puis `page` et publier `trader/fx/briefing.html` avec l'outil Artifact), règles de vocabulaire, section Sécurité (éducatif, pas un conseil, aucun ordre).
- [ ] **Step 2: Essai en direct à froid** : `python3 .claude/skills/trader-fx/fx.py brief` ; attendu : code 0, résumé de 40 lignes au plus, durée sous 90 s (`time`), `trader/fx/briefing.json` présent. Noter dans le message de commit les comptes réels (demandés, reçus, échecs).
- [ ] **Step 3: Identifier et corriger le symbole d'indice en échec** (spec §8) : lire `counts.failed` ; remplacer ou retirer le symbole dans `trader/lists/indices.txt` ; relancer `brief` ; attendu : plus d'échec sur les indices.
- [ ] **Step 4: Vérifier la plage asiatique** (spec §8) : dans `briefing.json`, `day_plan.levels` d'EURUSD=X a `asia_high >= asia_low` et ces valeurs sont dans le haut/bas des 5 derniers jours ; sinon signaler.
- [ ] **Step 5: Générer la page** `python3 .claude/skills/trader-fx/fx.py page`, la publier avec l'outil Artifact (icône `chart`), contrôler les six sections et les deux thèmes.
- [ ] **Step 6: Suite complète** `python3 -m unittest discover -s .claude/skills/trader-fx/tests -v` ; attendu : tous PASS.
- [ ] **Step 7: Commit et push** `git add -A && git commit -m "feat(trader-fx): SKILL.md, liste indices corrigée" && git push` (le remote `origin` existe).
