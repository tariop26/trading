# trader-fx : briefing publié automatiquement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** À 04 h 30 UTC (lundi au vendredi) et 22 h 15 UTC (dimanche au jeudi), un workflow GitHub lance le briefing, publie la page sur GitHub Pages et envoie sur Telegram le résumé et le lien.

**Architecture:** Un workflow `briefing.yml` à un seul job `publish` appelle un exécuteur Python `briefing_run.py` (sous-commandes `build` puis `notify`) qui réutilise `fx.main`, `page.render_page`, `briefing.render_summary` et `telegram.send_message`. La publication utilise les actions officielles Pages. Rien n'est publié si le briefing échoue.

**Tech Stack:** Python 3 (bibliothèque standard seulement), `unittest`, GitHub Actions (`actions/checkout@v6`, `actions/upload-pages-artifact@v5`, `actions/deploy-pages@v5`, `actions/cache/restore@v5`, `actions/cache/save@v5`, versions vérifiées sur les pages de publication le 2026-11-16, toutes sur Node 24), Telegram Bot API.

**Spec:** `docs/superpowers/specs/2026-11-16-trader-fx-briefing-publication-design.md` (à lire avant de commencer ; ses numéros de section sont cités ci-dessous).

## Décisions du plan (écarts à la spec, la spec est mise à jour en même temps)

- **Un seul job `publish`** au lieu des trois jobs `build`, `deploy`, `notify` : les étapes se suivent dans le même job (`build`, `upload-pages-artifact`, `deploy-pages`, puis `notify`), donc le fichier `site/summary.txt` est lu directement sur disque et rien ne passe par une variable ou un second artefact. Coût : le job reçoit `pages: write` et `id-token: write` en même temps que l'exécuteur ; le code exécuté est le nôtre et les secrets restent lus par `env:` seulement.
- **`--dry-run`** exécute le briefing, affiche le message et le résumé, n'écrit pas `site/` ; les étapes `upload-pages-artifact`, `deploy-pages` et `notify` sont sautées par `if: ${{ inputs.dry_run != true }}` (vrai pour un lancement planifié, dont `inputs` est vide).

## Global Constraints

