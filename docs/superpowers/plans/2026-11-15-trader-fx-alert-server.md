# trader-fx : serveur d'alertes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un serveur GitHub Actions qui, en séance, relance le briefing, surveille les stops et cibles des trades ouverts et envoie sur Telegram les idées de trade nouvelles, les contacts de stop ou de cible et les annonces à fort impact ; `journal.py` pousse seul `alerts.json`.

**Architecture:** Un workflow `alerts.yml` lance `alerts_run.py`, qui orchestre cinq petits modules plats (`alert_state`, `alert_checks`, `alert_messages`, `telegram`, plus le briefing existant via `fx.main`). Les modules de vérification sont des fonctions pures ; le réseau, `git` et l'heure sont injectés, donc tout se teste sans réseau. L'état de déduplication vit dans le cache d'Actions.

**Tech Stack:** Python 3 (bibliothèque standard seulement), `unittest`, GitHub Actions (`actions/checkout@v4`, `actions/cache/restore@v4`, `actions/cache/save@v4`), Telegram Bot API.

**Spec:** `docs/superpowers/specs/2026-11-15-trader-fx-alert-server-design.md` (la lire avant de commencer ; ses numéros de section sont cités ci-dessous).

## Global Constraints

- Python 3, bibliothèque standard seulement ; tests `unittest`, jamais de réseau ni de vrai `git` dans un test (`fetch_bars`, `fetch_calendar`, l'envoi Telegram, `run_git`, l'heure sont injectés).
- Commandes lancées depuis `C:/Users/m.poirat/trading`. Modules plats dans `.claude/skills/trader-fx/` ; chaque fichier de test commence par `import _path  # noqa`. Suite : `python3 -W error -m unittest discover -s .claude/skills/trader-fx/tests` (491 tests passent aujourd'hui, sortie sans avertissement).
- Heures stockées et comparées en UTC (ISO 8601), affichées en heure de Paris (`sessions.PARIS`).
- Messages en français ; « haussier » et « baissier » ; interdits comme mots entiers : achat, acheter, vente, vendre, buy, sell, et l'expression « à prendre » ; aucun conseil, aucune prévision. Aucun résultat, capital ni identifiant de compte dans un message ou dans `alerts.json`.
- Un secret (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADER_FX_CONFIG`) n'apparaît dans aucune sortie, aucune exception, aucun test de sortie. Les erreurs Telegram ne donnent que le type et le code HTTP. Pas de `parse_mode` : le texte part en texte brut.
- Chaque message de commit se termine par une ligne vide puis `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Ne rien pousser, ne rien publier : le seul `git push` du plan est celui, testé avec un `git` simulé, de `journal.py`.
- Valeurs exactes de la spec : cron `*/15 7-21 * * 1-5` (UTC) ; `timeout-minutes: 10` ; concurrence `alerts` sans annulation ; au plus 3 idées par lancement ; annonce entre 15 et 30 minutes devant (bornes comprises) ; barres `("5m", "5d")` ; état `{"v": 1, "day", "ideas_sent", "rules_fired", "events_sent", "down_notified_day"}` ; message de commit `alerts: règles de stop et de cible`.

## Review Focus

1. Un trade ouvert dont `since` tombe au milieu d'une barre de 5 minutes, ou après la dernière barre reçue : aucune alerte, aucun plantage (Task 5).
2. Un symbole sans barres, des barres vides, une règle mal formée (`level` ou `since` illisible) : la règle est sautée avec une ligne de journal, les autres règles sont traitées ; panne de toutes les barres : un seul message « Panne » par jour (Tasks 5 et 8).
3. État du cache perdu au démarrage d'un lancement : état vide, au pire un message en double, jamais un plantage ni un message manquant (Task 4).
4. Titre d'annonce contenant `<`, `&` ou des guillemets : il part tel quel, sans `parse_mode` (Task 7).
5. Lancement un week-end ou hors séance (déclenchement manuel) : le briefing dit `closed_weekend`, aucune idée n'est annoncée (les prix sont des clôtures, rien n'est « en formation »), le suivi et les annonces tournent normalement (Task 5).

---

### Task 1: section `alerts` de la configuration

**Files:**
- Modify: `.claude/skills/trader-fx/config.py`, `.claude/skills/trader-fx/config.example.json`, `.claude/skills/trader-fx/tests/test_config.py`

**Interfaces:**
- Produces: `config.DEFAULTS["alerts"] == {"auto_push": False}` ; `config.validate(cfg)["alerts"]["auto_push"]` est un `bool` ; `ConfigError` d'une ligne si ce n'est pas un booléen, si la section n'est pas un objet ou contient une clé inconnue.

- [ ] **Step 1: Écrire les tests (échouent)** dans `test_config.py` : mettre à jour `EXPECTED` avec `"alerts": {"auto_push": False}` ; `test_alerts_section_defaults_and_booleans` (absent donne `False` ; `{"alerts": {"auto_push": true}}` donne `True`) ; `test_alerts_section_rejects` (`"yes"`, `1`, `null` pour `auto_push` ; la section `"alerts": 3` ; la clé `{"alerts": {"foo": true}}`) avec un message qui contient `alerts.auto_push` ou `alerts.foo`.
- [ ] **Step 2: Lancer** `python3 -W error -m unittest discover -s .claude/skills/trader-fx/tests -p "test_config.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** dans `config.py` (même style que `ideas`) : l'entrée `DEFAULTS`, la validation dans `validate` (`isinstance(v, bool)`, message `La valeur de alerts.auto_push doit être true ou false.`) ; ajouter `"alerts": {"auto_push": false}` à `config.example.json`.
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS (`test_example_file_is_valid` inclus).
- [ ] **Step 5: Commit** `git add .claude/skills/trader-fx && git commit -m "feat(trader-fx): section alerts de la configuration (auto_push)"`

### Task 2: champ `since` dans `alerts.json`

**Files:**
- Modify: `.claude/skills/trader-fx/journal.py` (`build_alerts`), `.claude/skills/trader-fx/tests/test_journal_cli.py` (tests d'alertes existants)

**Interfaces:**
- Produces: chaque règle de `journal.build_alerts(journal, now_utc)["rules"]` a en plus `"since": str` (heure UTC ISO 8601) : pour une règle `stop`, l'heure du dernier évènement d'historique `stop_deplace` du trade, sinon `entry.time` ; pour une règle `cible`, le dernier `cible_deplacee`, sinon `entry.time`. Les autres clés ne changent pas (`id`, `trade_id`, `symbol`, `type`, `side`, `level`, `decimals`), `v` reste 1.

- [ ] **Step 1: Écrire les tests (échouent)** : `test_alert_rules_carry_since` (ouverture : les deux règles ont `since == entry.time`) ; `test_since_follows_the_last_move_of_each_level` (stop déplacé à T1 puis T2, cible jamais déplacée : `since` du stop vaut T2, celui de la cible l'ouverture ; puis cible déplacée à T3 : seule la cible passe à T3) ; mettre à jour le test existant « rien de financier » pour que l'ensemble exact des clés d'une règle soit `{id, trade_id, symbol, type, side, level, decimals, since}`.
- [ ] **Step 2: Lancer** `-p "test_journal_cli.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** dans `build_alerts` une petite fonction privée `_level_since(trade, kind) -> str` qui parcourt `trade["history"]` ; ne pas dupliquer la lecture de l'historique ailleurs.
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): alerts.json porte since (depuis quand surveiller)`

### Task 3: `alerts.json` régénéré et poussé par `journal.py`

**Files:**
- Modify: `.claude/skills/trader-fx/journal.py`
- Create: `.claude/skills/trader-fx/tests/test_journal_alerts_push.py`

**Interfaces:**
- Consumes: `config.validate(...)["alerts"]["auto_push"]` (Task 1) ; `build_alerts` (Task 2) ; `write_json_atomic`.
- Produces: option `--alerts PATH` sur `open`, `amend` et `close` (défaut : `alerts.json` dans le dossier de `--journal`, soit `trader/fx/alerts.json` par défaut ; ce défaut évite qu'un test écrive dans le dépôt) ; `ALERTS_COMMIT_MESSAGE = "alerts: règles de stop et de cible"` ; `default_run_git(args: list[str]) -> tuple[int, str]` (`subprocess.run(["git", *args], capture_output=True, text=True)`, code de retour et sortie standard ; `(127, "")` si `git` est introuvable) ; `publish_alerts(path: str, *, auto_push: bool, run_git) -> list[str]` renvoie les avertissements (liste vide si tout va bien) ; la clé de dépendance `deps["run_git"]` (défaut `default_run_git`).

Comportement (spec 3.3) : `open`, `amend` et `close` enregistrent le trade comme aujourd'hui, puis réécrivent `alerts.json` ; si `auto_push` est faux ou absent, aucun appel à `run_git`. Si vrai : `git rev-parse --abbrev-ref HEAD` doit donner `main` (sinon pas de push, avertissement) ; `git status --porcelain -- <path>` vide : rien à faire ; sinon `git add -- <path>`, `git commit -m ALERTS_COMMIT_MESSAGE -- <path>`, puis `git push`. Tout échec (code ≠ 0) donne un avertissement `alerts.json non poussé : <raison>. Poussez-le à la main.` imprimé après la confirmation du trade, code de sortie 0, trade déjà enregistré. `amend` charge maintenant la configuration (`_load_config`) pour lire `auto_push`.

- [ ] **Step 1: Écrire les tests (échouent)** dans `test_journal_alerts_push.py`, `run_git` simulé qui enregistre ses appels, dossier temporaire : `test_alerts_file_rewritten_after_open_amend_close` ; `test_no_git_call_when_auto_push_is_false_or_absent` ; `test_auto_push_runs_add_commit_push_limited_to_the_file` (les arguments du commit se terminent par `["--", path]` ; aucun appel ne mentionne `journal.json`) ; `test_nothing_committed_when_the_file_did_not_change` ; `test_no_push_off_main_says_why` ; `test_commit_or_push_failure_keeps_the_trade_prints_one_warning_and_exits_0` (le journal contient bien le trade, la sortie se termine par la ligne `alerts.json non poussé : … Poussez-le à la main.`) ; `test_git_missing_gives_a_warning` (`run_git` renvoie `(127, "")`).
- [ ] **Step 2: Lancer** `-p "test_journal_alerts_push.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** `publish_alerts` et le câblage dans `cmd_open`, `cmd_amend`, `cmd_close` (une seule fonction privée `_refresh_alerts(args, doc, cfg, deps)` appelée après `save_journal`) ; les autres tests du journal ne doivent pas changer.
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): journal.py régénère et pousse alerts.json (alerts.auto_push)`

### Task 4: état de déduplication

**Files:**
- Create: `.claude/skills/trader-fx/alert_state.py`, `.claude/skills/trader-fx/tests/test_alert_state.py`

**Interfaces:**
- Produces:
  - `empty_state(day: str) -> dict` (`{"v": 1, "day": day, "ideas_sent": [], "rules_fired": [], "events_sent": [], "down_notified_day": None}`).
  - `load_state(path: str, today: str) -> dict` : fichier absent, illisible, non objet, d'une autre version : `empty_state(today)` ; si `state["day"] != today` : `ideas_sent` et `down_notified_day` remis à zéro, `day = today`, `rules_fired` et `events_sent` gardés. Ne lève jamais.
  - `prune(state: dict, active_rule_ids: set, future_event_keys: set) -> dict` : copie où `rules_fired` ne garde que les ids actifs et `events_sent` que les clés à venir.
  - `save_state(path: str, state: dict) -> None` (écriture atomique en réutilisant `journal.write_json_atomic`).

- [ ] **Step 1: Écrire les tests (échouent)** : `test_missing_corrupt_and_other_version_give_an_empty_state` (trois cas, sans exception) ; `test_new_day_resets_ideas_and_down_flag_but_keeps_rules_and_events` ; `test_prune_forgets_rules_that_left_alerts_json_and_past_events` ; `test_save_then_load_roundtrip` ; `test_prune_does_not_mutate_its_input`.
- [ ] **Step 2: Lancer** `-p "test_alert_state.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** `alert_state.py` (fonctions pures sauf `load_state` et `save_state`).
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): alert_state.py (état de déduplication des alertes)`

### Task 5: les vérifications

**Files:**
- Modify: `.claude/skills/trader-fx/data.py` (une constante)
- Create: `.claude/skills/trader-fx/alert_checks.py`, `.claude/skills/trader-fx/tests/test_alert_checks.py`

**Interfaces:**
- Consumes: `alert_state` (Task 4) ; `strength.pair_currencies` ; bars `data.Series.bars` = liste de `(ts_utc_secondes, open, high, low, close)`.
- Produces:
  - `data.INTRADAY = ("5m", "5d")`.
  - `idea_key(idea: dict, today: str) -> str` = `"<symbole>|<sens>|<AAAA-MM-JJ>"`.
  - `new_ideas(briefing: dict, open_rules: list[dict], state: dict, today: str, limit: int = 3) -> tuple[list[dict], int]` : (idées à annoncer dans l'ordre du rang, nombre d'idées éligibles laissées en attente). Éligible : clé absente de `state["ideas_sent"]`, aucune règle ouverte de même symbole et même sens, `since_close` sans stop franchi ni cible atteinte ; liste vide si `briefing["market_state"] == "closed_weekend"` (décision du plan : rien n'est « en formation » un week-end).
  - `touched_rules(rules: list[dict], bars: dict, state: dict, fallback_since: str) -> tuple[list[dict], list[str]]` : (contacts, lignes de journal). Un contact est `{"rule": rule, "bar_time": ISO UTC du début de la barre, "extreme": float, "extreme_kind": "plus haut" | "plus bas"}` ; première barre qui touche, barres dont l'heure de début est strictement postérieure à `since` (la règle, sinon `fallback_since`) ; règle déjà dans `rules_fired` ignorée ; règle mal formée (`level` non numérique, `since` illisible, symbole absent de `bars`) sautée avec une ligne de journal. Sens du contact : stop haussier `low <= level`, stop baissier `high >= level`, cible haussière `high >= level`, cible baissière `low <= level`.
  - `trade_currencies(symbol: str) -> set` : devises de la paire forex, sinon `{"USD"}`.
  - `event_key(event: dict) -> str` = `"<utc>|<devise>|<titre>"`.
  - `upcoming_events(events: list[dict], open_rules: list[dict], now_utc: datetime, state: dict) -> list[dict]` : événements `impact == "High"` dont le début est dans `[now+15 min, now+30 min]`, dont la devise est dans l'union des `trade_currencies` des symboles des règles, et dont la clé n'est pas dans `events_sent` ; chaque élément est `{"event": event, "minutes": int, "symbols": list[str]}` ; liste vide sans règle.

- [ ] **Step 1: Écrire les tests (échouent)**, chiffres calculés à la main : `new_ideas` (nouvelle idée annoncée ; même clé déjà envoyée non renvoyée ; idée dont le symbole et le sens sont dans une règle ouverte sautée ; `since_close` avec `stop_crossed` ou `target_crossed` sautée ; 5 idées éligibles donnent 3 et `waiting == 2` dans l'ordre du rang ; `closed_weekend` donne `([], 0)`) ; `touched_rules` (les quatre combinaisons stop et cible, haussier et baissier ; barre antérieure ou égale à `since` ignorée ; `since` au milieu d'une barre : la barre qui commence avant ne compte pas ; plus haut et plus bas bruts : une mèche au milieu de plusieurs barres est vue ; règle déjà tirée ignorée ; première barre qui touche choisie ; `since` plus récent que la dernière barre : aucun contact ; barres vides et symbole absent : aucune alerte ni exception ; règle mal formée sautée avec une ligne et les autres règles traitées ; `since` manquant : `fallback_since`) ; `upcoming_events` (15 min et 30 min inclus, 14 et 31 exclus ; impact `Medium` exclu ; devise absente ; sans règle ; clé déjà envoyée ; instrument non forex : USD ; un trade EURJPY concerné par un événement `JPY`).
- [ ] **Step 2: Lancer** `-p "test_alert_checks.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** `alert_checks.py` (fonctions pures, aucune lecture de fichier ni réseau) et la constante de `data.py`.
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): alert_checks.py (idées, contacts de stop et de cible, annonces)`

### Task 6: les messages

**Files:**
- Create: `.claude/skills/trader-fx/alert_messages.py`, `.claude/skills/trader-fx/tests/test_alert_messages.py`

**Interfaces:**
- Consumes: formes de `new_ideas`, `touched_rules`, `upcoming_events` (Task 5) ; `strength.pair_currencies`, `sessions.PARIS`.
- Produces (toutes renvoient un `str`) :
  - `pair_label(symbol: str) -> str` (`"EUR/JPY"` pour `EURJPY=X`, sinon le symbole).
  - `idea_message(idea: dict, account: dict, waiting: int = 0) -> str`, `account` étant `briefing["trade_ideas"]["account"]`.
  - `touch_message(hit: dict) -> str`.
  - `event_message(item: dict) -> str`.
  - `down_message() -> str`.

Formats exacts (spec 5) : idée = lignes séparées par `\n` : `Idée de trade, en formation, non confirmée à la clôture : EUR/JPY baissier.` / `Entrée 176.659, stop 178.408, cible 173.161 (1:2).` (prix avec `decimals` de l'idée ; `1:%g` de `rr`) / `Taille 0.45 lot, risque 480.75 USD (0.5 % du capital).` (`lot` sous 2 lots, `lots` sinon ; taille de contrat : `Taille 4.5, risque …` ; le pourcentage est `risk_per_trade_usd / capital * 100` ; statut `to_confirm` : `Taille à confirmer chez le courtier.` ; `too_wide` : `Stop trop large pour le risque fixé.`) / `Règles : lose_ma20.` / `Plan mécanique à valider, pas un conseil. Prix Yahoo, retardé.` ; si `account["source"] == "default"`, une ligne `Taille calculée sur le capital par défaut.` avant la dernière ligne ; si `waiting > 0`, une ligne finale `N autres idées en attente.`. Contact : `Stop touché : EUR/JPY baissier, trade 2026-11-16-EURJPY-1.` / `Niveau 178.408 franchi à 14:35 (plus haut de la barre 5 min : 178.412).` (heure de Paris du début de la barre) / `Vérifiez la position chez le courtier.` ; `Cible touchée` pour une cible. Annonce : `Annonce à fort impact dans 25 min : 14:30 Paris, USD, Core CPI m/m.` / `Vos trades concernés : EUR/JPY.` (`time_paris` de l'événement ; symboles via `pair_label`). Panne : `Impossible de vérifier vos stops : données Yahoo indisponibles.`

- [ ] **Step 1: Écrire les tests (échouent)** avec les chaînes complètes ci-dessus comme valeurs attendues (idée forex `ok`, idée `to_confirm`, idée `too_wide`, contrat à taille 4.5, compte `default` et `waiting=2`, contact de stop et de cible, événement, panne) ; `test_no_message_has_a_forbidden_word_or_a_financial_field` (regex RAW `\b(achat|acheter|vente|vendre|buy|sell)\b` insensible à la casse avec un contrôle négatif sur `survente`, et l'absence de `à prendre`, `pnl`, `capital` hors de la phrase `du capital`) ; `test_every_message_fits_telegram_limit` (moins de 4 096 caractères, même avec 12 règles dans l'idée).
- [ ] **Step 2: Lancer** `-p "test_alert_messages.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** `alert_messages.py` ; réutiliser `strength.pair_currencies` pour `pair_label`, aucun calcul de prix (les niveaux viennent des idées et des règles).
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): alert_messages.py (textes Telegram)`

### Task 7: envoi Telegram

**Files:**
- Create: `.claude/skills/trader-fx/telegram.py`, `.claude/skills/trader-fx/tests/test_telegram.py`

**Interfaces:**
- Produces:
  - `send_message(token: str, chat_id: str, text: str, *, http_post=None, sleep=time.sleep) -> tuple[bool, str | None]` : (envoyé, raison sans secret). `http_post(url: str, payload: dict, timeout: float) -> tuple[int, str]` (code HTTP, corps) est injectable ; la valeur par défaut utilise `urllib.request` et convertit une exception réseau en `(0, "<NomDuType>")`. Le payload est `{"chat_id": chat_id, "text": text}` et rien d'autre (pas de `parse_mode`). Une nouvelle tentative après un 429 (attente `parameters.retry_after` du corps JSON, plafonnée à 30 s, 5 s par défaut) ou un 5xx (5 s) ; au plus deux envois au total. La raison est de la forme `HTTP 400` ou `erreur réseau (URLError)`, jamais l'adresse ni le token.

- [ ] **Step 1: Écrire les tests (échouent)** : `test_success_returns_true`, `test_retry_once_on_429_with_retry_after_capped_at_30s`, `test_retry_once_on_500_then_gives_up`, `test_400_is_not_retried`, `test_network_error_reason_has_no_token_or_url` (le token factice n'apparaît ni dans la raison ni dans une exception), `test_payload_has_no_parse_mode_and_keeps_special_characters` (texte `Core <CPI> & "m/m"` envoyé tel quel).
- [ ] **Step 2: Lancer** `-p "test_telegram.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** `telegram.py` (URL `https://api.telegram.org/bot<token>/sendMessage`, construite seulement dans la fonction par défaut de `http_post`).
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): telegram.py (envoi avec nouvelle tentative, sans fuite de secret)`

### Task 8: l'exécuteur `alerts_run.py`

**Files:**
- Create: `.claude/skills/trader-fx/alerts_run.py`, `.claude/skills/trader-fx/tests/test_alerts_run.py`
- Modify: `.gitignore` (ajouter `trader/fx/alerts_state.json`)

**Interfaces:**
- Consumes: `alert_state`, `alert_checks`, `alert_messages`, `telegram.send_message`, `fx.main(argv, deps)`, `data.fetch_bars`, `data.INTRADAY`, `economic_calendar.fetch_calendar`, `config.load_config`.
- Produces: `main(argv=None, deps=None) -> int`. Options : `--dry-run`, `--state PATH` (défaut `trader/fx/alerts_state.json`), `--alerts PATH` (défaut `trader/fx/alerts.json`), `--config PATH` (défaut `trader/fx/config.json`), `--now "AAAA-MM-JJ HH:MM"` (UTC, pour les essais). Clés de `deps` : `fetch_bars`, `fetch_calendar`, `brief` (appelable `(config_path) -> dict | None`, défaut : `fx.main(["brief", "--no-cache", "--out", <fichier temporaire>, "--config", config_path])` puis lecture du JSON), `send` (défaut `telegram.send_message`), `now`. Variables d'environnement : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADER_FX_CONFIG` ; si `GITHUB_OUTPUT` existe, y écrit `state_changed=true|false`. Code de sortie : 0, ou 1 quand un envoi échoue après sa nouvelle tentative, ou quand les secrets Telegram manquent hors `--dry-run`.

