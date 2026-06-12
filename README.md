# classement-stages

Moteur de classement des candidats au programme de mobilité de courte durée à l'étranger
(perfectionnement, résidences scientifiques, manifestations internationales) défini par
l'**arrêté MESRS n° 345 du 9 mars 2026**.

Les neuf barèmes annexés à l'arrêté sont transcrits en JSON dans
[data/grids/](data/grids/) (voir [data/grids/README.md](data/grids/README.md) pour la
cartographie des annexes, le modèle de données et les lectures validées). Le moteur charge
une grille, évalue chaque dossier candidat (avec son historique de mobilités) et produit le
détail du score par critère ainsi que le classement par population et par groupe.

Deux circuits d'utilisation : le **circuit Excel** (phase 1, piloté par la CLI) et
l'**application web** ([webapp/](webapp/), phase 2) qui couvre la campagne de bout en
bout — déclaration en ligne avec justificatifs PDF, validation par la commission avec
rejets motivés, classement gelé et exports officiels.

## Prérequis

Python ≥ 3.10 et `openpyxl` (`pip install openpyxl`) pour le moteur, les modèles de
saisie et les exports Excel ; pytest pour les tests. Pour l'application web :
`pip install -e .[webapp,dev]` (FastAPI, SQLAlchemy, Alembic…).

## Profils d'établissement

Le moteur est générique ; la personnalisation passe par un **profil d'établissement** dans
[data/institutions/](data/institutions/) (départements, populations, grilles applicables,
règles de classement, quotas). Le profil de référence est
**[enset-skikda.json](data/institutions/enset-skikda.json)** — École Normale Supérieure
d'Enseignement Technologique de Skikda (Azzaba), quatre départements : Technologie,
Mathématiques et Informatique, Physique et Chimie, Sciences Naturelles. Étant une école
(type « université » au sens des grilles), seules les grilles u1–u4 s'y appliquent.

Avec `--institution`, la CLI :

