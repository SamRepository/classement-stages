# Feuille de route — rendre le moteur de classement utilisable

État au 11/06/2026 : le moteur de scoring (paquet [classement/](../classement/)) couvre les
neuf grilles de l'arrêté n° 345 ([data/grids/](../data/grids/)), les profils
d'établissement ([enset-skikda](../data/institutions/enset-skikda.json)), le circuit Excel
complet (modèles, import, PV, fiches, HTML) et la couche coûts/budget (indemnités de
l'arrêté du 25/12/2011, simulation par campagne et par exercice selon l'art. 6).

Contexte ENSET pour l'exercice 2026 : seule la campagne **u3 — résidences scientifiques
de haut niveau (7–15 jours)** nécessite un classement (41 candidatures recensées). Les
autres mobilités sont servies par priorité du conseil (perfectionnement en anglais —
programme spécial, doctorants non salariés, MCA préparant un doctorat). La collecte des
demandes se fait via un module **« Stages » sous Odoo 14** (portail website) qui ne couvre
ni les critères/activités, ni la validation, ni le classement.

Infrastructure disponible : serveur **Proxmox** avec instance **Coolify** (déploiement de
projets GitHub, conteneurs Docker, instance **PostgreSQL** possible).

---

## Phase 1 — Excel entrée/sortie ✅ (réalisée le 10/06/2026)

Modèles de saisie générés depuis les grilles, import avec rapport d'erreurs, exports
officiels (PV, fiches d'évaluation, HTML imprimable), simulation budgétaire (`budget`)
et simulation d'exercice multi-campagnes (`exercice`, art. 6). Guide utilisateur :
[guide-excel.md](guide-excel.md).

## Phase 1bis — Campagne u3 2026 (pont Odoo → Excel) — EN COURS

Objectif : lancer le classement réel des 41 candidatures u3 sans attendre l'application
web.

1. **Convertisseur `scripts/import_odoo.py`** : export Excel du module Odoo « Stages » →
   pré-remplissage de la feuille Candidats de `dossier-u3.xlsx` (id, nom, prénom,
   département, et selon l'export : rang, destination, durée). *En attente de l'export
   Odoo (ou de ses en-têtes de colonnes) pour le mapping.*
2. **Collecte des critères et activités** — choix à fixer :
   - fiche de déclaration individuelle (mini-classeur ou formulaire généré depuis la
     grille u3, pré-rempli au nom du candidat), ou
   - formulaire Google Forms (export CSV → consolidation scriptée), ou
   - saisie directe par le service depuis les dossiers déposés.
3. **Justificatifs** : dossier réseau `justificatifs/<id_candidat>/`, lien par les
   colonnes DOI/URL pour les publications.
4. Classement + PV + fiches + simulation budgétaire u3 avec l'outillage existant.

## Phase 2 — Application web sur Coolify (campagne 2027)

Application **FastAPI + PostgreSQL** réutilisant le paquet `classement` tel quel (le
moteur est déjà une bibliothèque pilotée par les grilles JSON).

**Déploiement** (infrastructure déjà en place) :
- repo GitHub → Coolify (build Dockerfile, HTTPS, redéploiement sur push) ;
- PostgreSQL en instance Coolify adjacente ; volumes persistants pour les pièces
  jointes ;
- configuration par variables d'environnement (établissement, campagne, plafonds).

**Espace enseignant** :
- authentification simple (comptes pré-créés depuis les candidatures Odoo) ;
- formulaire généré depuis la grille JSON (même principe que les modèles Excel) ;
- une entrée par activité (publication, communication, encadrement…) avec **upload du
  justificatif PDF rattaché à l'élément déclaré**, DOI/URL, dates ;
- score provisoire visible en temps réel, dossier soumis = gelé.

**Espace commission** :
- chaque élément déclaré affiché côte à côte avec son justificatif → **valider /
  rejeter avec motif** (le rejet motivé est une exigence de l'art. 14-15) ;
- recalcul du score en direct ; gel du classement ;
- PV, fiches d'évaluation et **simulation budgétaire / exercice** intégrés (réutilisation
  directe de `exports.py` et `budget.py`).

**Base de données** (apport décisif par rapport à l'Excel) :
- candidats, dossiers, éléments déclarés, pièces, décisions de la commission ;
- **historique des mobilités persistant** : les bénéficiaires financés de l'exercice N
  alimentent automatiquement les pénalités (`3-n`, `-5×n`) et la fenêtre « après dernier
  bénéfice » de l'exercice N+1 — plus de feuille Historique à ressaisir.

**Intégration Odoo (entrée)** : import des candidatures depuis le module « Stages » via
l'API XML-RPC d'Odoo 14 (demandes + pièces jointes), à défaut import de l'export Excel.
Odoo reste la porte d'entrée de la *demande* ; l'application gère critères, validation,
classement et budget.

## Phase 3 — Adaptation du module Odoo 14 « Stages »

Objectif : aligner le module existant sur les nouvelles spécifications sans dupliquer le
moteur. Deux variantes, de la plus légère à la plus intégrée :

**3a — Odoo comme façade (recommandée)** :
- étendre le formulaire de demande du portail : type de mobilité (référentiel arrêté
  345), rang/population, destination + durée (calcul de zone), estimation billet et
  frais, upload des justificatifs par activité déclarée ;
- synchronisation avec l'application de classement via XML-RPC (export des demandes et
  pièces ; en retour, publication du **statut** au candidat : reçu, en vérification,
  classé n/N, retenu/non retenu avec motif) ;
- le moteur, la validation commission et la simulation budgétaire restent dans
  l'application Coolify — un seul endroit où la logique réglementaire vit.

**3b — Intégration native (si l'équipe Odoo le souhaite)** :
- le paquet `classement` étant du Python pur sans dépendance lourde, il peut être
  installé dans l'environnement Odoo et appelé depuis un module (vues commission,
  rapports QWeb pour PV/fiches) ;
- coût : développement Odoo spécifique plus important, et Odoo 14 est en fin de support —
  à n'envisager qu'adossé à une migration de version (16/17+).

Critère de choix : 3a préserve l'indépendance du moteur (testable, versionné, réutilisable
par d'autres établissements) et minimise le développement Odoo ; 3b ne se justifie que si
tout le SI doit converger dans Odoo.

## Phase 4 — Confort et fiabilisation

- Notifications (dépôt, validation, publication des résultats) ;
- vérification semi-automatique des publications via les API Crossref/Scopus (les DOI
  collectés depuis la phase 1 rendent ce contrôle direct : classe de revue, position
  d'auteur réelle, date) ;
- archivage des campagnes et des justificatifs ; statistiques pluriannuelles.

---

## Décision

| Phase | Contenu | Statut |
|---|---|---|
| 1 | Modèle Excel + import + PV/fiches + budget/exercice | **Réalisée** (10/06/2026) |
| 1bis | Campagne u3 2026 : convertisseur Odoo→Excel + collecte critères | **En cours** — en attente de l'export Odoo et du choix du mode de collecte |
| 2 | Application web FastAPI + PostgreSQL sur Coolify, uploads PDF, validation commission, historique persistant | Cible campagne 2027 — démarrage en parallèle de 1bis |
| 3 | Adaptation du module Odoo 14 « Stages » (3a façade XML-RPC recommandée / 3b intégration native) | Après le socle de la phase 2 |
| 4 | Notifications, vérification Crossref/Scopus, archivage | Ultérieur |
