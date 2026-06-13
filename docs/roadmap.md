# Feuille de route — rendre le moteur de classement utilisable

État au 12/06/2026 : le moteur de scoring (paquet [classement/](../classement/)) couvre les
neuf grilles de l'arrêté n° 345 ([data/grids/](../data/grids/)), les profils
d'établissement ([enset-skikda](../data/institutions/enset-skikda.json)), le circuit Excel
complet (modèles, import, PV, fiches, HTML) et la couche coûts/budget (indemnités de
l'arrêté du 25/12/2011, simulation par campagne et par exercice selon l'art. 6).
S'y ajoute désormais l'**application web** ([webapp/](../webapp/), MVP de la phase 2) :
espaces enseignant/commission/admin, justificatifs PDF, rejets motivés, gel du
classement et exports officiels — prête à déployer sur Coolify
([guide](guide-deploiement-coolify.md)). Le projet est versionné sur GitHub
(`SamRepository/classement-stages`), historique purgé des données nominatives.

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

## Phase 1bis — Campagne u3 2026 (pont Odoo → Excel) — ABSORBÉE PAR LA PHASE 2

Objectif initial : lancer le classement réel des 41 candidatures u3 sans attendre
l'application web. Le MVP web étant arrivé avant la collecte, la phase 1bis se réduit
au pont Odoo → application :

1. **Convertisseur [scripts/import_odoo.py](../scripts/import_odoo.py)** ✅ — export
   Excel du module Odoo « Stages » (avec colonne **Email** ajoutée côté Odoo) →
   `dossier-u3.xlsx` : 41 candidatures (id, e-mail, nom, département, rang,
   destination, durée, montant) + feuille Historique (date du dernier stage), avec
   contrôle croisé zones/montants contre `data/costs`.
2. **Collecte des critères et activités** : décision actée — **directement dans
   l'application web** (un élément déclaré = une ligne + son justificatif PDF). Les
   fiches de déclaration Excel ([scripts/fiches_declaration.py](../scripts/fiches_declaration.py),
   `declarations/`) sont conservées en secours mais ne seront pas distribuées.
3. **Justificatifs** : uploadés dans l'application (volume persistant), servis à la
   commission sous contrôle d'accès — plus de dossier réseau.
4. Classement + PV + fiches u3 : produits par l'application (mêmes exports que la CLI).

## Phase 2 — Application web sur Coolify — MVP RÉALISÉ (12/06/2026), ciblée campagne u3 2026

Application **FastAPI + Jinja2/HTMX + SQLAlchemy/PostgreSQL** ([webapp/](../webapp/))
réutilisant le paquet `classement` tel quel — aucune logique réglementaire dupliquée,
le moteur est rappelé à chaque calcul. 59 tests dédiés (147 au total), dont la **parité**
dossier web ≡ dict moteur pour chaque type de critère.

**Réalisé** :
- **Espace enseignant** : connexion par e-mail (le même identifiant qu'Odoo), formulaire
  généré depuis la grille JSON, une ligne par activité avec **justificatif PDF rattaché**,
  score provisoire recalculé en temps réel (HTMX), soumission = dossier gelé, **rang et
  score retenus affichés après le gel** (lus depuis le snapshot d'audit, avec rappel que
  le rang ne vaut pas attribution) ;
- **Espace commission** : chaque élément face à son justificatif (visionneuse), **valider /
  rejeter avec motif obligatoire** (art. 14-15, contrainte en base), élément rejeté exclu
  du calcul avec trace, observations du moteur affichées, classement (ex aequo signalés),
  **gel** bloqué tant qu'un élément reste en attente + instantané JSON d'audit, exports
  PV / fiches / HTML, **simulation budgétaire** (13/06/2026 : enveloppe + plafond billet,
  ordre de financement par rang, coupure stricte, synthèse par population — lecture
  seule, mêmes règles que la CLI `budget`) ;
- **Espace admin** : import de comptes **directement depuis `dossier-u3.xlsx`** (comptes +
  dossiers + mobilité + historique des bénéfices en une opération, idempotent — recette
  réelle : 41/41), gestion des bénéfices, fenêtre de campagne, réouverture d'un dossier ;
- **Base de données** : dossiers, éléments déclarés, pièces, décisions, **bénéfices
  persistants** (pénalités `3-n` et fenêtre calculées automatiquement), journal des
  actions ; migrations Alembic ;
- **Déploiement** : Dockerfile, docker-compose de dev, variables d'environnement,
  [guide Coolify pas-à-pas](guide-deploiement-coolify.md) ;
- **Préparation à la mise en service** (13/06/2026) : changement de mot de passe par
  l'utilisateur connecté, pages d'erreur HTML en français (+ alerte HTMX pour les refus),
  bandeau « phase expérimentale » avec contact sur la page de connexion.

**Reste à faire** :
- déploiement effectif sur l'instance Coolify (PostgreSQL + volume `/data/uploads` +
  HTTPS) puis recette réelle (un dossier complet saisi et comparé au barème) ;
- simulation d'**exercice multi-campagnes** (art. 6) dans l'interface — la simulation
  budgétaire par campagne est faite (13/06/2026) ; l'exercice attend que l'application
  gère plusieurs campagnes simultanées (MVP : une seule), reste disponible via la CLI ;
- import Odoo via **XML-RPC** (remplaçant l'export Excel manuel) — reporté en phase 3.

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
| 1bis | Campagne u3 2026 : pont Odoo → application | **Absorbée par la phase 2** — convertisseur `import_odoo.py` réalisé (export reçu avec e-mail, 41 candidatures) ; collecte des critères : directement dans l'application web, fiches Excel en secours |
| 2 | Application web FastAPI + PostgreSQL sur Coolify, uploads PDF, validation commission, historique persistant | **MVP réalisé** (12/06/2026) pour la campagne u3 2026 — `webapp/`, 135 tests, dépôt GitHub ; simulation budgétaire commission ajoutée (13/06/2026) ; reste : déploiement effectif sur Coolify ([guide](guide-deploiement-coolify.md)), recette réelle, exercice multi-campagnes dans l'interface |
| 3 | Adaptation du module Odoo 14 « Stages » (3a façade XML-RPC recommandée / 3b intégration native) | Après le déploiement de la phase 2 |
| 4 | Notifications, vérification Crossref/Scopus, archivage | Ultérieur |
