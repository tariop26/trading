# trader-fx : signaux en séance et alertes de trade (sous-projet 6)

Date : 2026-11-17. Statut : en attente d'approbation de l'utilisateur.
S'appuie sur `2026-11-13-trader-fx-briefing-design.md`, `2026-11-14-trader-fx-trade-ideas-design.md`, `2026-11-14-trader-fx-journal-design.md` et `2026-11-15-trader-fx-alert-server-design.md` (le serveur d'alertes que ce projet étend).

## 1. Contexte et objectif

Aujourd'hui l'utilisateur reçoit le briefing du matin et, rarement, des alertes d'idées : il en a reçu deux dans la nuit (EUR/JPY baissier `lose_ma20`, EUR/SGD baissier `breakdown_20d`). Le serveur fonctionne. Mais ces idées viennent de règles sur barres **journalières** : elles sortent peu et tard, quand la barre du jour a fini de se former, et au plus une fois par jour pour chaque paire et chaque sens. Sans trade ouvert, il n'y a ni alerte de stop ou de cible ni d'annonce. Aucune alerte n'est construite sur les mouvements en séance.

Objectif : que le serveur d'alertes détecte seul, en cours de séance, des trades sur forex, matières premières et indices (CFD), et les envoie sur Telegram avec un plan que l'utilisateur saisit **à la main** dans MetaTrader 5.

