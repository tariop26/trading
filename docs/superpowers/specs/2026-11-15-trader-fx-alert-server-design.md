# trader-fx : serveur d'alertes (sous-projet 3)

Date : 2026-11-15. Statut : en attente de relecture.
S'appuie sur `2026-11-13-trader-fx-briefing-design.md`, `2026-11-14-trader-fx-trade-ideas-design.md` et `2026-11-14-trader-fx-journal-design.md` (le journal produit `alerts.json`, que ce serveur lit).

## 1. Contexte et objectif

Le briefing, les idées de trade et le journal existent, mais tout se lance à la main. Rien ne prévient l'utilisateur quand une idée apparaît, quand le stop ou la cible d'un trade ouvert est touché, ni avant une annonce économique à fort impact.

Objectif : un serveur sur GitHub Actions qui, en séance, relance le briefing, surveille les trades ouverts et envoie des messages Telegram. Tous les calculs se font en Python pur, sans appel à Claude (le quota doit être ménagé).

Ce que l'utilisateur a dit :
- Le dépôt `tariop26/trading` est **privé** ; le serveur peut lire `alerts.json` dans le dépôt.
- Trois alertes, toutes voulues : stop touché, cible touchée, annonce à fort impact 30 minutes avant (seulement pour les devises de ses trades ouverts).
- Il veut aussi des alertes d'**idées de trade** (« trades à prendre »). Il a choisi de **tester la lecture 1** : relancer le briefing existant en séance et annoncer les nouvelles idées. Une idée est un plan mécanique à valider : les messages ne disent jamais « à prendre », achat, vente, ni aucun conseil.
- Le choix de prendre ou non une idée reste le sien.
- Il ne veut pas pousser `alerts.json` à la main à chaque changement de trade : `journal.py` le fait seul, après son accord explicite, pour ce seul fichier (niveaux, sans résultat).

Verdict du test de faisabilité (workflow `Probe sources`, lancé le 2026-11-15 sur un runner `ubuntu-latest`, Python 3.14.4) : Yahoo répond sur les deux hôtes (6 sondes sur 6, barres 1 h), le calendrier économique répond (119 événements), Telegram répond 200. Aucune dépendance ne bloque.

Critères de réussite :
1. Une nouvelle idée est annoncée une fois par jour UTC et par couple symbole et sens.
2. Un stop ou une cible touché après l'ouverture du trade donne un seul message par règle.
3. Une annonce à fort impact d'une devise d'un trade ouvert est annoncée une fois, entre 15 et 30 minutes avant.
4. Le coût reste sous 2 000 minutes Actions par mois (forfait gratuit, dépôt privé).
5. `--dry-run` montre exactement les messages sans rien envoyer ni mémoriser.
6. Un essai en direct fait arriver un vrai message sur le Telegram de l'utilisateur.
7. Après un `open`, un `amend` ou un `close`, le serveur connaît les nouveaux niveaux sans que l'utilisateur pousse quoi que ce soit (option `alerts.auto_push`).

## 2. Hors périmètre

