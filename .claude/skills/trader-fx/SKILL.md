---
name: trader-fx
description: >-
  Briefing forex, matières premières et indices (CFD). Lit des graphiques
  Yahoo gratuits et retardés (jour et 1 heure) pour environ 104 symboles : paires
  forex, matières premières, indices. Calcule la force des devises (1, 5 et 20
  séances), lit le calendrier économique de la semaine (annonces à fort impact
  des prochaines 24 h), cherche les setups swing (cassure du plus haut de 20
  jours, drapeau haussier, retour au-dessus de la moyenne 20 jours, survente,
  rebond de survente, et leurs règles baissières miroir) avec RSI, ATR et
  tendance, regroupe les signaux corrélés par devise commune, range les
  meilleures idées dans les deux sens en « trades potentiels » avec un plan
  mécanique (entrée, stop, cible) et une taille de position calculée pour le
  compte de l'utilisateur (risque fixé, lots, levier), et prépare un plan du
  jour (niveaux de la veille et de la semaine, plage de la session asiatique,
  sessions Tokyo, Londres, New York). Écrit trader/fx/briefing.json et une page
  HTML à publier en Artifact. Tient aussi un journal de trading : les trades
  réellement pris (entrée, taille, stop, cible, clôture), leur résultat en USD
  et en R, des statistiques honnêtes (avec leur nombre de trades), les règles
  de stop et de cible des trades ouverts (alerts.json) et une page « Journal
  de trading ». Un serveur d'alertes sur GitHub Actions surveille les stops et
  les cibles, annonce les annonces à fort impact et les idées de trade en
  formation, détecte des signaux en séance sur des barres de 15 minutes (cinq
  familles, plafonnés à 10 par jour, à saisir à la main dans MT5) et écrit sur
  Telegram. Un briefing automatique publie la page du
  briefing sur GitHub Pages (lisible sur téléphone) à 04 h 30 et 22 h 15 UTC et
  envoie le lien et le résumé sur Telegram. Use when the user says "briefing forex", "scan
  forex", "force des devises", "calendrier économique", "matières premières",
  "indices", "briefing CFD", "trades potentiels", "taille de position", "idées
  de trade", "journal de trading", "statistiques de trades", "j'ai pris
  l'idée", "forex briefing", "currency strength", "economic calendar", "what
  is moving in forex", "commodities and indices scan", "trade ideas", "position
  size", "lot size", "trading journal", "trade stats", "serveur d'alertes", "alertes Telegram",
  "alert server", "Telegram alerts", "signaux en séance", "alertes intraday",
  "intraday signals", "briefing automatique", "briefing sur
  téléphone", "auto briefing", "briefing on my phone", or at the start of a
  forex / CFD trading day.
argument-hint: "[brief | page] [--list FILE] [--no-cache] [--json] [--config PATH] ; journal.py [open | amend | close | list | stats | alerts | page]"
---

# trader-fx

Le briefing FX lit des graphiques gratuits et dit lesquels ont matché une règle.
C'est tout. Une liste de graphiques qui ont matché une règle n'est pas une liste de
positions à prendre, et un setup sur un graphique n'est pas une prévision. La
plupart des particuliers qui tradent des CFD ou du forex perdent de l'argent ;
ce briefing ne change rien à cela. Il vous évite d'ouvrir 104 graphiques à la
main. Les données sont des données Yahoo retardées, jamais du temps réel.

`${CLAUDE_SKILL_DIR}` ci-dessous est le dossier de ce skill (là où vit ce
SKILL.md). Les commandes se lancent depuis la racine du dépôt.

```bash
python3 "${CLAUDE_SKILL_DIR}/fx.py" brief                    # -> trader/fx/briefing.json + résumé terminal
python3 "${CLAUDE_SKILL_DIR}/fx.py" brief --list trader/lists/fx_pairs.txt   # une seule famille (--list est répétable)
python3 "${CLAUDE_SKILL_DIR}/fx.py" brief --no-cache         # ignore le cache disque
python3 "${CLAUDE_SKILL_DIR}/fx.py" brief --json             # JSON complet sur la sortie standard
python3 "${CLAUDE_SKILL_DIR}/fx.py" brief --now "2026-11-13 07:00"   # fige l'heure (New York), pour les essais
python3 "${CLAUDE_SKILL_DIR}/fx.py" brief --config PATH      # autre fichier de configuration (défaut : trader/fx/config.json)
python3 "${CLAUDE_SKILL_DIR}/fx.py" page                     # trader/fx/briefing.json -> trader/fx/briefing.html
python3 "${CLAUDE_SKILL_DIR}/fx.py" page --in PATH --out PATH   # défauts : --in trader/fx/briefing.json, --out trader/fx/briefing.html
```

Options de `brief` : `--list FILE` (répétable ; par défaut les trois listes
`trader/lists/fx_pairs.txt`, `commodities.txt`, `indices.txt`), `--no-cache`,
`--json`, `--now "YYYY-MM-DD HH:MM"` (heure de New York), `--out PATH` (par
défaut `trader/fx/briefing.json`), `--config PATH` (par défaut
`trader/fx/config.json`, voir « Configuration »). Code de sortie 0 quand le
briefing est produit, 1 sinon, avec une ligne d'explication. Si aucun symbole
n'est reçu, ou si la configuration est invalide, aucun `briefing.json` n'est
écrit.

## Ce qu'il lit et écrit

| fichier | quoi |
| --- | --- |
| `trader/lists/fx_pairs.txt`, `commodities.txt`, `indices.txt` | lus par `brief` : une ligne `SYMBOLE\|Nom` par symbole (symboles Yahoo : `EURUSD=X`, `GC=F`, `^GSPC`) |
| `trader/fx/config.json` | lu par `brief`, facultatif : capital, risque, levier, table de contrats (voir « Configuration »). Contient le capital de l'utilisateur : ignoré par git |
| `trader/fx/briefing.json` | écrit par `brief` : `as_of`, `market_state`, `counts`, `data_age`, `calendar`, `strength`, `swing`, `trade_ideas`, `day_plan`, `warnings`, `disclaimer` |
| `trader/fx/briefing.html` | écrit par `page` : page autonome, données intégrées, aucun appel réseau |
| `trader/fx/cache/` | cache disque des barres Yahoo : 6 h pour les barres journalières (jamais réutilisé d'un jour UTC à l'autre), 10 min pour les barres 1 h. Ignoré par git |
| `trader/fx/journal.json` | le journal des trades pris : lu par toutes les sous-commandes de `journal.py`, écrit par `open`, `amend` et `close` (écriture atomique). Contient les résultats de l'utilisateur ; versionné par git |
| `trader/fx/journal.json.bak` | copie de la version précédente du journal, faite avant chaque écriture de `open`, `amend` et `close`. Ignorée par git |
| `trader/fx/alerts.json` | écrit par `journal.py` après chaque `open`, `amend` et `close` (et par `journal.py alerts`) : les niveaux de stop et de cible des trades ouverts, avec `since` (depuis quand surveiller) ; poussé sur `main` si `alerts.auto_push` ; lu par le serveur d'alertes. Versionné par git |
| `trader/fx/alerts_state.json` | écrit par `alerts_run.py` : ce qui a déjà été envoyé (idées du jour, règles déclenchées, annonces, jour de la dernière alerte de panne). Sur GitHub il vit dans le cache d'Actions. Ignoré par git |
| `site/` | écrit par `briefing_run.py build` : `index.html` (la page du briefing) et `summary.txt` (le résumé texte). Publié sur GitHub Pages par le workflow ; jamais commité (ignoré par git) |
| `trader/fx/journal.html` | écrit par `journal.py page` : page « Journal de trading », données intégrées, aucun appel réseau. Contient les résultats : ignorée par git, à publier en Artifact privé seulement |

`briefing.json` et `briefing.html` sont des sorties du jour, ignorées par git.
`journal.json`, lui, n'est pas une sortie du jour : c'est la mémoire des trades.
`journal.py` lit aussi `trader/fx/briefing.json` (pour retrouver l'idée d'un
trade) et `trader/fx/config.json` (capital, plafond de risque, table de
contrats).

