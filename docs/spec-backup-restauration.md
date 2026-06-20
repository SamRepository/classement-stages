# Spécification — Sauvegarde et restauration des données

État : **implémentée** sur la branche `feat/backup-restauration` (rédigée et réalisée le
20/06/2026, phase d'utilisation expérimentale). Cible : `webapp/` déployée sur Coolify
(PostgreSQL + volume `/data/uploads`). Implémentation : `webapp/services/backup.py`,
routes `/admin/sauvegarde|backup|restore/*` ([webapp/routes/admin.py](../webapp/routes/admin.py)),
template `admin/sauvegarde.html`, tests `tests/webapp/test_backup.py`.

## 1. Objectif et motivation

L'application est en service réel pour la campagne **u3 2026** : elle détient des données
qui n'existent nulle part ailleurs — dossiers saisis par les enseignants, décisions de la
commission (validations/rejets motivés, art. 14-15), instantanés de classement gelés,
historique des bénéfices, et les **justificatifs PDF**. Une perte serait irréparable.

Coolify (PostgreSQL → onglet *Backups*) et les snapshots Proxmox couvrent déjà la
sauvegarde **côté infrastructure**. Cette spec ajoute une **sauvegarde/restauration
pilotable depuis le portail admin**, indépendante de l'hébergeur, pour faire face à toute
éventualité :

- l'admin métier (chef de service des stages) n'a pas forcément accès au dashboard
  Coolify ni au serveur Proxmox ;
- besoin d'une **copie hors-serveur** récupérable d'un clic (téléchargée sur le poste de
  l'admin), pour le cas où le serveur lui-même est perdu ;
- besoin de **restaurer sur une instance neuve** (migration de serveur, reconstruction)
  sans dépendre des dumps internes de Coolify ;
- vérifiabilité : une archive lisible (JSON + PDF) qu'on peut ouvrir et contrôler.

Les deux mécanismes sont **complémentaires**, pas concurrents :

| | Coolify / Proxmox | Portail admin (cette spec) |
|---|---|---|
| Déclenchement | planifié (quotidien) | à la demande, par l'admin |
| Emplacement | sur le serveur | **téléchargé hors-serveur** |
| Périmètre | base + volume séparément | **archive unique** base **+** PDF cohérents |
| Restauration | par l'hébergeur (ops) | par l'admin, dans l'interface |
| Dépendances | infra | aucune (HTTP + navigateur) |

## 2. Périmètre des données

Une sauvegarde **complète** = l'état applicatif reconstituble à l'identique. Deux
composants indissociables, à capturer ensemble :

1. **Base de données** — toutes les tables métier de [webapp/models.py](../webapp/models.py) :
   `campaigns`, `users` (y compris `password_hash`), `dossiers`, `entries`,
   `attachments` (métadonnées des fichiers), `benefits`, `ranking_snapshots`, `events`.
   Plus la table `alembic_version` (révision de schéma).
2. **Justificatifs PDF** — l'arborescence `UPLOAD_DIR/justificatifs/<dossier_id>/<entry_id>.pdf`,
   référencée par `attachments.stored_path` / `attachments.dossier_id`.

> ⚠️ Une sauvegarde de la base **sans** les PDF (ou l'inverse) est inutilisable : la
> commission ne peut pas valider un élément sans son justificatif. Les deux composants
> voyagent dans la **même archive**.

**Hors périmètre** (versionné dans le dépôt, pas une donnée d'exploitation) : grilles
`data/grids/`, profils `data/institutions/`, coûts `data/costs/`, code, migrations. La
restauration suppose une image applicative **de même version** que celle qui a produit
l'archive (cf. §6, contrôle de compatibilité).

## 3. Format de l'archive

Décision : **archive ZIP portable, export applicatif** (sérialisation SQLAlchemy en JSON +
fichiers), et non un dump `pg_dump`. Justification :

- portable : fonctionne en dev (SQLite) comme en prod (PostgreSQL), restaurable sur une
  base vierge quel que soit le moteur ;
- ne dépend **pas** du binaire `pg_dump`/`pg_restore`, absent de l'image `python:3.12-slim`
  ([Dockerfile](../Dockerfile)) ;
- lisible et vérifiable (JSON ouvrable, PDF extractibles) ;
- s'appuie sur le mapping SQLAlchemy déjà en place — une seule source de vérité du schéma.

### Structure

```
classement-backup-<institution>-<AAAAMMJJ-HHMMSS>.zip
├── manifest.json
├── data/
│   ├── campaigns.json
│   ├── users.json
│   ├── dossiers.json
│   ├── entries.json
│   ├── attachments.json
│   ├── benefits.json
│   ├── ranking_snapshots.json
│   └── events.json
└── uploads/
    └── justificatifs/<dossier_id>/<entry_id>.pdf
```

Chaque `data/<table>.json` : liste d'objets, une entrée par ligne, **clés primaires et
étrangères incluses telles quelles** (les ID sont préservés, condition de cohérence avec
les chemins de fichiers et les FK). Types non-JSON sérialisés en chaînes ISO 8601
(`date`, `datetime` UTC) ; colonnes `JSON` (`payload`, snapshots) écrites telles quelles.

### `manifest.json`

```json
{
  "format_version": 1,
  "generated_at": "2026-06-20T14:30:00Z",
  "app": "classement-stages",
  "alembic_revision": "b7e1c4a9d2f3",
  "institution_id": "enset-skikda",
  "database_backend": "postgresql",
  "counts": { "users": 43, "dossiers": 41, "entries": 312, "attachments": 305, "...": 0 },
  "files": { "count": 305, "total_bytes": 734003200 },
  "checksums": { "data/users.json": "sha256:…", "uploads/justificatifs/…": "sha256:…" }
}
```

- `alembic_revision` : révision **head** au moment de la sauvegarde (lue depuis
  `alembic_version`). Verrou de compatibilité de schéma à la restauration (§6).
- `counts` / `files` : contrôle d'intégrité rapide et affichage de prévisualisation avant
  restauration.
- `checksums` : SHA-256 de chaque fichier de l'archive (détection de corruption ; vérif
  des PDF à la restauration).

## 4. Flux côté portail admin

Nouvelle page **« Sauvegarde / Restauration »** dans l'espace admin (rôle `admin`
uniquement, via `require_role("admin")` comme les autres routes de
[webapp/routes/admin.py](../webapp/routes/admin.py)). Entrée dans la navigation admin.

### 4.1 Sauvegarde (téléchargement)

- Bouton **« Télécharger une sauvegarde complète »** → `GET /admin/backup`.
- Le serveur : (a) sérialise les tables dans l'ordre, (b) ajoute les PDF du volume, (c)
  calcule le manifeste, (d) renvoie le ZIP en `StreamingResponse` avec
  `Content-Disposition: attachment; filename="classement-backup-…zip"`.
- **Construction sur fichier temporaire** (`tempfile`) puis streaming, pas en mémoire :
  41 dossiers × PDF jusqu'à 10 Mo ⇒ archive potentiellement de plusieurs centaines de Mo.
  Le temporaire est supprimé après l'envoi.
- L'opération est **lecture seule** : aucun risque pour la production. Journalisée dans
  `events` (`action="backup_telecharge"`).
- La page rappelle que **l'archive contient des données nominatives et des hachages de
  mots de passe** → à stocker de façon sécurisée (poste chiffré, pas de partage public).

### 4.2 Restauration (remplacement complet)

Décision : **remplacement intégral** (reprise après sinistre), pas de restauration
sélective dans cette version. La restauration **écrase tout l'état** par celui de
l'archive.

Flux en **deux temps** (anti-fausse-manœuvre) :

1. `POST /admin/restore/preview` — upload de l'archive. Le serveur valide (cf. §6) et
   **n'écrit rien** : il renvoie un récapitulatif (date de l'archive, révision Alembic,
   `counts`, nombre de PDF, état actuel de la base pour comparaison) et un **jeton de
   confirmation** à usage unique (en session).
2. `POST /admin/restore/confirm` — l'admin doit **saisir une phrase exacte** (ex.
   `REMPLACER TOUTES LES DONNÉES`) + le jeton. Sans correspondance stricte → refus 422.
   Alors seulement la restauration s'exécute.