Déroulé (spec 3.1) : 1 configuration (le secret `TRADER_FX_CONFIG` est écrit dans le fichier de `--config` sans jamais être affiché, validé par `config.load_config`) ; 2 charger l'état et lire `alerts.json` (absent, illisible ou `v != 1` : suivi et annonces sautés avec une ligne de journal, la partie idées continue) ; 3 barres 5 minutes des symboles des règles, contacts (`since` de repli = champ `updated` du fichier) ; 4 calendrier, annonces ; 5 briefing, idées ; 6 envoi dans l'ordre stops et cibles, annonces, idées, chaque message marqué dans l'état seulement après succès ; `prune` avant la sauvegarde ; l'état n'est écrit que s'il a changé. Si des règles existent et qu'aucune barre n'est reçue pour elles : un seul message `down_message()` par jour (`down_notified_day`). Briefing indisponible : la partie idées est sautée avec une ligne. En `--dry-run` : aucun envoi, aucun fichier d'état écrit, chaque message s'affiche entre deux lignes `---`.

- [ ] **Step 1: Écrire les tests (échouent)** avec de fausses sources et un faux `send` : `test_full_run_sends_stops_then_events_then_ideas_in_order_and_marks_them` ; `test_second_run_sends_nothing_new` (même état) ; `test_failed_send_is_not_marked_and_exit_code_is_1` (puis le lancement suivant le renvoie) ; `test_missing_telegram_secrets_exit_1_except_in_dry_run` ; `test_dry_run_prints_messages_and_writes_no_state` ; `test_alerts_json_invalid_or_wrong_version_still_sends_ideas` ; `test_all_bars_missing_sends_one_down_message_per_day` ; `test_briefing_unavailable_skips_ideas_but_not_stops` ; `test_state_saved_only_when_changed_and_github_output_says_so` ; `test_trader_fx_config_secret_is_written_validated_and_never_printed` (valeur factice absente de la sortie standard et d'erreur ; un secret invalide donne une ligne d'erreur et le code 1) ; `test_closed_weekend_sends_no_idea_but_still_checks_stops` (Review Focus 5).
- [ ] **Step 2: Lancer** `-p "test_alerts_run.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** `alerts_run.py` : une fonction par étape (privées), `if __name__ == "__main__": sys.exit(main())`, sortie standard et d'erreur reconfigurées en UTF-8 comme `fx.py`.
- [ ] **Step 4: Relancer** le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 5: Commit** `feat(trader-fx): alerts_run.py (orchestration d'un lancement d'alertes)`

### Task 9: workflow, nettoyage, SKILL.md, vérifications

**Files:**
- Create: `.github/workflows/alerts.yml`, `.claude/skills/trader-fx/tests/test_alerts_workflow.py`
- Delete: `.github/workflows/probe.yml`, `probe/probe.py`
- Modify: `.claude/skills/trader-fx/SKILL.md`

- [ ] **Step 1: Écrire les tests (échouent)** dans `test_alerts_workflow.py` (lecture du texte du YAML, sans bibliothèque YAML) : le cron vaut exactement `*/15 7-21 * * 1-5` ; `workflow_dispatch` avec une entrée `dry_run` ; `concurrency` de groupe `alerts` avec `cancel-in-progress: false` ; `timeout-minutes: 10` ; `permissions: contents: read` ; les actions sont épinglées (`actions/checkout@v4`, `actions/cache/restore@v4`, `actions/cache/save@v4`) ; les trois secrets sont lus par `${{ secrets.… }}` dans `env:` et jamais dans une ligne `run:` ni un `echo` ; la clé de cache commence par `alerts-state-` avec `restore-keys: alerts-state-` ; la sauvegarde est conditionnée par `state_changed` ; le fichier `probe.yml` et le dossier `probe/` n'existent plus.
- [ ] **Step 2: Lancer** `-p "test_alerts_workflow.py"` ; attendu : FAIL.
- [ ] **Step 3: Écrire `alerts.yml`** (spec 3.1) : étapes checkout, restauration du cache, `python3 .claude/skills/trader-fx/alerts_run.py` (avec `--dry-run` si l'entrée `dry_run` vaut `true`), sauvegarde du cache ; supprimer le workflow et le dossier du test de faisabilité.
- [ ] **Step 4: Mettre à jour `SKILL.md`** (français, exact par rapport au code) : section « Serveur d'alertes » (ce que fait chaque lancement, les trois types d'alertes et les idées « en formation », la fréquence et le coût, les secrets à créer, `alerts.auto_push` et ce qui se passe quand il est faux, comment lancer à blanc depuis l'onglet Actions, les limites de la spec 6) ; compléter « Ce qu'il lit et écrit » (`alerts_state.json` n'est pas un fichier du dépôt) ; étape « Journal » : `alerts.json` est régénéré après chaque changement de trade ; la description du frontmatter ajoute « serveur d'alertes » et « alertes Telegram ».
- [ ] **Step 5: Suite complète** `python3 -m unittest discover -s .claude/skills/trader-fx/tests -v` (aussi `-W error`) ; attendu : tout PASS, sortie sans avertissement.
- [ ] **Step 6: Commit** `feat(trader-fx): workflow alerts.yml, SKILL.md du serveur d'alertes`
- [ ] **Step 7 (manuel, avec l'utilisateur, après son accord pour pousser) :** pousser `main`, créer le secret facultatif `TRADER_FX_CONFIG`, lancer « Alerts » à la main avec `dry_run` coché et lire les messages dans le journal du lancement ; puis un vrai lancement avec une règle fictive proche du prix actuel pour voir arriver un message sur Telegram. Consigner le résultat dans la section « Statut » de la spec.