## Les données

- Source : l'endpoint graphique v8 de Yahoo Finance, gratuit, non officiel,
  parfois en retard. Barres journalières (6 mois) pour tous les symboles ;
  barres 1 h (5 jours) seulement pour les symboles qui ont matché une règle et
  pour les 7 paires majeures. query2 d'abord, query1 en repli.
- Les prix Yahoo sont des prix de référence. Le prix de votre courtier CFD
  diffère (spread, financement, écart de cotation).
- Un briefing complet à froid prend environ 30 secondes (mesuré à 31 s le
  2026-11-14 pour 104 symboles, avec 3 requêtes en parallèle ; environ 85 s en
  séquentiel). Avec le cache, un second passage est quasi immédiat.
- Résultat partiel dit partiel : « Reçus : N sur M (k en échec) ». Le résumé et la
  page listent les symboles en échec ; les raisons sont dans `briefing.json`
  (`counts.failed[].reason`), et un avertissement le dit quand des données sont
  périmées ou en échec. Un symbole avec moins de 30 séances complètes est
  exclu de l'analyse et compté à part.
- Le calendrier vient d'un flux public non officiel (`nfs.faireconomy.media`).
  Il peut changer ou disparaître. Dans ce cas le briefing indique
  `calendar.status` `unavailable` ou `partial` avec une raison, jamais un
  calendrier « ok » vide. Le fichier de la semaine suivante n'est en général
  publié que plus tard dans la semaine : un statut `partial` avec « pas encore
  publié » est normal en fin de semaine.
- `zoneinfo` a besoin du paquet `tzdata` sous Windows si les fuseaux horaires
  manquent : `pip install tzdata`. Sans lui, `fx.py` échoue dès l'import avec
  une trace d'erreur Python, pas avec un message d'une ligne et un code de
  sortie 1.

## Le briefing

| partie | contenu |
| --- | --- |
| état et comptes | marché ouvert ou fermé (week-end : du vendredi 17:00 au dimanche 17:00, heure de New York), heure Paris et New York, symboles demandés, reçus, analysés, échecs |
| force des devises | score par devise sur 1, 5 et 20 séances, calculé sur les paires reçues ; la meilleure et la pire sur 5 séances sont dites dans le résumé |
| calendrier | annonces de la semaine, à fort impact dans les prochaines 24 h, en heure de Paris et de New York |
| setups swing | `breakout_20d`, `bull_flag`, `reclaim_ma20`, `oversold`, `oversold_bounce` et leurs miroirs baissiers (voir « Trades potentiels ») avec RSI, ATR en % du prix et tendance, par famille (forex, matières premières, indices) ; le message de corrélation dit combien de signaux forex partagent une devise (par exemple « 6 des 9 signaux forex concernent le dollar (USD) : signaux corrélés, pas indépendants ») |
| trades potentiels | `trade_ideas` : au plus 5 idées haussières ou baissières, chacune avec score, entrée, stop, cible, taille et risque ; risque cumulé ; idées écartées et leur raison (voir « Trades potentiels ») |
| plan du jour | sessions Tokyo, Londres, New York ; niveaux par symbole : plus haut et plus bas de la veille, de la semaine précédente, de 20 jours, plage de la session asiatique (00:00 à 07:00 UTC) et plus haut/bas du jour |
| avertissements | marché fermé, symboles exclus, calendrier partiel, cache périmé utilisé après un échec (âge affiché) |