- **valide** chaque dossier (département connu, population admise pour la grille, grille
  applicable à l'établissement) et ajoute les anomalies aux avertissements ;
- applique les **règles de classement du profil** (`ranking_rules`, première règle qui
  matche) : la commission de l'ENSET a opté pour un classement de toutes les populations —
  doctorants et maîtres assistants compris — **à l'échelle de l'école**. Ce niveau est
  paramétrable sans toucher au code : le profil contient en
  `ranking_rules_alternatives` la variante « doctorants classés par département » (note de
  l'annexe u4), à insérer en tête de `ranking_rules` pour l'activer ;
- répartit les **places selon les quotas** de l'article 5 (commande `places`).

Pour ajouter un autre établissement : copier
[_template.json](data/institutions/_template.json) vers `<id>.json` et l'adapter.

## Application web (phase 2 — campagne en ligne)

Application **FastAPI + Jinja2/HTMX + SQLAlchemy** ([webapp/](webapp/)) qui réutilise le
moteur tel quel — chaque score affiché est recalculé par `classement.engine`, aucune
logique réglementaire dupliquée. Trois espaces :

- **Enseignant** : connexion par e-mail (le même identifiant que le portail Odoo),
  formulaire généré depuis la grille JSON, une ligne par activité avec son **justificatif
  PDF**, score provisoire en temps réel, soumission = dossier gelé ;
- **Commission** : chaque élément déclaré face à son justificatif, **valider / rejeter
  avec motif obligatoire** (art. 14-15), recalcul immédiat, classement avec ex aequo
  signalés, **gel** (bloqué tant qu'un élément reste en attente, instantané d'audit en
  base), exports PV / fiches / HTML ;
- **Admin** : import des comptes et dossiers **directement depuis `dossier-u3.xlsx`**
  (produit par [scripts/import_odoo.py](scripts/import_odoo.py) : comptes, mobilité et
  historique des bénéfices en une opération idempotente), gestion de la campagne,
  réouverture de dossiers.

Démarrage local (SQLite par défaut) :

```powershell
pip install -e .[webapp,dev]
python -m webapp.scripts.seed --admin-email admin@local
python -m uvicorn webapp.main:app --reload
```

Déploiement : Dockerfile + PostgreSQL + volume pour les pièces jointes — guide pas-à-pas
Coolify : **[docs/guide-deploiement-coolify.md](docs/guide-deploiement-coolify.md)**.

## Circuit Excel (phase 1 — recommandé pour la commission)

Le circuit complet : générer un modèle de saisie → le faire remplir par le service →
importer, scorer, classer → produire les documents officiels à signer.
**Guide détaillé pour l'opérateur et la commission : [docs/guide-excel.md](docs/guide-excel.md).**

### Étape 1 — Choisir la grille et générer le modèle

Une campagne = une grille = un classeur. Pour l'ENSET :

| Population | Type de mobilité | Grille |
|---|---|---|
| Enseignants, maîtres assistants, doctorants | Manifestation scientifique indexée | `u1-manifestations-internationales` |
| Personnel administratif et technique | Stage de perfectionnement | `u2-personnel-administratif` |
| Enseignants (MCB et plus) | Résidence scientifique de haut niveau | `u3-residences-scientifiques` |
| Doctorants, maîtres assistants, enseignants | Stage de perfectionnement | `u4-perfectionnement` |

```powershell
python -m classement template --grid u3-residences-scientifiques --institution enset-skikda `
    --out modele-u3.xlsx
```

Les quatre modèles ENSET pré-générés sont dans [examples/enset/](examples/enset/).
Note : le rang scientifique se saisit dans u1, u2 (catégories) et u3 — **pas dans u4**,
dont l'annexe n'attribue aucun point au grade.

### Étape 2 — Remplir le classeur

Le classeur contient cinq feuilles. Commencer par lire **Referentiel**, qui documente
chaque critère : libellé, points, plafonds et surtout la colonne « où saisir ».

**Feuille Candidats** — une ligne par candidat :
- `id` (obligatoire, identifiant unique, ex. matricule), `nom`, `prenom` ;
- `population` et `departement` : menus déroulants (libellés français) ;
- critères à choix (rang…) : menu déroulant — ex. « Maître de conférences B », avec la
  colonne `... (bonus Oui/Non)` pour le bonus habilitation +4 des MCB ;
- critères Oui/Non (polycopié, projet startup…) et leurs colonnes bonus
  (« +2 si en anglais »…) ;
- critères en points (évaluation du supérieur, poste supérieur…) : valeur numérique,
  plafonnée automatiquement ;
- compteurs simples (années d'ancienneté, inscriptions au doctorat…) : colonnes `(qte)`.

**Feuille Activites** — une ligne par élément compté nécessitant un détail
(publications, communications, encadrements, e-learning…) :
- `candidat_id` : doit correspondre à un `id` de la feuille Candidats ;
- `element` : menu déroulant « critère :: item » (ex. `publications :: classe_a`) ;
- `quantite` (défaut 1) ;
- `position_auteur` : pour les publications — position du candidat parmi les auteurs
  (1 = 100 %, 2 = 90 %, 3 = 80 %, 4 = 70 %, 5+ = 50 %) ;
- `date (AAAA-MM-JJ)` : date de l'élément — les éléments antérieurs au dernier bénéfice
  sont automatiquement écartés ; un élément non daté est compté mais signalé ;
- `doi` / `url` : référence de la publication ou de la communication indexée — reportée
  sur la fiche d'évaluation pour la vérification par la commission ; son absence sur un
  élément indexé est signalée en observation ;
- `porteur_nb` : nombre de projets dont le candidat est porteur (+1/projet, grilles
  chercheurs) ;
- `bonus_nb` : nombre d'éléments donnant droit au bonus du critère (ex. cours e-learning
  en anglais).

**Feuille Historique** — une ligne par mobilité déjà obtenue : `candidat_id`,
`date_mobilite`, `date_cloture_plateforme`. C'est cette feuille qui alimente les
pénalités (`3-n`, `-5×n`…) et la fenêtre « après dernier bénéfice » — la remplir
soigneusement.

### Étape 3 — Importer, scorer, classer et exporter

```powershell
python -m classement score --grid u3-residences-scientifiques --institution enset-skikda `
    --candidates dossiers-u3.xlsx --campaign-date 2026-06-30 `
    --export-pv pv-u3.xlsx --export-fiches fiches-u3.xlsx --export-html classement-u3.html `
    --format markdown
```

Les erreurs de saisie (département inconnu, valeur hors barème, date invalide, candidat
inconnu dans Activites/Historique…) sont rapportées avec **la feuille et la ligne**
(ex. `Candidats!L4 : valeur 'Recteur' hors barème pour rang_scientifique`) ; les lignes
valides sont traitées. Corriger le classeur puis relancer la commande.

### Étape 4 — Documents produits

- **`pv-u3.xlsx`** : PV de classement, une feuille par groupe (rang, candidat, score,
  ex aequo, colonnes Décision — menu Accepté/Rejeté — et Motif, bloc signature du
  président du conseil scientifique) ;
- **`fiches-u3.xlsx`** : une fiche d'évaluation par candidat — détail par critère,
  observations (plafonnements appliqués, pièces hors fenêtre…), total, rang,
  décision/motif (le rejet doit être motivé, art. 14-15) ;
- **`classement-u3.html`** : version imprimable de l'ensemble, une page par fiche —
  **c'est la voie PDF** (Imprimer → Enregistrer en PDF dans le navigateur).

### Bon à savoir

- `--campaign-date` doit être la date de clôture du dépôt des dossiers de la campagne :
  c'est la référence des fenêtres de pénalité (3/4/5/6 ans selon la grille).
- Chaque publication occupe sa propre ligne dans Activites (à cause de la position
  d'auteur et de la date) : c'est ce qui permet la pondération 100/90/80/70/50 % et le
  contrôle de la fenêtre imposés par l'arrêté.
- Les menus acceptent aussi les identifiants techniques (`mcb`, `technologie`…) si le
  classeur est rempli par programme — voir [scripts/make_example_xlsx.py](scripts/make_example_xlsx.py).
- Exemple complet rempli : [examples/enset/dossiers-u4.xlsx](examples/enset/dossiers-u4.xlsx)
  (régénérable via `python scripts/make_example_xlsx.py`).

## Utilisation (JSON)

```powershell
# Scorer et classer les candidats ENSET-Skikda
python -m classement score --grid u4-perfectionnement --institution enset-skikda `
    --candidates examples\enset\candidats-u4.json --campaign-date 2026-06-30 `
    --format markdown --breakdown

# Répartir 40 places selon les quotas de l'article 5
python -m classement places --institution enset-skikda --total 40

# Simulation budgétaire : qui peut bénéficier avec l'enveloppe disponible ?
# (indemnités de l'arrêté du 25/12/2011 + billet plafonné + frais divers)
python -m classement budget --grid u4-perfectionnement --institution enset-skikda `
    --candidates examples\enset\dossiers-u4.xlsx --campaign-date 2026-06-30 `
    --budget 1000000 --plafond-billet 250000

# Simulation de l'exercice complet : répartition proposée de l'enveloppe (art. 6),
# campagnes financées dans l'ordre de priorité (premières = prioritaires)
python -m classement exercice --institution enset-skikda --budget 5000000 `
    --campagne u4-perfectionnement=dossiers-u4.xlsx `
    --campagne u3-residences-scientifiques=dossiers-u3.xlsx `
    --campaign-date 2026-06-30 --plafond-billet 250000

# Scorer et classer des candidats sur une grille (sortie JSON, sans profil)
python -m classement score --grid u1-manifestations-internationales `
    --candidates examples\candidats-u1.json --campaign-date 2026-06-30

# Classement par département (règle u4 pour les doctorants), rendu markdown avec détail
python -m classement score --grid u1-manifestations-internationales `
    --candidates examples\candidats-u1.json --campaign-date 2026-06-30 `
    --group-by departement --format markdown --breakdown

# Écrire le résultat dans un fichier
python -m classement score --grid u2-personnel-administratif `
    --candidates examples\candidats-u2.json --out resultats.json
```

`--grid` accepte l'identifiant d'une grille de `data/grids/` ou le chemin d'un JSON de
grille. `--campaign-date` est la date de référence pour les fenêtres de pénalité
(défaut : aujourd'hui).

### En tant que bibliothèque

```python
from classement import (
    find_grid, load_shared_rules, score_candidate, rank_candidates,
    load_institution, validate_candidate, group_by_for, allocate_places,
)

grid = find_grid("u4-perfectionnement")
shared = load_shared_rules()
enset = load_institution("enset-skikda")

breakdowns = [score_candidate(grid, c, shared, "2026-06-30") for c in candidates]
for c, b in zip(candidates, breakdowns):
    b.warnings.extend(validate_candidate(enset, c, grid))

groups = rank_candidates(
    candidates, breakdowns,
    group_by=lambda c: group_by_for(enset, grid["id"], c.get("population")),
)
places = allocate_places(40, enset)  # quotas de l'article 5
```

## Format du dossier candidat

Voir les exemples dans [examples/](examples/) et la documentation détaillée en tête de
[classement/engine.py](classement/engine.py). En résumé :

```json
{
  "id": "C001",
  "population": "enseignant_chercheur",
  "grouping": { "departement": "Informatique", "faculte": "NTIC" },
  "benefits": [{ "date": "2024-09-15", "platform_close_date": "2024-04-30" }],
  "entries": {
    "rang_scientifique": { "value": "professeur" },
    "penalite_beneficies_3ans": {},
    "publications": {
      "items": [{ "item": "classe_a", "count": 1, "author_position": 2, "date": "2025-03-10" }]
    }
  }
}
```

Le moteur applique automatiquement :

- la **pondération par position d'auteur** (1er 100 %, 2e 90 %, 3e 80 %, 4e 70 %, 5e+ 50 %) ;
- les **plafonds** par item (`cap_units`, `cap_points`), partagés (`shared_caps`) et de bloc
  (`block_caps`, ex. 70 pts max de publications dans les grilles chercheurs) — en conservant
  les unités les mieux valorisées ;
- les **formules de pénalité** (`3-n`, `4-n`, `5-n`, `-5×n`) avec calcul automatique de `n`
  depuis `benefits` et la fenêtre du critère (3/4/5/6 ans selon la grille) ;
- le **filtrage « après dernier bénéfice »** : les travaux datés antérieurs à la clôture de la
  plateforme de la dernière mobilité sont ignorés (les travaux non datés sont comptés avec
  avertissement) ;
- les **bonus** : habilitation MCB (+4, une fois), porteur de projet (+1/projet), supports en
  anglais (+2), etc.

Chaque entorse ou approximation (plafonnement appliqué, entrée non datée, valeur inconnue,
population hors champ de la grille) est signalée dans les `warnings` du détail — la
traçabilité est pensée pour les commissions, qui doivent motiver leurs décisions (art. 14-15).

## Classement et ex aequo

Le classement est calculé par groupe `(grille, population[, clés de regroupement])` en rang
« compétition » (1, 2, 2, 4). **L'arrêté ne définit pas de critère de départage** : les ex
aequo sont signalés (`ex_aequo: true`) et laissés à l'arbitrage de la commission.

## Tests

```powershell
python -m pytest -q
```

135 tests : le moteur (six types de critères, plafonds, pondération auteur, fenêtres
temporelles, formules, classement, profils d'établissement, coûts/budget) et le circuit
Excel (modèle, menus en libellés français, import avec rapport d'erreurs, équivalence
Excel/JSON, exports PV/fiches/HTML), plus l'application web
([tests/webapp/](tests/webapp/)) : **parité dossier web ≡ dict moteur** pour chaque type
de critère, application des rejets avec trace, workflow brouillon/soumis/gelé,
permissions par rôle, uploads (octets magiques, taille), import de comptes, classement,
gel, exports et simulation budgétaire commission.

## Structure du projet

```
classement/          # paquet Python : moteur + classement + profils + coûts/budget + Excel + CLI
webapp/              # application web FastAPI (espaces enseignant/commission/admin, Alembic)
data/grids/          # barèmes de l'arrêté 345 transcrits en JSON + règles transverses
data/costs/          # indemnités (arrêté du 25/12/2011) + zones I/II
data/institutions/   # profils d'établissement (enset-skikda + modèle _template)
docs/decret_loi/     # arrêté source (scan) + JORA n° 71 (indemnités)
docs/roadmap.md      # feuille de route ; guide-deploiement-coolify.md ; guide-excel.md
examples/enset/      # modèles Excel u1-u4 ENSET + exemple rempli + JSON
scripts/             # import Odoo, génération des exemples Excel, audit des grilles
tests/               # suite pytest (moteur + tests/webapp/)
Dockerfile           # image de production (migrations au démarrage) ; docker-compose.yml : dev
```
