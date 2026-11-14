# trader-fx : trades potentiels avec taille de position

Date : 2026-11-14. Statut : en attente de relecture.
Complète le spec du briefing (`2026-11-13-trader-fx-briefing-design.md`) et réalise la partie « taille de position » du sous-projet 2.

## 1. Contexte et objectif

Le briefing `trader-fx` liste des graphiques qui ont matché une règle, mais ne dit pas lesquels méritent d'être regardés en premier ni quelle taille de position leur donner. Les 5 règles actuelles sont toutes haussières.

Objectif : une section « Trades potentiels » qui range les meilleures idées dans les deux sens, avec un plan chiffré (entrée, stop, cible, rapport gain/risque) et une taille de position calculée pour le compte de l'utilisateur. Ce sont des idées de plan mécaniques à valider, jamais des conseils ni des ordres.

Ce que l'utilisateur a dit : « voir plus clairement les trades potentiels à prendre », avec plan chiffré et taille de position ; compte de 100 000 USD ; risque de 0,5 % par trade ; levier maximum 30:1 ; règles symétriques (hausse et baisse) ; pour les indices et matières premières, une table de contrats que l'utilisateur remplit.
Hypothèses (à corriger à la relecture) : le prix de référence est la dernière clôture Yahoo (retardée) ; une idée n'est valable qu'après revalidation à l'ouverture ; aucune intégration avec un courtier.

## 2. Hors périmètre

- Aucun ordre, aucun lien avec un courtier, aucun suivi de positions ouvertes.
- Pas d'alertes (sous-projet 3) ni de journal (sous-projet 4).
- Pas de chiffre de gain ou de perte potentiel : seulement le risque maximal au stop, le rapport gain/risque, les lots, le levier et la valeur du pip.
- Une devise de compte autre que l'USD (version 1).
- Pas de calcul du financement (swap), ni du spread, ni de la marge exacte d'un courtier.

## 3. Critères de succès

1. `fx.py brief` écrit `trade_ideas` dans `briefing.json` : au plus `max_shown` idées, chacune avec sens, règles, score, entrée, stop, cible, rapport gain/risque et une taille ou un statut explicite.
2. Le risque réel d'une idée ne dépasse jamais `risk.per_trade_pct` du capital.
3. Une taille non calculable s'affiche « à confirmer », jamais un chiffre inventé.
4. Une configuration invalide donne une seule ligne claire, code de sortie 1, et aucun `briefing.json` n'est écrit.
5. Le résumé terminal reste à 40 lignes au plus ; la page s'affiche correctement avec zéro idée.
6. Vocabulaire : « haussier » et « baissier » ; jamais achat, acheter, vente, vendre, buy, sell, gagnant, profit ; aucun chiffre de gain ou de perte.
7. Tous les tests passent sans réseau.

## 4. Architecture

Nouvelles unités dans `.claude/skills/trader-fx/` (Python 3, bibliothèque standard seulement), qui s'ajoutent aux modules existants.

| Fichier | Rôle | Dépend de |
| --- | --- | --- |
| `config.py` | lit et valide `trader/fx/config.json` | rien |
| `signals.py` (étendu) | règles baissières miroir ; ATR en prix | rien de nouveau |
| `plan.py` | idées, score, diversification, entrée/stop/cible | `signals`, `config` |
| `sizing.py` | valeur du pip, lots, plafond de levier, table de contrats | `config` |
| `briefing.py` (étendu) | assemble `trade_ideas`, règle les budgets du résumé | toutes |
| `report_template.html` (étendu) | section « Trades potentiels » | `briefing.json` |
| `fx.py` (étendu) | charge la configuration et la passe à `build_briefing` | `config`, `briefing` |

### 4.1 signals.py

- `find_short_setups(closes) -> (tags, numbers)` : mêmes conditions que `find_setups`, inversées, sur les clôtures (30 séances minimum). `find_setups` reste inchangé (tests de parité avec `scan.py`).

