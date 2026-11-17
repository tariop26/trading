# Rejeu historique et recherche intraday : résultats (17 novembre 2026)

## 1. Résumé

Le rejeu historique des signaux en séance (spec `2026-11-17-trader-fx-intraday-signals`, section 6) a été fait sur
10 ans de barres 1 minute, puis étendu à une vingtaine d'hypothèses intraday classiques. **Aucune stratégie intraday
rentable après coûts n'a été trouvée.** Les seuls signes durables sont petits et lents.

| Piste | Résultat |
|---|---|
| Alertes 15 min (5 familles), 3 paires, 2016-2026 | R moyen −0,07 par trade ; aucune famille positive |
| Setups MTF, cassure, range, niveaux clés | nuls ou négatifs |
| Bollinger 5 min (160 ; 2,8) en retournement, indices | négatif partout, aucun réglage voisin positif |
| Momentum intraday, effets de session | rien d'exploitable (la dérive nocturne des indices est absorbée par le financement) |
| Tendance H1/H4/D1 sur 3 paires USD | rien de distinguable de zéro |
| Tendance D1 diversifiée (18 marchés) | Sharpe d'environ 0,35 à 0,4, stable mais petit |
| Signal MQL5 2265877 (entrée, gestion, filtre horaire) | non reproduit |

Conséquences dans le dépôt : `intraday.enabled` vaut `false` par défaut ; `SKILL.md` ne dit plus « non testés » mais
« testés, sans avantage » ; les scripts sont dans `research/intraday/`.

## 2. Données et méthode

- **Barres 1 min** (Google Drive, export MT5, `date,time,open,high,low,close,volume,spread_moyen,spread_max`) :
  EURUSD, GBPUSD, USDJPY de 2016-01 à 2026-10 (130 mois chacune) ; XAUUSD, DAX, NAS100, US30 de 2018-01 à fin sept. ou oct. 2026.
  Heure du fichier = heure du serveur du courtier = New York + 7 h (UTC+2 l'hiver, UTC+3 l'été). Vérifié en
  comparant les prix de deux relevés de positions aux barres (écart médian 0,4 à 0,7 point).
- **Barres journalières Yahoo** (18 marchés, ETF avec dividendes et forex spot) pour la tendance diversifiée.
- **Coûts** : achat à l'ask, vente au bid, spread du fichier. Pas de glissement. Pas de financement (swap) des CFD.
- **Simulation** : stop avant cible si les deux sont touchés dans la même minute (pessimiste). Entrée à la minute
  suivant le signal (rejeu des alertes : 7 min après la clôture de la barre, comme le cron `:07/:22/:37/:52`).
- **Discipline** : règles fixées avant de regarder ; exploration 2016/2018-2022 puis confirmation 2023-2026 sans
  retoucher les paramètres ; témoin « miroir » (même géométrie, sens inverse) ; intervalles de confiance à 95 %.
- Les fonctions du dépôt (`scan_symbol`, `select`, `mark_signal`) ont été réutilisées telles quelles pour le rejeu.

## 3. Résultats

R = résultat en multiple du risque initial. pb = point de base. t = écart à zéro en erreurs types.

### 3.1 Alertes 15 min (les 5 familles du dépôt)

- **Or, 13 mois** (sept. 2025 à sept. 2026) : 1 642 alertes, 1 240 entrées prises, R moyen −0,10 (IC −0,17 à −0,03).
- **EURUSD, GBPUSD, USDJPY, 10 ans** : 53 428 alertes, 43 119 entrées prises (dans la zone de validité).

| | R moyen (IC95) |
|---|---|
| EURUSD / GBPUSD / USDJPY | −0,065 / −0,087 / −0,066 |
| Exploration 2016-2022 / confirmation 2023-2026 | −0,067 / −0,083 |
| Par famille principale | `session_break` −0,042, `bb_return` −0,069, `engulfing` −0,080, `fractal_break` −0,085, `rsi_exit` −0,123 |
| Signal moins sens inverse (appariés) | −0,026 (−0,045 à −0,007) |

Chaque année de 2016 à 2026 est négative. Le brut est proche de zéro : les coûts font la perte.

### 3.2 Point mort à 30 % de la distance au TP

Mêmes entrées avec et sans point mort. Alertes 15 min : +0,006 R (−0,000 à +0,012). Setups S1 à S3 : de −0,006 à
+0,011 R. Le point mort transforme environ 25 à 39 % des trades en sorties à zéro mais n'ajoute pas d'espérance.

### 3.3 Tendance par croisement de moyennes (3 paires, 2016-2026)

Sharpe du portefeuille des 3 paires (IC95 ±0,55) : H1 10/50 −0,07, H1 20/100 +0,18, H4 10/50 −0,11, H4 20/100 −0,15,
D1 10/50 +0,08, D1 20/100 +0,21. Aucune combinaison ne tient dans les deux périodes.