Ce que l'utilisateur a dit (à la lettre quand il est cité) :
- Il reste sur forex, CFD et matières premières.
- Son objectif final était des trades « tout seuls ». Sa prop firm interdit les EA : « Les traders disposant de comptes de 50 000 $ et plus doivent trader entièrement manuellement sur MetaTrader 4 ou MetaTrader 5, tant pour les comptes Challenge que FundedNext. » Il a **renoncé** à l'envoi automatique d'ordres : « On va faire 1 et 2 » (1 : détection en séance et alertes Telegram automatiques ; 2 : ordre passé à la main dans MT5).
- Premier signal : **A**, la cassure d'une plage de session. Puis : un signal **Bollinger** (variante 1 : retour dans la bande), **surachat/survente**, **englobante**, **cassure de fractale**.
- Politique d'alertes : **option c** (chaque signal peut alerter seul, classé par accord entre signaux, signal contraire = pas d'alerte), **jusqu'à 10 alertes par jour**.
- Il a validé les choix listés en 4.2 (univers, contenu de l'alerte, filtre d'annonces, pas d'IA dans la boucle, vocabulaire, rejeu historique en projet suivant).

Critères de réussite :
1. Un signal sur une barre de 15 minutes clôturée donne une alerte Telegram dans les 15 minutes qui suivent la clôture de cette barre (délai normal du cron : environ 7 à 10 minutes).
2. Au plus 3 alertes de signal par lancement et 10 par jour UTC ; aucune alerte en double pour la même barre.
3. Aucune alerte n'est calculée sur une barre non clôturée.
4. Chaque alerte porte un plan complet (sens, entrée, stop, cible, rapport 1:R, taille et risque, zone de validité, signaux concordants) saisissable à la main dans MT5.
5. `--dry-run` montre exactement les alertes qui partiraient, sans rien envoyer ni mémoriser.
6. Un lancement reste sous le délai de 10 minutes de GitHub Actions et le mois sous 2 000 minutes (dépôt public : gratuit ; à garder si le dépôt redevient privé).
7. Chaque famille de signal est une fonction pure (série de barres et position dans la série en entrée, signal ou rien en sortie), réutilisable telle quelle par le futur rejeu historique.

## 2. Hors périmètre, non-objectifs et anti-objectifs

Hors périmètre de ce projet :
- Le rejeu historique des signaux (projet suivant, voir 6) ; le lien Telegram vers MT5.
- Répondre à Telegram (boutons, commandes) ; déclarer un trade depuis Telegram.
- La stratégie B (idée journalière + moment d'entrée) ; le signal « compression puis expansion » ; la cassure de bande (variantes 2 et 3 de Bollinger).
- Un changement du briefing du matin et de ses idées swing, qui continuent comme avant.

**Anti-objectifs (échec même si « ça marche ») :**
- Tout ce qui passe un ordre, pilote MT5, simule une saisie humaine ou dissimule qu'un programme est en jeu. Ce projet n'ouvre aucune liaison avec MT5. L'utilisateur saisit chaque ordre lui-même.
- Une alerte présentée comme un conseil, ou avec les mots achat, acheter, vente, vendre, buy, sell, « à prendre », conseil, prévision, gagnant, profit.
- Une taille inventée : une taille non calculable reste « à confirmer ».
- Une inondation de Telegram : le plafond de 10 par jour est une limite dure.

## 3. Contraintes

- Python 3 standard, `unittest`, sans réseau dans les tests (faux Telegram, fausses barres, faux calendrier, heure injectée). Aucune dépendance nouvelle (le projet n'en a pas).
- Tout s'exécute dans le serveur existant (`.github/workflows/alerts.yml`, cron `7,22,37,52 7-21 * * 1-5`, UTC). L'état de déduplication reste dans `alerts_state.json` (cache d'Actions) ; toute extension de l'état reste compatible : un état ancien ou corrompu repart d'un état vide, avec au pire un message en double.
- Données : Yahoo (non officiel, retardé). Barres de 15 minutes. Le forex n'a pas de volume chez Yahoo : aucun signal de volume.
- Secrets inchangés : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADER_FX_CONFIG` (jamais affichés ; les erreurs ne donnent que le code HTTP).
- Toute règle de langage du projet s'applique (« haussier » et « baissier », « plan mécanique à valider »). Les messages tiennent dans la limite Telegram de 4 096 caractères.
- Le dépôt est public : les fichiers commités ne contiennent ni capital réel ni résultat. Les messages Telegram sont privés et affichent le risque en USD, comme les messages d'idées existants ; le capital vient du secret `TRADER_FX_CONFIG` (sinon valeur par défaut, avec la mention « taille calculée sur le capital par défaut »).

## 4. Approches et décisions

### 4.1 Approches considérées

1. **Choix de la détection en séance** (choisi : A).
   - **A. Cassure de plage de session** : plage asiatique, plages d'ouverture de Londres et de New York, cassure sur clôture de barre de 15 min. Réutilise les sessions et les données de 5 minutes du serveur ; le plus simple à tester.
   - **B. Idée journalière + moment d'entrée** : plus sélectif, plus complexe, moins d'alertes. Reporté.
   - **C. A filtrée par B** : reportée, ajoutable si A est trop bruyante.
2. **Variante Bollinger** (choisie : 1, retour dans la bande). Écartées : cassure de bande (2), compression puis expansion (3). Le retour dans la bande est le partenaire de A : A joue les marchés qui partent, lui joue ceux qui reviennent à la moyenne.
3. **Politique d'alertes** (choisie : c).
   - a. Chaque signal alerte seul : bruyant.
   - b. Deux signaux d'accord obligatoires : trop peu d'alertes.
   - **c. Seul ou à plusieurs, classés par score, plafonnés** : choisie.

### 4.2 Décisions validées par l'utilisateur

- Univers : les listes du briefing (forex, matières premières, indices), barres de 15 min, lundi à vendredi de 07 h à 21 h UTC (cron actuel), 3 meilleures alertes par lancement.
- Contenu d'une alerte : ce qu'on saisit dans MT5 (paire, sens, entrée, stop, cible, lots à 0,5 % de risque, zone de validité, signaux concordants), avec une table facultative des noms de symbole du courtier.
- Filtre d'annonces : pas d'alerte dans les 30 minutes qui précèdent une annonce à fort impact sur une devise de la paire.
- Pas d'IA dans la boucle : tout est calculé en Python, sans appel à Claude.
- Le rejeu historique est un deuxième projet, à faire avant que l'utilisateur se fie aux alertes.

### 4.3 Les signaux (définitions proposées par Claude : à valider par la relecture)

Tous sur barres de 15 min **clôturées** (barre dont la fin est ≤ « maintenant »). Chaque signal vaut pour un sens (haussier ou baissier) et produit un plan avec stop et cible. Valeurs par défaut, toutes réglables dans une section `intraday` de `config.json` (toute clé inconnue refusée, bornes validées, comme le reste de la configuration) :

| famille | déclencheur | stop | cible |
| --- | --- | --- | --- |
| `session_break` (A) | une barre clôture hors de la plage : Asie (00:00 à 07:00 UTC, déjà calculée dans `signals.asia_range`), ouverture de Londres, ouverture de New York (les 30 premières minutes de chaque session, d'après `sessions.SESSIONS`) | l'autre côté de la plage | 2R |
| `bb_return` (Bollinger, variante 1) | bandes 20 périodes, 2 écarts-types sur les clôtures ; la barre précédente a clôturé hors de la bande, la barre courante clôture de nouveau dedans ; le sens est celui du retour vers le milieu | au-delà de l'extrême de la barre qui était hors bande | bande du milieu |
| `rsi_exit` (surachat/survente) | RSI 14 sous 30 à la barre précédente et ≥ 30 à la courante (haussier) ; au-dessus de 70 puis ≤ 70 (baissier). Le signal part au retour dans la zone normale, pas pendant que le prix reste en zone | 1,5 ATR (15 min) | 2R |
| `engulfing` | le corps de la barre courante englobe celui de la précédente, de couleur opposée, après au moins 3 barres consécutives dans le sens opposé | au-delà de l'extrême de l'englobante | 2R |
| `fractal_break` | fractale de Williams (un extrême entouré de 2 barres moins extrêmes de chaque côté, confirmée 2 barres plus tard) ; une barre clôture au-delà de la dernière fractale confirmée | la dernière fractale opposée confirmée, ou 1,5 ATR s'il n'y en a pas | 2R |

Règles communes (propositions) : l'entrée est la clôture de la barre du signal, arrondie comme les idées du briefing ; un plan impossible après arrondi aux pas de prix est écarté ; le rapport 1:R minimal est réglable (défaut 1:1, un plan en dessous est écarté avec sa raison). La distance minimale au stop du briefing (0,15 % du prix) est trop large pour des barres de 15 minutes (elle écarterait presque tout) : les signaux ont leur propre minimum `intraday.min_stop_pct` (défaut 0,05 %, à ajuster après mesure sur des barres réelles). Un maximum écarte les stops trop larges, par exemple une plage asiatique démesurée (cible lointaine, taille minuscule) : `intraday.max_stop_daily_atr` (défaut 1,0 : stop au plus égal à 1 ATR journalier, calculé avec `signals.atr`), le plan est écarté avec sa raison au-delà. `session_break` n'alerte que dans les 3 heures qui suivent la fin de la plage, une fois par plage et par sens.

### 4.4 Classement, plafonds et déduplication (propositions)

- **Score** d'une alerte : +2 par famille de signal concordante dans la fenêtre des 4 dernières barres clôturées du symbole (1 heure), +1 si la tendance journalière (`signals.trend`) va dans le sens, −1 à contre-sens. Un signal contraire dans la même fenêtre annule l'alerte (raison « signaux contradictoires », comme les idées du briefing). Les poids sont réglables.
- **Diversification** : au plus 2 alertes par exposition de devise (même logique que `plan._diversify`).
- **Plafonds** : 3 alertes par lancement, 10 par jour UTC (limite dure de l'utilisateur) ; au-delà, les alertes restantes sont écartées et le dernier message du jour le dit une fois (« plafond du jour atteint »). Classement : score décroissant, puis nombre de signaux, puis symbole. Le classement agit à l'intérieur d'un lancement ; d'un lancement à l'autre c'est premier arrivé, premier servi (aucune capacité réservée). Un score minimal facultatif `intraday.min_score` (défaut : aucun) permet de couper les alertes faibles si les 10 sont épuisés trop tôt dans la journée.
- **Déduplication** : jamais deux alertes pour la même barre, le même symbole et le même sens ; un délai de repos de 2 heures par symbole et sens (réglable) avant une nouvelle alerte. Exception, le **renforcement** : pendant le délai de repos, un nouveau signal concordant sur le même symbole et le même sens produit une nouvelle alerte seulement si son score est strictement supérieur à celui de la dernière alerte envoyée pour ce couple ; le message dit alors « signal renforcé » et rappelle les signaux déjà vus. Cette alerte compte dans les plafonds.
- **Cohabitation avec l'existant** : les alertes d'idées du briefing gardent leur plafond de 3 par lancement ; le plafond de 10 par jour ne compte que les alertes de signal. Une alerte de signal est sautée quand un trade de même symbole et de même sens est déjà ouvert (règle dans `alerts.json`), et quand le marché est fermé ou le plan est caduc : plus de 30 minutes (2 barres) écoulées depuis la **clôture** de la barre du signal. Si `alerts.json` est absent ou illisible, la vérification des trades ouverts est sautée et l'alerte part quand même (une ligne le dit dans le journal du lancement) ; `alerts.json` peut aussi être en retard sur les trades réels, l'utilisateur sait ce qu'il tient.
- **Zone de validité** : chaque alerte donne un prix limite d'entrée (entrée + 0,25 R dans le sens du trade) ; au-delà, le plan est caduc. Le message le dit.

### 4.5 Message (proposition)

Français, heure de Paris, même vocabulaire que les messages existants. Exemple de forme :

« Signal en séance, non confirmé par le courtier : EUR/JPY baissier. Signaux : session_break (Londres), rsi_exit. Barre 15 min de 09:15 Paris. Entrée 176.700 (zone valable jusqu'à 176.640), stop 177.100, cible 175.900 (1:2). Taille 0.45 lot, risque 480.75 USD (0.5 % du capital). Plan mécanique à valider, pas un conseil. Prix Yahoo, retardé. »

Le nom du symbole peut être traduit par une table facultative `intraday.mt5_symbols` (nom Yahoo vers nom du courtier), pour les suffixes de FundedNext.

## 5. Contenu et fichiers (suggestion, au choix du constructeur)

Modules plats dans `.claude/skills/trader-fx/`, un fichier de test par module, comme le reste du projet :

| fichier | rôle |
| --- | --- |
| `intraday_signals.py` | les cinq familles de signaux, fonctions pures (aucun réseau, aucune horloge interne) |
| `intraday_plan.py` | du signal au plan (stop, cible, arrondis, taille via `sizing`), score, classement, plafonds |
| `alert_checks.py` (étendu) | filtre d'annonces et règles de cohabitation avec les trades ouverts |
| `alert_messages.py` (étendu) | texte de l'alerte de signal |
| `alert_state.py` (étendu) | compteur du jour, délais de repos, barres déjà alertées |
| `alerts_run.py` (étendu) | étape « signaux en séance » ajoutée au lancement, après les stops, les annonces et les idées, avant l'envoi |
| `config.py` (étendu) | section facultative `intraday` |
| `SKILL.md` | section « Signaux en séance » |

## 6. Rejeu historique (projet suivant)

Avant que l'utilisateur se fie aux alertes, un rejeu fait tourner les mêmes fonctions de signal sur l'historique (barres de 15 min), avec stop et cible, et rapporte honnêtement : nombre de signaux, taux de réussite et espérance en R par famille, avec leur effectif et l'avertissement d'échantillon. Ce projet ne le construit pas, mais sa contrainte de conception (fonctions pures) est un critère de réussite (7). **Tant que le rejeu n'existe pas, `SKILL.md` et les alertes disent que ces signaux n'ont pas été testés sur l'historique.**

## 7. Journal

Un trade pris à partir d'une alerte de signal n'est pas dans `briefing.json` : `journal.py open` le déclare « hors plan » et exige `--stop`. Acceptable pour la version 1 ; le nom des familles de signal pourra servir d'étiquettes de règle. Un `open --from-alert` est à décider plus tard.

## 8. Erreurs et risques

- Yahoo indisponible ou barres de 15 minutes manquantes pour un symbole : ce symbole est sauté, une ligne le dit dans le journal du lancement ; si toutes les barres manquent, le message « Panne » existant part une fois par jour.
- GitHub peut retarder ou abandonner un lancement planifié : une alerte peut arriver tard (zone de validité et caducité à 2 barres) ou jamais. Rien ne signale l'arrêt du planificateur.
- Un lancement de 104 symboles en barres de 15 minutes doit tenir sous le délai de 10 minutes avec le briefing déjà relancé à chaque lancement. Le constructeur le mesure ; au besoin, `intraday.symbols` restreint l'univers.
- « Clôturé » veut dire « vu dans les données Yahoo » : l'entrée à saisir est un plan, le prix du courtier diffère (spread, glissement).
- Cinq familles sur de nombreux symboles augmentent les faux signaux : le plafond limite le bruit mais ne prouve pas que les signaux sont bons (voir 6).

## 9. Tests

`unittest`, sans réseau, heure injectée, séries de barres fabriquées avec résultat connu :
- Chaque famille, dans les deux sens : signal attendu, aucun signal quand la condition manque d'une barre, aucune lecture d'une barre non clôturée (pas d'anticipation), arrondis de prix (JPY à 3 décimales).
- Score : accord, tendance, contradiction (alerte annulée), diversification, ordre des égalités.
- Plafonds : 3 par lancement, 10 par jour, message de plafond unique, remise à zéro au changement de jour UTC.
- Déduplication : même barre, délai de repos, état corrompu ou ancien.
- Filtres : annonce à fort impact dans les 30 minutes, trade déjà ouvert, marché fermé, barre trop ancienne, plan impossible, stop trop proche, rapport 1:R sous le minimum.
- Message : forme exacte, `decimals`, aucun mot interdit, aucun résultat de trade, risque en USD cohérent avec la configuration (mention « capital par défaut » sans secret), longueur, table `mt5_symbols`.
- Orchestration : `alerts_run` avec fausses sources, envoi puis marquage, échec d'envoi non marqué, `--dry-run` sans état écrit ni envoi.
- Configuration : section `intraday` validée (clé inconnue refusée, bornes).

## 10. Ce qui est laissé au constructeur

Le découpage exact en modules et fonctions ; les valeurs numériques marquées « proposition » si un essai montre mieux (le dire) ; la source des barres de 15 minutes (fetch direct à 15 min ou regroupement des barres de 5 minutes) ; la mesure de durée d'un lancement et la réduction d'univers éventuelle ; le format exact de l'état étendu ; le choix de réutiliser ou de dupliquer des helpers de `plan.py` et `signals.py`.