| Règle | Définition |
| --- | --- |
| `breakdown_20d` | la dernière clôture est sous toutes les clôtures des 20 séances précédentes |
| `bear_flag` | baisse de plus de 10 % sur les 10 séances avant les 5 dernières, puis ces 5 clôtures dans une fourchette de moins de 5 % |
| `lose_ma20` | la clôture précédente était au-dessus de la moyenne 20 jours précédente, la dernière est sous la moyenne 20 jours |
| `overbought` | RSI 14 (Wilder) au-dessus de 70 |
| `overbought_reject` | RSI 14 au-dessus de 70 hier et la dernière clôture est en baisse |

- `analyze` ajoute `setups_short` (liste, éventuellement vide) à son résultat ; `swing.hits` = analyses dont `setups` ou `setups_short` est non vide.
- Libellés de page : `breakdown_20d` « Cassure du plus bas 20 j », `bear_flag` « Drapeau baissier », `lose_ma20` « Perte de la moyenne 20 j », `overbought` « Surachat », `overbought_reject` « Rejet depuis le surachat ».

### 4.2 plan.py

**Déclencheurs.** Haussiers : `breakout_20d`, `bull_flag`, `reclaim_ma20`, `oversold_bounce`. Baissiers : `breakdown_20d`, `bear_flag`, `lose_ma20`, `overbought_reject`. `oversold` et `overbought` sont des états : ils comptent dans le score mais ne créent pas d'idée.

**Idée.** Un symbole a une idée haussière s'il a au moins un déclencheur haussier et aucun déclencheur baissier ; inversement pour une idée baissière. Les deux sens à la fois : pas d'idée (raison « signaux contradictoires »).

**Score.** `2 × nombre de déclencheurs concordants` + points de tendance + points de RSI.
- Tendance : concordante +1, contraire −1, « mixed » ou absente 0 (haussière pour une idée haussière, baissière pour une idée baissière).
- RSI : idée haussière, RSI sous 30 : +1, au-dessus de 70 : −1. Idée baissière, RSI au-dessus de 70 : +1, sous 30 : −1.
- Ordre : score décroissant, puis nombre de déclencheurs décroissant, puis symbole croissant (ordre déterministe).

