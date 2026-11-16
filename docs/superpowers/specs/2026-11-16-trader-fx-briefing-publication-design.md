# trader-fx : briefing publié automatiquement (GitHub Pages et Telegram)

Date : 2026-11-16. Statut : en attente de relecture.
S'appuie sur `2026-11-13-trader-fx-briefing-design.md` (le briefing et sa page) et `2026-11-15-trader-fx-alert-server-design.md` (même schéma : un workflow GitHub, un exécuteur Python, Telegram).

## 1. Contexte et objectif

Aujourd'hui le briefing se met à jour quand l'utilisateur le demande à Claude sur son PC (`fx.py brief` puis `fx.py page`, puis publication en Artifact). Il en a besoin sans que le PC soit allumé, et lisible sur son téléphone.

Objectif : un workflow GitHub qui, à heure fixe, lance le briefing, publie la page sur GitHub Pages (un lien fixe à mettre en favori) et envoie sur Telegram le résumé et ce lien. Tous les calculs sont en Python, sans appel à Claude.

Ce que l'utilisateur a dit :
- Il passe le dépôt `tariop26/trading` en **public** : c'est un compte de prop firm, pas de l'argent réel. Le capital qui apparaîtrait sur la page ne le gêne pas.
- Il veut le briefing à **04 h 30 UTC** et à **22 h 15 UTC**. Hypothèse du spec, à corriger à la relecture : 04 h 30 du lundi au vendredi, 22 h 15 du dimanche au jeudi (le soir prépare le lendemain ; le vendredi soir ne sert à rien avant le week-end).
- Il lira la page sur son téléphone.

Critères de réussite :
1. Aux deux heures, la page à `https://tariop26.github.io/trading/` est remplacée par le briefing du moment, et un message Telegram donne le résumé et le lien.
2. Si le briefing échoue (Yahoo en panne), la page précédente reste en place, aucune page vide n'est publiée, et un message Telegram d'une ligne le dit.
3. Le lancement peut se faire à la main depuis le navigateur du téléphone (Actions, Run workflow).
4. `--dry-run` montre le résumé sans rien envoyer ni publier (le message de succès contient le lien de la page, connu seulement après la publication).
5. Aucun secret dans les journaux, les messages ou la page. Aucun mot interdit dans les messages.

## 2. Hors périmètre

- La page du journal (`journal.html`) : elle contient des résultats, elle n'est jamais publiée.
- Une commande Telegram qui déclenche le briefing (la mise à jour à la demande se fait depuis le navigateur).
- Plusieurs pages, un historique des briefings, une page par jour : seule la dernière est en ligne.
- Passer le dépôt en public et activer Pages : réglages GitHub faits par l'utilisateur (section 8).

## 3. Architecture

Un workflow, un job, un exécuteur ; même schéma que le serveur d'alertes.

| fichier | rôle | dépend de |
| --- | --- | --- |
| `.github/workflows/briefing.yml` | planification, permissions Pages, un job `publish` | |
| `.claude/skills/trader-fx/briefing_run.py` | sous-commandes `build` et `notify` ; construit le dossier `site/` et le message ; envoie le message | `fx`, `briefing`, `page`, `config`, `telegram`, `alerts_run` (le secret de configuration) |
| `alerts_run.py` (modifié) | `_apply_config_secret` devient publique (`apply_config_secret`) pour être réutilisée | |
| `tests/test_telegram.py` (modifié) | le chat id réel est remplacé par une valeur factice | |

### 3.1 Un lancement

Le workflow se déclenche par `cron: "30 4 * * 1-5"` et `cron: "15 22 * * 0-4"` (UTC ; 0 est le dimanche) et à la main (`workflow_dispatch`, avec une case `dry_run`). Groupe de concurrence `briefing`, sans annulation ; `permissions: contents: read` au niveau du workflow.

Un seul job `publish` (`timeout-minutes: 10`, `environment: github-pages`, `permissions: pages: write, id-token: write` en plus de `contents: read`), dont les étapes se suivent ; le résumé reste donc un fichier sur disque (`site/summary.txt`) d'une étape à l'autre :

1. `checkout`.
2. `briefing_run.py build --out-dir site` (avec `--dry-run` si la case est cochée). `build` :
   - écrit la configuration issue du secret `TRADER_FX_CONFIG` si elle existe (jamais affichée) ;
   - lance `fx.main(["brief", "--no-cache", "--out", <temporaire>, ...])`, puis `page.render_page` avec `report_template.html` ;
   - écrit `site/index.html` (la page) et `site/summary.txt` (le résumé de `briefing.render_summary`) ;
   - en cas d'échec du briefing : n'écrit rien dans `site/`, envoie le message « Briefing indisponible » (voir 4), et se termine avec le code 1 ; le job s'arrête, rien n'est publié.
3. `actions/upload-pages-artifact` sur `site/`, puis `actions/deploy-pages` (`id: deployment`) ; l'URL publiée sort de cette étape.
4. `briefing_run.py notify --url "$PAGE_URL"` : envoie le message de succès.
5. Si l'envoi du briefing à Pages échoue (étape `upload` ou `deploy`), `briefing_run.py fail --reason "publication sur GitHub Pages en échec"` envoie le message d'échec (même texte que 4, raison ci-contre). Un échec de `build` a déjà annoncé le sien et n'y mène pas.