Garde-fous additionnels :

- **Sauvegarde de sécurité automatique avant écrasement** : le serveur produit d'abord
  une archive de l'état courant (même routine que §4.1) et l'écrit dans
  `UPLOAD_DIR/_pre_restore/…zip` (filet en cas de restauration erronée).
- Recommandation affichée : restaurer de préférence sur une **instance neuve / base
  vide**. La restauration sur une base peuplée est permise mais clairement signalée comme
  destructive.
- Journalisée (`action="restauration"`, détail = manifeste résumé).

## 5. Procédure de restauration (algorithme)

Exécutée dans une **transaction** unique côté base, fichiers appliqués après le commit.

1. **Valider** l'archive (§6). En cas d'échec : refus, aucune écriture.
2. **Sauvegarde de sécurité** de l'état courant (§4.2).
3. **Purge** des tables métier dans l'ordre inverse des dépendances FK
   (`events`, `ranking_snapshots`, `attachments`, `entries`, `benefits`, `dossiers`,
   `users`, `campaigns`) — `DELETE` plutôt que `DROP` (le schéma reste celui des
   migrations Alembic déjà appliquées).
4. **Insertion** dans l'ordre des dépendances (`campaigns`, `users`, `benefits`,
   `dossiers`, `entries`, `attachments`, `ranking_snapshots`, `events`), **ID préservés**.
5. **Réalignement des séquences** PostgreSQL : `setval` sur chaque séquence d'`id` au
   `max(id)+1` (les insertions à ID explicite ne touchent pas la séquence ; sans ça, la
   prochaine création échouerait sur conflit de PK). Sans objet sous SQLite (AUTOINCREMENT).
6. **Commit** de la transaction base. En cas d'erreur avant ce point : rollback complet,
   état inchangé.
