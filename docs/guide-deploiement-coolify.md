# Guide de déploiement — application web sur Coolify (pas à pas)

Application FastAPI (`webapp/`) réutilisant le moteur `classement/` tel quel.
Campagne cible : **u3 2026** (résidences scientifiques, ENSET-Skikda).
Dépôt : `https://github.com/SamRepository/classement-stages` (branche `main`).

> Les deux points où ça accroche habituellement : le préfixe
> `postgresql+psycopg://` dans `DATABASE_URL`, et l'oubli du volume
> `/data/uploads`.

## Étape 0 — Préparer la clé secrète (sur votre poste)

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Gardez le résultat : ce sera `SECRET_KEY`.

## Étape 1 — Créer la base PostgreSQL

1. Dashboard Coolify → votre **Project** → environnement (ex. *production*) →
   **+ New** → **Database** → **PostgreSQL** (16).
2. Laissez les valeurs générées (user/password/db) → **Start**.
3. Ouvrez la ressource → copiez l'**URL interne** (*Postgres URL (internal)*),
   de la forme `postgres://user:motdepasse@nom-interne:5432/postgres`.
4. Transformez-la pour l'application (préfixe SQLAlchemy) :
   `postgresql+psycopg://user:motdepasse@nom-interne:5432/postgres`
   ⚠️ Sans `+psycopg`, l'application ne démarre pas.

## Étape 2 — Créer l'application

1. **+ New** → **Public Repository** (si le dépôt est privé — recommandé à
   terme — : **Private Repository (GitHub App)** et installer l'app GitHub
   proposée par Coolify).
2. URL du dépôt, branche **main**.
3. **Build Pack : Dockerfile** (à la racine, détecté automatiquement).
4. **Ports Exposes : `8000`** — et laisser **Ports Mappings vide**.
   Pas de conflit avec un dashboard Coolify servi sur le port 8000 de l'hôte :
   le 8000 de l'application est **interne au conteneur**, le proxy Coolify
   route le domaine vers lui.

## Étape 3 — Domaine

Onglet **General** de l'application, champ **Domains** :

- avec un domaine : `https://stages.<etablissement>.dz` (créer d'abord
  l'enregistrement DNS A → IP du serveur) ; certificat Let's Encrypt
  automatique ;
- sinon : Coolify propose un domaine `http://xyz.<ip>.sslip.io` — utilisable
  pour la recette, mais **passer en HTTPS avant de distribuer les vrais mots
  de passe**.

## Étape 4 — Variables d'environnement

Onglet **Environment Variables** :

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | l'URL de l'étape 1 (avec `+psycopg`) |
| `SECRET_KEY` | la clé de l'étape 0 |
| `COOKIE_SECURE` | `1` (si HTTPS ; `0` temporairement si sslip.io en HTTP) |
| `CAMPAIGN_GRID_ID` | `u3-residences-scientifiques` |
| `CAMPAIGN_INSTITUTION_ID` | `enset-skikda` |
| `CAMPAIGN_DATE` | date de référence de la campagne, ex. `2026-06-30` |
| `CAMPAIGN_WINDOW_REFERENCE` | `cloture` (ou `mobilite`, décision commission) |

`UPLOAD_DIR=/data/uploads` et `MAX_UPLOAD_MB=10` sont les valeurs par défaut
du Dockerfile.

## Étape 5 — Volume persistant (justificatifs PDF)

Onglet **Storages** → **+ Add** → type **Volume Mount** :

- Name : `uploads`
- Destination Path : `/data/uploads`

Sans ce volume, les PDF sont perdus à chaque redéploiement.

## Étape 6 — Healthcheck

Onglet **Healthcheck** : activer, **Path** `/sante`, **Port** `8000`
(méthode GET, valeurs par défaut pour le reste).

## Étape 7 — Déployer

Cliquer **Deploy** et suivre les logs. Séquence attendue :

1. build de l'image (pip install…) ;
2. au démarrage : `Running upgrade -> …, schema initial` (migrations Alembic) ;
3. `Uvicorn running on http://0.0.0.0:8000`.

Vérification : `https://votre-domaine/sante` → `{"statut":"ok"}`.

## Étape 8 — Initialisation (une seule fois)

Onglet **Terminal** de l'application (shell dans le conteneur) :

```bash
python -m webapp.scripts.seed --admin-email <email-admin>
```

Le mot de passe admin généré s'affiche — **le noter immédiatement** (ou passer
`--admin-password ...`). La campagne est créée depuis les variables
`CAMPAIGN_*`. La commande est idempotente.

