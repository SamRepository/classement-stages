"""Espace admin : comptes, historique des bénéfices, campagne, réouvertures."""

from __future__ import annotations

import secrets
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile

from webapp.auth import require_role
from webapp.config import get_settings
from webapp.db import Base, get_db
from webapp.models import Benefit, Dossier, User
from webapp.security import generate_password, hash_password
from webapp.services import backup
from webapp.services.accounts import import_accounts, import_benefits
from webapp.services.dossier import get_campaign, log_event, reopen_dossier
from webapp.services.mailer import notify_new_accounts
from webapp.templating import templates

router = APIRouter(prefix="/admin")

ADMIN = Depends(require_role("admin"))


def _page_utilisateurs(request: Request, db: Session, user: User, *, tri: str = "role", **extra):
    order = User.email if tri == "email" else (User.role, User.nom)
    if tri != "email":
        tri = "role"
    stmt = select(User).order_by(*(order if isinstance(order, tuple) else (order,)))
    users = list(db.scalars(stmt))
    contexte = {"user": user, "users": users, "nouveaux": [], "ignores": [],
                "envoi": None, "tri": tri, **extra}
    return templates.TemplateResponse(request, "admin/utilisateurs.html", contexte)


@router.get("/utilisateurs")
def utilisateurs(
    request: Request, tri: str = "role", user: User = ADMIN, db: Session = Depends(get_db)
):
    return _page_utilisateurs(request, db, user, tri=tri)