**Diversification.** Chaque idée porte des expositions (devise, signe). Forex `XXXYYY` : haussière = (+XXX, −YYY), baissière = (−XXX, +YYY). Hors forex : l'exposition est le symbole lui-même (la limite ne s'applique pas). En parcourant les idées dans l'ordre, une idée est écartée si l'une de ses expositions est déjà portée par `max_per_exposure` idées retenues (raison « corrélée à <symbole de la première idée retenue> »). On retient au plus `max_shown` idées ; les suivantes sont écartées (« au-delà des N idées affichées (score S) », S étant le score de l'idée écartée). `ties_at_cutoff` = nombre d'idées écartées par cette limite dont le score égale celui de la dernière idée affichée (0 sinon).

**Plan.** ATR en prix = `last × atr_pct / 100`.
- Entrée = dernière clôture.
- Stop = entrée ∓ `stop_atr_mult × ATR` (sous l'entrée pour une idée haussière, au-dessus pour une baissière).
- Cible = entrée ± `target_r × |entrée − stop|` ; rapport gain/risque = `target_r`.
- Arrondi (vague finale) : pas de prix = `10^-decimals` ; forex 5 décimales (3 pour une cotation en JPY) ; autres instruments selon le prix : sous 10, 4 décimales ; sous 100, 3 ; sinon 2. Chaque idée porte `decimals`. Entrée = dernière clôture arrondie au pas le PLUS PROCHE ; stop calculé depuis la clôture NON arrondie puis arrondi en s'éloignant de l'entrée (`floor`/`ceil(round(x/pas, 6))·pas`) ; distance `d = |entrée − stop|` arrondis ; cible = entrée ± `target_r × d`, arrondie en se rapprochant de l'entrée. `reference_price` = entrée arrondie ; la taille est calculée sur l'entrée et le stop arrondis. `rr` reste le `target_r` nominal : la cible étant recalculée depuis la distance arrondie, puis arrondie vers l'entrée, le rapport réalisé est égal au nominal quand `target_r × d` tombe sur la grille de prix, et s'en écarte de moins d'un pas de prix sinon.
- Côtés stricts : haussier `stop < entrée < cible`, baissier `cible < entrée < stop`, stop et cible > 0 ; sinon idée écartée (« plan impossible : stop ou cible sous zéro »).
- Plancher : si `d / entrée × 100 < MIN_STOP_PCT` (constante 0,15) l'idée est écartée (« ATR trop faible : stop dans le bruit ou l'écart de cotation »), jamais dimensionnée.
- ATR indisponible ou nulle : idée écartée (« ATR indisponible »).

**Pourquoi.** Chaque idée porte la liste des points du score, en français (par exemple « +2 cassure du plus haut 20 j », « +1 tendance haussière », « −1 RSI déjà au-dessus de 70 »).

### 4.3 sizing.py

Entrées : capital, `risk.per_trade_pct`, `leverage_max`, le plan, les derniers cours des paires forex analysées, la table `contracts`.
`risk_usd = capital × per_trade_pct / 100`.

**Forex.** Pip = 0,01 si la devise de cotation est JPY, sinon 0,0001. Lot = 100 000 unités ; pas = 0,01 lot (1 000 unités).
- Conversion cotation → USD (`q2u`) : 1 si la cotation est USD ; `1 / cours(USD<cotation>=X)` si cette paire existe ; sinon `cours(<cotation>USD=X)` si elle existe ; sinon aucune.
- Conversion base → USD (`b2u`) : même règle pour la devise de base.
- `perte_par_unité = |entrée − stop| × q2u` pour une cotation en USD (`q2u = 1`, exact) et pour les croisées (ni base ni cotation en USD : conversion au cours du jour de l'entrée ; le cours au stop est inconnu, l'écart résiduel est de l'ordre de la distance au stop en %, documenté dans SKILL.md). Pour une paire dont la BASE est l'USD (USDJPY, USDCHF, USDCAD, USDZAR...) : `perte_par_unité = |entrée − stop| / stop` (la cotation se convertit en USD au cours du stop, exact dans les deux sens). `unités = floor(round(risque_usd / perte_par_unité / 1000, 6)) × 1000` ; lots = unités / 100 000. Exemple : USDJPY 150,00, stop 149,25 → perte 0,75/149,25 par unité → 99 000 unités, 0,99 lot, risque 497,49 USD, levier 0,99, valeur du pip 6,6667 ; baissier 150,00 → 153,00 : 25 000 unités, risque 490,20.
- Plafond de levier : valeur = `unités × b2u` ; si elle dépasse `leverage_max × capital`, les unités sont ramenées au plus grand multiple de 1 000 sous le plafond et `limited_by = "levier"` (sinon `"risque"`).
- Risque réel = `unités × perte_par_unité` ; levier résultant = valeur / capital (2 décimales) ; valeur du pip par lot = `100 000 × pip × q2u` (toujours au cours de l'entrée).
- Statuts : `ok` ; `too_wide` si moins de 0,01 lot tient dans le risque ; `to_confirm` si `q2u` ou `b2u` est inconnu.

**Indices et matières premières.** `contracts["<symbole>"] = {"usd_per_point": ..., "step": ..., "min": ...}` : `usd_per_point` est la valeur en USD d'un mouvement de 1,0 du prix pour une unité de taille (1 lot).
- `perte_par_taille = |entrée − stop| × usd_per_point` ; taille = `floor(risque_usd / perte_par_taille / step) × step` ; `too_wide` si la taille est sous `min`.
- Valeur = `taille × dernier prix × usd_per_point` ; plafond de levier comme ci-dessus ; levier résultant et risque réel de la même façon.
- Symbole absent de la table : `to_confirm` (« taille à confirmer chez le courtier »).

**Risque cumulé.** `total_risk_usd` = somme des risques réels des idées en statut `ok` plus, pour celles en `to_confirm`, le risque prévu `risk_usd`. `over_cap` comparé au centime : `round(total, 2) > round(capital × max_total_pct / 100, 2)`. `max_ideas_within_cap` = plus grand k tel que la somme des k plus grands risques comptés tient dans le plafond (au centime) ; `over_cap` est faux exactement quand k = nombre d'idées comptées. `total_leverage` = somme des leviers des idées `ok` (2 décimales).

### 4.4 config.py et `trader/fx/config.json`

Valeurs par défaut (un fichier absent donne ces valeurs sans erreur) :

```
account: {currency: "USD", capital: 100000}
risk: {per_trade_pct: 0.5, max_total_pct: 2.0}
leverage_max: 30
plan: {stop_atr_mult: 1.5, target_r: 2.0}
ideas: {max_shown: 5, max_per_exposure: 2}
contracts: {}
```

Validation (toute violation lève `ConfigError` avec une phrase) : `currency` doit être `"USD"` (« devise de compte non gérée : USD seulement ») ; `capital > 0` ; `0 < per_trade_pct <= 2` ; `per_trade_pct <= max_total_pct <= 10` ; `1 <= leverage_max <= 500` ; `0.5 <= stop_atr_mult <= 5` ; `1 <= target_r <= 5` ; `1 <= max_shown <= 10` ; `1 <= max_per_exposure <= 5` ; chaque entrée de `contracts` a `usd_per_point > 0`, `step > 0`, `min > 0` ; toute clé inconnue est refusée (faute de frappe). Un fichier illisible ou qui n'est pas du JSON : une phrase aussi.
Le fichier contient le capital de l'utilisateur : il est exclu de git (`.gitignore`). Un `config.example.json` est livré dans le skill, avec des entrées d'exemple pour `^FCHI` et `GC=F` marquées comme à vérifier chez le courtier.

### 4.5 briefing.py, fx.py, page, résumé

**briefing.json** gagne la clé `trade_ideas` :

```
trade_ideas: {
  reference: "last_close",
  account: {currency, capital, risk_per_trade_usd, leverage_max},
  ideas: [{rank, symbol, name, side: "haussier"|"baissier", score, setups:[...], trend,
           reference_price, stop, target, rr, atr,
           size: {status: "ok"|"too_wide"|"to_confirm", lots, units, size, risk_usd,
                  leverage, pip_value_usd_per_lot, limited_by, note},
           why:[texte, ...]}],
  skipped: [{symbol, reason}],
  total_risk_usd, total_risk_pct, max_total_pct, over_cap
}
```

(`lots`/`units` pour le forex, `size` pour les autres instruments ; les champs sans objet valent `null`.)
Clés additives (vague finale) : `account.source` (`"default"` ou `"file"`) ; par idée `decimals` (entier), `last_bar_date` (date ISO de la clôture utilisée, ou `null`) et `since_close` (`null` sans barre 1 h après cette clôture, sinon `{last, stop_crossed, target_crossed}` calculé sur les barres 1 h dont la date UTC est postérieure à `last_bar_date`) ; au niveau de `trade_ideas` : `max_ideas_within_cap`, `ties_at_cutoff`, `total_leverage`.
`build_briefing` reçoit la configuration et calcule `trade_ideas` à partir des analyses, comme les autres sections (fonction pure).

**fx.py** charge la configuration au début de `brief` ; une `ConfigError` donne une ligne, code 1, sans écrire `briefing.json`. Un `--config` explicite (différent du chemin par défaut) qui n'existe pas donne « Fichier de configuration introuvable : <chemin>. », code 1, aucun appel réseau ; le chemin par défaut peut être absent (valeurs par défaut, `account.source = "default"`).

**Ligne de compte** (résumé et page) : capital, risque par idée en % et en USD, levier max, suivie de « (valeurs par défaut) » quand `account.source` vaut `"default"`. **Plafond dépassé** : « Risque cumulé au-dessus du plafond : au plus N idées ouvertes en même temps. » (N = `max_ideas_within_cap`) ; résumé : « : dépassé, au plus N idées ouvertes en même temps ».

**Page.** Section « Trades potentiels » juste après l'en-tête, avant « Résumé » : une note (« Idées de plan mécaniques, issues des règles ci-dessous. À valider, pas des conseils. Prix de référence : dernière clôture. »), une carte par idée (rang, symbole et nom, sens, règles, quatre chiffres : entrée, stop, cible, taille ; puis risque maximal en USD, rapport 1:R, levier, valeur du pip, et la liste « Pourquoi »), une ligne de risque cumulé avec un bandeau si `over_cap`, et la liste des idées écartées avec leur raison. Statuts : `to_confirm` affiche « Taille à confirmer chez le courtier » et l'indication de renseigner `contracts` ; `too_wide` affiche « Stop trop large pour le risque fixé ». Zéro idée : message explicite. Le style suit la charte 4884 déjà appliquée (pas d'emoji, pas de bordure latérale, or en accent seulement). Le sens se lit par le mot (« Haussier », « Baissier ») et pas par la couleur seule.

**Résumé terminal.** Un bloc « Idées de trade (N), plan mécanique à valider » de 8 lignes au plus (une par idée : rang, symbole, sens, entrée, stop, cible, lots ou « taille à confirmer », risque) puis une ligne de risque cumulé. Le budget du reste du résumé est réduit pour rester à 40 lignes.

## 5. Gestion des erreurs

- Configuration invalide : une ligne, code 1, aucun fichier écrit.
- Taille non calculable : statut `to_confirm`, jamais de chiffre inventé.
- Week-end ou données périmées : le bandeau existant s'applique ; la note de la section rappelle que l'entrée est la dernière clôture à revalider.
- Un symbole dont le calcul lève une exception arithmétique est écarté avec sa raison, sans arrêter le briefing. Dans `plan.py`, le plan et la taille de chaque candidat sont protégés par `try/except ArithmeticError` : l'idée est écartée (« calcul impossible (<TypeErreur>) », groupe des écarts précoces, ordre d'entrée).
- Aucune idée : `ideas` vide, message explicite, le reste du briefing est inchangé.

## 6. Tests

`unittest`, sans réseau.
- `signals` : règles baissières par symétrie (série inversée donne les mêmes déclenchements miroir) ; `find_setups` inchangé (parité avec `scan.py`).
- `plan` : score, tendance et RSI aux deux sens ; contradiction sans idée ; ordre déterministe en cas d'égalité ; diversification (3e idée avec la même exposition écartée, « corrélée à ») ; limite `max_shown` ; stop et cible aux deux sens avec arrondis dans le bon sens ; ATR nulle.
- `sizing` : exemples chiffrés à la main (EURUSD : 500 USD de risque et 50 pips donnent 1,00 lot ; USDJPY ; une croisée convertie via une paire en dollar ; plafond de levier qui réduit la taille ; moins de 0,01 lot donne `too_wide` ; arrondi vers le bas ; table `contracts` avec pas et minimum ; symbole absent ; conversion inconnue donne `to_confirm`) ; le risque réel n'excède jamais le risque fixé.
- `config` : valeurs par défaut ; chaque règle de validation ; clé inconnue ; JSON invalide ; fichier absent.
- `briefing` : clés de `trade_ideas`, risque cumulé et `over_cap`, résumé de 40 lignes au plus avec le pire cas, mots interdits.
- Page : rendu avec trois idées, avec zéro idée, avec `to_confirm` et `too_wide`, avec `over_cap` ; le test réseau reste inchangé.
- Essai manuel en direct, à part, avant livraison.

## 7. Points à traiter pendant l'implémentation

- Vérifier sur de vraies données que `q2u` et `b2u` sont trouvés pour les paires exotiques et croisées du briefing, et lister celles qui restent `to_confirm`.
- Remplir `config.example.json` avec des valeurs d'exemple clairement signalées comme à vérifier chez le courtier.
- Ajouter à `SKILL.md` la section sur la configuration, la taille de position et les limites (cours Yahoo retardés, valeur du pip et taille de lot à vérifier chez le courtier).
- Étendre les tests de vocabulaire interdit à « vente », « vendre » et « sell ».

## 8. Suite

Sous-projets 3 (alertes) et 4 (journal) : chacun aura son brainstorming, son spec et son plan. Le journal pourra reprendre les champs de `trade_ideas`.
