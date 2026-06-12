# Guide du circuit Excel — saisie, scoring et documents officiels

Guide de la phase 1 (voir [roadmap.md](roadmap.md)) à destination de l'opérateur qui
prépare la campagne (service de la post-graduation / des relations extérieures) et de la
commission. Il couvre la génération du modèle de saisie, le remplissage du classeur,
l'import avec contrôles, et la production des documents à signer.

Référence réglementaire : arrêté MESRS n° 345 du 09/03/2026 ([345-1.pdf](decret_loi/345-1.pdf)),
barèmes transcrits dans [../data/grids/](../data/grids/) (audit de conformité :
[audit-grilles.md](audit-grilles.md)).

---

## Vue d'ensemble

```
template ──► classeur vierge ──► remplissage par le service ──► score ──► PV + fiches + HTML
   (1)            (2)                       (3)                   (4)            (5)
```

Une **campagne = une grille = un classeur**. Chaque type de mobilité a sa propre grille et donc son propre fichier de saisie.

## 1. Choisir la grille

Pour l'ENSET-Skikda (profil [enset-skikda.json](../data/institutions/enset-skikda.json)) :

| Vous organisez…                                                        | Population concernée                        | Grille à utiliser                    |
| ----------------------------------------------------------------------- | -------------------------------------------- | ------------------------------------- |
| Participation à une manifestation scientifique internationale indexée | Enseignants, maîtres assistants, doctorants | `u1-manifestations-internationales` |
| Stage de perfectionnement du personnel                                  | Personnel administratif et technique         | `u2-personnel-administratif`        |
| Résidence scientifique de haut niveau (7–15 jours)                    | Enseignants MCB et plus                      | `u3-residences-scientifiques`       |
| Stage de perfectionnement (15–30 jours)                                | Doctorants, maîtres assistants, enseignants | `u4-perfectionnement`               |

Points à connaître :

- le **rang scientifique** ne se saisit que dans u1 et u3 (et les catégories de grade dans u2). La grille u4 n'attribue aucun point au grade — c'est conforme à l'annexe 4 du décret, ce n'est pas un oubli ;
- les grilles centres de recherche (rc5–rc9) ne s'appliquent pas à l'ENSET ;
- une seule mobilité par agent et par année budgétaire (art. 13).

## Campagne u3 2026 — workflow complet (41 candidats, source Odoo)

Cette section décrit le circuit de bout en bout tel qu'il est pratiqué à l'ENSET-Skikda
pour la campagne u3 2026 : de l'export Odoo jusqu'à la signature du PV et au calcul de
la ligne de coupure budgétaire.

```
Odoo ──► dossier maître ──► fiches individuelles ──► distribution
                                                          │
                                              retour des candidats
                                                          │
                                             consolidation + rapport d'erreurs
                                                          │
                                      renvoi des fiches fautives ──► correction
                                                          │
                                              vérification commission
                                                          │
                                        score + budget → PV + fiches + coupure
```

### Étape 0 — Export Odoo et dossier maître

```powershell
python -X utf8 scripts/import_odoo.py `
    --source examples/enset/stages.candidature.sejour.xlsx `
    --cloture-precedente 2025-03-31   # optionnel, voir ci-dessous
```

Produit `dossier-u3.xlsx` pré-rempli (identités, rangs, départements, destinations,
durées, montants d'indemnité, historique des derniers stages) et signale immédiatement
les dossiers à arbitrer :
département hors champ, destination invalide, écart de zone ou de montant entre Odoo et
le référentiel `data/costs`.

**Colonne `date_cloture_plateforme` de l'Historique** (point de départ de la fenêtre
« après dernier bénéfice ») — deux façons de la renseigner :

- `--cloture-precedente AAAA-MM-JJ` : la date de clôture du dépôt de la dernière
  campagne, fixée par la commission, est appliquée à toutes les lignes ;
- sans l'option, la colonne reste vide : le moteur se rabat sur la `date_mobilite` de
  chaque ligne (repli plus sévère — les travaux entre la clôture et le départ en
  mobilité sont écartés).

### Étape 1 — Génération des fiches de déclaration individuelles

```powershell
python -X utf8 scripts/fiches_declaration.py `
    --dossier examples/enset/dossier-u3.xlsx `
    --out-dir declarations
```

Crée une fiche Excel par candidat dans `declarations/` : feuille **Instructions** +
identité pré-remplie. Chaque candidat y déclare ses critères et ses activités, et joint
ses justificatifs en PDF.

### Étape 2 — Distribution aux candidats