@router.post("/utilisateurs")
async def creer_utilisateur(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    nom = (form.get("nom") or "").strip()
    role = form.get("role") or "enseignant"
    if not email or "@" not in email or not nom:
        raise HTTPException(status_code=422, detail="Email et nom obligatoires.")
    if role not in ("enseignant", "commission", "admin"):
        raise HTTPException(status_code=422, detail=f"Rôle inconnu : {role!r}.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=422, detail=f"{email} existe déjà.")
    password = generate_password()
    nouveau = User(email=email, password_hash=hash_password(password), nom=nom,
                   prenom=(form.get("prenom") or "").strip(), role=role,
                   must_change_password=True)
    db.add(nouveau)
    log_event(db, user, "creation_compte", detail=f"{email} ({role})")
    db.commit()
    created = [{"email": email, "nom": nom, "prenom": nouveau.prenom, "password": password}]
    envoi = notify_new_accounts(created)
    return _page_utilisateurs(request, db, user, nouveaux=created, envoi=envoi)


@router.post("/utilisateurs/import")
async def importer_utilisateurs(
    request: Request, user: User = ADMIN, db: Session = Depends(get_db)
):
    form = await request.form()
    fichier = form.get("fichier")
    if not (isinstance(fichier, UploadFile) and fichier.filename):
        raise HTTPException(status_code=422, detail="Aucun fichier fourni.")
    campaign = get_campaign(db)
    created, skipped = import_accounts(db, campaign, fichier.filename, await fichier.read())
    envoi = notify_new_accounts(created)
    log_event(db, user, "import_comptes",
              detail=f"{fichier.filename} : {len(created)} créé(s), {len(skipped)} ignoré(s), "
                     f"{envoi['envoyes']} e-mail(s) envoyé(s)")
    db.commit()
    return _page_utilisateurs(request, db, user, nouveaux=created, ignores=skipped, envoi=envoi)


@router.post("/utilisateurs/{user_id}/basculer-actif")
def basculer_actif(
    request: Request, user_id: int, user: User = ADMIN, db: Session = Depends(get_db)
):
    cible = db.get(User, user_id)
    if cible is None:
        raise HTTPException(status_code=404)
    if cible.id == user.id:
        raise HTTPException(status_code=422, detail="Impossible de désactiver son propre compte.")
    cible.actif = not cible.actif
    log_event(db, user, "bascule_actif", detail=f"{cible.email} → actif={cible.actif}")
    db.commit()
    request.session["flash"] = (
        f"Compte {cible.email} {'réactivé' if cible.actif else 'désactivé'}."
    )
    return RedirectResponse("/admin/utilisateurs", status_code=303)


@router.post("/utilisateurs/{user_id}/motdepasse")
def reinitialiser_motdepasse(
    request: Request, user_id: int, user: User = ADMIN, db: Session = Depends(get_db)
):
    cible = db.get(User, user_id)
    if cible is None:
        raise HTTPException(status_code=404)
    password = generate_password()
    cible.password_hash = hash_password(password)
    cible.must_change_password = True
    log_event(db, user, "reinit_motdepasse", detail=cible.email)
    db.commit()
    created = [{"email": cible.email, "nom": cible.nom, "prenom": cible.prenom,
                "password": password}]
    envoi = notify_new_accounts(created)
    return _page_utilisateurs(request, db, user, nouveaux=created, envoi=envoi)


@router.post("/utilisateurs/envoyer-identifiants")
async def envoyer_identifiants(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    """Envoi groupé : (ré)génère un mot de passe provisoire pour chaque compte
    sélectionné et le communique par e-mail (ou l'affiche si SMTP hors-ligne).

    Le mot de passe stocké étant haché (irrécupérable), chaque envoi produit un
    nouveau mot de passe provisoire ; l'ancien cesse alors d'être valable.
    """
    form = await request.form()
    ids = [int(v) for v in form.getlist("user_ids") if str(v).isdigit()]
    if not ids:
        raise HTTPException(status_code=422, detail="Aucun compte sélectionné.")
    created: list[dict] = []
    for cible in db.scalars(select(User).where(User.id.in_(ids))):
        password = generate_password()
        cible.password_hash = hash_password(password)
        cible.must_change_password = True
        created.append({"email": cible.email, "nom": cible.nom, "prenom": cible.prenom,
                        "password": password})
    log_event(db, user, "envoi_identifiants_groupe", detail=f"{len(created)} compte(s)")
    db.commit()
    envoi = notify_new_accounts(created)
    return _page_utilisateurs(request, db, user, nouveaux=created, envoi=envoi)


# ---------------------------------------------------------------------------
# Historique des bénéfices
# ---------------------------------------------------------------------------


def _page_benefices(request: Request, db: Session, user: User, cible: User | None = None, **extra):
    enseignants = list(
        db.scalars(select(User).where(User.role == "enseignant").order_by(User.nom))
    )
    contexte = {
        "user": user, "enseignants": enseignants, "cible": cible,
        "benefits": cible.benefits if cible else [],
        "import_count": None, "import_messages": [], **extra,
    }
    return templates.TemplateResponse(request, "admin/benefices.html", contexte)


@router.get("/benefices")
def benefices(
    request: Request,
    user_id: int | None = None,
    user: User = ADMIN,
    db: Session = Depends(get_db),
):
    cible = db.get(User, user_id) if user_id else None
    return _page_benefices(request, db, user, cible)


@router.post("/benefices/import")
async def importer_benefices(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    form = await request.form()
    fichier = form.get("fichier")
    if not (isinstance(fichier, UploadFile) and fichier.filename):
        raise HTTPException(status_code=422, detail="Aucun fichier fourni.")
    count, messages = import_benefits(db, fichier.filename, await fichier.read())
    log_event(db, user, "import_benefices",
              detail=f"{fichier.filename} : {count} importé(s), {len(messages)} ignoré(s)")
    db.commit()
    return _page_benefices(request, db, user, import_count=count, import_messages=messages)


@router.post("/benefices")
async def ajouter_benefice(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    form = await request.form()
    cible = db.get(User, int(form.get("user_id") or 0))
    if cible is None:
        raise HTTPException(status_code=404, detail="Enseignant introuvable.")
    try:
        date_mobilite = date.fromisoformat(form.get("date") or "")
    except ValueError:
        raise HTTPException(status_code=422, detail="Date de mobilité invalide (AAAA-MM-JJ).")
    close = None
    if form.get("platform_close_date"):
        try:
            close = date.fromisoformat(form.get("platform_close_date"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Date de clôture invalide (AAAA-MM-JJ).")
    db.add(Benefit(user_id=cible.id, date=date_mobilite, platform_close_date=close,
                   note=(form.get("note") or "").strip() or None))
    log_event(db, user, "ajout_benefice", detail=f"{cible.email} : {date_mobilite}")
    db.commit()
    request.session["flash"] = f"Bénéfice du {date_mobilite} ajouté."
    return RedirectResponse(f"/admin/benefices?user_id={cible.id}", status_code=303)


@router.post("/benefices/{benefit_id}/supprimer")
def supprimer_benefice(
    request: Request, benefit_id: int, user: User = ADMIN, db: Session = Depends(get_db)
):
    benefit = db.get(Benefit, benefit_id)
    if benefit is None:
        raise HTTPException(status_code=404)
    user_id = benefit.user_id
    log_event(db, user, "suppression_benefice", detail=f"user={user_id} date={benefit.date}")
    db.delete(benefit)
    db.commit()
    request.session["flash"] = "Bénéfice supprimé."
    return RedirectResponse(f"/admin/benefices?user_id={user_id}", status_code=303)


# ---------------------------------------------------------------------------
# Campagne et réouvertures
# ---------------------------------------------------------------------------


@router.get("/campagne")
def campagne(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    camp = get_campaign(db)
    dossiers = list(
        db.scalars(select(Dossier).where(Dossier.campaign_id == camp.id).order_by(Dossier.id))
    )
    return templates.TemplateResponse(
        request,
        "admin/campagne.html",
        {"user": user, "campaign": camp, "dossiers": dossiers},
    )


@router.post("/campagne")
async def maj_campagne(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    camp = get_campaign(db)
    if camp.statut == "gelee":
        raise HTTPException(status_code=403, detail="Campagne gelée : paramètres figés.")
    form = await request.form()

    def _dt(name: str) -> datetime | None:
        raw = (form.get(name) or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Date/heure invalide : {raw!r}.")

    statut = form.get("statut") or camp.statut
    if statut not in ("ouverte", "cloturee"):
        raise HTTPException(status_code=422, detail=f"Statut inconnu : {statut!r}.")
    if form.get("campaign_date"):
        try:
            camp.campaign_date = date.fromisoformat(form.get("campaign_date"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Date de campagne invalide.")
    camp.date_ouverture = _dt("date_ouverture")
    camp.date_cloture = _dt("date_cloture")
    camp.statut = statut

    # Repère de la fenêtre « après dernier bénéfice » pour les activités.
    wref = form.get("window_reference") or camp.window_reference
    if wref not in ("cloture", "mobilite"):
        raise HTTPException(status_code=422, detail=f"Repère de fenêtre inconnu : {wref!r}.")
    camp.window_reference = wref

    def _window_date(name: str, libelle: str) -> date | None:
        raw = (form.get(name) or "").strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{libelle} invalide.")

    start = _window_date("window_start_date", "Début de l'exercice budgétaire")
    end = _window_date("window_end_date", "Fin de l'exercice budgétaire")
    if start and end and start > end:
        raise HTTPException(
            status_code=422,
            detail="L'exercice budgétaire commence après sa date de fin.",
        )
    camp.window_start_date = start
    camp.window_end_date = end

    log_event(db, user, "maj_campagne", detail=f"statut={statut} fenetre={wref}")
    db.commit()
    request.session["flash"] = "Paramètres de campagne enregistrés."
    return RedirectResponse("/admin/campagne", status_code=303)


@router.post("/dossiers/{dossier_id}/reouvrir")
def reouvrir(
    request: Request, dossier_id: int, user: User = ADMIN, db: Session = Depends(get_db)
):
    dossier = db.get(Dossier, dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404)
    reopen_dossier(db, dossier, user)
    request.session["flash"] = "Dossier rouvert pour modification."
    return RedirectResponse("/admin/campagne", status_code=303)


# ---------------------------------------------------------------------------
# Sauvegarde et restauration (cf. docs/spec-backup-restauration.md)
# ---------------------------------------------------------------------------


def _db_counts(db: Session) -> dict[str, int]:
    return {
        table.name: db.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }


def _page_sauvegarde(request: Request, db: Session, user: User, *, preview=None, rapport=None):
    contexte = {
        "user": user,
        "counts": _db_counts(db),
        "phrase": backup.CONFIRM_PHRASE,
        "preview": preview,
        "rapport": rapport,
    }
    return templates.TemplateResponse(request, "admin/sauvegarde.html", contexte)


@router.get("/sauvegarde")
def sauvegarde(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    return _page_sauvegarde(request, db, user)


@router.get("/backup")
def telecharger_backup(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    """Archive ZIP complète (base + justificatifs), téléchargée hors-serveur."""
    settings = get_settings()
    institution_id = get_campaign(db).institution_id
    archive = backup.build_archive(db, settings.upload_dir, institution_id=institution_id)
    log_event(db, user, "backup_telecharge", detail=archive.name)
    db.commit()
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=backup.archive_filename(institution_id),
        background=BackgroundTask(archive.unlink, missing_ok=True),
    )


@router.post("/restore/preview")
async def restore_preview(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    """Valide l'archive sans rien écrire, conserve-la, et propose la confirmation."""
    form = await request.form()
    fichier = form.get("fichier")
    if not (isinstance(fichier, UploadFile) and fichier.filename):
        raise HTTPException(status_code=422, detail="Aucune archive fournie.")

    settings = get_settings()
    pending_dir = settings.upload_dir / "_restore_pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(16)
    pending = pending_dir / f"{token}.zip"
    pending.write_bytes(await fichier.read())

    try:
        # Validation complète (révision, tables, sommes de contrôle) sans écriture.
        manifest = backup.validate_archive(db, pending)
    except HTTPException:
        pending.unlink(missing_ok=True)
        raise

    request.session["restore_token"] = token
    preview = {
        "token": token,
        "filename": fichier.filename,
        "generated_at": manifest.get("generated_at"),
        "counts": manifest.get("counts", {}),
        "files": manifest.get("files", {}),
    }
    return _page_sauvegarde(request, db, user, preview=preview)


@router.post("/restore/confirm")
async def restore_confirm(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    form = await request.form()
    token = (form.get("token") or "").strip()
    phrase = (form.get("phrase") or "").strip()
    session_token = request.session.get("restore_token")
    settings = get_settings()
    pending = settings.upload_dir / "_restore_pending" / f"{token}.zip"

    if not token or token != session_token or not pending.exists():
        raise HTTPException(status_code=422, detail="Session de restauration expirée — recommencez.")
    if phrase != backup.CONFIRM_PHRASE:
        raise HTTPException(
            status_code=422,
            detail=f"Confirmation incorrecte : saisissez exactement « {backup.CONFIRM_PHRASE} ».",
        )

    rapport = backup.restore_archive(db, settings.upload_dir, pending, confirmed=True)
    request.session.pop("restore_token", None)
    pending.unlink(missing_ok=True)
    log_event(db, user, "restauration",
              detail=f"{sum(rapport.counts.values())} ligne(s), "
                     f"{rapport.files_restored} fichier(s), {len(rapport.warnings)} avert.")
    db.commit()
    return _page_sauvegarde(request, db, user, rapport=rapport)
