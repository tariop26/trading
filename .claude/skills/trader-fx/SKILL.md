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
  HTML à publier en Artifact. Use when the user says "briefing forex", "scan
  forex", "force des devises", "calendrier économique", "matières premières",
  "indices", "briefing CFD", "trades potentiels", "taille de position", "idées
  de trade", "forex briefing", "currency strength", "economic calendar", "what
  is moving in forex", "commodities and indices scan", "trade ideas", "position
  size", "lot size", or at the start of a forex / CFD trading day.
argument-hint: "[brief | page] [--list FILE] [--no-cache] [--json] [--config PATH]"
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

`briefing.json` et `briefing.html` sont des sorties du jour, ignorées par git.

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
sombre, largeur mobile.

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
  raison « corrélée à <symbole> ». Au plus 5 idées affichées (`ideas.max_shown`).
  Hors forex, l'exposition est le symbole lui-même.
- Plan : entrée = dernière clôture ; stop = 1,5 ATR de l'entrée (sous l'entrée
  pour une idée haussière, au-dessus pour une baissière) ; cible = 2R,
  c'est-à-dire 2 fois la distance au stop, du côté opposé ; rapport 1:2. Arrondi
  au dixième de pip (2 décimales hors forex), stop éloigné et cible rapprochée.
  ATR indisponible : idée écartée.
- Taille : risque fixé = 0,5 % du capital par idée (500 USD pour 100 000 USD),
  arrondi toujours vers le bas, donc le risque réel ne dépasse jamais 0,5 %.
  Forex : lot de 100 000 unités, pas de 0,01 lot, conversion de la devise de
  cotation en USD par la paire en dollar du briefing, plafond de levier 30:1 (la
  taille est réduite si besoin, `limited_by` vaut alors `levier`). Indices et
  matières premières : taille calculée avec la table `contracts`.
- Statuts de taille : `ok` ; `too_wide` quand moins de 0,01 lot (ou moins que le
  minimum du contrat) tient dans le risque fixé, ou quand le plafond de levier
  passe sous le minimum ; `to_confirm` quand une taille ne peut pas être
  calculée (symbole absent de `contracts`, taux de conversion USD introuvable,
  distance au stop nulle). Jamais une taille inventée.
- Risque cumulé : somme des risques réels des idées `ok`, plus le risque fixé
  (0,5 %) pour chaque idée `to_confirm`. Au-dessus de `risk.max_total_pct`
  (2 % par défaut), `over_cap` vaut vrai et le résumé et la page le disent :
  c'est un avertissement, aucune idée n'est supprimée.

## Configuration

`trader/fx/config.json` est facultatif : un fichier absent donne les valeurs par
défaut, sans erreur. Il contient le capital de l'utilisateur : il est ignoré par
git. `fx.py brief --config PATH` lit un autre fichier. Les sections absentes
reprennent leurs valeurs par défaut, section par section.

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

## Règles

- Dire ce qui a été lu : combien de symboles demandés, reçus, analysés, et
  l'heure des données (dernière barre).
- Dire « a matché une règle », jamais « achat », « vente », « gagnant » ni
  « bon trade ». Pour une idée : « haussier » ou « baissier », jamais les mots
  achat, acheter, vente, vendre, buy, sell, gagnant, profit.
- Aucun chiffre de gain ou de perte sur un trade, aucun profit : seulement le
  risque maximal au stop, le rapport 1:R, les lots, le levier et la valeur du pip.
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
- Devise de compte : USD seulement (version 1).
- Les règles ne créent jamais une idée à partir d'un état seul (`oversold`,
  `overbought`).
- Particularité connue : une série parfaitement plate (flux gelé) a un RSI de
  100 dans le calcul partagé et reçoit donc l'état `overbought`. Ce n'est pas un
  signal de marché.
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
confirmer ».

## Sécurité

- Éducation et outillage, pas un conseil financier. « A matché une règle »
  n'est pas une recommandation.
- Les idées de trade sont des plans mécaniques à valider, pas des conseils.
- Aucun ordre n'est jamais placé par ce skill. Il lit des graphiques, lit le
  fichier de configuration facultatif et écrit deux fichiers sous `trader/fx/`.
- Les comptes CFD et forex de particuliers perdent couramment de l'argent, et
  le levier amplifie les pertes. Commencer par un compte de démonstration
  (paper trading) avant tout compte réel.
- Les clés de courtier restent dans des variables d'environnement, jamais dans
  le chat.