- Déclarer, modifier ou clôturer un trade depuis Telegram (le format du journal le prévoit, la commande viendra plus tard).
- L'alerte « prix proche du stop ou de la cible ».
- Les lectures 2 (revenir sur le niveau d'entrée) et 3 (règles intrajournalières sur barres 1 h) des idées.
- Toute liaison avec le courtier ; tout ordre.
- Un signal « le serveur est vivant » (voir les limites).

## 3. Architecture

Une approche, un seul workflow et un seul exécuteur : un lancement fait les trois tâches avec les mêmes données. L'état de déduplication vit dans le cache d'Actions, pas dans l'historique git.

Fichiers (modules plats dans `.claude/skills/trader-fx/`, un fichier de test par module) :

| fichier | rôle | dépend de |
| --- | --- | --- |
| `.github/workflows/alerts.yml` | planification, secrets, cache d'état, appel de `alerts_run.py` | |
| `alert_state.py` | charger, nettoyer et écrire l'état de déduplication (fonctions pures sur un dictionnaire) | |
| `alert_checks.py` | fonctions pures : nouvelles idées, contacts de stop et de cible, annonces à venir | `data` (barres), `economic_calendar` |
| `alert_messages.py` | texte des messages Telegram (français, heure de Paris) | `plan`, `sessions` |
| `telegram.py` | envoi d'un message, avec nouvelle tentative ; aucune requête réseau si `dry_run` | |
| `alerts_run.py` | ligne de commande et orchestration d'un lancement | tous les précédents, `fx`, `config` |
| `journal.py` (modifié) | `open`, `amend` et `close` régénèrent `alerts.json` et, si `alerts.auto_push` est vrai, le commitent et le poussent (3.3) | `config`, `git` (via `subprocess`) |
| `config.py` (modifié) | nouvelle section facultative `alerts` : `{"auto_push": false}` | |

Supprimés : `.github/workflows/probe.yml` et `probe/probe.py` (le test de faisabilité jetable).

### 3.1 Un lancement

Le workflow se déclenche par `cron: "*/15 7-21 * * 1-5"` (UTC, du lundi au vendredi, de 07 h à 21 h UTC), et à la main (`workflow_dispatch`, avec une case `dry_run`). Il tourne dans le groupe de concurrence `alerts`, sans annuler le lancement en cours, avec `timeout-minutes: 10`. Il restaure l'état, lance `python3 .claude/skills/trader-fx/alerts_run.py`, puis sauvegarde l'état s'il a changé (clé `alerts-state-<run_id>`, restauration par préfixe `alerts-state-`).

`alerts_run.py` fait, dans cet ordre :
1. **Configuration.** Si le secret `TRADER_FX_CONFIG` existe, il écrit son contenu dans `trader/fx/config.json` (jamais affiché), puis le valide avec `config.load_config`. Sans lui, les valeurs par défaut s'appliquent et chaque message d'idée porte la ligne « taille calculée sur le capital par défaut ».
2. **Suivi des trades ouverts.** Il lit `trader/fx/alerts.json` ; pour les symboles des règles, il lit les barres de 5 minutes sur 5 jours (nouveau profil `data.INTRADAY = ("5m", "5d")`, jamais mis en cache) et cherche les contacts (4.2).
3. **Annonces.** Il lit le calendrier (`economic_calendar.fetch_calendar`) et cherche les annonces à venir (4.3).
4. **Idées.** Il lance `fx.main(["brief", "--no-cache", "--out", <fichier temporaire>])` puis lit le `briefing.json` produit et cherche les nouvelles idées (4.1). Le briefing complet est relancé à chaque lancement : le cache disque du runner est vide, un lancement à froid prend environ une minute.
5. **Envoi.** Messages dans cet ordre : stops et cibles, annonces, idées. Chaque message est marqué envoyé dans l'état seulement après une réponse 200 de Telegram.

### 3.2 Changement du journal : le champ `since`

Sans lui, une barre de 09 h qui a touché un niveau déclencherait une alerte pour un trade ouvert à 10 h. `journal.build_alerts` ajoute à chaque règle un champ `since` : l'heure UTC (ISO 8601) de l'ouverture du trade, ou du dernier déplacement du niveau (dernier évènement `stop_deplace` pour une règle de stop, dernier `cible_deplacee` pour une règle de cible). Ce n'est pas une donnée financière ; `v` reste à 1 (ajout compatible). Un `alerts.json` sans `since` (écrit avant ce changement) : le serveur prend l'heure `updated` du fichier, ce qui ne crée jamais de fausse alerte.

### 3.3 Comment le serveur reçoit les trades

Le serveur lit `trader/fx/alerts.json` dans le dépôt, branche `main`. `journal.py` le tient à jour tout seul :

1. `open`, `amend` et `close` enregistrent d'abord le trade dans `journal.json` (comme aujourd'hui), puis réécrivent `alerts.json` (option `--alerts PATH`, défaut `trader/fx/alerts.json` ; la sous-commande `alerts` reste).
2. Si `alerts.auto_push` vaut `true` dans `trader/fx/config.json` (défaut `false`), il commite ensuite **ce seul fichier** (`git commit -m "alerts: règles de stop et de cible" -- trader/fx/alerts.json`, sans toucher au reste de l'index ni de l'arbre de travail) et lance `git push`. Il ne pousse jamais `journal.json`, qui contient les résultats de l'utilisateur.
3. Il ne commite rien si `alerts.json` n'a pas changé. Il ne pousse que si la branche courante est `main` ; sinon il le dit.
4. Un échec après l'enregistrement du trade (dépôt git absent, pas de réseau, identifiants refusés, branche autre que `main`, push rejeté) n'annule rien : la confirmation du trade s'affiche, suivie d'une ligne « alerts.json non poussé : <raison>. Poussez-le à la main. », et le code de sortie reste 0.

