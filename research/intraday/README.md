# Scripts de recherche intraday (jetables)

Ces scripts ont produit les résultats de `docs/research/2026-11-17-intraday-replay-findings.md`.
Ce sont des **spikes** : ils ne sont ni testés, ni maintenus, ni dans la suite de tests du dépôt.
Ils servent à refaire ou contrôler les chiffres de la note.

## Données attendues (non versionnées)

- **Barres 1 minute MT5** exportées de Google Drive en CSV (`date;time;open;high;low;close;volume;spread_moyen;spread_max`,
  séparateur virgule, une feuille par mois, nom `SYMBOLE_AAAA_MM.csv`), à ranger dans `fx_data/<SYMBOLE>/`
  à côté des scripts : EURUSD, GBPUSD, USDJPY (2016-01 à 2026-10), XAUUSD, DAX, NAS100, US30 (2018-01 à fin sept. ou oct. 2026).
- L'heure des fichiers est celle du serveur du courtier : **New York + 7 h** (UTC+2 l'hiver, UTC+3 l'été).
  `replay2.server_to_utc` fait la conversion.
- Barres journalières Yahoo (18 marchés) : `trend_d1.py` les télécharge lui-même (bornes de dates explicites ;
  `range=max` renvoie des barres mensuelles).
- Relevés de positions MQL5 (`*.positions.csv`, données de tiers) : non versionnés (voir `.gitignore`).

## Chemins à adapter

`replay2.py` importe les modules de `.claude/skills/trader-fx` via un chemin absolu (`SKILL`) ; les scripts
`an*.py` et `analyse_positions.py` lisent des relevés à un chemin absolu. Ajuster avant usage.

## Ordre des scripts

| Étape | Scripts |
|---|---|
| Rejeu des alertes 15 min | `replay_spike.py` (or, 13 mois), `replay2.py` (10 ans) puis `report.py` ; `be_report.py` (effet du point mort) |
| Tendance H1/H4/D1, 3 paires | `trend_test.py` |
| Tendance D1 diversifiée (18 marchés) | `trend_d1.py` |
| Momentum intraday et effets de session | `intraday_mom.py`, `session_open.py` |
| Setups MTF / cassure / niveaux | `setups_test.py` puis `setups_report.py` |
| Bollinger 5 min (160 ; 2,8), retournement | `bb_user.py` + `bbu_report.py`, `bb_sl.py` (stops courts), `bb_grid.py` (robustesse), `bb_reint.py` + `bbr_report.py` (entrée à la réintégration) |
| Cassure de bande / de fenêtre (études d'événements) | `bb_event.py` + `bbe_report.py`, `brk_event.py` + `brk_report.py` |
| Gestion sur cassures de 4 h | `mgmt_test.py` (les tableaux de résultats ont été produits par un script de résumé lancé à la volée, non conservé : voir la note) |
| Analyse des relevés MQL5 | `analyse_positions.py` (relevé 2381033), `an2.py` à `an7.py` (relevé 2265877) |

## Conventions communes

- Coût : achat à l'ask, vente au bid (le spread du fichier est intégré). Aucun glissement.
- Sur une même barre 1 min, le stop passe avant la cible (hypothèse pessimiste).
- Les règles sont fixées avant les résultats ; exploration 2016/2018-2022, confirmation 2023-2026.
- Témoin « miroir » : même géométrie, sens inverse, pour isoler l'effet de la direction.