## Étape 9 — Mise en route de la campagne (interface, connecté admin)

1. **Utilisateurs → Importer des comptes** : déposer le `dossier-u3.xlsx`
   produit par `python scripts/import_odoo.py --source <export-odoo.xlsx>
   [--cloture-precedente AAAA-MM-JJ]` (export Odoo avec colonne Email).
   En une opération : les comptes (login = e-mail, le même qu'Odoo), les
   dossiers brouillon (référence, département, pays, durée, billet) et
   l'historique des bénéfices depuis la feuille Historique (pénalité `3 − n`
   + fenêtre « après dernier bénéfice »). **La page des mots de passe ne
   s'affiche qu'une fois** → copier le tableau pour la distribution
   individuelle. Import idempotent (réimport sans doublon). Un CSV simple
   (`email, nom, …`) est aussi accepté.
2. **Utilisateurs → Créer un compte** : les membres de la **commission**
   (rôle *commission*).
3. **Bénéfices** : contrôle visuel de l'historique importé.
4. **Campagne** : fixer la fenêtre d'ouverture/clôture de la saisie.
5. **Recette finale** : se connecter avec un compte enseignant réel, saisir un
   dossier complet avec quelques PDF, comparer le score provisoire au barème —
   puis distribuer les accès aux autres candidats.

## Étape 10 — Après la mise en service

- **Redéploiement** : dépôt public sans webhook → bouton **Redeploy** après un
  `git push` (ou configurer la GitHub App pour le déploiement automatique).
- **Sauvegardes** : ressource PostgreSQL → onglet **Backups** → planifier
  (quotidien) ; le volume `uploads` vit sur le serveur Proxmox — l'inclure
  dans les snapshots/backups Proxmox.
- **Dépôt privé** : passer le dépôt GitHub en privé (Settings → Change
  visibility) puis reconnecter l'application via la GitHub App.

---

## Cycle de la campagne (rappel)

1. **Enseignants** : saisie du dossier (un élément déclaré = une ligne + son
   justificatif PDF), score provisoire en temps réel, soumission (gel du
   dossier côté candidat).
2. **Commission** (`/commission/dossiers`) : examen élément par élément avec le
   justificatif en visionneuse — *Valider* / *Rejeter avec motif obligatoire*
   (art. 14-15) ; « Valider le reste du dossier » pour les éléments restants ;
   les observations du moteur (plafonds, fenêtres, références manquantes)
   restent affichées pour la traçabilité.
3. **Classement** (`/commission/classement`) : rang « compétition » (1, 2, 2, 4),
   ex aequo signalés (pas de départage : choix du décret). **Gel** possible
   uniquement quand plus aucun élément n'est en attente ; un instantané JSON
   est archivé en base.
4. **Exports** : PV de classement (.xlsx), fiches d'évaluation (.xlsx), document
   imprimable (HTML → PDF navigateur) — générés par `classement.exports`.
5. L'admin peut **rouvrir** un dossier soumis (correction) tant que le
   classement n'est pas gelé.

## Développement local (Windows)

```powershell
pip install -e .[webapp,dev]
copy .env.example .env            # DATABASE_URL=sqlite:///./dev.db par défaut
python -m webapp.scripts.seed --admin-email admin@local
python -m uvicorn webapp.main:app --reload
# tests
python -m pytest -q
```

Parité PostgreSQL avant mise en production : `docker compose up --build`
(application sur `http://localhost:9000`, mapping `9000:8000`).

## Recette de parité (avant le lancement réel)

Le même dossier saisi via l'application et scoré via la CLI doit donner un
score identique :

```powershell
python -m classement score --grid u3-residences-scientifiques `
  --institution enset-skikda --candidates dossier-reference.json `
  --campaign-date 2026-06-30
```

Les tests `tests/webapp/test_assemble.py` verrouillent cette équivalence pour
chaque type de critère.