Sans `auto_push`, `alerts.json` est tout de même régénéré mais reste local : l'utilisateur doit le pousser lui-même, et un trade clôturé non poussé continue de déclencher des alertes de stop. `SKILL.md` le dit.

## 4. Les vérifications

### 4.1 Idées

Une idée du briefing est annoncée quand toutes ces conditions sont vraies :
- Son couple (symbole, sens, date UTC) n'est pas dans `ideas_sent` de l'état.
- Aucune règle de `alerts.json` n'est ouverte sur le même symbole et le même sens (le trade est déjà pris).
- Son `since_close` n'indique ni stop franchi ni cible atteinte (idée caduque).

Au plus 3 idées par lancement, dans l'ordre du rang du briefing ; les autres restent en attente pour le lancement suivant et le dernier message le dit (« N autres idées en attente »). Une idée dont la taille est `to_confirm` ou `too_wide` est annoncée avec cette mention, jamais avec une taille inventée.

### 4.2 Stops et cibles

Pour chaque règle (`type` `stop` ou `cible`), parmi les barres de 5 minutes dont l'heure de début est strictement postérieure à `since` :
- stop d'un trade haussier : plus bas ≤ niveau ; stop d'un trade baissier : plus haut ≥ niveau ;
- cible d'un trade haussier : plus haut ≥ niveau ; cible d'un trade baissier : plus bas ≤ niveau.

Le contact est décidé sur les plus hauts et plus bas bruts des barres, pas sur le dernier prix : un contact entre deux lancements n'est pas manqué. Une règle déjà dans `rules_fired` n'envoie rien. Si le stop et la cible d'un même trade ont été touchés, deux messages partent. Si `since` est plus ancien que 5 jours, la fenêtre est limitée à ces 5 jours.

### 4.3 Annonces

Une annonce du calendrier (impact « High ») est annoncée quand elle est entre 15 et 30 minutes devant (bornes comprises), que sa devise est l'une des devises des trades ouverts, et que sa clé (`utc|devise|titre`) n'est pas dans `events_sent`. Les devises d'un trade ouvert sont celles de la paire pour un trade forex (`strength.pair_currencies`) ; pour un autre instrument, l'USD. Sans trade ouvert, aucune annonce.

## 5. Messages

Français, heure de Paris, mots « haussier » et « baissier ». Jamais : achat, acheter, vente, vendre, buy, sell, « à prendre », conseil, prévision. Aucun résultat, capital ni identifiant de compte (le serveur ne les connaît pas). Chaque message tient dans la limite de 4 096 caractères de Telegram.

- **Idée** : « Idée de trade, en formation, non confirmée à la clôture : EUR/JPY baissier. Entrée 176.700, stop 178.408, cible 173.161 (1:2). Taille 0.45 lot, risque 480.75 USD (0.5 % du capital). Règles : lose_ma20. Plan mécanique à valider, pas un conseil. Prix Yahoo, retardé. » Prix avec les `decimals` de l'idée.
- **Stop ou cible touché** : « Stop touché : EUR/JPY baissier, trade 2026-11-16-EURJPY-1. Niveau 178.408 franchi à 14:35 (plus haut de la barre 5 min : 178.412). Vérifiez la position chez le courtier. » Même forme pour « Cible touchée ».
- **Annonce** : « Annonce à fort impact dans 30 min : 14:30 Paris, USD, <titre>. Vos trades concernés : EUR/JPY. »
- **Panne** : « Impossible de vérifier vos stops : données Yahoo indisponibles. » Une fois par jour UTC au plus.

## 6. État, erreurs et sécurité