### 3.4 Tendance D1 diversifiée (18 marchés Yahoo, 2007-2026)

5 actions, 2 obligations, 5 matières premières, 6 devises ; volatilité cible 10 % par marché ; coût 2 pb.

| Règle | 2007-2015 | 2016-2022 | 2023-2026 | Tout (IC95) |
|---|---|---|---|---|
| SMA 20/100 | 0,44 | 0,41 | 0,16 | 0,38 (±0,43) |
| Momentum 252 j | 0,31 | 0,37 | 0,39 | 0,35 (±0,43) |
| SMA 10/50 | 0,42 | 0,12 | −0,27 | 0,18 |
| Témoin toujours long | 0,28 | 0,39 | 1,22 | 0,52 |

Par classe (SMA 20/100) : obligations 0,46, actions 0,29, matières premières 0,16, devises 0,10. Rendement faible
(environ 1,6 à 1,9 % par an à 4,6 % de volatilité). Univers choisi avec le recul, frais de vente à découvert ignorés.

### 3.5 Momentum intraday (indices et or, 2018-2026, net par trade)

Règle A : sens veille → ouverture+30 min, tenue sur les 30 dernières minutes. Règle B : première demi-heure tenue
jusqu'à la clôture.

| Instrument | A | t | B | t |
|---|---|---|---|---|
| NAS100 | −1,6 pb | −1,9 | +2,1 pb | 0,9 |
| US30 | −2,1 pb | −3,1 | −2,5 pb | −1,5 |
| DAX | −0,3 pb | −0,6 | −1,0 pb | −0,6 |
| Or, Londres | −1,3 pb | −3,2 | −3,1 pb | −2,0 |
| Or, New York | −1,3 pb | −4,7 | −1,5 pb | −1,2 |

### 3.6 Effets d'ouverture de session

