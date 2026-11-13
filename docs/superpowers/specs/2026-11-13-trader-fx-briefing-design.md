# trader-fx : données et briefing (sous-projet 1)

Date : 2026-11-13. Statut : en attente de relecture.

## 1. Contexte et objectif

L'utilisateur trade le forex, les CFD (indices) et les matières premières, en day trading ou en swing selon les jours. Le pack `trader-*` existant ne couvre que les actions US (univers Nasdaq Trader, horaires NYSE, actions entières, Alpaca).

Objectif du sous-projet 1 : une commande `brief` qui, chaque matin, collecte les prix, détecte les setups, mesure la force des devises, lit le calendrier économique et produit un briefing en deux formes : un résumé court dans le terminal et une page web (Artifact).

C'est le premier de cinq sous-projets d'un outil tout-en-un. Les suivants (hors de ce spec) : 2 risque et taille de position, 3 alertes, 4 journal et statistiques, 5 tableau de bord. Chacun aura son propre spec.

Ce que l'utilisateur a dit : outil tout-en-un pour forex, CFD et matières premières ; commencer par données et briefing ; horizon « les deux selon le jour » (swing et intraday) ; sortie « terminal + page web ».
Hypothèses (à corriger à la relecture) : l'outil aide à décider et n'envoie aucun ordre ; données gratuites uniquement ; exécution locale ; l'utilisateur est en Europe (heures affichées à Paris et à New York).

## 2. Hors périmètre

- Aucun ordre, aucun lien avec un courtier.
- Pas de taille de position, ni d'alertes, ni de journal (sous-projets 2 à 4).
- Pas de ticks en temps réel. Les barres sont celles de Yahoo, retardées et non officielles.
- Les prix Yahoo sont des prix de référence ; ceux d'un courtier CFD diffèrent (spread, financement). Le briefing le dit.
- Aucune recommandation d'achat ou de vente, aucun chiffre de gain ou de perte.

## 3. Critères de succès

1. `python3 fx.py brief` produit `trader/fx/briefing.json` et un résumé terminal d'environ 40 lignes au plus, en moins de 90 secondes à froid.
2. Le résumé et la page disent combien de symboles ont été demandés, reçus et analysés, et lesquels ont échoué.
3. Un calendrier indisponible, un week-end ou un cache périmé sont signalés dans le briefing, jamais passés sous silence.
4. Tous les tests passent sans réseau.

## 4. Emplacement et approche

Nouveau skill `C:/Users/m.poirat/TRADING/.claude/skills/trader-fx/` : Python 3, bibliothèque standard seulement (comme `scan.py`), tests `unittest`. Les sorties vont dans `trader/fx/`. Les listes d'entrée existent déjà : `trader/lists/fx_pairs.txt` (75 paires), `commodities.txt` (18 futures), `indices.txt` (12 indices et DXY).