- **État** (`alerts_state.json`, restauré depuis le cache d'Actions) : `{"v": 1, "day": "AAAA-MM-JJ", "ideas_sent": [...], "rules_fired": [...], "events_sent": [...], "down_notified_day": "..."}`. `ideas_sent` et `down_notified_day` se remettent à zéro quand `day` change ; une règle de `rules_fired` est oubliée quand elle n'est plus dans `alerts.json` ; une annonce de `events_sent` est oubliée quand elle est passée. L'état est sauvegardé seulement s'il a changé. Un état corrompu ou d'une autre version : on repart d'un état vide, avec au pire un message en double.
- **Telegram** : une nouvelle tentative après un 429 (délai donné par la réponse, au plus 30 s) ou une erreur 5xx. Un échec final laisse le message non marqué (il repart au lancement suivant) et le lancement se termine en échec (code 1), pour que GitHub prévienne l'utilisateur.
- **`alerts.json`** absent, illisible ou d'une autre version : le suivi et les annonces sont sautés, une ligne le dit dans le journal du lancement, la partie idées continue.
- **Yahoo** : si les barres de 5 minutes ou le briefing sont indisponibles, la partie concernée est sautée ; si des règles existent et que leurs barres manquent, le message « Panne » part une fois par jour.
- **Secrets** (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADER_FX_CONFIG`) : jamais affichés. L'adresse Telegram contient le token : les erreurs ne donnent que le type et le code HTTP. `--dry-run` n'envoie rien, n'écrit pas l'état et affiche les messages.
- **Limites** : le seul calendrier gratuit connu (flux non officiel) peut disparaître, et Yahoo est retardé : « touché » veut dire « vu dans les données Yahoo », pas « exécuté chez le courtier ». GitHub peut retarder un lancement planifié de plusieurs minutes. Aucun signal ne prévient si le planificateur s'arrête. Les idées en séance viennent d'une barre du jour encore en formation : elles peuvent disparaître avant la clôture.

## 7. Coût

Environ 56 lancements par jour ouvré (4 par heure, 14 heures), au moins une minute facturée chacun : environ 1 200 minutes par mois, sous le forfait gratuit de 2 000 minutes des dépôts privés. Le lancement ne coûte rien de plus quand il n'y a ni trade ouvert ni nouvelle idée, mais il lance quand même le briefing (c'est la source des idées).

## 8. Tests

`unittest`, sans réseau : faux Telegram, fausses barres, faux calendrier, heure injectée.
- `alert_checks` : nouvelle idée annoncée ; même idée non renvoyée ; idée d'un trade déjà ouvert sautée ; idée caduque sautée ; au plus 3 idées ; contact de stop et de cible, dans les deux sens ; barre antérieure à `since` ignorée ; plus haut et plus bas bruts (contact entre deux lancements) ; annonce dans la fenêtre de 15 à 30 minutes, hors fenêtre, devise absente, sans trade ouvert, instrument non forex (USD).
- `alert_state` : remise à zéro au changement de jour ; oubli des règles disparues ; état corrompu ; version inconnue ; écriture seulement si changé.
- `alert_messages` : forme de chaque message avec chiffres exacts ; aucun mot interdit ; aucun champ de résultat ou de capital ; longueur ; `decimals` respectés ; mention « taille calculée sur le capital par défaut ».
- `telegram` : succès ; nouvelle tentative sur 429 et 5xx ; échec final ; le token n'apparaît dans aucune sortie ; `dry_run` sans réseau.
- `alerts_run` : orchestration complète avec fausses sources ; envoi puis marquage ; échec d'envoi non marqué et code de sortie 1 ; `alerts.json` invalide sans arrêt des idées ; `--dry-run` sans état écrit ni envoi ; secret de configuration écrit et jamais affiché.
- `journal` : `since` présent dans les règles (ouverture, stop déplacé, cible déplacée), et `alerts.json` sans champ financier.
- `journal` et `config` (envoi automatique, `git` simulé par un exécuteur injecté, jamais de vrai dépôt ni de réseau) : `alerts.json` régénéré après `open`, `amend` et `close` ; `auto_push` à `false` ou absent : aucun appel à git ; `true` : un seul commit limité au fichier puis un push ; pas de commit si le fichier n'a pas changé ; branche autre que `main` : pas de push et une ligne d'explication ; échec de commit ou de push : le trade reste enregistré, ligne d'avertissement, code 0 ; `journal.json` jamais ajouté au commit ; section `alerts` de la configuration validée (booléen exigé, clé inconnue refusée).
- Essai en direct, à part : lancement manuel à blanc, puis vrai lancement avec une règle fictive proche du prix actuel pour voir arriver le message sur Telegram.

## 9. Fichiers lus et écrits

| fichier | quoi |
| --- | --- |
| `trader/fx/alerts.json` | écrit par `journal.py` après chaque changement de trade (et poussé sur `main` si `alerts.auto_push`), lu par le serveur (règles `id`, `trade_id`, `symbol`, `type`, `side`, `level`, `decimals`, `since`) |
| `trader/fx/config.json` | écrit sur le runner depuis le secret `TRADER_FX_CONFIG`, jamais commité (déjà ignoré par git) |
| `alerts_state.json` | état de déduplication, dans le cache d'Actions |
| `SKILL.md` | section « Serveur d'alertes » : ce que fait chaque lancement, les secrets à créer, comment lancer à blanc, `alerts.auto_push` et ce qui se passe quand il est faux |