- **H1 devises** (littérature Breedon-Ranaldo) : EURUSD vendu 07-13 h UTC +0,8 pb (t = 1,5, s'érode : +1,0 → +0,4) ;
  GBPUSD +0,1 ; USDJPY acheté 00-07 h UTC −0,7 ; euro et livre achetés 13-21 h UTC −0,3 / −0,2.
- **H3 cassure de la plage de Londres** (08:00-08:30) tenue jusqu'à 16:30 : EURUSD −1,0 pb, GBPUSD +1,0, or +0,1.
- **H2 dérive nocturne** (clôture → ouverture suivante, achat) : DAX +2,0, NAS100 +3,3, US30 +2,7 pb par nuit
  (t = 1,2 à 1,8). Seul signe de même sens partout, mais le financement CFD (environ 1,4 pb par nuit à 5 % l'an,
  plus le week-end) l'absorbe presque entièrement ; non testé avec les vrais swaps du courtier.

### 3.7 Setups classiques (stop 1,5 ATR H1, cible 2R, 24 h max ; 7 instruments, 2016/2018-2026)

| Setup | Trades | R moyen (IC95) | Signal moins sens inverse |
|---|---|---|---|
| S1 MTF : tendance D1 + reprise de l'EMA 20 en H1 | 12 497 | −0,052 (−0,074 à −0,029) | −0,042 |
| S2a compression + cassure | 8 741 | +0,002 | +0,047 |
| S2b cassure dans le sens de la tendance D1 | 3 635 | +0,013 (−0,031 à +0,056) | +0,060 (non significatif) |
| S2c range : fade d'une cassure ratée | 7 275 | −0,031 | −0,005 |
| S3 rejet sur niveau clé (veille, semaine, SMA 50 D1) | 3 219 | −0,044 (−0,089 à 0,000) | −0,025 |

### 3.8 Bollinger 5 min (160 ; 2,8), retournement sur les indices (DAX, NAS100, US30, 2018-2026)

Entrée limite sur la bande, moitié à la médiane (TP1) puis point mort, moitié à la bande opposée (TP2), séance de
bourse, une entrée par excursion.

| Stop (× distance bande → médiane) | Trades | R moyen |
|---|---|---|
| 0,1 / 0,2 / 0,3 | 21 969 / 17 859 / 15 559 | −0,256 / −0,153 / −0,121 |
| 0,5 / 1,0 | 13 046 / 10 490 | −0,093 / −0,054 |

- **Robustesse** (période 40, 80, 160, 320 × écart 2,0 à 3,6, stop 1,0) : les 20 cases sont négatives, de −0,096 à
  −0,020. (160 ; 2,8) n'est pas un pic isolé. Moins négatif avec des bandes plus larges et moins de trades.
- **Entrée à la réintégration** (clôture 5 min revenue dans la bande, stop au-delà de la mèche) : −0,071 (18 680
  trades) ; −0,063 si risque ≥ 3 spreads ; −0,024 (−0,053 à +0,005) si risque ≥ 10 spreads (filtre ajouté après coup).
- **Hypothèse d'exécution optimiste** : ordre limite exécuté exactement sur la bande, sans glissement.

### 3.9 Deux relevés de positions MQL5 (données de tiers, XAUUSD)

**2381033** (84 positions, juillet à novembre 2026, net +419 $, dépôts de 70 $ à 2 000 $) : entrées à trois
créneaux fixes (07:02, 12:01, 15:02 à New York), sens du mouvement des 30 min à 2 h précédentes (19 cas sur 20),
renforts toutes les 30 min contre la position, sortie groupée, aucun stop visible, taille multipliée par 6 après une
perte (15 septembre : panier à −65 $ puis paniers de 0,23 et 0,24 lot). 31 paniers gagnants sur 33 mais pire panier
= 5 fois le gain moyen : profil de moyennage sans stop.

**2265877** (933 positions, oct. 2024 à nov. 2026, net +5 141 $ pour un dépôt d'environ 1 600 $, 71 % de gagnantes,
facteur de profit 2,0, tous les semestres positifs, achats +2 476 $ et ventes +2 665 $, pire drawdown réalisé −665 $) :
- Entrées **dans le sens du mouvement** (99 à 100 % d'accord de 1 h à 24 h), au plus haut ou au plus bas récent
  (médiane : 1 minute après l'extrême des 4 h, 0,2 ATR 5 min de distance). 97 à 98 % des entrées dépassent le plus
  haut ou bas de la bougie H1 ou H4 précédente (25 à 47 % à des instants aléatoires). Concentration 13-15 h UTC.
- Pas de rythme de bougie, pas d'objectif ni de stop fixe lisible ; 27 % de sorties autour de zéro ; les 10 meilleures
  positions font 45 % du profit.
- **Ce n'est pas Bollinger.** Un z autour de +2,8 à l'entrée décrit seulement un prix près de son plus haut récent ; ma
  première lecture « bande (160 ; 2,8) » était une erreur de cadrage (corrigée avec l'utilisateur).
- **Reproduction hors de son historique, sans succès** (cassure du plus haut/bas des 4 h, or et 3 indices) :
  - entrée seule, fixe à +5/+15/+60/+240 min : brut proche de zéro, net négatif ;
  - gestions testées (stop 3 ATR ; A objectif 1:1, B point mort puis trailing, C moitié à +3 ATR) sur l'or :
    −0,23 R (2018-2022), −0,19 à −0,21 (2023-oct. 2024), −0,04 à −0,07 (sa période), sens inverse souvent meilleur ;
  - filtre 13-15 h UTC : moins négatif (coûts plus faibles en R à l'ouverture US) mais jamais positif de façon
    significative (or, gestion B : +0,03 à +0,07 R, t ≈ 0,8).
- **Biais de sélection probable** : un signal MQL5 est affiché parce qu'il a bien marché.

## 4. Erreurs rencontrées et corrigées pendant l'étude

- Rejeu : le sens « long » était comparé à « haussier » (toutes les alertes simulées baissières) → corrigé, résultats
  refaits.
- Yahoo `range=max` renvoie des barres mensuelles → bornes de dates explicites ; premiers résultats D1 écartés.
- Hypothèse H3 mal définie (cassure impossible à 08:30) → redéfinie sur les clôtures 15 min 08:45-12:00.
- Test Bollinger : ré-entrées en boucle dans la même excursion (15 trades par jour) → une entrée par excursion.
- Relevé 2265877 : lecture initiale « Bollinger 160 ; 2,8 » abandonnée (voir 3.9).

## 5. Limites

- Résultats valables pour des CFD (spreads, heures et financement du courtier), pas pour des futures ou ETF.
- Une seule définition par idée ; pas de recherche de réglages (ce serait du surajustement).
- Univers restreint : 3 paires USD, l'or, 3 indices ; pas de croisés (JPY, CHF), pas de pétrole, pas de cuivre en 1 min.
- Filtre d'annonces et swaps non simulés. Le simulateur n'a pas de test automatisé (contrôles : reproduction exacte
  du premier script, témoin « miroir »).
- Un grand nombre d'hypothèses ont été testées : quelques faux positifs étaient attendus, aucun n'est apparu.

## 6. Conclusions et suite possible

1. Ne pas risquer de capital réel sur les alertes en séance ; elles sont désactivées par défaut.
2. Si une approche est poursuivie, la tendance lente diversifiée (Sharpe 0,35 à 0,4) est la mieux documentée, mais
   son rendement reste faible pour son risque.
3. Suivre le signal MQL5 2265877 en direct, sans risque, pendant 2 à 3 mois : seule vérification non biaisée.
4. Pistes non testées : financement réel des swaps pour la dérive nocturne, futures ou ETF, filtre d'annonces,
   croisés de devises.