- Python 3, bibliothèque standard seulement ; tests `unittest`, jamais de réseau dans un test (`fx.main`/le briefing, l'envoi Telegram, l'heure, l'environnement sont injectés).
- Commandes lancées depuis `C:/Users/m.poirat/trading`. Modules plats dans `.claude/skills/trader-fx/` ; chaque fichier de test commence par `import _path  # noqa`. Suite : `python3 -W error -m unittest discover -s .claude/skills/trader-fx/tests` (610 tests passent aujourd'hui, sortie sans avertissement).
- Messages : texte brut (pas de `parse_mode`), français, heure UTC dans le titre ; interdits comme mots entiers : achat, acheter, vente, vendre, buy, sell, et l'expression « à prendre » ; aucun conseil, aucune prévision.
- Aucun secret (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADER_FX_CONFIG`) dans une sortie, un message, un fichier de `site/` ou une ligne `run:` du workflow ; les secrets ne sont lus que par `env:`.
- Seul le contenu de `site/` (la page du briefing et `summary.txt`) est publié : jamais le journal, `alerts.json`, ni la configuration.
- Valeurs exactes de la spec : `cron: "30 4 * * 1-5"` et `cron: "15 22 * * 0-4"` (UTC) ; groupe de concurrence `briefing` sans annulation ; `timeout-minutes: 10` ; `environment: github-pages` ; titre `Briefing marchés, AAAA-MM-JJ HH:MM UTC.` ; message d'échec `Briefing indisponible (AAAA-MM-JJ HH:MM UTC) : <raison>. La page précédente reste en ligne.` ; message tronqué à 4 000 caractères.
- Chaque message de commit se termine par une ligne vide puis `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Ne rien pousser, ne rien publier.

## Review Focus

1. Le briefing réussit mais l'écriture de `site/` échoue à mi-chemin (disque, droits) : aucun fichier à moitié écrit, un message « Briefing indisponible », code 1 (Task 3).
2. Un dimanche soir ou un week-end (le briefing dit `closed_weekend`) : la page est publiée normalement, ce n'est pas une erreur (Task 3).
3. `summary.txt` absent ou vide au moment de `notify` : absent donne une ligne et le code 1 ; vide envoie le titre et le lien seuls (Task 4).
4. Secrets Telegram absents pendant `build` : la page est construite quand même (la publication n'en dépend pas) ; seul le message d'échec est impossible et le dit en une ligne (Task 3).
5. Résumé contenant `<`, `&`, des guillemets ou plus de 4 000 caractères : texte brut inchangé, tronqué avec le lien conservé en tête (Task 4).

---

### Task 1: valeur factice pour le chat id de test

**Files:**
- Modify: `.claude/skills/trader-fx/tests/test_telegram.py`

**Interfaces:**
- Produces: aucune ; la constante `CHAT` du test vaut `"123456789"`.

- [ ] **Step 1: Écrire le test (échoue)** : dans `test_telegram.py`, un test `test_the_real_chat_id_is_not_in_the_tests` qui lit les fichiers `tests/*.py` et vérifie que la chaîne `540412883` n'apparaît dans aucun (le test lui-même la construit par concaténation, `"5404" + "12883"`, pour ne pas se déclencher lui-même).
- [ ] **Step 2: Lancer** `python3 -W error -m unittest discover -s .claude/skills/trader-fx/tests -p "test_telegram.py"` ; attendu : FAIL.
- [ ] **Step 3: Remplacer** `CHAT = "540412883"` par `CHAT = "123456789"` ; relancer le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 4: Commit** `git add .claude/skills/trader-fx && git commit -m "test(trader-fx): valeur factice pour le chat id de test"`

### Task 2: actions Node 24 dans `alerts.yml`

**Files:**
- Modify: `.github/workflows/alerts.yml`, `.claude/skills/trader-fx/tests/test_alerts_workflow.py`

**Interfaces:**
- Produces: `alerts.yml` utilise `actions/checkout@v6`, `actions/cache/restore@v5`, `actions/cache/save@v5` (la constante `PINNED` du test suit).

- [ ] **Step 1: Mettre à jour `PINNED`** dans `test_alerts_workflow.py` avec ces trois versions ; **Step 2: lancer** le fichier ; attendu : FAIL (le YAML est encore en `@v4`).
- [ ] **Step 3: Changer** les trois lignes `uses:` de `alerts.yml` ; relancer le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 4: Commit** `ci(trader-fx): actions du serveur d'alertes sur Node 24 (checkout v6, cache v5)`

### Task 3: `briefing_run.py build`

**Files:**
- Modify: `.claude/skills/trader-fx/alerts_run.py` (`_apply_config_secret` devient `apply_config_secret`, tous ses appels suivent)
- Create: `.claude/skills/trader-fx/briefing_run.py`, `.claude/skills/trader-fx/tests/test_briefing_run.py`

**Interfaces:**
- Consumes: `alerts_run.apply_config_secret(secret: str, path: str) -> str | None` (ligne d'erreur ou `None`) ; `fx.main(argv)` (écrit sa ligne d'échec sur la sortie standard) ; `fx.TEMPLATE` ; `page.render_page(doc, template_path)` ; `briefing.render_summary(doc)` ; `telegram.send_message(token, chat_id, text) -> (bool, str | None)`.
- Produces:
  - `run_brief(config_path: str) -> tuple[dict | None, str]` : (document du briefing ou `None`, raison courte). Lance `fx.main(["brief", "--no-cache", "--out", <fichier temporaire>] + (["--config", config_path] si le fichier existe))` en capturant la sortie ; en cas d'échec la raison est la dernière ligne non vide capturée, coupée à 200 caractères (`"briefing impossible"` si rien) ; une exception donne `"briefing en échec (<NomDuType>)"`.
  - `title(now: datetime) -> str` = `"Briefing marchés, 2026-11-16 04:30 UTC."` ; `failure_message(now: datetime, reason: str) -> str`.
  - `build_parser()` : sous-commande `build` (`--out-dir` défaut `site`, `--config` défaut `trader/fx/config.json`, `--dry-run`, `--now "AAAA-MM-JJ HH:MM"` UTC) ; sous-commande `notify` (Task 4).
  - `main(argv=None, deps=None) -> int` ; clés de `deps` : `brief` (`config_path -> (doc | None, reason)`), `send`, `now`, `env`.

Comportement de `build` (spec 3.1) : écrit la configuration issue de `TRADER_FX_CONFIG` si elle existe (`apply_config_secret` ; erreur : une ligne, code 1) ; appelle `brief` ; en cas d'échec : n'écrit rien, envoie `failure_message` (sans secrets Telegram : une ligne qui dit que le message n'a pas pu partir), code 1 ; en cas de succès : construit `index.html` et `summary.txt` **en mémoire**, puis les écrit dans `--out-dir` (si l'écriture échoue : supprimer ce qui a été écrit, traiter comme un échec) ; un week-end (`closed_weekend`) n'est pas une erreur. Avec `--dry-run` : n'écrit rien, n'envoie rien, imprime le résumé et, en cas d'échec, le message d'échec.

- [ ] **Step 1: Écrire les tests (échouent)** dans `test_briefing_run.py`, avec un briefing de fixture (`tests/fixtures/briefing_sample.json`) : `test_build_writes_the_exact_page_and_the_summary` (`index.html` égal à `page.render_page(doc, fx.TEMPLATE)` ; `summary.txt` égal à `briefing.render_summary(doc) + "\n"`) ; `test_config_secret_is_written_validated_and_never_printed` et `test_invalid_secret_is_one_line_exit_1_no_value` (comme pour `alerts_run`) ; `test_brief_failure_writes_nothing_sends_one_failure_message_exit_1` (message exact `Briefing indisponible (2026-11-16 04:30 UTC) : <raison>. La page précédente reste en ligne.`, `--out-dir` absent) ; `test_exception_in_the_brief_is_a_failure_with_the_type_only` ; `test_write_failure_leaves_no_partial_site` (écriture simulée en échec sur le second fichier : le premier est supprimé, code 1, message d'échec) ; `test_closed_weekend_is_published_normally` ; `test_missing_telegram_secrets_do_not_stop_the_build_but_the_failure_notice_says_it_could_not_be_sent` ; `test_dry_run_writes_nothing_and_sends_nothing` ; `test_failure_reason_is_clipped_to_200_characters` ; `test_no_forbidden_word_or_secret_in_any_message` (regex RAW `\b(achat|acheter|vente|vendre|buy|sell)\b` avec contrôle négatif sur `survente`). Test de `run_brief` avec un `fx.main` simulé (monkeypatch) : succès, code 1 avec ligne d'erreur, exception.
- [ ] **Step 2: Lancer** `-p "test_briefing_run.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** `briefing_run.py` et renommer `apply_config_secret` ; relancer le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 4: Commit** `feat(trader-fx): briefing_run.py build (page du briefing pour GitHub Pages)`

### Task 4: `briefing_run.py notify`

**Files:**
- Modify: `.claude/skills/trader-fx/briefing_run.py`, `.claude/skills/trader-fx/tests/test_briefing_run.py`

**Interfaces:**
- Consumes: Task 3.
- Produces: `success_message(now: datetime, url: str, summary: str) -> str` ; `TELEGRAM_CLIP = 4000` ; sous-commande `notify --url URL [--summary-file PATH (défaut site/summary.txt)] [--dry-run] [--now ...]`.

Message de succès (spec 4) : `Briefing marchés, 2026-11-16 04:30 UTC.` / `Page : <url>` / ligne vide / résumé ; tronqué à `TELEGRAM_CLIP` caractères avec `…`, le titre et le lien toujours conservés ; résumé vide : titre et lien seuls. `notify` : secrets Telegram manquants (hors `--dry-run`) : une ligne, code 1 ; fichier de résumé absent : une ligne, code 1 ; échec d'envoi : une ligne avec la raison (code HTTP ou type d'erreur, jamais le token), code 1.

- [ ] **Step 1: Écrire les tests (échouent)** : `test_success_message_has_the_link_before_the_summary` (chaîne complète attendue) ; `test_a_10000_character_summary_is_clipped_under_4096_and_keeps_the_link` ; `test_special_characters_stay_as_they_are` (`Core <CPI> & "m/m"`) ; `test_empty_summary_sends_title_and_link_only` ; `test_missing_summary_file_is_one_line_exit_1` ; `test_missing_telegram_secrets_exit_1_except_in_dry_run` ; `test_send_failure_exit_1_without_the_token_in_the_output` ; `test_dry_run_prints_the_message_and_sends_nothing` ; interdit : aucun mot interdit dans le message de succès construit avec le résumé de la fixture.
- [ ] **Step 2: Lancer** `-p "test_briefing_run.py"` ; attendu : FAIL.
- [ ] **Step 3: Implémenter** `success_message` et la sous-commande `notify` ; relancer le fichier puis la suite complète ; attendu : PASS.
- [ ] **Step 4: Commit** `feat(trader-fx): briefing_run.py notify (message Telegram avec le lien de la page)`

### Task 5: workflow, SKILL.md, vérifications

**Files:**
- Create: `.github/workflows/briefing.yml`, `.claude/skills/trader-fx/tests/test_briefing_workflow.py`
- Modify: `.claude/skills/trader-fx/SKILL.md`, `docs/superpowers/specs/2026-11-16-trader-fx-briefing-publication-design.md` (le job unique, selon « Décisions du plan »)

- [ ] **Step 1: Écrire les tests (échouent)** dans `test_briefing_workflow.py` (lecture du texte du YAML, sans bibliothèque YAML ; même style que `test_alerts_workflow.py`) : les deux `cron` exacts et aucun autre ; `workflow_dispatch` avec une entrée `dry_run` booléenne par défaut `false` ; concurrence `briefing` avec `cancel-in-progress: false` ; `permissions: contents: read` au niveau du workflow, et `pages: write` et `id-token: write` seulement dans le job `publish` ; un seul job `publish` avec `environment:` de nom `github-pages` et `timeout-minutes: 10` ; actions utilisées exactement `actions/checkout@v6`, `actions/upload-pages-artifact@v5`, `actions/deploy-pages@v5` ; `upload-pages-artifact` avec `path: site` ; l'ordre des étapes (checkout, build, upload, deploy, notify) ; les trois étapes upload, deploy et notify portent `if: ${{ inputs.dry_run != true }}` ; `deploy` a `id: deployment` et `notify` lit `${{ steps.deployment.outputs.page_url }}` dans un `env:` (pas dans la ligne `run:`) ; les trois secrets ne sont lus que par `env:`, aucun `echo`, aucun `set -x` ; les commandes appellent `briefing_run.py build --out-dir site` (avec `--dry-run` quand la case est cochée) et `briefing_run.py notify --url "$PAGE_URL"`.
- [ ] **Step 2: Lancer** `-p "test_briefing_workflow.py"` ; attendu : FAIL.
- [ ] **Step 3: Écrire `briefing.yml`** (spec 3.1) ; mettre à jour la spec (un job `publish` à la place des trois jobs, `--dry-run` et conditions des étapes).
- [ ] **Step 4: Mettre à jour `SKILL.md`** (français, exact par rapport au code) : section « Briefing publié » (les deux heures et leurs jours, le lien `https://tariop26.github.io/trading/`, ce que contient le message Telegram, lancer à la main depuis le navigateur, les réglages faits une fois : dépôt public et Pages sur « GitHub Actions », la page publique montre la ligne « Compte » si `TRADER_FX_CONFIG` existe, la page précédente reste en ligne si le briefing échoue) ; compléter « Ce qu'il lit et écrit » (`site/` n'est jamais commité) ; ajouter `site/` à `.gitignore` ; la description du frontmatter ajoute « briefing automatique », « briefing sur téléphone » et « auto briefing ».
- [ ] **Step 5: Suite complète** `python3 -m unittest discover -s .claude/skills/trader-fx/tests -v` (aussi `-W error`) ; attendu : tout PASS, sortie sans avertissement.
- [ ] **Step 6: Commit** `feat(trader-fx): workflow briefing.yml (GitHub Pages et Telegram), SKILL.md`
- [ ] **Step 7 (manuel, avec l'utilisateur, après son accord pour pousser) :** pousser `main`, lancer « Briefing » à la main avec `dry_run` coché et lire le résumé et le message dans le journal ; puis lancer réellement ; ouvrir `https://tariop26.github.io/trading/` sur le téléphone et vérifier le message Telegram. Consigner le résultat dans la section « Statut » de la spec.