Approches écartées : étendre `scan.py` (fichier déjà long et propre aux actions) ; tout faire dans une page web (les requêtes sortantes d'une page publiée sont bloquées).

Flux : Python collecte et calcule, écrit `briefing.json`, affiche le résumé ; Claude publie ensuite la page en y intégrant le contenu du JSON.

## 5. Unités

| Fichier | Rôle | Dépend de |
| --- | --- | --- |
| `data.py` | Récupère et met en cache les barres Yahoo | rien |
| `signals.py` | Setups, ATR, tendance, niveaux | `data.py` |
| `strength.py` | Force des 8 devises, regroupement des signaux corrélés | `data.py` |
| `economic_calendar.py` | Annonces économiques | source externe |
| `sessions.py` | Heures des sessions de marché, état ouvert/fermé | rien |
| `briefing.py` | Assemble `briefing.json` et le résumé terminal | toutes |
| `fx.py` | Ligne de commande (`brief`) | `briefing.py` |

### 5.1 data.py

- Source : Yahoo, endpoint `v8/finance/chart` (il fournit open, high, low, close ; le endpoint spark n'a que les clôtures et ne suffit pas pour l'ATR et les niveaux). Un appel par symbole, pause de 0,3 s, query2 puis query1 sur 429 ou 5xx, une nouvelle tentative après 5 s sur 429, comme `scan.py`.
- `fetch_bars(symbols, interval, range) -> (bars, failed)` où `bars[symbol]` est une liste ordonnée de `(timestamp_utc, open, high, low, close)` et `failed` la liste des symboles sans données avec la raison.
- Deux profils : journalier (plage `6mo`, environ 125 séances) pour tous les symboles ; 1 h sur 5 jours uniquement pour les paires en alerte et les majors. Pas de barres 5 min : aucune sortie du briefing n'en a besoin.
- Cache sur disque dans `trader/fx/cache/`, une entrée par (symbole, intervalle, plage). Durées de validité : 6 h pour le journalier, 10 min pour l'intraday. `--no-cache` l'ignore. Une entrée périmée utilisée après un échec réseau est marquée avec son âge.
- Les barres à valeurs nulles sont supprimées.

### 5.2 signals.py

Par symbole, calculé sur le journalier :

- Les cinq règles du scanner sur les clôtures : `breakout_20d`, `bull_flag`, `reclaim_ma20`, `oversold`, `oversold_bounce`, avec les mêmes définitions que `scan.py` (RSI 14 de Wilder).
- ATR 14 (en prix et en pourcentage du prix).
- Tendance : `up` si clôture au-dessus de la moyenne 50 jours et moyenne 20 au-dessus de la 50, `down` dans le cas inverse, `mixed` sinon.
- Niveaux : haut et bas de la veille, haut et bas de la semaine précédente (semaine calendaire), haut et bas des 20 dernières séances.

Pour les paires en alerte et les majors, à partir des barres 1 h : plage de la session asiatique du jour (00:00 à 07:00 UTC) et plus haut / plus bas depuis 00:00 UTC.

Les règles s'écrivent « a matché une règle », jamais « achat ».

### 5.3 strength.py

- Devises : USD, EUR, GBP, JPY, CHF, AUD, NZD, CAD. Les 28 paires majeures et croisées de `fx_pairs.txt` suffisent (7 majors et 21 croisées).
- Pour chaque paire `BASEQUOTE`, rendement logarithmique sur 1, 5 et 20 séances. Le score d'une devise est la moyenne, sur ses 7 paires, du rendement signé : `+` quand elle est base, `-` quand elle est cotée.
- Sortie : classement des 8 devises sur chaque fenêtre, avec le score.
- Regroupement : les signaux sont regroupés par devise commune. Le briefing indique, par exemple, « 20 des 28 signaux concernent le dollar », pour ne pas présenter des signaux corrélés comme indépendants.
- Les exotiques, les matières premières et les indices n'entrent pas dans ce calcul.

### 5.4 economic_calendar.py

- Source : `https://nfs.faireconomy.media/ff_calendar_thisweek.json` (flux public non officiel, testé le 2026-11-13 : 106 événements, champs `title`, `country`, `date`, `impact`, `forecast`, `previous`). La semaine suivante (`ff_calendar_nextweek.json`) renvoyait 404 ce jour-là.
- Le module tente le fichier de la semaine suivante ; une 404 n'est pas une erreur, c'est « pas encore publié ».
- Filtre : impact `High` par défaut (option pour inclure `Medium`), devises présentes dans les symboles analysés.
- Heures converties en Europe/Paris et America/New_York.
- Statut : `ok`, `partial` (semaine en cours seulement) ou `unavailable` (échec). Le briefing affiche toujours ce statut.
- Flux non officiel : il peut changer ou disparaître. Le design l'isole dans ce seul module.

### 5.5 sessions.py

Sessions sur la convention du forex, avec heure d'été gérée par `zoneinfo` : Sydney 07:00 à 16:00 (Australia/Sydney), Tokyo 09:00 à 18:00 (Asia/Tokyo), Londres 08:00 à 17:00 (Europe/London), New York 08:00 à 17:00 (America/New_York). Sortie : heures d'ouverture et de fermeture du jour à Paris et à New York, session en cours, et état du marché : ouvert, ou fermé (week-end : du vendredi 17:00 au dimanche 17:00 New York). Les futures de matières premières et les indices ont leurs propres horaires ; le briefing n'en déduit pas d'ouverture et affiche seulement la date de la dernière barre reçue.

### 5.6 briefing.py et fx.py

`fx.py brief` accepte `--list FILE` (répétable, par défaut les trois listes), `--no-cache`, `--json` (JSON sur la sortie standard), `--now "YYYY-MM-DD HH:MM"` (heure de New York, pour les tests), `--out PATH` (par défaut `trader/fx/briefing.json`). Code de sortie 0 si le briefing a été produit, 1 sinon, avec une ligne d'explication.

#### briefing.json

```
as_of            horodatage ISO, avec heures Paris et New York
market_state     "open" | "closed_weekend"
counts           {requested, fetched, scanned, failed:[{symbol, reason}]}
data_age         âge du plus ancien cache utilisé, ou null
calendar         {status, events:[{time_paris, time_ny, currency, title, impact, forecast, previous}]}
strength         {windows:{"1d":[{ccy, score}], "5d":[...], "20d":[...]}}
swing            {hits:[{symbol, name, last, rsi, atr_pct, trend, setups:[...]}],
                  clusters:[{ccy, count, of}]}
day_plan         {sessions:[...], levels:[{symbol, prev_high, prev_low, week_high, week_low,
                  asia_high, asia_low}], events_24h:[...]}
warnings         [texte]
disclaimer       "Liste de graphiques qui ont matché une règle. Pas un conseil. Données Yahoo, retardées."
```

#### Résumé terminal

Ordre : état du marché et heure, comptes (demandés, reçus, analysés, échecs), force des devises (meilleure et pire sur 5 jours), annonces à fort impact des prochaines 24 h, hits swing regroupés par famille (forex, matières premières, indices) avec le message de corrélation, avertissements.

#### Page web

Claude lit `briefing.json` et publie un Artifact en y intégrant les données (la page ne fait aucun appel réseau). Sections : en-tête (état, heure, comptes), force des devises (barres), calendrier, setups swing, plan du jour, avertissements. Thème clair et sombre, largeur mobile. La page se republie au même lien à chaque briefing.

## 6. Gestion des erreurs

- Résultat partiel dit partiel : « 74 de 75 paires reçues », avec la liste des échecs.
- Calendrier indisponible : le briefing continue, `calendar.status = "unavailable"`, bandeau visible.
- Cache périmé utilisé après un échec : âge affiché dans `data_age` et dans les avertissements.
- Week-end : dernières clôtures, `market_state = "closed_weekend"`, mention explicite.
- Aucun symbole reçu : une ligne claire, code de sortie 1, pas de `briefing.json` écrit.
- Moins de 30 séances pour un symbole : exclu de l'analyse et compté (comme `scan.py`).
- Garde-fous du pack : pas de « achat » ni de « gagnant », aucun chiffre de gain ou de perte, aucune donnée présentée comme du temps réel.

## 7. Tests

`unittest`, sans réseau, avec des données sauvegardées dans `tests/fixtures/`.

- `signals` : séries synthétiques à RSI, cassure, drapeau et reclaim connus ; ATR sur une série simple ; tendance sur trois cas.
- `strength` : paires synthétiques où une devise monte, elle ressort première ; devise neutre au milieu ; regroupement par devise commune.
- `economic_calendar` : fichier JSON sauvegardé pour le parseur et le filtre ; cas 404 sur la semaine suivante ; cas d'échec total.
- `sessions` : heures correctes avant et après le changement d'heure d'été ; vendredi 17:00 et dimanche 17:00 à New York.
- `data` : lecture et péremption du cache ; barres nulles supprimées ; repli query1.
- Bout en bout : `brief` sur des fixtures complètes ; vérification de chaque clé de `briefing.json` et du résumé terminal.
- Essai manuel en direct, à part, avant livraison.

## 8. Points à traiter pendant l'implémentation

- Un des 12 symboles de `trader/lists/indices.txt` n'a pas renvoyé de données lors d'un scan test le 2026-11-13. Identifier lequel et corriger la liste.
- Vérifier que les endpoints v8 renvoient bien open, high, low pour les symboles `=X` et `=F`.
- Vérifier la plage de la session asiatique sur de vraies barres 1 h de Yahoo pour une paire forex.

## 9. Suite

Sous-projets 2 (risque et taille de position en pips et lots), 3 (alertes), 4 (journal), 5 (tableau de bord) : chacun aura son brainstorming, son spec et son plan. Le sous-projet 2 réutilisera `data.py` pour la valeur du pip et les prix.