- **Par mail** : joindre le fichier `declarations/<ref>.xlsx` à un message individuel.
- **Par dépôt réseau** : copier les fiches dans un dossier partagé dont chaque candidat
  ne voit que le sien.

Délai à indiquer dans le courrier. Les justificatifs PDF doivent être nommés
`<référence>_<n° ligne Activites>.pdf` et déposés dans `justificatifs/<référence>/`.

### Étape 3 — Consolidation et rapport d'erreurs

Au retour des fiches remplies, replacer chaque fichier dans `declarations/` puis :

```powershell
python -X utf8 scripts/consolider_declarations.py `
    --dir declarations `
    --out dossier-u3-consolide.xlsx
```

Le script produit :

- `dossier-u3-consolide.xlsx` — dossier unique prêt pour le scoring ;
- un **rapport d'erreurs** listé par fiche fautive (valeur hors barème, champ
  obligatoire manquant, activité sans date…).

**Renvoyer à chaque auteur sa fiche avec les erreurs signalées** (copier-coller le
bloc d'erreurs dans le mail de relance). Dès correction reçue, relancer la consolidation.
Répéter jusqu'à rapport d'erreurs vide.

### Étape 4 — Vérification de la commission sur pièces

La commission instruit chaque dossier sur la base des **fiches d'évaluation** (produites
à l'étape suivante ou en avant-première avec `--export-fiches`). Chaque fiche porte :

- le **DOI** et/ou **l'URL** de chaque publication/communication, pour vérification
  directe de la classe de revue, de la position d'auteur et de la date ;
- les **observations** du moteur (éléments hors fenêtre, non datés, plafonnements,
  déduplication Scopus/WOS) — ce sont les rejets motivés exigés par les art. 14-15 ;
- la colonne **Décision / Motif** à remplir par la commission pour tout écart entre la
  déclaration et les pièces justificatives.

Un élément indexé sans DOI ni URL est signalé en observation et doit être arbitré.

### Étape 5 — Score, budget et ligne de coupure

```powershell
# Classement + documents officiels
python -m classement score `
    --grid u3-residences-scientifiques `
    --institution enset-skikda `
    --candidates dossier-u3-consolide.xlsx `
    --campaign-date 2026-03-31 `
    --export-pv pv-u3.xlsx `
    --export-fiches fiches-u3.xlsx `
    --export-html classement-u3.html

# Simulation budgétaire et ligne de coupure
python -m classement budget `
    --grid u3-residences-scientifiques `
    --institution enset-skikda `
    --candidates dossier-u3-consolide.xlsx `
    --campaign-date 2026-03-31 `
    --budget <enveloppe_DA> `
    --plafond-billet <plafond_DA>
```

`--campaign-date` est la **date de clôture du dépôt des dossiers** (référence des
fenêtres `3-n`). Une mauvaise date fausse les pénalités.

`--reference-fenetre` (commandes `score`, `budget` et `exercice`) applique la décision
de la commission sur le repère de la fenêtre « après dernier bénéfice » :

- `cloture` (défaut) : la clôture de plateforme du dernier bénéfice (colonne
  `date_cloture_plateforme` de l'Historique), avec repli sur la date de mobilité si
  elle n'est pas renseignée ;
- `mobilite` : toujours la date de la mobilité, même si des clôtures sont saisies.

Le budget détermine la **ligne de coupure** : les dossiers sont financés dans l'ordre
du classement ; dès qu'un dossier ne tient pas dans le reliquat, lui et tous les suivants
passent en « non finançable ». Les ex aequo à la coupure sont signalés — la commission
arbitre (l'arrêté ne prévoit pas de critère de départage).

**Documents produits :**

| Fichier                | Contenu                                                                   | Usage                                                                  |
| ---------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `pv-u3.xlsx`         | Rang, candidat, score, ex aequo, colonnes Décision/Motif, bloc signature | À compléter et faire signer par le conseil scientifique              |
| `fiches-u3.xlsx`     | Détail par critère, DOI/URL, observations, total, rang, décision       | Traçabilité individuelle — le rejet doit être motivé (art. 14-15) |
| `classement-u3.html` | PV + toutes les fiches                                                    | Voie PDF : Imprimer → Enregistrer en PDF dans le navigateur           |

## 2. Générer le modèle de saisie

```powershell
python -m classement template --grid u3-residences-scientifiques --institution enset-skikda `
    --out modele-u3.xlsx
```

`--institution` injecte les départements de l'école dans les menus déroulants et
restreint les populations proposées. Les quatre modèles ENSET sont pré-générés dans
[../examples/enset/](../examples/enset/).

## 3. Remplir le classeur

Le classeur contient cinq feuilles. **Commencer par lire la feuille Referentiel** : elle liste chaque critère avec son libellé, ses points, ses plafonds et la colonne
« où saisir » (Candidats, Activites, ou automatique via Historique).

### Feuille « Candidats » — une ligne par candidat

| Colonne                                                                                      | Contenu                                                                                                                                                                                     |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                                                                                       | **Obligatoire et unique** (matricule recommandé). C'est la clé utilisée par les feuilles Activites et Historique.                                                                  |
| `nom_prenom`                                                                               | Nom et prénom en un seul champ (même format que l'export Odoo ; repris dans le PV et les fiches).                                                                                         |
| `citations_scopus.citation (qte)` / `citations_scopus (url profil)` (u1/u3)              | Nombre de citations depuis le dernier bénéfice (0,1 pt/citation) + URL du profil Scopus ou Google Scholar pour vérification.                                                             |
| `population`                                                                               | Menu déroulant (ex.`doctorant_non_salarie`). Détermine le groupe de classement.                                                                                                         |
| `departement`                                                                              | Menu déroulant en français (« Département de Technologie »…).                                                                                                                         |
| Critère à choix (ex.`rang_scientifique`)                                                 | Menu déroulant en français (« Professeur émérite », « Maître de conférences A »…).                                                                                               |
| `rang_scientifique (bonus Oui/Non)`                                                        | « Oui » pour un MCB qui prépare l'habilitation (bonus +4, une seule fois, engagement écrit exigé — u3).                                                                               |
| Critères Oui/Non (`polycopie_pedagogique (Oui/Non)`…)                                    | « Oui » si la pièce justificative est présente ; colonnes `(bonus N Oui/Non)` pour les majorations (+2 si en anglais…).                                                              |
| Critères en points (`evaluation_superieur.assiduite`, `poste_superieur (points)`…)     | Valeur numérique attribuée par l'évaluateur — plafonnée automatiquement au maximum du barème.                                                                                         |
| Compteurs simples (`anciennete.annee (qte)`, `inscription_doctorat.inscription (qte)`…) | Quantité (années, inscriptions…).                                                                                                                                                        |
| Colonnes `(n manuel)` / `(N)`                                                            | À laisser vides en général :`n` est calculé depuis la feuille Historique. Ne remplir que pour forcer une valeur.                                                                      |
| `pays_destination`                                                                         | Pays d'accueil de la mobilité — détermine la zone d'indemnité (Zone I : liste de `data/costs/zones.json`, dont Russie et Jordanie ; Zone II : autres pays).                           |
| `duree_jours`                                                                              | Durée effective en jours — base du calcul de l'indemnité réglementaire (arrêté du 25/12/2011).                                                                                        |
| `montant_indemnite (DA)` *(fin de feuille)*                                              | Montant d'indemnité exporté d'Odoo —**informatif** : la simulation budgétaire recalcule l'indemnité depuis le référentiel `data/costs` et l'import Odoo signale tout écart. |
| `billet_estime (DA)` *(fin de feuille)*                                                  | Estimation du titre de voyage (billet d'avion). Peut être plafonné à la simulation (`--plafond-billet`).                                                                               |
| `frais_divers (DA)` *(fin de feuille)*                                                   | Visa, assurance voyage et autres frais estimés.                                                                                                                                            |

Les trois colonnes budgétaires (`montant_indemnite`, `billet_estime`, `frais_divers`)
sont regroupées **en fin de feuille**, après les colonnes de critères.

### Feuille « Activites » — une ligne par élément compté

Pour tout ce qui exige un détail par élément : publications, communications,
encadrements, e-learning, projets…

| Colonne               | Contenu                                                                                                                                                                                                                                                                           |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `candidat_id`       | Doit correspondre à un `id` de la feuille Candidats.                                                                                                                                                                                                                           |
| `element`           | Menu déroulant « critère :: item », ex.`publications :: classe_a`, `communications :: intl_indexee_scopus_wos`, `elearning :: cours`.                                                                                                                                   |
| `quantite`          | Nombre d'éléments identiques (défaut 1).                                                                                                                                                                                                                                       |
| `position_auteur`   | **Publications uniquement** : position du candidat parmi les auteurs. 1 = 100 % des points, 2 = 90 %, 3 = 80 %, 4 = 70 %, 5 et plus = 50 %. Une publication par ligne dès que la position ou la date diffère.                                                             |
| `date (AAAA-MM-JJ)` | Date de l'élément. Les éléments antérieurs à la clôture de la plateforme du dernier bénéfice sont**automatiquement écartés** (règle « après dernier bénéfice »). Un élément non daté est compté mais signalé en observation — la commission tranche. |
| `doi`               | **Publications et communications indexées** : le DOI de l'article (ex. `10.1016/j.xxxx`). Reporté sur la fiche d'évaluation pour permettre à la commission de vérifier la publication en un clic. Son absence sur un élément indexé est signalée en observation. |
| `url`               | Lien direct vers la notice (page Scopus/WOS, ASJP pour les revues classe C, programme de la conférence…). Alternative ou complément au DOI.                                                                                                                                    |
| `porteur_nb`        | Nombre de projets dont le candidat est**porteur** (+1/projet — grilles chercheurs).                                                                                                                                                                                        |
| `bonus_nb`          | Nombre d'éléments ouvrant droit au bonus du critère (ex. nombre de cours e-learning en anglais : +2 chacun).                                                                                                                                                                   |

### Feuille « Historique » — les mobilités déjà obtenues

Une ligne par mobilité antérieure de chaque candidat : `candidat_id`, `date_mobilite`,
`date_cloture_plateforme` (date de clôture du dépôt de la campagne où il avait été
retenu).

**C'est la feuille la plus sensible** : elle alimente

- les pénalités de bénéfices antérieurs (`3-n` sur 3 ans pour u1/u3/u4, `-5` points par
  stage sur 6 ans pour u2) ;
- la fenêtre « après dernier bénéfice » qui écarte les travaux antérieurs.

Un candidat sans mobilité antérieure : aucune ligne (il obtient le maximum de la
pénalité, ex. 3 points pour `3-n`).

### Feuilles « Listes » et « Referentiel »

Générées automatiquement : sources des menus déroulants et documentation du barème.
Ne pas les modifier.

## 4. Importer, scorer et classer

```powershell
python -m classement score --grid u3-residences-scientifiques --institution enset-skikda `
    --candidates dossiers-u3.xlsx --campaign-date 2026-06-30 `
    --export-pv pv-u3.xlsx --export-fiches fiches-u3.xlsx --export-html classement-u3.html `
    --format markdown
```

- `--campaign-date` : **date de clôture du dépôt des dossiers** de la campagne en cours.
  C'est la référence des fenêtres de pénalité — une mauvaise date fausse les `3-n`.
- Le **rapport d'erreurs** s'affiche avant les résultats, avec la feuille et la ligne :

  ```
  -- 3 erreur(s) d'import --
    Candidats!L4 : valeur 'Recteur' hors barème pour rang_scientifique (attendues : ...)
    Candidats!L7 : département inconnu 'Génie Civil'.
    Activites!L12 : candidat inconnu 'D999'.
  ```

  Les lignes valides sont traitées malgré tout : corriger le classeur puis relancer.
- Le profil d'établissement ajoute ses contrôles (population hors champ de la grille,
  grille non applicable…) dans les observations des fiches.

## 5. Documents produits

| Fichier                | Contenu                                                                                                                                                                       | Usage                                                                                                                        |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `pv-u3.xlsx`         | Une feuille par groupe de classement : rang, candidat, département, score, ex aequo, colonnes**Décision** (menu Accepté/Rejeté) et **Motif**, bloc signature. | PV à compléter et faire signer par le conseil scientifique / la commission.                                                |
| `fiches-u3.xlsx`     | Une feuille par candidat : détail par critère, observations (plafonnements appliqués, pièces hors fenêtre, entrées non datées), total, rang, décision/motif.          | Traçabilité individuelle —**le rejet doit être motivé** (art. 14-15) ; la fiche peut être notifiée au candidat. |
| `classement-u3.html` | PV + toutes les fiches, une page par fiche.                                                                                                                                   | **Voie PDF** : ouvrir dans un navigateur → Imprimer → Enregistrer en PDF.                                            |

Les **ex aequo** partagent le même rang (1, 2, 2, 4) et sont signalés : l'arrêté ne
définit pas de critère de départage, l'arbitrage revient à la commission.

## 6. Simulation budgétaire

À partir des mêmes classeurs, la commande `budget` estime le coût de chaque dossier et
détermine, en suivant le classement, qui peut bénéficier avec l'enveloppe disponible :

```powershell
python -m classement budget --grid u4-perfectionnement --institution enset-skikda `
    --candidates dossiers-u4.xlsx --campaign-date 2026-06-30 `
    --budget 1000000 --plafond-billet 250000 --out simulation-u4.md
```

Le coût d'un dossier = **indemnité réglementaire** + **billet retenu** + **frais divers** :

- l'**indemnité** est calculée automatiquement (arrêté interministériel du 25/12/2011,
  transcrit dans `data/costs/indemnites.json` et validé contre le tableau « Nouveau ») :
  zone du pays × durée × barème, **majorée de 20 %** pour les enseignants chercheurs et
  chercheurs permanents (le personnel administratif reste au barème de base, les
  manifestations avec communication sont au barème × 1,4) ;
- le **billet** est l'estimation saisie, écrêtée par `--plafond-billet` le cas échéant
  (les destinations chères) — la fiche affiche « estimé » et « retenu » ;
- les **frais divers** (visa, assurance) sont repris tels que saisis.

Règle de coupure : **le rang prime**. Les dossiers sont financés dans l'ordre (tous les
rangs 1, puis les rangs 2…, départage par score) ; dès qu'un dossier ne tient pas dans
le budget restant, lui et tous les suivants sont « non finançables » — pas de saut vers
un dossier moins cher. Le reliquat est affiché et son usage relève de la commission.

La synthèse donne le coût de **toutes** les demandes (le budget suffit-il ?), le coût
financé éclaté en indemnités / billets / frais divers, et la répartition par population.

Le budget est celui de **l'exercice en cours** : il ne se reporte pas, chaque année a
son enveloppe et ses campagnes. En revanche l'**historique des mobilités** des agents
traverse les exercices (pénalités `3-n` sur 3 ans, `-5×n` sur 6 ans, fenêtre « après
dernier bénéfice ») : reporter les bénéficiaires financés de l'exercice dans la feuille
Historique des classeurs de l'année suivante.

### Simulation de l'exercice complet (art. 6 — répartition proposée)

L'art. 6 de l'arrêté 345 permet à l'établissement de **proposer une répartition de
l'enveloppe selon ses besoins et les demandes**, en dérogation des quotas de l'art. 5
(80/10/10). Cas typique : peu de demandes de perfectionnement/doctorants (prioritaires),
beaucoup de demandes de résidences — combien de résidences peut-on autoriser ?

```powershell
python -m classement exercice --institution enset-skikda --budget 5000000 `
    --campaign-date 2026-06-30 --plafond-billet 250000 `
    --campagne u4-perfectionnement=dossiers-u4.xlsx `
    --campagne u2-personnel-administratif=dossiers-u2.xlsx `
    --campagne u3-residences-scientifiques=dossiers-u3.xlsx `
    --campagne u1-manifestations-internationales=dossiers-u1.xlsx `
    --out simulation-exercice.md
```

**L'ordre des `--campagne` est l'ordre de priorité** : la première campagne est financée
en totalité de ses demandes (dans la limite du budget), la suivante consomme le
reliquat, etc. La sortie donne le détail de chaque campagne (qui passe la coupure) et le
tableau final « **Répartition proposée de l'enveloppe (art. 6)** » — montants et parts du
budget par campagne — qui sert de justificatif à la proposition de l'établissement
auprès de la tutelle.

## 7. Erreurs et questions fréquentes

**« PermissionError […] dossiers.xlsx » à la génération/au score** : le classeur est
ouvert dans Excel. Le fermer puis relancer.

**« Je ne trouve pas où saisir le rang »** : vérifier la grille — le rang n'existe que
dans u1, u2 (catégories) et u3. La feuille Referentiel de chaque classeur fait foi.

**Une publication Scopus et WOS à la fois** (grilles chercheurs) : la saisir une seule
fois, à la valeur la plus élevée.

**Travaux sans date précise** : ils sont comptés avec une observation « non datée » sur
la fiche — fournir la date dès que possible, c'est elle qui prouve que le travail est
postérieur au dernier bénéfice.

**DOI/URL des publications** : leur saisie n'est pas bloquante mais fortement
recommandée — la référence apparaît sur la fiche d'évaluation et permet à la commission
de vérifier l'article (classe de revue, position d'auteur, date) sans chercher. Un
élément indexé sans DOI ni URL est signalé en observation sur la fiche.

**Re-générer les modèles/exemples** : `python scripts/make_example_xlsx.py`.
**Vérifier l'intégrité des grilles** : `python scripts/audit_grids.py`.

## Limites connues de la phase 1

- L'historique des mobilités est ressaisi à chaque campagne (feuille Historique) ; la
  phase 2 (application web + base de données, voir [roadmap.md](roadmap.md)) le rendra
  persistant.
- Les justificatifs (PDF) ne sont pas gérés : la vérification des pièces reste un
  processus papier/à part.
- Le PDF s'obtient par impression du HTML (pas de génération PDF directe).
