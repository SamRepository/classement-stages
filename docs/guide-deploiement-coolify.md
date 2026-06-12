# Guide de déploiement — application web sur Coolify

Application FastAPI (`webapp/`) réutilisant le moteur `classement/` tel quel.
Campagne cible : **u3 2026** (résidences scientifiques, ENSET-Skikda).

## 1. Dépôt GitHub

Le projet est versionné localement (git). Créer un dépôt **privé** (les données
sont nominatives) puis pousser :

```powershell
# après création du dépôt vide sur github.com
git remote add origin https://github.com/<compte>/classement-stages.git
git push -u origin main
```

`declarations/`, `out/`, `.env` et `dev.db` sont exclus par `.gitignore`.

## 2. Ressources Coolify

1. **PostgreSQL** : créer une ressource PostgreSQL ; noter l'URL interne
   (`postgresql://user:pass@nom-interne:5432/base`).
2. **Application** : nouvelle ressource depuis le dépôt GitHub, build pack
   **Dockerfile** (à la racine), port exposé **8000**.
3. **Volume persistant** : monter un volume sur `/data/uploads` (justificatifs
   PDF — ils doivent survivre aux redéploiements).
4. **Healthcheck** : `GET /sante`.
5. HTTPS : assuré par le proxy Coolify (Let's Encrypt).

## 3. Variables d'environnement (application)

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://user:pass@nom-interne:5432/base` (préfixe **postgresql+psycopg**) |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `COOKIE_SECURE` | `1` |
| `UPLOAD_DIR` | `/data/uploads` (défaut du Dockerfile) |
| `MAX_UPLOAD_MB` | `10` |
| `CAMPAIGN_GRID_ID` | `u3-residences-scientifiques` |
| `CAMPAIGN_INSTITUTION_ID` | `enset-skikda` |
| `CAMPAIGN_DATE` | date de référence de la campagne (AAAA-MM-JJ) |
| `CAMPAIGN_WINDOW_REFERENCE` | `cloture` (ou `mobilite`, décision commission) |

Les migrations Alembic s'exécutent automatiquement au démarrage du conteneur.

## 4. Initialisation (une fois, terminal du conteneur)

```bash
# campagne + premier compte admin (mot de passe affiché si non fourni)
python -m webapp.scripts.seed --admin-email admin@enset-skikda.dz
```

Puis dans l'interface, connecté en admin :

1. **Utilisateurs** → *Importer des comptes* : fichier CSV/xlsx avec colonnes
   `email, nom, prénom, référence, département` (export Odoo retravaillé).
   Les mots de passe initiaux s'affichent **une seule fois** → les communiquer
   individuellement. Chaque enseignant reçoit un dossier brouillon.
2. **Bénéfices** : saisir l'historique des mobilités de chaque candidat
   (date + clôture de plateforme). Ces données pilotent la pénalité `3 − n`
   et la fenêtre « après dernier bénéfice ».
3. **Campagne** : fixer la fenêtre de saisie (ouverture/clôture).

## 5. Cycle de la campagne

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
   uniquement quand plus aucun élément n'est en attente ; un instantané JSON est
   archivé en base.
4. **Exports** : PV de classement (.xlsx), fiches d'évaluation (.xlsx), document
   imprimable (HTML → PDF navigateur) — générés par `classement.exports`.

L'admin peut **rouvrir** un dossier soumis (correction) tant que le classement
n'est pas gelé.

## 6. Développement local (Windows)

```powershell
pip install -e .[webapp,dev]
copy .env.example .env            # DATABASE_URL=sqlite:///./dev.db par défaut
python -m webapp.scripts.seed --admin-email admin@local
python -m uvicorn webapp.main:app --reload
# tests
python -m pytest -q
```

Parité PostgreSQL avant mise en production : `docker compose up --build`.

## 7. Recette de parité (avant le lancement réel)

Le même dossier saisi via l'application et scoré via la CLI doit donner un
score identique :

```powershell
python -m classement score --grid u3-residences-scientifiques `
  --institution enset-skikda --candidates dossier-reference.json `
  --campaign-date 2026-06-30
```

Les tests `tests/webapp/test_assemble.py` verrouillent cette équivalence pour
chaque type de critère.
