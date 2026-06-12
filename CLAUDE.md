# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Le projet

Moteur de classement des candidats à la mobilité à l'étranger selon l'**arrêté MESRS
n° 345 du 09/03/2026** (Algérie). Déployé d'abord pour l'ENSET-Skikda, conçu
multi-établissements. Langue du projet : **français** (docstrings, libellés, sorties,
docs) ; identifiants de code en anglais.

## Commandes

```powershell
python -m pytest -q                                  # suite complète
python -m pytest tests/test_engine.py::test_item_cap_units -q   # un seul test
python scripts/audit_grids.py                        # à lancer après TOUTE modification d'une grille
python scripts/make_example_xlsx.py                  # régénère les modèles/exemples Excel (échoue en PermissionError si un .xlsx est ouvert dans Excel)
python -m classement template --grid <id> --institution enset-skikda --out modele.xlsx
python -m classement score --grid <id> --institution enset-skikda --candidates <fichier .json|.xlsx> --campaign-date AAAA-MM-JJ [--export-pv pv.xlsx --export-fiches fiches.xlsx --export-html doc.html]
python -m classement places --institution enset-skikda --total 40
```

Dépendance unique : `openpyxl` (pip). Python ≥ 3.10.

## Architecture — piloté par les données

**Les barèmes ne sont JAMAIS codés en dur en Python.** `data/grids/*.json` (9 grilles
transcrites du décret : u1–u4 universités/écoles, rc5–rc9 centres de recherche) sont la
source de vérité ; `classement/engine.py` les interprète génériquement. Toute évolution
d'un barème = édition du JSON, pas du moteur. `data/grids/shared-rules.json` porte les
règles transverses (pondération par position d'auteur, fenêtres, déduplication
Scopus/WOS, quotas art. 5), référencées par id dans les tableaux `rules` des grilles.

Chaîne de traitement :

```
grille JSON + profil établissement + dossiers candidats (JSON ou .xlsx)
   └─ engine.score_candidate() ─ 6 types de critères : enum, count, fixed, capped,
      manual_scores, formula → ScoreBreakdown (lignes + détails + warnings)
   └─ ranking.rank_candidates() ─ groupes (grille, population[, grouping]) ;
      rang « compétition » 1,2,2,4 ; group_by = liste OU callable par candidat
   └─ exports.py ─ PV de classement, fiches d'évaluation, HTML imprimable (voie PDF)
```

Subtilités du moteur à connaître avant de le modifier :

- **Plafonds** : `cap_units` (unités, on garde les mieux valorisées — tri glouton),
  `cap_points` (ligne), `shared_caps` (unités partagées entre items, ex. 4
  communications orales+posters), `block_caps` (bloc par scope, ex. 70 pts max de
  publications chercheurs). Ordre d'application dans `_score_count`.
- **Fenêtre `after_last_benefit`** : filtre les items datés antérieurs à la clôture de
  plateforme du dernier bénéfice ; item non daté = compté + warning.
- **Formules** (`3-n`, `-5*n`…) : `n` est calculé depuis `candidate.benefits` et la
  fenêtre déduite du **nom du critère** (regex `(\d)ans` sur l'id, ex.
  `penalite_beneficies_3ans`). **Renommer un id de critère formule casse cette
  inférence.** rc6 (`(N) - n`) exige `n` et `N` explicites, plafonné à N-1.
- Les `warnings` des lignes sont la traçabilité pour la commission (rejets motivés,
  art. 14-15) — ne pas les supprimer pour « nettoyer » la sortie.

**Profils d'établissement** (`data/institutions/*.json`, modèle `_template.json`) :
départements, populations, grilles applicables, `ranking_rules` (première règle qui
matche → group_by), quotas. Décision commission ENSET : classement de toutes les
populations à l'échelle de l'école ; la variante « doctorants par département » est
conservée dans `ranking_rules_alternatives`. Le moteur reste générique — toute
personnalisation passe par le profil.

**Circuit Excel** (`classement/excel_io.py`) : `column_plan(grid)` est l'unique source
de vérité partagée entre la génération du modèle et l'import — toute évolution de l'un
doit passer par lui. Routage automatique des critères `count` : feuille « Activites »
(format long) si fenêtre/pondération/bonus/shared_cap, sinon colonnes `(qte)` dans
« Candidats ». Les menus déroulants affichent les `label_fr` ; l'import accepte libellé
ou identifiant. Guide utilisateur : `docs/guide-excel.md`.

## Conventions des grilles JSON

- `flags` = incertitude de lecture **non résolue** (à confirmer) ; `notes` = lecture
  **confirmée** ou écart documenté entre grilles. Historique des validations dans
  `data/grids/README.md` et `docs/audit-grilles.md`.
- u3 est structurellement identique à u1 (seuls les rangs éligibles diffèrent) ; u4 n'a
  **pas** de critère de rang (conforme à l'annexe 4). Les écarts rc5/rc6 sont réels.
- Pas de critère de départage des ex aequo : choix du décret, ne pas en inventer un.

## Économie de contexte (important)

- **Ne jamais relire** `docs/345-1.pdf` ni les rendus `docs/_pages/*.png` (très coûteux
  en tokens) : les barèmes sont intégralement transcrits dans `data/grids/` et validés
  (voir `docs/audit-grilles.md`). Idem pour `docs/journal71-1.pdf` → `data/costs/`.
- Les classeurs Excel se lisent via `classement.excel_io.read_candidates`, pas en
  inspection cellule par cellule.
- Le gros œuvre est verrouillé par la suite de tests : pour la maintenance courante,
  un modèle économique suffit — réserver les modèles premium aux décisions
  d'architecture.

## Source réglementaire

`docs/345-1.pdf` est un **scan arabe sans couche texte**. Pour le relire : rendre les
pages en PNG 300 DPI via PyMuPDF (`fitz`) puis lecture visuelle — `pdftoppm` n'est pas
disponible sur cette machine, `pypdf`/`pdfplumber` non installés. Rendus existants dans
`docs/_pages/` (régénérables, supprimables).
