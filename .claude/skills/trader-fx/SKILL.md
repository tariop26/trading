---
name: trader-fx
description: >-
  Briefing forex, matières premières et indices (CFD). Lit des graphiques
  Yahoo gratuits et retardés (jour et 1 heure) pour environ 104 symboles : paires
  forex, matières premières, indices. Calcule la force des devises (1, 5 et 20
  séances), lit le calendrier économique de la semaine (annonces à fort impact
  des prochaines 24 h), cherche les setups swing (cassure du plus haut de 20
  jours, drapeau haussier, retour au-dessus de la moyenne 20 jours, survente,
  rebond de survente) avec RSI, ATR et tendance, regroupe les signaux corrélés
  par devise commune, et prépare un plan du jour (niveaux de la veille et de la
  semaine, plage de la session asiatique, sessions Tokyo, Londres, New York).
  Écrit trader/fx/briefing.json et une page HTML à publier en Artifact. Use
  when the user says "briefing forex", "scan forex", "force des devises",
  "calendrier économique", "matières premières", "indices", "briefing CFD",
  "forex briefing", "currency strength", "economic calendar", "what is moving
  in forex", "commodities and indices scan", or at the start of a forex / CFD
  trading day.
argument-hint: "[brief | page] [--list FILE] [--no-cache] [--json]"
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
python3 "${CLAUDE_SKILL_DIR}/fx.py" page                     # trader/fx/briefing.json -> trader/fx/briefing.html
python3 "${CLAUDE_SKILL_DIR}/fx.py" page --in PATH --out PATH   # défauts : --in trader/fx/briefing.json, --out trader/fx/briefing.html
```

Options de `brief` : `--list FILE` (répétable ; par défaut les trois listes
`trader/lists/fx_pairs.txt`, `commodities.txt`, `indices.txt`), `--no-cache`,
`--json`, `--now "YYYY-MM-DD HH:MM"` (heure de New York), `--out PATH` (par
défaut `trader/fx/briefing.json`). Code de sortie 0 quand le briefing est
produit, 1 sinon, avec une ligne d'explication. Si aucun symbole n'est reçu,
aucun `briefing.json` n'est écrit.

## Ce qu'il lit et écrit

| fichier | quoi |
| --- | --- |
| `trader/lists/fx_pairs.txt`, `commodities.txt`, `indices.txt` | lus par `brief` : une ligne `SYMBOLE\|Nom` par symbole (symboles Yahoo : `EURUSD=X`, `GC=F`, `^GSPC`) |
| `trader/fx/briefing.json` | écrit par `brief` : `as_of`, `market_state`, `counts`, `data_age`, `calendar`, `strength`, `swing`, `day_plan`, `warnings`, `disclaimer` |
| `trader/fx/briefing.html` | écrit par `page` : page autonome, données intégrées, aucun appel réseau |
| `trader/fx/cache/` | cache disque des barres Yahoo : 6 h pour les barres journalières, 10 min pour les barres 1 h. Ignoré par git |

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
- Résultat partiel dit partiel : « Reçus : N sur M (k en échec) », avec la liste des
  échecs et leur raison. Un symbole avec moins de 30 séances complètes est
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
| setups swing | `breakout_20d`, `bull_flag`, `reclaim_ma20`, `oversold`, `oversold_bounce` avec RSI, ATR en % du prix et tendance, par famille (forex, matières premières, indices) ; le message de corrélation dit combien de signaux forex partagent une devise (par exemple « 6 des 9 signaux forex concernent le dollar (USD) : signaux corrélés, pas indépendants ») |
| plan du jour | sessions Tokyo, Londres, New York ; niveaux par symbole : plus haut et plus bas de la veille, de la semaine précédente, de 20 jours, plage de la session asiatique (00:00 à 07:00 UTC) et plus haut/bas du jour |
| avertissements | marché fermé, symboles exclus, calendrier partiel, cache périmé utilisé après un échec (âge affiché) |

Le résumé terminal tient en 40 lignes au plus. La page web a six sections :
Résumé, Force des devises, Calendrier, Setups swing, Plan du jour,
Avertissements. Thème clair et sombre, largeur mobile.

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
   message de corrélation, enfin les avertissements (calendrier partiel,
   week-end, cache).
3. Lancer `fx.py page`, puis contrôler la fraîcheur : lire `as_of` dans
   l'en-tête de la page (ou dans `briefing.json`) et le comparer à l'heure
   actuelle. La page affiche aussi un bandeau rouge « périmé » quand `as_of`
   a plus de 12 heures. Ne pas publier une page périmée comme si elle datait
   d'aujourd'hui.
4. Publier `trader/fx/briefing.html` avec l'outil Artifact (icône `chart`).
   Aux exécutions suivantes, republier au même lien (même chemin de fichier,
   ou le `url` de l'Artifact déjà publié). Donner le lien à l'utilisateur.
5. L'utilisateur choisit un graphique. Ne jamais choisir à sa place. Lui
   remettre le graphique choisi : le jugement est le sien. Les skills
   `trader-news`, `trader-entry`, `trader-exit`, `trader-budget`,
   `trader-risk` et `trader-broker` sont faits pour les actions américaines
   et ne s'appliquent PAS au forex, aux matières premières ni aux indices : le
   dire à l'utilisateur plutôt que de les enchaîner.

## Règles

- Dire ce qui a été lu : combien de symboles demandés, reçus, analysés, et
  l'heure des données (dernière barre).
- Dire « a matché une règle », jamais « achat », « vente », « gagnant » ni
  « bon trade ».
- Aucun chiffre de gain ou de perte, aucun rendement, aucun profit.
- Les données Yahoo sont retardées : ne jamais les présenter comme du temps
  réel. Un setup est périmé dès que le prix a bougé : relancer avant d'en parler.
- Un week-end, les valeurs sont les dernières clôtures, et la plage de la
  session asiatique du jour est vide : le dire.
- Les signaux forex qui partagent une devise (par exemple plusieurs paires
  contre le dollar) sont corrélés : ce n'est pas une confirmation
  indépendante.

## Limites connues

- Pas de barres de 5 minutes, pas de données tick par tick : les plus fines
  sont les barres 1 h.
- Le volume du forex n'est pas disponible chez Yahoo : aucun signal de volume
  sur les paires.
- Flux de calendrier non officiel, Yahoo non officiel : l'un ou l'autre peut
  changer de format ou disparaître.

## Ce qu'il ne fait jamais

Il ne place, ne dimensionne et ne vérifie aucun ordre, ne dit jamais quoi
acheter ou vendre, ne présente jamais des données retardées comme du temps
réel, et ne promet jamais qu'un setup fonctionne.

## Sécurité

- Éducation et outillage, pas un conseil financier. « A matché une règle »
  n'est pas une recommandation.
- Aucun ordre n'est jamais placé par ce skill. Il lit des graphiques et écrit
  deux fichiers sous `trader/fx/`.
- Les comptes CFD et forex de particuliers perdent couramment de l'argent, et
  le levier amplifie les pertes. Commencer par un compte de démonstration
  (paper trading).
- Les clés de courtier restent dans des variables d'environnement, jamais dans
  le chat.
