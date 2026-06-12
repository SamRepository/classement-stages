# Grilles d'évaluation — Arrêté n° 345 du 9 mars 2026

Transcription structurée des barèmes annexés à l'arrêté n° 345 (MESRS, Algérie) fixant les
critères de sélection pour le programme de mobilité de courte durée à l'étranger
(*perfectionnement à l'étranger*). Source : [docs/decret_loi/345-1.pdf](../../docs/decret_loi/345-1.pdf) (scan, 34 pages).

L'arrêté abroge l'arrêté n° 255 du 25/02/2024 et s'applique en vertu de l'article 40 du décret
présidentiel n° 14-196 du 06/07/2014.

## Cartographie des annexes

| Fichier | Pages | Population | Type de mobilité |
|---|---|---|---|
| [u1-manifestations-internationales.json](u1-manifestations-internationales.json) | 10–13 | Enseignants-chercheurs + doctorants (universités/écoles) | Manifestations scientifiques internationales indexées |
| [u2-personnel-administratif.json](u2-personnel-administratif.json) | 14–15 | Personnel administratif et technique (universités/écoles) | Stage de perfectionnement |
| [u3-residences-scientifiques.json](u3-residences-scientifiques.json) | 16–19 | Enseignants-chercheurs MCB et + (universités/écoles) | Résidence scientifique de haut niveau |
| [u4-perfectionnement.json](u4-perfectionnement.json) | 20–21 | Doctorants, maîtres assistants (universités/écoles) | Stage de perfectionnement |
| [rc5-chercheurs-residences-manifestations.json](rc5-chercheurs-residences-manifestations.json) | 22–25 | Chercheurs permanents (centres de recherche) | Manifestations + résidences |
| [rc6-chercheurs-stages.json](rc6-chercheurs-stages.json) | 26–29 | Chercheurs permanents (centres de recherche) | Stages courts |
| [rc7-personnel-administratif.json](rc7-personnel-administratif.json) | 30 | Personnel administratif des centres (divisions administration + information scientifique) | Stages courts |
| [rc8-techniciens-ingenierie.json](rc8-techniciens-ingenierie.json) | 31–32 | Personnel technique de soutien (division ingénierie) | Stages courts |
| [rc9-techniciens-developpement-technologique.json](rc9-techniciens-developpement-technologique.json) | 33–34 | Personnel technique de soutien (division développement technologique) | Stages courts |

[shared-rules.json](shared-rules.json) regroupe les règles transverses (pondération par position
d'auteur, fenêtres de comptabilisation, déduplication Scopus/WOS, conditions e-learning,
conflits d'intérêts, quotas de l'article 5, durées de l'article 12).

## Modèle de données

Chaque grille contient `criteria[]`, où chaque critère a un `type` :

- **`enum`** — choix unique avec points associés (`options[]`), ex. rang scientifique.
  Une option peut porter un `bonus` conditionnel (ex. +4 pts préparation d'habilitation pour MCB, une seule fois).
- **`count`** — éléments comptés (`items[]`), chacun avec `points_per_unit` et éventuellement :
  - `cap_units` : plafond en nombre d'unités comptées ;
  - `cap_points` : plafond en points pour la ligne ;
  - `shared_cap` / `shared_caps` : plafond partagé entre plusieurs lignes (ex. 4 communications internationales orales+posters confondues) ;
  - `block_caps` : plafond global du bloc (ex. 70 pts max pour l'ensemble des publications, grilles chercheurs) ;
  - `reference_recommended` : l'élément (publication, communication indexée) devrait être
    accompagné d'un DOI/URL — le moteur reporte la référence sur la fiche d'évaluation et
    signale son absence en observation (ajout projet, pas une exigence du décret).
- **`fixed`** — points forfaitaires si la condition est remplie ; `bonuses[]` éventuels (ex. +2 si en anglais).
- **`capped`** — score apprécié par l'évaluateur dans la limite de `cap_points`.
- **`manual_scores`** — sous-scores attribués par le supérieur hiérarchique (grille u2).
- **`formula`** — valeur calculée, ex. pénalité de bénéfices antérieurs `3 - n`.

`window` précise la fenêtre temporelle : `after_last_benefit` (depuis la clôture de la plateforme
de dépôt de la dernière mobilité obtenue) ou `last_3_years`. Les règles transverses applicables
sont référencées par identifiant dans `rules[]` (définies dans shared-rules.json).

## Règles métier importantes pour le moteur de classement

1. **Historique requis** : les pénalités (`3-n`, `4-n`, `5-n`, `-5/stage`) et la fenêtre
   `after_last_benefit` exigent de stocker l'historique des mobilités de chaque candidat et la
   date de clôture de la plateforme de chaque campagne.
2. **Pondération auteur** : pour les publications, le score est multiplié selon la position du
   candidat dans la liste des auteurs (1er 100 %, 2e 90 %, 3e 80 %, 4e 70 %, 5e+ 50 %).
3. **Déduplication Scopus/WOS** (grilles chercheurs) : une publication présente dans les deux
   bases compte une seule fois, à la valeur maximale.
4. **Classement par population** : doctorants non salariés classés au niveau du département ;
   doctorants en cotutelle au niveau de la faculté/du département (u4).
5. **Procédure** : rejet obligatoirement motivé ; un membre du comité de sélection ne peut pas
   être candidat la même année ; stages courts exclusivement dans le cadre d'accords
   internationaux conclus.
6. **Quotas budgétaires (art. 5)** : 90 % perfectionnement (dont 80 % enseignants/chercheurs/
   doctorants et 10 % personnel administratif et technique) ; 10 % résidences scientifiques et
   manifestations indexées.
7. **Durées (art. 12)** : perfectionnement 15–30 jours (jusqu'à 5 mois pour les masters
   co-badgés / double diplôme) ; résidences 7–15 jours ; manifestations 7 jours max ;
   une seule mobilité par année budgétaire.

## Lectures validées et points restants

Les lectures suivantes ont été **confirmées** (validation utilisateur du 09/06/2026) et sont
consignées dans les champs `notes` des fichiers concernés :

- **Formules de pénalité** : `4-n` (rc5) et `5-n` (rc7/rc8/rc9) — l'affichage `n-4` / `(n-5)` du
  scan est un artefact de rendu bidirectionnel arabe/latin.
- **rc6** : la ligne « nombre de stages réalisés » avec ses deux barèmes dégressifs
  `4-ن (max 03)` et `5-ن (max 04)` s'applique à la catégorie des chercheurs permanents des
  centres de recherche (خاصة بالباحثين الدائمين).
- **u2** : la fenêtre de la pénalité est bien de six dernières années.
- **u1/u3** : la ligne reviewing « revue A+ : 5 pts » est bien sans plafond explicite
  (contrairement à A : 16, B : 8, C : 4).

Point restant ouvert :

- Les critères d'égalité (tie-breaking) ne sont pas définis par l'arrêté.

## Reproduction de la transcription

Le PDF est un scan sans couche texte. Les pages ont été rendues en PNG (200 et 300 DPI,
PyMuPDF) puis lues visuellement. Les rendus intermédiaires sont dans `docs/_pages/`
(supprimable, regénérable à la demande).