Avec `--dry-run`, `build` exécute le briefing, imprime le résumé et n'écrit pas `site/` ; les étapes 3, 4 et 5 portent `if: ${{ inputs.dry_run != true }}` et sont sautées (la condition est vraie pour un lancement planifié, dont `inputs` est vide).

Versions des actions (vérifiées le 2026-11-16, toutes sur Node 24) : `actions/checkout@v6`, `actions/upload-pages-artifact@v5`, `actions/deploy-pages@v5`. Le serveur d'alertes passe aussi à `checkout@v6` et `cache@v5`.

## 4. Les messages Telegram

Texte brut, français, heure UTC (le titre ne donne pas l'heure de Paris : elle change avec l'heure d'été), aucun mot interdit (achat, acheter, vente, vendre, buy, sell, « à prendre »), aucun secret.

- **Succès** : `Briefing marchés, 2026-11-16 04:30 UTC.` / `Page : https://tariop26.github.io/trading/` / une ligne vide / le résumé de `render_summary`. Le lien est avant le résumé : si le résumé est coupé, le lien reste. Le message est tronqué à 4 000 caractères avec `…`.
- **Échec** : `Briefing indisponible (2026-11-16 04:30 UTC) : <raison courte>. La page précédente reste en ligne.` La raison est la ligne d'erreur de `fx.py` (une ligne, sans secret).

## 5. Erreurs et sécurité

- Un échec du briefing ne publie rien et n'écrase pas la page en ligne. `build` écrit d'abord des fichiers temporaires puis les met en place : une écriture qui échoue ne laisse ni fichier partiel ni page remplacée à moitié.
- Un échec de l'envoi à Pages est annoncé par le message d'échec ; un lancement planifié qui n'a pas lieu, ou arrêté par le délai de 10 minutes, n'est pas annoncé (GitHub peut le signaler par e-mail).
- Un échec d'envoi Telegram (`telegram.send_message`, avec sa nouvelle tentative) met le job en échec (code 1) sans défaire la publication, qui est déjà faite.
- Le secret `TRADER_FX_CONFIG` (facultatif) fait calculer les tailles sur le vrai capital ; la page publique affiche alors la ligne « Compte : … USD · risque par idée … ». Sans lui, les valeurs par défaut s'appliquent et la ligne le dit déjà.
- Les secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADER_FX_CONFIG`) ne sont lus que par `env:` dans le workflow, jamais dans une ligne `run:`, jamais affichés.
- Seul le contenu de `site/` est publié : la page du briefing. Ni `journal.json`, ni `alerts.json`, ni la configuration.
- La page ne fait aucune requête réseau (hors la feuille de polices du gabarit, déjà acceptée) ; son bandeau « périmé » apparaît au bout de 12 heures si le lien n'a pas été mis à jour.

## 6. Coût

Environ 10 lancements par semaine de moins de 2 minutes. Les minutes Actions sont gratuites et illimitées sur un dépôt public.

## 7. Tests

`unittest`, sans réseau : `fx.main`, l'envoi Telegram et l'heure sont injectés.
- `briefing_run build` : `site/index.html` est exactement `page.render_page(briefing, report_template.html)` ; `site/summary.txt` est le résumé ; le secret de configuration est écrit, validé, jamais affiché ; un secret invalide donne une ligne sans valeur et le code 1.
- Échec du briefing (code 1 de `fx.main`, ou exception) : `site/` reste vide ou absent, un seul message « Briefing indisponible » part, code 1.
- `briefing_run notify` : le message de succès contient le lien avant le résumé ; un résumé de 10 000 caractères est tronqué sous 4 096 avec le lien conservé ; échec d'envoi : code 1.
- Aucun mot interdit ni secret dans aucun message ; `--dry-run` n'envoie rien et n'écrit pas `site/`.
- Workflow (lecture du texte du YAML) : les deux `cron` exacts ; `workflow_dispatch` avec `dry_run` booléen ; concurrence `briefing` sans annulation ; permissions `contents: read` seulement au niveau du workflow, `pages: write` et `id-token: write` seulement dans le job `publish` ; `environment: github-pages` ; versions d'actions fixées ; secrets uniquement par `env:` ; un seul job `publish` ; étapes dans l'ordre checkout, build, upload, deploy, notify, les trois dernières conditionnées par `inputs.dry_run != true`.
- Essai en direct, à part (voir 8) : lancement manuel à blanc, puis lancement réel, vérifié sur le téléphone.

## 8. Mise en place, à faire par l'utilisateur (une seule fois)

1. Passer le dépôt en **public** : Settings, tout en bas, « Change visibility ». À faire seulement quand l'utilisateur est prêt : le dépôt montrera alors son nom et son adresse e-mail (sur les commits), `alerts.json`, et tout ce qui est commité.
2. Settings, Pages, Source : **GitHub Actions**.
3. Lancer « Briefing » à la main (case `dry_run` cochée d'abord), puis réellement, et ouvrir le lien sur le téléphone.

## 9. Fichiers lus et écrits

| fichier | quoi |
| --- | --- |
| `site/index.html` | écrit par `briefing_run build` : la page du briefing. Publié sur Pages ; jamais commité |
| `site/summary.txt` | écrit par `briefing_run build` : le résumé texte, passé au job `notify` |
| `trader/fx/config.json` | écrit sur le runner depuis le secret `TRADER_FX_CONFIG`, jamais commité |
| `SKILL.md` | section « Briefing publié » : les heures, le lien, comment lancer à la main, les réglages à faire, ce que la page publique montre |