Le résumé terminal tient en 40 lignes au plus ; il dit toujours la date de la
dernière barre (« Dernière barre : AAAA-MM-JJ »), pas seulement le week-end. Il
contient le bloc « Idées de trade (N), plan mécanique à valider » (8 lignes au
plus, une par idée, puis la ligne « Risque cumulé »). La page web a sept
sections : Trades potentiels (juste après l'en-tête), Résumé, Force des
devises, Calendrier, Setups swing, Plan du jour, Avertissements. Thème clair et
sombre ; sur un écran de 640 px ou moins la page est repensée pour le téléphone (barre de
navigation, blocs repliables, tableaux en cartes : voir « Briefing publié »).

## Trades potentiels

Une idée est un plan mécanique issu des règles, à valider, pas un conseil.
Les règles existent dans les deux sens ; les règles baissières sont le miroir
des règles haussières, calculées sur les clôtures (30 séances minimum).

| haussier | baissier (miroir) | type |
| --- | --- | --- |
| `breakout_20d` : clôture au-dessus des 20 clôtures précédentes | `breakdown_20d` : clôture sous les 20 clôtures précédentes | déclencheur |
| `bull_flag` : hausse de plus de 10 % puis 5 séances serrées (moins de 5 %) | `bear_flag` : baisse de plus de 10 % puis 5 séances serrées | déclencheur |
| `reclaim_ma20` : retour au-dessus de la moyenne 20 jours | `lose_ma20` : passage sous la moyenne 20 jours | déclencheur |
| `oversold_bounce` : RSI sous 30 hier, clôture en hausse | `overbought_reject` : RSI au-dessus de 70 hier, clôture en baisse | déclencheur |
| `oversold` : RSI 14 sous 30 | `overbought` : RSI 14 au-dessus de 70 | état |

- Un déclencheur peut créer une idée. Un état (`oversold`, `overbought`) compte
  dans le score mais ne crée jamais une idée à lui seul.
- Un symbole a une idée haussière s'il a au moins un déclencheur haussier et
  aucun déclencheur baissier ; inversement pour une idée baissière. Les deux à
  la fois : pas d'idée, raison « signaux contradictoires ».
- Score : +2 par déclencheur concordant, +1 si la tendance va dans le sens de
  l'idée, −1 si elle va à contre-sens (0 si `mixed` ou absente), +1 si le RSI
  est sous 30 pour une idée haussière ou au-dessus de 70 pour une idée
  baissière, −1 dans le cas contraire. Classement : score décroissant, puis
  nombre de déclencheurs, puis symbole. Chaque idée porte la liste « Pourquoi »
  de ses points.
- Diversification : chaque idée porte des expositions par devise (une idée
  haussière sur `EURUSD=X` est plus EUR et moins USD). Au plus 2 idées retenues
  par exposition (`ideas.max_per_exposure`) : la suivante est écartée avec la
  raison « corrélée à <symbole> ». Au plus 5 idées affichées (`ideas.max_shown`) :
  les suivantes sont écartées avec « au-delà des 5 idées affichées (score S) ».
  Hors forex, l'exposition est le symbole lui-même.
- Égalités : à score égal (et à nombre de déclencheurs égal), l'ordre est
  alphabétique. `ties_at_cutoff` compte les idées écartées par la limite
  d'affichage qui ont le même score que la dernière affichée, et la page le dit
  (« N autres idées ont le même score que la dernière affichée »). Rien n'est
  choisi pour l'utilisateur.
- Plan : entrée = dernière clôture, arrondie au pas de prix le plus proche ;
  stop = 1,5 ATR de la clôture (sous l'entrée pour une idée haussière, au-dessus
  pour une baissière), arrondi en s'éloignant de l'entrée ; cible = 2 fois la
  distance arrondie entrée-stop, du côté opposé, arrondie en se rapprochant de
  l'entrée. Pas de prix : forex au dixième de pip (5 décimales, 3 pour une
  cotation en JPY) ; autres instruments selon le prix (sous 10 : 4 décimales,
  sous 100 : 3, sinon 2) ; chaque idée porte ses `decimals`. La taille est
  calculée sur l'entrée et le stop arrondis, ceux qui sont affichés. `rr` est le
  rapport nominal (`target_r`) : la cible est recalculée depuis la distance
  arrondie, puis arrondie vers l'entrée ; le rapport réalisé est égal au
  nominal quand `target_r` × distance tombe sur la grille de prix, et s'en écarte
  de moins d'un pas de prix sinon. ATR indisponible : idée écartée. Un plan dont l'ordre stop <
  entrée < cible (haussier) ou cible < entrée < stop (baissier) ne tient pas
  après arrondi, ou dont le stop ou la cible n'est pas positif, est écarté
  (« plan impossible »). Une distance au stop sous 0,15 % du prix est écartée
  (« ATR trop faible : stop dans le bruit ou l'écart de cotation »). Un calcul
  qui échoue sur un symbole l'écarte seul (« calcul impossible (<erreur>) »).
- Taille : risque fixé = 0,5 % du capital par idée (500 USD pour 100 000 USD),
  taille toujours arrondie vers le bas. Le risque affiché au stop est exact pour
  les paires cotées en USD (EURUSD...) et pour les paires dont la base est l'USD
  (USDJPY, USDCHF, USDCAD...) : leur risque au stop est converti au cours du stop
  (`|entrée − stop| / stop` USD par unité). Pour les croisées (ni base ni
  cotation en USD, EURJPY, GBPCHF...), le cours de la devise de cotation en USD
  au moment du stop est inconnu : le chiffre est calculé au cours du jour de
  l'entrée et peut s'écarter du vrai d'environ la taille du stop en pourcentage
  (un stop à 2 % : environ 2 % d'écart). Les écarts d'ouverture (gaps) et le
  glissement ne sont jamais inclus.
  Forex : lot de 100 000 unités, pas de 0,01 lot, conversion de la devise de
  cotation en USD par la paire en dollar du briefing, plafond de levier 30:1 (la
  taille est réduite si besoin, `limited_by` vaut alors `levier`). Indices et
  matières premières : taille calculée avec la table `contracts`.
- Date et caducité : chaque idée porte la date de la clôture sur laquelle elle
  repose (`last_bar_date`). Quand des barres 1 h existent après cette clôture,
  `since_close` donne le dernier cours 1 h (arrondi aux `decimals` de l'idée) et dit si le stop ou la cible a déjà
  été franchi depuis. Une idée dont le stop est déjà franchi est caduque : la
  page et le résumé le disent (« Stop déjà franchi depuis la clôture : plan
  caduc. », « stop déjà franchi »). Pas de barres 1 h (week-end, matières
  premières sans données) : `since_close` vaut `null`.
- Statuts de taille : `ok` ; `too_wide` quand moins de 0,01 lot (ou moins que le
  minimum du contrat) tient dans le risque fixé, ou quand le plafond de levier
  passe sous le minimum ; `to_confirm` quand une taille ne peut pas être
  calculée (symbole absent de `contracts`, taux de conversion USD introuvable,
  distance au stop nulle). Jamais une taille inventée.
- Risque cumulé : somme des risques réels des idées `ok`, plus le risque fixé
  (0,5 %) pour chaque idée `to_confirm`. Au-dessus de `risk.max_total_pct`
  (2 % par défaut, comparé au centime), `over_cap` vaut vrai et le résumé et la
  page le disent avec le nombre maximal d'idées qui tiennent ensemble dans le
  plafond (`max_ideas_within_cap`, calculé avec les risques les plus grands :
  « au plus N idées ouvertes en même temps ») : c'est un avertissement, aucune
  idée n'est supprimée et le message ne choisit jamais lesquelles ouvrir. Le
  levier cumulé des idées `ok` (`total_leverage`) suit la ligne de risque.
- Avec les valeurs par défaut, 5 idées affichées à 0,5 % chacune font 2,5 %, au-
  dessus du plafond de 2 % : c'est voulu, et le bandeau dit combien d'idées
  peuvent être ouvertes en même temps.

## Configuration

`trader/fx/config.json` est facultatif : à ce chemin par défaut, un fichier absent
donne les valeurs par défaut, sans erreur ; le résumé et la page l'indiquent alors
par « (valeurs par défaut) ». Il contient le capital de l'utilisateur : il est
ignoré par git. `fx.py brief --config PATH` lit un autre fichier ; un chemin donné
explicitement doit exister, sinon une seule ligne (« Fichier de configuration
introuvable : PATH. »), code de sortie 1, aucun appel réseau, aucun fichier écrit.
Les sections absentes reprennent leurs valeurs par défaut, section par section.
`trade_ideas.account.source` vaut `file` quand un fichier a été lu, `default`
sinon. La ligne de compte du résumé et de la page (« Compte : 100 000 USD ·
risque par idée 0.5 % (500.00 USD) · levier max 30:1 ») dit sur quelle base les
tailles sont calculées. Une clé de `contracts` qui ne correspond à aucun symbole
demandé, ou qui est une paire forex, donne un avertissement et est ignorée.

| clé | défaut |
| --- | --- |
| `account` | `{"currency": "USD", "capital": 100000}` (USD seulement) |
| `risk` | `{"per_trade_pct": 0.5, "max_total_pct": 2.0}` |
| `leverage_max` | `30` |
| `plan` | `{"stop_atr_mult": 1.5, "target_r": 2.0}` |
| `ideas` | `{"max_shown": 5, "max_per_exposure": 2}` |
| `contracts` | `{}` (aucun instrument hors forex n'est dimensionné) |

Validation : toute clé inconnue est refusée (faute de frappe), de même qu'une
valeur hors bornes (`0 < per_trade_pct <= 2`, `per_trade_pct <= max_total_pct <= 10`,
`1 <= leverage_max <= 500`, `0,5 <= stop_atr_mult <= 5`, `1 <= target_r <= 5`,
`1 <= max_shown <= 10`, `1 <= max_per_exposure <= 5`, `capital > 0`). Un fichier
invalide ou illisible donne une seule ligne d'explication et le code de sortie
1 ; aucun `briefing.json` n'est écrit (l'ancien reste intact).

La table `contracts` donne, pour un symbole hors forex, la valeur d'un point :
`usd_per_point` est la valeur en USD d'un mouvement de 1,0 du prix pour une
unité de taille ; `step` est le pas de taille ; `min` la taille minimale. Les
trois valeurs sont obligatoires et positives. Exemple, repris de
`config.example.json` (dans le dossier du skill) :

```json
{
  "contracts": {
    "^FCHI": {"usd_per_point": 1.1, "step": 0.1, "min": 0.1},
    "GC=F": {"usd_per_point": 100.0, "step": 0.01, "min": 0.01}
  }
}
```

Ce sont des valeurs d'exemple, à vérifier chez le courtier (le fichier d'exemple
ne peut pas porter cette note, car les clés inconnues sont refusées). Copier
`config.example.json` vers `trader/fx/config.json` puis corriger les valeurs et
le capital. Un symbole absent de la table reste `to_confirm`.

## Journal de trading

Le journal garde les trades que l'utilisateur a réellement pris, calcule leur
résultat en USD et en R, produit des statistiques et écrit les règles de stop et
de cible que le futur serveur d'alertes surveillera. Il rapporte des faits. Il ne
passe aucun ordre et ne lit pas le compte du courtier : tout vient de ce que
l'utilisateur dit.

```bash
python3 "${CLAUDE_SKILL_DIR}/journal.py" open --symbol EURJPY=X --side baissier --price 176.70 --lots 0.45
python3 "${CLAUDE_SKILL_DIR}/journal.py" amend ID --stop 178.90          # déplace le stop et/ou la cible
python3 "${CLAUDE_SKILL_DIR}/journal.py" close ID --price 175.20 --pnl 380.00 --reason cible
python3 "${CLAUDE_SKILL_DIR}/journal.py" list [--open | --closed]
python3 "${CLAUDE_SKILL_DIR}/journal.py" stats [--json]
python3 "${CLAUDE_SKILL_DIR}/journal.py" alerts [--out PATH]            # -> trader/fx/alerts.json
python3 "${CLAUDE_SKILL_DIR}/journal.py" page [--out PATH]              # -> trader/fx/journal.html
```

Toutes les sous-commandes prennent `--journal PATH` (défaut `trader/fx/journal.json`)
et `--config PATH` (défaut `trader/fx/config.json`). Une erreur tient en une
ligne, avec le code de sortie 1, et ne modifie aucun fichier.

**Déclarer un trade en une phrase.** « J'ai pris l'idée EURJPY baissier à 176,70,
0,45 lot » donne la première commande ci-dessus. Il faut le symbole, le sens, le
prix d'entrée réel et la taille : les demander s'il en manque un, ne jamais les
inventer.
- `open` cherche dans `trader/fx/briefing.json` l'idée de même symbole et de même
  sens. Trouvée, le stop et la cible de l'idée sont repris (`--stop` et
  `--target` les remplacent) et le trade est « idée du briefing » ; sinon le trade
  est « hors plan » et `--stop` est obligatoire.
- Une paire forex se saisit en lots (`--lots`, 1 lot = 100 000 unités), tout autre
  instrument en taille de contrat (`--size`). `--time "AAAA-MM-JJ HH:MM"` (heure de
  Paris) donne l'heure d'entrée, par défaut maintenant.
- Le risque prévu au stop est calculé avec `sizing.risk_at`. Pour une paire croisée,
  le cours de la devise de cotation en USD est lu chez Yahoo (dernière clôture
  journalière) sauf si `--quote-usd-rate` (valeur en USD d'une unité de la devise de
  cotation) ou `--risk-usd` (risque prévu connu) est donné. Risque inconnu : il est
  dit, le R sera « non calculable ».
- L'identifiant est `AAAA-MM-JJ-SYMBOLE-n` (date UTC, symbole sans `=X`, numéro
  d'ordre du jour), par exemple `2026-11-16-EURJPY-1`.

**Clôturer : demander le résultat du courtier.** À la clôture, demander à
l'utilisateur le prix de sortie et le résultat en USD donné par son courtier, et le
passer avec `--pnl` : il inclut les frais, le swap et le glissement, et le trade est
marqué « courtier ». Sans `--pnl`, le résultat est estimé avec `sizing.pnl_at` et
marqué « estimé, hors frais ». Pour une paire croisée clôturée un autre jour que
l'entrée, l'estimation prendrait le cours d'aujourd'hui : donner `--quote-usd-rate`
ou `--pnl`. `--reason` vaut `stop`, `cible` ou `manuel` ; `--tags a,b` ajoute des
étiquettes d'erreur libres (par exemple `entree_tardive`, `hors_plan_taille`) ;
`--note` garde une remarque. Le R est le résultat divisé par le risque prévu à
l'ouverture.

**Stop déplacé.** `amend ID --stop X` (et/ou `--target Y`) change le stop ou la
cible en vigueur. Le stop initial et le risque prévu ne changent jamais, pour que le
R garde son unité. Un stop éloigné du prix, du côté de la perte (plus bas pour un
trade haussier, plus haut pour un baissier), ajoute l'étiquette `stop_deplace` ; un
stop rapproché du prix, pour protéger un gain, ne l'ajoute pas.

**Statistiques.** `stats` ne compte que les trades clôturés : réussite et R (taux
positif, R moyen des positifs et des négatifs, espérance, R total, résultat), par
règle (un trade compte dans chacune de ses règles) et par sens, par paire, session
d'entrée et jour de la semaine (Paris), erreurs (étiquettes), capital et drawdown
(courbe après chaque trade, pire série de trades négatifs, comparée au plafond de
risque cumulé de la configuration). Chaque ligne affiche son `n`. Un trade est « à
l'équilibre » quand son |R| est sous 0,05.

**Alertes et page.** `alerts` écrit une règle par stop et par cible de chaque trade
ouvert (`id`, `trade_id`, `symbol`, `type`, `side`, `level`, `decimals`). `alerts.json`
ne contient aucun résultat, aucun capital, aucune taille et aucun risque : seulement
des niveaux. `page` écrit la page « Journal de trading » (Résumé, Trades ouverts,
Statistiques, Trades clôturés) ; elle contient les résultats de l'utilisateur.

## Serveur d'alertes

`alerts_run.py` est un lancement du serveur ; le workflow `.github/workflows/alerts.yml`
l'appelle sur GitHub Actions **toutes les 15 minutes (à :07, :22, :37 et :52), de 07 h 07 à 21 h 52 UTC, du lundi
au vendredi** (le cron de GitHub est en UTC et peut avoir quelques minutes de retard).
Il coûte environ 1 200 minutes par mois (gratuit tant que le dépôt est public ; sous les
2 000 minutes gratuites s'il redevenait privé). Tous les calculs sont en Python, sans appel à Claude. Un lancement :

1. lit `trader/fx/alerts.json` (les règles de stop et de cible des trades ouverts) ;
2. **stop ou cible touché** : lit les barres de 5 minutes de chaque symbole et compare
   leur plus haut et leur plus bas au niveau, à partir de `since` (heure d'ouverture
   du trade ou du dernier déplacement du niveau). Un contact entre deux lancements
   n'est donc pas manqué. Un message par règle et par niveau : un niveau déplacé
   après son alerte est surveillé de nouveau à partir du déplacement ;
3. **annonce à fort impact** : si une annonce touche une devise d'un trade ouvert
   (les deux devises de la paire ; l'USD pour un autre instrument), elle est annoncée
   une seule fois, par le premier lancement qui la voit dans les 30 minutes à venir
   (normalement 30 à 15 minutes avant ; un lancement en retard l'annonce plus tard
   plutôt que jamais) ;
4. **idées de trade** : relance le briefing et annonce les idées nouvelles (au plus
   3 par lancement, une fois par jour UTC et par symbole et sens), sauf celles que
   l'utilisateur tient déjà, les idées caduques, et tout un week-end (briefing
   `closed_weekend`). Le message dit « idée de trade, en formation, non confirmée à la
   clôture » : en séance la barre du jour n'est pas finie et l'idée peut disparaître.
   C'est un plan mécanique à valider, jamais un conseil ;
5. envoie les messages dans cet ordre : stops et cibles, annonces, idées. Un message
   n'est mémorisé qu'après la réponse 200 de Telegram ; un échec repart au lancement
   suivant et le lancement se termine en échec (GitHub peut alors prévenir par e-mail).

Si les barres de 5 minutes sont toutes indisponibles alors qu'il y a des règles, un
seul message par jour dit « Impossible de vérifier vos stops ».

**Secrets GitHub** (dépôt, Settings, Secrets and variables, Actions) : `TELEGRAM_BOT_TOKEN`
et `TELEGRAM_CHAT_ID` (obligatoires) ; `TRADER_FX_CONFIG` (facultatif : le contenu de
`trader/fx/config.json`, pour que les tailles des idées utilisent le vrai capital ;
sans lui les messages disent « Taille calculée sur le capital par défaut »). Ils ne sont
jamais affichés. Ne jamais coller un token dans le chat : s'il l'a été, le révoquer avec
`/revoke` chez `@BotFather`.

**Essai à blanc.** Onglet Actions, workflow « Alerts », Run workflow, case `dry_run` cochée :
les messages s'affichent dans le journal du lancement, rien n'est envoyé ni mémorisé. En
local : `python3 "${CLAUDE_SKILL_DIR}/alerts_run.py" --dry-run`.

**Garder `alerts.json` à jour.** `open`, `amend` et `close` réécrivent `alerts.json`. Avec
`"alerts": {"auto_push": true}` dans `trader/fx/config.json` (défaut `false`), `journal.py`
le commite seul (ce fichier uniquement, jamais `journal.json`) et le pousse, depuis la
branche `main` seulement. Sans cela, ou si le push échoue (une ligne « alerts.json non
poussé : … » le dit), pousser `alerts.json` à la main : sinon le serveur ne voit pas les
nouveaux niveaux, et un trade clôturé continue de déclencher des alertes de stop.

**Limites.** « Touché » veut dire « vu dans les données Yahoo », retardées, pas « exécuté
chez le courtier » : le stop réel reste chez le courtier. Le calendrier est un flux non
officiel. GitHub peut retarder un lancement planifié ; rien ne prévient si le
planificateur s'arrête. Les idées en séance viennent d'une barre du jour en formation.

## Garde-fou FundedNext et niveaux de reverse

Ajoutés le 23 novembre 2026 pour le challenge FundedNext Stellar 2-Step 100k. Tout est calculé en
Python dans `alerts_run.py`, sans appel à Claude, et rien n'est jamais envoyé au courtier.

**Source des positions : le classeur.** Quand le secret `POSITIONS_CSV_URL` existe (lien CSV de
l'onglet « Positions ouvertes » du classeur Google Sheets, publié sur le Web), `positions.py` lit
les positions ouvertes et les chiffres du compte (solde clos, résultat clos du jour, seuils du
plan) et remplace `alerts.json`. Classeur illisible : `alerts.json` reprend la main et un message
par jour le dit. Le lien CSV est privé : il n'est jamais affiché. `live_gold.py` lit aussi le
classeur (niveaux CFD tels quels : Twelve Data cote l'or au comptant).

**Écart CFD.** Les prix Yahoo (futures pour l'or et les indices US, indice au comptant pour le DAX
et le CAC) ne sont pas ceux du CFD. L'écart est mesuré à l'heure d'ouverture (clôture de la barre
5 min qui contient l'ouverture, moins l'entrée CFD) ; les niveaux de stop et de cible et le
résultat latent en sont corrigés. Heure d'ouverture fausse ou écart de plus de 3 % : pas de
correction, une ligne le dit dans le journal du lancement.

**Garde-fou (`guard.py`)**, un message par seuil et par jour UTC, envoyé avant tout le reste :
résultat du jour estimé (clos du jour + latent) sous l'alerte (1 000 $), sous le stop interne
(1 500 $), sous 70 % de la perte journalière FundedNext (5 000 $) ; équité estimée à moins de 20 %
de la marge au-dessus du plancher (90 000 $) ; risque ouvert aux stops au-dessus du plafond
(1 500 $). Les seuils viennent du classeur. Un saut qui franchit plusieurs seuils n'envoie que le
plus grave. Estimation sur prix retardés : l'équité exacte est dans MT5.

**Niveaux de reverse (`reversal.py`)** pour les actifs de `TRADER_FX_REVERSE_LIST`
(`trader/lists/fundednext.txt`) : bascule de tendance D1 (dernier swing fractal contre la
tendance), zones de retournement (plus hauts et bas 5 et 20 séances, extensions moyenne 20 j
± 3 amplitudes), Parabolic SAR D1 et H4 (0,02 ; 0,2). Un résumé par jour à partir de 06 h Paris,
puis des alertes : bascule franchie, zone approchée à moins d'un quart d'amplitude, SAR retourné
(au plus 3 par lancement). Ce sont des niveaux à surveiller, pas des setups du plan.

**Setup D, retournement de l'or sur niveau H4 (`gold_reverse.py`)**, activé par `SETUP_D_GOLD=1` et le
secret `TWELVE_DATA_API_KEY` (un crédit par lancement : barres 1 h de XAU/USD au comptant, l'échelle du
XAUUSD du courtier). Niveaux : zones de swings H4 touchées au moins deux fois, plus haut et plus bas de
la veille et de la semaine dernière (jour du serveur MT5, New York + 7 h), chiffres ronds de 50 $ ;
les niveaux proches sont fusionnés (confluence). Quand le prix arrive à moins d'une demi-ATR H4 d'un
niveau : plan d'ordre limite au niveau, stop à 0,6 ATR H4 derrière, cible 2R, taille au risque autorisé
du classeur. Une alerte par niveau et par jour, deux au plus par lancement, aucune dans les 30 minutes
avant une annonce USD à fort impact. Règles fixées par l'utilisateur le 23 novembre 2026, **non validées
par un rejeu historique** (le message le dit). Quota Twelve Data gratuit : 800 appels par jour, partagés
avec `live_gold.py`.

**Univers.** `TRADER_FX_LISTS` (liste de fichiers séparés par des virgules) remplace les trois
listes par défaut quand `--list` n'est pas donné ; les workflows le fixent à
`trader/lists/fundednext.txt` (les 6 actifs du plan).

**Lancements fiables.** GitHub abandonne la plupart des lancements planifiés d'un petit dépôt
(constaté : 2 lancements par jour au lieu de 60, un briefing parti 9 h en retard). Le déclencheur
fiable est un minuteur externe (cron-job.org) qui appelle l'API `workflow_dispatch` ; les crons
restent en secours.

## Signaux en séance

Le serveur d'alertes détecte aussi des trades pendant la séance, sur des barres de
15 minutes Yahoo (mêmes symboles que le briefing), et les envoie sur Telegram. **C'est
l'utilisateur qui passe chaque ordre, à la main, dans MT5** : le serveur ne se connecte
jamais au courtier et n'envoie aucun ordre (FundedNext exige un trading manuel). Une
alerte est un plan mécanique à valider, pas un conseil. Tout est calculé en Python, sans
appel à Claude, et Claude ne choisit aucun signal à la place de l'utilisateur.

**Les cinq familles.** Toutes lisent des barres de 15 minutes **clôturées** (une barre dont
la fin est passée) ; chacune vaut pour un sens (haussier ou baissier). L'entrée est la
clôture de la barre du signal.

| famille | déclencheur | stop | cible |
| --- | --- | --- | --- |
| `session_break` | une barre clôture hors d'une plage : Asie (00:00 à 07:00 UTC), ouverture de Londres, ouverture de New York (30 premières minutes de chaque session) ; seulement dans les 3 h qui suivent la fin de la plage, première clôture de ce côté | l'autre côté de la plage | 2R |
| `bb_return` | bandes de Bollinger 20 périodes, 2 écarts-types sur les clôtures : la barre précédente a clôturé hors de la bande, la courante clôture de nouveau dedans ; le sens est celui du retour vers le milieu | extrême de la barre qui était hors bande | bande du milieu |
| `fractal_break` | fractale de Williams (un extrême entouré de 2 barres moins extrêmes de chaque côté, confirmée 2 barres plus tard) : une barre clôture au-delà de la dernière fractale confirmée, qu'aucune clôture n'avait encore franchie | dernière fractale opposée confirmée, ou 1,5 ATR (15 min) s'il n'y en a pas | 2R |
| `engulfing` | le corps de la barre courante englobe celui de la précédente, de couleur opposée, après au moins 3 barres consécutives dans le sens opposé | extrême de l'englobante | 2R |
| `rsi_exit` | RSI 14 sous 30 à la barre précédente et au moins 30 à la courante (haussier) ; au-dessus de 70 puis 70 ou moins (baissier). Le signal part au retour dans la zone normale, pas pendant que le prix reste en zone | 1,5 ATR (15 min) | 2R |

La cible 2R est `plan.target_r`, le stop 1,5 ATR est `plan.stop_atr_mult` (section
« Configuration »). Le plan est arrondi comme les idées du briefing (stop en s'éloignant de
l'entrée, cible en se rapprochant). Il est écarté, avec sa raison, quand il est impossible
après arrondi, quand le stop est sous `intraday.min_stop_pct` du prix (« stop trop proche »),
au-dessus de `intraday.max_stop_daily_atr` fois l'ATR journalier (« stop trop large »,
par exemple une plage asiatique démesurée), quand le rapport 1:R est sous `intraday.min_rr`
ou quand l'ATR journalier manque. Le stop et la cible sont ceux du signal de la barre la plus
récente.

**Score, classement, plafonds.**

- Score : +2 par famille concordante dans les 4 dernières barres clôturées du symbole (une
  heure), +1 si la tendance journalière va dans le sens, −1 à contre-sens. Un signal contraire
  dans la même fenêtre annule l'alerte (« signaux contradictoires »).
- Classement : score décroissant, puis nombre de familles, puis symbole. Diversification : au
  plus 2 alertes par exposition de devise (`intraday.max_per_exposure`).
- Plafonds : 3 alertes par lancement, 10 par jour UTC. Quand le plafond du jour est atteint,
  un seul message le dit (« Plafond de 10 alertes de signal atteint pour aujourd'hui »), puis
  rien. Le classement agit à l'intérieur d'un lancement ; d'un lancement à l'autre c'est
  premier arrivé, premier servi, aucune capacité n'est réservée. Si les 10 sont épuisés trop tôt
  dans la journée, `intraday.min_score` coupe les alertes faibles (défaut : aucun seuil).
- Déduplication : jamais deux alertes pour la même barre, le même symbole et le même sens. Après
  une alerte, un repos de 2 heures par symbole et par sens. Exception, le **renforcement** : un
  nouveau signal concordant pendant le repos produit une alerte seulement si son score est
  **strictement supérieur** à celui de la dernière alerte ; le message dit alors « Signal en
  séance renforcé » et rappelle les familles déjà alertées. Elle compte dans les plafonds.
- Le repos et le compteur du jour sont remis à zéro au changement de jour UTC. Le cron ne tourne
  jamais entre 21 h 52 et 07 h 07 UTC : en production le repos ne peut donc pas enjamber minuit ;
  un lancement manuel à cette heure pourrait répéter une alerte.

**Validité et filtres.**

- Plan caduc : plus de 30 minutes (`intraday.max_age_minutes`) depuis la **clôture** de la barre
  du signal (une barre qui a clôturé à 09:30 n'alerte plus après 10:00).
- Zone de validité : le message donne un prix limite, l'entrée plus 0,25 R dans le sens du trade
  (`intraday.validity_r`) ; au-delà, le plan est caduc.
- Pas d'alerte dans les 30 minutes qui précèdent une annonce à fort impact sur une devise de la
  paire.
- Alerte sautée quand un trade de même symbole et de même sens est déjà ouvert dans `alerts.json`.
  Si `alerts.json` est absent, cette vérification est sautée et l'alerte part quand même.
- Aucune alerte un week-end fermé (`closed_weekend`).
- Si le briefing échoue, il n'y a aucun signal ce lancement : l'ATR et la tendance journaliers
  viennent du briefing (une ligne « briefing indisponible : signaux en séance sautés. » le dit).
- Un symbole sans barres de 15 minutes est sauté, une ligne le dit dans le journal du lancement.

**Le message.** Français, heure de Paris, texte brut ; l'heure de la barre est son heure de
début. Exemple de forme :

```text
Signal en séance, non confirmé par le courtier : EUR/JPY baissier.
Signaux : session_break (Londres), rsi_exit. Barre 15 min de 09:15 Paris.
Entrée 176.700 (zone valable jusqu'à 176.640), stop 177.100, cible 175.900 (1:2).
Taille 0.45 lot, risque 480.75 USD (0.5 % du capital).
Plan mécanique à valider, pas un conseil. Prix Yahoo, retardé.
```

Une taille non calculable reste « Taille à confirmer chez le courtier ». Pour un renforcement,
le titre devient « Signal en séance renforcé » et une ligne « Déjà alerté à HH:MM Paris : … »
rappelle les familles déjà vues. Pour saisir l'ordre dans MT5, `intraday.mt5_symbols` traduit le
nom Yahoo en nom du courtier (suffixes de FundedNext), par exemple
`{"EURJPY=X": "EURJPY.r"}` : le nom du courtier remplace alors le nom de la paire dans le
message.

**Configuration `intraday`.** Section facultative de `trader/fx/config.json` ; toute clé
inconnue est refusée, toute valeur hors bornes aussi (une ligne d'explication, code de sortie 1).
Les valeurs par défaut s'appliquent clé par clé.

| clé | défaut | bornes |
| --- | --- | --- |
| `enabled` | `false` (désactivé depuis le rejeu historique, voir ci-dessous) | `true` ou `false` |
| `symbols` | `[]` (tous les symboles du briefing) | liste de symboles Yahoo |
| `mt5_symbols` | `{}` | objet nom Yahoo vers nom du courtier |
| `families` | les cinq familles | liste non vide, sans doublon, parmi `session_break`, `bb_return`, `fractal_break`, `engulfing`, `rsi_exit` |
| `range_minutes` | 30 | entier de 15 à 120, multiple de 15 |
| `break_window_hours` | 3 | 1 à 6 |
| `bb_period` | 20 | entier de 5 à 100 |
| `bb_std` | 2.0 | 1 à 4 |
| `rsi_period` | 14 | entier de 5 à 50 |
| `rsi_low` | 30 | 5 à 50 |
| `rsi_high` | 70 | 50 à 95 |
| `engulfing_min_prior` | 3 | entier de 1 à 6 |
| `min_stop_pct` | 0.05 | plus de 0 et au plus 1 (en % du prix) |
| `max_stop_daily_atr` | 1.0 | plus de 0 et au plus 5 (en ATR journalier) |
| `min_rr` | 1.0 | 0,5 à 5 |
| `score_per_signal` | 2 | entier de 1 à 5 |
| `score_trend` | 1 | entier de 0 à 3 |
| `window_bars` | 4 | entier de 1 à 12 |
| `max_age_minutes` | 30 | entier de 15 à 120 |
| `validity_r` | 0.25 | plus de 0 et au plus 1 |
| `max_per_run` | 3 | entier de 1 à 10 |
| `max_per_day` | 10 | entier de 1 à 50 |
| `max_per_exposure` | 2 | entier de 1 à 5 |
| `cooldown_minutes` | 120 | entier de 0 à 720 (0 : pas de repos) |
| `min_score` | `null` (aucun seuil) | entier ou `null` |

`config.example.json` contient un bloc `intraday` minimal ; copier le fichier vers
`trader/fx/config.json`. Sur GitHub, la section vient du secret `TRADER_FX_CONFIG`.

**Limites, dites honnêtement.**

- Ces signaux **ont été testés sur l'historique (2016-2026, barres 1 min) et n'ont montré aucun
  avantage** : le R moyen par trade est négatif après coûts sur EURUSD, GBPUSD, USDJPY et l'or
  (environ −0,07 R sur 53 000 alertes simulées ; aucune famille n'est positive ; résultat stable entre
  l'exploration 2016-2022 et la confirmation 2023-2026). C'est pourquoi `intraday.enabled` vaut `false`
  par défaut. Ne pas risquer de capital réel sur ces alertes. Détail, méthode et limites :
  `docs/research/2026-11-17-intraday-replay-findings.md` ; scripts : `research/intraday/`.
- Les barres Yahoo sont gratuites, non officielles et retardées. « Clôturé » veut dire « vu dans
  les données Yahoo » : le prix du courtier diffère (spread, glissement), l'entrée est un plan.
- `intraday.min_stop_pct` (0,05 %) et `intraday.max_stop_daily_atr` (1,0) sont des valeurs de
  départ, à ajuster après avoir mesuré des alertes réelles.
- Le cron est inchangé (toutes les 15 minutes à :07, :22, :37 et :52, de 07 à 21 h UTC, du lundi
  au vendredi) : une alerte arrive environ 7 à 10 minutes après la clôture de la barre.
  GitHub peut retarder ou abandonner un lancement, donc une alerte peut arriver tard (plan
  caduc après 30 minutes) ou jamais.
- Un trade pris à partir d'une alerte de signal n'est pas dans `briefing.json` : pour le
  journal, `journal.py open` le déclare « hors plan » et exige `--stop`.
- Le plafond de 10 par jour ne compte que les alertes de signal ; les idées du briefing gardent
  leur plafond de 3 par lancement. `alerts.json` peut être en retard sur les trades réels.

## Briefing publié

Le briefing se met à jour tout seul sur GitHub, sans que le PC soit allumé, et se lit sur
le téléphone. Le workflow `.github/workflows/briefing.yml` se lance à **04 h 30 UTC du lundi
au vendredi** et à **22 h 15 UTC du dimanche au jeudi** (le cron de GitHub est en UTC : l'heure
de Paris avance ou recule d'une heure avec l'heure d'été, donc 05 h 30 l'hiver et 06 h 30
l'été pour le premier). Un lancement :

1. `briefing_run.py build --out-dir site` lance `fx.py brief --no-cache`, construit la page avec
   le gabarit du briefing et écrit `site/index.html` et `site/summary.txt` ;
2. les actions Pages publient `site/` : le lien est `https://tariop26.github.io/trading/`, à
   mettre en favori sur le téléphone ; chaque briefing remplace la page précédente ;
3. `briefing_run.py notify --url ...` envoie sur Telegram un message : le titre
   (« Briefing marchés, AAAA-MM-JJ HH:MM UTC. »), le lien, puis le résumé (40 lignes au plus).

Si le briefing échoue (par exemple Yahoo en panne), rien n'est publié : **la page précédente
reste en ligne**, et un message Telegram d'une ligne le dit (« Briefing indisponible (…) : …
La page précédente reste en ligne. »). Il en va de même si la publication sur GitHub Pages
échoue (Pages non activé, panne de Pages) : la raison est « publication sur GitHub Pages en
échec ». Un briefing qui n'arrive pas du tout (lancement planifié abandonné ou arrêté par le
délai de 10 minutes) ne déclenche aucun message : seul GitHub peut le signaler par e-mail.

**Lecture sur téléphone.** Le fichier publié est un document complet (`page.standalone` ajoute
`<!doctype html>`, `<meta charset>` et `<meta name="viewport">`, que la plateforme des
Artifacts fournit d'elle-même mais pas GitHub Pages ; sans la balise viewport un téléphone
dessine la page à la largeur d'un écran de bureau, rétrécie). Sous 640 px (le téléphone) la
page change de forme : une barre de pastilles collée en haut (Idées, Résumé, Devises,
Calendrier, Setups, Niveaux) saute à une section ; chaque idée garde son plan (entrée, stop,
cible, taille) visible et replie les chiffres annexes et le « Pourquoi » dans « Détails et
pourquoi » ; la force des devises se fait glisser une période à la fois ; le calendrier garde
les annonces des 24 h visibles et replie le reste de la semaine ; les familles de setups et les
niveaux à surveiller sont repliés avec leur nombre ; le résumé tient sur deux colonnes ; les
tableaux deviennent des cartes allégées, sans défilement sur le côté. Sur un grand écran tout
reste ouvert et la mise en page ne change pas. Tout le texte reste dans la page, seul
l'affichage change. La page des Artifacts bénéficie des mêmes repliages (ils suivent la largeur
de l'écran) mais n'a pas besoin du squelette de document.

La page affiche son heure de production et un bandeau rouge « périmé » au bout de 12 heures.
Comme il n'y a que deux briefings par jour, ce bandeau apparaît **sans panne** entre les
lancements : de 16 h 30 à 22 h 15 UTC en semaine, et du vendredi soir au dimanche soir. Seul le
message Telegram « Briefing indisponible » signale un vrai échec. Un lancement manuel le
week-end publie aussi la page, avec la mention « Marché fermé (week-end) » ; le briefing du
dimanche à 22 h 15 UTC tombe après l'ouverture du marché et ne la porte pas.

**Mettre à jour à la demande** : depuis le navigateur du téléphone, onglet Actions du dépôt,
workflow « Briefing », Run workflow. La case `dry_run` affiche le résumé dans le journal du
lancement (le message Telegram, qui contient le lien, n'existe qu'après la publication) sans
rien publier ni envoyer. En local : `python3
"${CLAUDE_SKILL_DIR}/briefing_run.py" build --out-dir site --dry-run`.

**Réglages faits une fois** : dépôt public, et dans Settings, Pages, Source « GitHub Actions ».
Les secrets sont les mêmes que pour le serveur d'alertes (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, et `TRADER_FX_CONFIG` facultatif).

**Ce que la page publique montre.** Seul le briefing est publié : jamais le journal, `alerts.json`
ni la configuration. Mais comme le dépôt est public, tout le monde peut lire la page, y compris
la ligne « Compte : … USD · risque par idée … » : avec le secret `TRADER_FX_CONFIG` c'est le
capital réel de l'utilisateur (ici un compte de prop firm, accepté), sans lui 100 000 USD par
défaut. Les messages Telegram ne contiennent aucun secret.

## Étapes pour Claude

1. Lancer `fx.py brief` (sans option, sauf demande de l'utilisateur). Si le
   code de sortie est 1, dire la ligne d'explication telle quelle et
   s'arrêter : un échec laisse l'ancien `briefing.json` et l'ancien
   `briefing.html` intacts, donc ne jamais les présenter comme le briefing du
   jour.
2. Résumer la sortie terminal à l'utilisateur, dans cet ordre : d'abord les
   comptes (demandés, reçus, analysés, échecs, avec les symboles en échec), puis
   l'état du marché et l'heure, la meilleure et la pire devise sur 5 séances,
   les annonces à fort impact des prochaines 24 h, les setups par famille et le
   message de corrélation, puis le bloc des idées de trade : combien d'idées,
   leur sens (haussier / baissier), leurs statuts (`ok`, `to_confirm`,
   `too_wide`), le risque cumulé et s'il dépasse le plafond (`over_cap`), enfin
   les avertissements (calendrier partiel, week-end, cache). Dire que ce sont
   des plans mécaniques à valider et que le prix d'entrée est la dernière
   clôture, à revalider à l'ouverture. Pour une idée `to_confirm` (indice ou
   matière première), dire que sa taille demande la table `contracts` de
   l'utilisateur dans `trader/fx/config.json`, avec les valeurs de son courtier ;
   ne jamais inventer ces valeurs. Si `brief` échoue sur la configuration, dire
   la ligne telle quelle.
3. Lancer `fx.py page`, puis contrôler la fraîcheur : lire `as_of` dans
   l'en-tête de la page (ou dans `briefing.json`) et le comparer à l'heure
   actuelle. La page affiche aussi un bandeau rouge « périmé » quand `as_of`
   a plus de 12 heures. Ne pas publier une page périmée comme si elle datait
   d'aujourd'hui.
4. Publier `trader/fx/briefing.html` avec l'outil Artifact (icône `chart`).
   Aux exécutions suivantes, republier au même lien (même chemin de fichier,
   ou le `url` de l'Artifact déjà publié). Donner le lien à l'utilisateur.
5. L'utilisateur choisit un graphique ou une idée. Ne jamais choisir à sa place,
   ne jamais dire laquelle des idées « prendre ». Lui remettre le choix : le
   jugement est le sien. Les skills
   `trader-news`, `trader-entry`, `trader-exit`, `trader-budget`,
   `trader-risk` et `trader-broker` sont faits pour les actions américaines
   et ne s'appliquent PAS au forex, aux matières premières ni aux indices : le
   dire à l'utilisateur plutôt que de les enchaîner.
6. Journal. Quand l'utilisateur dit avoir pris un trade, l'avoir déplacé ou
   l'avoir clôturé, lancer la commande `journal.py` correspondante (voir
   « Journal de trading »), avec les valeurs qu'il a données : prix réel, taille,
   heure, résultat du courtier. Demander ce qui manque. À la clôture, demander le
   résultat du courtier en USD et le passer avec `--pnl`. Redire la ligne de
   confirmation telle quelle, sans la commenter comme un conseil. Pour `stats`,
   dire toujours le nombre de trades derrière chaque chiffre et l'avertissement
   d'échantillon quand il apparaît (moins de 30 trades clôturés : « échantillon
   trop petit pour conclure »). Ne publier `journal.html` en Artifact que si
   l'utilisateur le demande, en privé : il contient ses résultats. Après chaque
   `open`, `amend` ou `close`, `alerts.json` est réécrit ; si la sortie dit
   « alerts.json non poussé », le dire et proposer de le pousser (ne jamais pousser
   sans que l'utilisateur l'ait demandé ou ait activé `alerts.auto_push`).
7. Briefing automatique. Quand l'utilisateur veut le briefing sur son téléphone ou sans
   le PC, lui donner le lien de la page (voir « Briefing publié ») et lui dire de lancer
   le workflow « Briefing » à la main depuis l'onglet Actions pour une mise à jour
   immédiate. Ne pas publier un Artifact à la place : la page automatique existe déjà.
8. Signaux en séance. Ils sont envoyés par le serveur d'alertes, pas par Claude (voir
   « Signaux en séance »). Claude ne choisit jamais un signal pour l'utilisateur et ne le
   présente jamais comme un conseil : c'est un plan mécanique, testé sur l'historique sans avantage,
   que l'utilisateur saisit lui-même dans MT5.

## Règles

- Dire ce qui a été lu : combien de symboles demandés, reçus, analysés, et
  l'heure des données (dernière barre).
- Dire « a matché une règle », jamais « achat », « vente », « gagnant » ni
  « bon trade ». Pour une idée : « haussier » ou « baissier », jamais les mots
  achat, acheter, vente, vendre, buy, sell, gagnant, profit.
- Dans le briefing et les trades potentiels, aucun chiffre de gain ou de perte
  sur un trade, aucun profit : seulement le risque maximal au stop, le rapport
  1:R, les lots, le levier et la valeur du pip.
- Dans le journal, seuls les faits sont rapportés : « résultat positif » ou
  « résultat négatif », montants en USD et en R. Un résultat estimé est toujours
  dit « estimé, hors frais » ; un résultat donné par le courtier est dit
  « courtier ». Jamais achat, acheter, vente, vendre, buy, sell, conseil ni
  prévision ; « haussier » et « baissier » désignent le sens.
- Les données Yahoo sont retardées : ne jamais les présenter comme du temps
  réel. Un setup est périmé dès que le prix a bougé : relancer avant d'en parler.
- Un week-end, les valeurs sont les dernières clôtures, et la plage de la
  session asiatique du jour est vide : le dire.
- Les signaux forex qui partagent une devise (par exemple plusieurs paires
  contre le dollar) sont corrélés : ce n'est pas une confirmation
  indépendante.
- Une idée est un plan mécanique à valider : ne jamais la présenter comme un
  conseil, ni choisir une idée pour l'utilisateur.

## Limites connues

- Pas de barres de 5 minutes, pas de données tick par tick : les plus fines
  sont les barres 1 h.
- Le volume du forex n'est pas disponible chez Yahoo : aucun signal de volume
  sur les paires.
- Flux de calendrier non officiel, Yahoo non officiel : l'un ou l'autre peut
  changer de format ou disparaître.
- Les barres historiques sont datées avec le décalage UTC actuel de la série :
  les niveaux de la semaine précédente peuvent être faux la semaine qui suit le
  changement d'heure d'automne (forex et contrats à terme).
- Entre le vendredi 17:00 à New York et le samedi 00:00 UTC, l'état du marché est
  `closed_weekend`, mais la barre forex du vendredi est encore traitée comme en
  cours.
- Les indices asiatiques (Nikkei, Hang Seng) ont une séance de retard le matin
  en Europe.
- Les jours fériés (Noël, Nouvel An) s'affichent « ouvert » : seul le week-end
  est modélisé.
- Une seule série périmée n'est pas signalée : regarder la `last_bar_date` de
  chaque signal.
- Les lignes de niveaux du plan du jour n'ont pas de date de dernière barre.
- Trades potentiels : le prix de référence est la dernière clôture Yahoo,
  retardée ; l'entrée doit être revalidée à l'ouverture, et le plan recalculé si
  le prix a bougé.
- Le lot est supposé valoir 100 000 unités et la valeur du pip est calculée à
  partir des cours Yahoo : les deux sont à vérifier chez le courtier.
- Aucun calcul du financement (swap), du spread ni de la marge exacte du
  courtier ; le levier affiché est la valeur de la position divisée par le
  capital.
- Le risque au stop des paires croisées est calculé au cours du jour de l'entrée
  (voir « Taille ») ; aucun chiffre n'inclut d'écart d'ouverture ni de glissement.
- Une distance au stop sous 0,15 % du prix est refusée (« ATR trop faible ») :
  une paire arrimée ou presque immobile (USDHKD...) ne donne jamais d'idée.
- Valeur du pip des cotations à très grande valeur (USDIDR, USDKRW) : affichée
  avec 4 décimales ; le pip usuel de ces paires peut différer de 0,0001 : à
  vérifier chez le courtier.
- Un symbole de six lettres qui n'est pas une paire de devises (métaux, crypto)
  écrit `XXXYYY=X` serait dimensionné comme du forex en lots : ne pas le mettre
  dans la liste forex.
- L'exemple `^FCHI` de la table `contracts` fige un cours EUR/USD dans
  `usd_per_point` (valeur d'un point en EUR multipliée par ce cours) : le
  recalculer avec le cours du jour.
- Un `usd_per_point` faux (par exemple 10 fois trop grand) donne une taille
  plausible mais fausse dans la même proportion : vérifier chaque valeur chez le
  courtier.
- `since_close` compare la date locale de la dernière barre journalière du
  symbole à des dates UTC : approximation possible d'un jour pour les marchés
  éloignés d'UTC.
- Devise de compte : USD seulement (version 1).
- Les règles ne créent jamais une idée à partir d'un état seul (`oversold`,
  `overbought`).
- Particularité connue : une série parfaitement plate (flux gelé) a un RSI de
  100 dans le calcul partagé et reçoit donc l'état `overbought`. Ce n'est pas un
  signal de marché.
- Journal : un résultat estimé ignore les frais, le swap et le glissement ; seul
  le résultat du courtier (`--pnl`) les inclut.
- Journal : un seul compte, en USD (le capital vient de `account.capital` de la
  configuration). Pas d'import depuis le courtier : tout est saisi à la main.
- Journal : moins de 30 trades clôturés, les statistiques ne permettent pas de
  conclure (l'avertissement est affiché) ; une ligne de moins de 5 trades porte la
  mention « peu de trades ».
- Journal : si le risque prévu est inconnu à l'ouverture (cours de conversion
  introuvable), le R du trade est « non calculable » et le trade reste hors des
  moyennes en R.
- Journal : l'estimation d'une paire croisée utilise un cours de conversion unique
  (celui du jour, sauf `--quote-usd-rate`), pas celui du moment de la sortie.
- Journal : `alerts.json` ne contient aucun résultat ni capital ; le journal
  lui-même n'envoie aucune alerte, c'est le serveur d'alertes (voir « Serveur
  d'alertes »).
- Tous les chemins sont relatifs au répertoire courant : lancer les commandes
  depuis la racine du dépôt, `C:/Users/m.poirat/TRADING`.
- Le téléchargement à 3 tâches fait trois requêtes Yahoo simultanées : mettre
  `WORKERS = 1` dans `fx.py` si une erreur HTTP 429 apparaît (les nouvelles
  tentatives après un 429 sont silencieuses).

## Ce qu'il ne fait jamais

Il ne place et ne vérifie aucun ordre, ne dit jamais quoi acheter ou vendre, ne
choisit jamais une idée pour l'utilisateur, ne présente jamais des données
retardées comme du temps réel, ne promet jamais qu'un setup fonctionne, et ne
donne jamais une taille inventée : une taille non calculable reste « à
confirmer ». Le journal n'invente jamais un prix, une taille ni un résultat : ce
que l'utilisateur ne donne pas est demandé ou reste « inconnu ».

## Sécurité

- Éducation et outillage, pas un conseil financier. « A matché une règle »
  n'est pas une recommandation.
- Les idées de trade sont des plans mécaniques à valider, pas des conseils.
- Aucun ordre n'est jamais placé par ce skill. Il lit des graphiques, lit le
  fichier de configuration facultatif et écrit deux fichiers sous `trader/fx/`
  (`briefing.json` et `briefing.html`). `journal.py` écrit en plus
  `journal.json`, `journal.json.bak`, `alerts.json` et `journal.html`, et ne
  touche jamais au courtier.
- Le serveur d'alertes lit ses secrets dans l'environnement GitHub et ne les affiche
  jamais ; les erreurs Telegram ne donnent que le code HTTP. `alerts.auto_push` ne
  pousse que `alerts.json` (des niveaux, pas de résultats).
- Le dépôt est **public** (compte de prop firm, accepté par l'utilisateur) : tout ce qui
  est commité est lisible par tous, y compris `alerts.json` (niveaux et symboles des
  trades ouverts) et la page du briefing sur GitHub Pages (avec la ligne « Compte »). Ne
  jamais commiter `trader/fx/config.json`, et ne pas commiter `journal.json` ni
  `journal.html` (ils contiennent les résultats) sans que l'utilisateur l'ait décidé ;
  ne publier `journal.html` qu'en Artifact privé.
- Les comptes CFD et forex de particuliers perdent couramment de l'argent, et
  le levier amplifie les pertes. Commencer par un compte de démonstration
  (paper trading) avant tout compte réel.
- Les clés de courtier restent dans des variables d'environnement, jamais dans
  le chat.