7. **Fichiers** : remplacer `UPLOAD_DIR/justificatifs/` par le contenu `uploads/` de
   l'archive (écrire dans un répertoire temporaire, vérifier les sommes de contrôle, puis
   bascule atomique ; conserver l'ancien sous `_pre_restore` jusqu'à confirmation).
8. **Contrôle post-restauration** : pour chaque `attachment`, vérifier que
   `stored_path` existe et que la taille correspond ; lister les écarts dans le rapport.

> L'app tourne en **un seul worker** (cf. Dockerfile, charge faible) : pas de
> concurrence d'écriture pendant la restauration. Recommandation opératoire : prévenir que
> l'app sera indisponible quelques instants ; idéalement restaurer hors période de saisie.

## 6. Contrôles de validité et compatibilité

Avant toute écriture, refuser (422, message français explicite) si :

- l'archive n'est pas un ZIP lisible, ou `manifest.json` manque/illisible ;
- une somme de contrôle ne correspond pas (archive corrompue) ;
- `format_version` inconnu (> version supportée) ;
- **`alembic_revision` du manifeste ≠ révision head de l'instance courante.** C'est le
  verrou central : restaurer des données issues d'un schéma différent corromprait la
  base. Message proposé : « Sauvegarde produite par une version différente de
  l'application (schéma `<X>` vs `<Y>`). Déployez la version correspondante avant de
  restaurer. » (Évolution possible : autoriser une restauration *en avant* en rejouant
  les migrations Alembic intermédiaires — hors périmètre v1.)
- une table attendue manque dans `data/` ;
- un PDF référencé par `attachments` est absent de `uploads/` (ou inversement) → au
  minimum un **avertissement** listé dans le récapitulatif.

## 7. Sécurité et confidentialité

- **Rôle `admin` strict** sur toutes les routes (`/admin/backup`, `/admin/restore/*`).
- L'archive contient `password_hash` (bcrypt — non réversible mais sensible), données
  nominatives et PDF → **HTTPS obligatoire** (déjà requis, `COOKIE_SECURE=1`), et
  avertissement de stockage sécurisé sur la page.
- Upload de restauration : limite de taille cohérente avec le volume attendu ; lecture en
  streaming ; extraction ZIP **protégée contre la traversée de chemins** (rejeter toute
  entrée dont le chemin normalisé sort de la racine d'extraction — *zip slip*) ; ne
  restaurer sous `uploads/` que des `*.pdf` aux chemins `justificatifs/<int>/<int>.pdf`.
- Le jeton de confirmation à usage unique évite un POST de restauration rejoué.

## 8. Articulation avec l'existant (à mettre à jour)

- [docs/guide-deploiement-coolify.md](guide-deploiement-coolify.md) §10 « Sauvegardes » :
  ajouter un renvoi vers la sauvegarde portail comme **second filet** (hors-serveur) en
  plus du backup PostgreSQL Coolify et des snapshots Proxmox. Préciser que les deux ne se
  remplacent pas.
- [docs/roadmap.md](roadmap.md) : la sauvegarde/restauration relève de la **phase 4
  (confort et fiabilisation)** ; à mentionner comme livrable anticipé motivé par la mise
  en service réelle.
- Pas d'impact sur le moteur `classement/` ni sur les grilles (hors périmètre).

## 9. Implémentation envisagée (indicatif, hors de cette spec)

- `webapp/services/backup.py` : `build_archive(db, upload_dir) -> Path` et
  `restore_archive(db, upload_dir, archive, *, confirmed) -> RestoreReport`. Réutilise le
  mapping SQLAlchemy (`Base.metadata.sorted_tables` pour l'ordre des FK) — pas de liste de
  tables codée en dur à maintenir en double.
- `webapp/routes/admin.py` : routes `/admin/backup`, `/admin/restore/preview`,
  `/admin/restore/confirm` ; template `admin/sauvegarde.html`.
- Sérialisation : helper générique colonne→JSON (gère `date`/`datetime`/`JSON`), partagé
  export/import pour garantir la symétrie (même esprit que `column_plan` côté Excel).

## 10. Plan de tests (pytest, `tests/webapp/`)

- **Aller-retour** : seed d'un état (campagne + comptes + dossiers + entries + PDF) →
  `build_archive` → base vierge → `restore_archive` → l'état est identique (comptages,
  champs, scores recalculés inchangés, PDF présents avec bonnes tailles/sommes).
- **Préservation des ID** et des FK après restauration ; séquences réalignées (création
  d'un nouvel objet sans conflit de PK post-restauration, sous PostgreSQL).
- **Refus** : révision Alembic divergente ; archive corrompue (checksum) ; table
  manquante ; PDF manquant ; ZIP malveillant (zip slip) → aucune écriture.
- **Garde-fous** : restauration sans phrase de confirmation exacte → 422, état inchangé ;
  jeton à usage unique non rejouable.
- **Sauvegarde de sécurité** créée avant écrasement.
- **Contrôle d'accès** : un compte non-admin reçoit 403 sur les trois routes.
- Maintien de la **parité** : un dossier restauré scoré via le moteur donne le même
  résultat qu'avant sauvegarde.
```
