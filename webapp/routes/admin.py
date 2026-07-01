"""Espace admin : comptes, historique des bénéfices, campagne, réouvertures."""

from __future__ import annotations

import secrets
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile

from webapp.auth import require_role
from webapp.config import get_settings
from webapp.db import Base, get_db
from webapp.models import Benefit, Dossier, ElementReview, Entry, Event, User
from webapp.security import generate_password, hash_password
from webapp.services import backup
from webapp.services.accounts import import_accounts, import_benefits
from webapp.services.dossier import (
    auto_submit_drafts,
    get_campaign,
    log_event,
    reopen_dossier,
)
from webapp.services.mailer import notify_new_accounts
from webapp.services.scoring import get_institution
from webapp.templating import templates

router = APIRouter(prefix="/admin")

ADMIN = Depends(require_role("admin"))

# Libellés et choix de rôles (une seule source pour la liste et l'édition).
ROLE_CHOICES = [
    ("enseignant", "Enseignant (candidat)"),
    ("commission", "Membre de la commission"),
    ("responsable_commission", "Responsable de la commission"),
    ("admin", "Administrateur"),
]
ROLE_LABELS = {
    "enseignant": "Enseignant",
    "commission": "Membre commission",
    "responsable_commission": "Responsable commission",
    "admin": "Administrateur",
}
VALID_ROLES = tuple(value for value, _ in ROLE_CHOICES)


def _commit(db: Session) -> None:
    """Commit en transformant un refus d'intégrité en message clair (au lieu d'un 500).

    Évite aussi de laisser la session dans un état cassé (rollback explicite).
    Cas typique : base non migrée après mise à jour (la contrainte de rôle
    ignore encore ``responsable_commission``) ou doublon d'e-mail concurrent.
    """
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=("Enregistrement refusé par la base (valeur non autorisée ou doublon). "
                    "Si le rôle « responsable de commission » est en cause, la base n'est "
                    "pas à jour : appliquez les migrations (alembic upgrade head)."),
        )


def _page_utilisateurs(request: Request, db: Session, user: User, *, tri: str = "role", **extra):
    order = User.email if tri == "email" else (User.role, User.nom)
    if tri != "email":
        tri = "role"
    stmt = select(User).order_by(*(order if isinstance(order, tuple) else (order,)))
    users = list(db.scalars(stmt))
    contexte = {"user": user, "users": users, "nouveaux": [], "ignores": [],
                "envoi": None, "tri": tri, "role_labels": ROLE_LABELS,
                "role_choices": ROLE_CHOICES, **extra}
    return templates.TemplateResponse(request, "admin/utilisateurs.html", contexte)


def _render_ligne(request: Request, u: User, *, edit: bool) -> HTMLResponse:
    """Rend une seule ligne de compte (affichage ou édition) pour les échanges HTMX."""
    html = templates.get_template("admin/fragments/ligne_compte.html").render(
        request=request, u=u, edit=edit,
        role_labels=ROLE_LABELS, role_choices=ROLE_CHOICES,
    )
    return HTMLResponse(html)


def _donnees_liees(db: Session, u: User) -> list[str]:
    """Libellés des données qui rattachent un compte (bloquent la suppression).

    Tant que l'une existe, la suppression physique casserait l'intégrité ou
    perdrait une donnée faisant foi : on refuse et on oriente vers la
    désactivation (cf. décision commission, conservation des traces art. 14-15).
    """
    checks = [
        ("dossier de candidature",
         select(func.count(Dossier.id)).where(Dossier.user_id == u.id)),
        ("dossier(s) affecté(s) en relecture",
         select(func.count(Dossier.id)).where(Dossier.assigned_reviewer_id == u.id)),
        ("décisions de commission",
         select(func.count(Entry.id)).where(Entry.decided_by == u.id)),
        ("avis de relecture",
         select(func.count(ElementReview.id)).where(ElementReview.reviewer_id == u.id)),
        ("historique de bénéfices",
         select(func.count(Benefit.id)).where(Benefit.user_id == u.id)),
        ("journal d'activité",
         select(func.count(Event.id)).where(Event.user_id == u.id)),
    ]
    return [libelle for libelle, stmt in checks if db.scalar(stmt)]


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
    if role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Rôle inconnu : {role!r}.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=422, detail=f"{email} existe déjà.")
    password = generate_password()
    nouveau = User(email=email, password_hash=hash_password(password), nom=nom,
                   prenom=(form.get("prenom") or "").strip(), role=role,
                   must_change_password=True)
    db.add(nouveau)
    log_event(db, user, "creation_compte", detail=f"{email} ({role})")
    _commit(db)
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


@router.get("/utilisateurs/{user_id}/edition")
def editer_compte(request: Request, user_id: int, user: User = ADMIN, db: Session = Depends(get_db)):
    cible = db.get(User, user_id)
    if cible is None:
        raise HTTPException(status_code=404)
    return _render_ligne(request, cible, edit=True)


@router.get("/utilisateurs/{user_id}/ligne")
def ligne_compte(request: Request, user_id: int, user: User = ADMIN, db: Session = Depends(get_db)):
    """Ligne d'affichage (utilisée pour annuler une édition)."""
    cible = db.get(User, user_id)
    if cible is None:
        raise HTTPException(status_code=404)
    return _render_ligne(request, cible, edit=False)


@router.post("/utilisateurs/{user_id}/modifier")
async def modifier_compte(
    request: Request, user_id: int, user: User = ADMIN, db: Session = Depends(get_db)
):
    cible = db.get(User, user_id)
    if cible is None:
        raise HTTPException(status_code=404)
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    nom = (form.get("nom") or "").strip()
    prenom = (form.get("prenom") or "").strip()
    role = form.get("role") or cible.role
    if not email or "@" not in email or not nom:
        raise HTTPException(status_code=422, detail="Email et nom obligatoires.")
    if role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Rôle inconnu : {role!r}.")
    if db.scalar(select(User).where(User.email == email, User.id != cible.id)):
        raise HTTPException(status_code=422, detail=f"L'email {email} est déjà utilisé.")
    if role != cible.role:
        if cible.id == user.id:
            raise HTTPException(
                status_code=422,
                detail="Vous ne pouvez pas changer votre propre rôle.",
            )
        if cible.role == "admin":
            autres_admins = db.scalar(
                select(func.count(User.id)).where(
                    User.role == "admin", User.actif.is_(True), User.id != cible.id
                )
            )
            if not autres_admins:
                raise HTTPException(
                    status_code=422,
                    detail="Au moins un administrateur actif doit subsister.",
                )
    cible.email, cible.nom, cible.prenom, cible.role = email, nom, prenom, role
    log_event(db, user, "modif_compte", detail=f"{email} ({role})")
    _commit(db)
    db.refresh(cible)
    return _render_ligne(request, cible, edit=False)


@router.post("/utilisateurs/{user_id}/supprimer")
def supprimer_compte(
    request: Request, user_id: int, user: User = ADMIN, db: Session = Depends(get_db)
):
    """Suppression physique — uniquement pour un compte sans aucune donnée liée."""
    cible = db.get(User, user_id)
    if cible is None:
        raise HTTPException(status_code=404)
    if cible.id == user.id:
        raise HTTPException(status_code=422, detail="Impossible de supprimer son propre compte.")
    liees = _donnees_liees(db, cible)
    if liees:
        raise HTTPException(
            status_code=422,
            detail=("Suppression impossible : ce compte a "
                    + ", ".join(liees)
                    + ". Désactivez-le plutôt (les traces sont conservées)."),
        )
    email = cible.email
    db.delete(cible)
    log_event(db, user, "suppression_compte", detail=email)
    db.commit()
    return HTMLResponse("")  # la ligne disparaît du tableau


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
    institution = get_institution(camp.institution_id)
    return templates.TemplateResponse(
        request,
        "admin/campagne.html",
        {"user": user, "campaign": camp, "dossiers": dossiers,
         "departements": institution.get("departements", []),
         "populations": institution.get("populations", [])},
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
    closing_saisie = statut == "cloturee" and camp.statut != "cloturee"
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

    flash = "Paramètres de campagne enregistrés."
    if closing_saisie:
        n = auto_submit_drafts(db, camp, user)
        if n:
            flash += f" {n} dossier(s) en brouillon soumis automatiquement."
    request.session["flash"] = flash
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


@router.post("/dossiers/{dossier_id}/infos")
async def maj_infos_dossier(
    request: Request, dossier_id: int, user: User = ADMIN, db: Session = Depends(get_db)
):
    """Corrige les infos administratives d'un dossier (département, population).

    Permet à l'admin de rectifier la classification d'un candidat sans rouvrir
    tout le dossier (ex. mauvais département saisi). Refusé après gel du
    classement (l'instantané figé ne doit plus bouger). Ces champs déterminent
    le groupe de classement — la modification est tracée.
    """
    dossier = db.get(Dossier, dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404)
    if dossier.campaign.statut == "gelee":
        raise HTTPException(status_code=403, detail="Classement gelé : correction impossible.")
    institution = get_institution(dossier.campaign.institution_id)
    form = await request.form()

    dep = (form.get("departement") or "").strip()
    if dep:
        if dep not in {d["id"] for d in institution.get("departements", [])}:
            raise HTTPException(status_code=422, detail=f"Département inconnu : {dep!r}.")
        dossier.departement = dep
    else:
        dossier.departement = None

    pop = (form.get("population") or "").strip()
    if pop:
        if pop not in set(institution.get("populations", [])):
            raise HTTPException(status_code=422, detail=f"Population inconnue : {pop!r}.")
        dossier.population = pop

    log_event(db, user, "maj_infos_dossier", dossier,
              detail=f"departement={dossier.departement} population={dossier.population}")
    db.commit()
    request.session["flash"] = f"Informations administratives de {dossier.candidate_ref} mises à jour."
    return RedirectResponse("/admin/campagne", status_code=303)


# ---------------------------------------------------------------------------
# Budget : billet / frais divers par bénéficiaire (saisie service budget)
# ---------------------------------------------------------------------------


def _parse_da(value: str | None, libelle: str) -> float | None:
    raw = (value or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        montant = float(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{libelle} : montant invalide.")
    if montant < 0:
        raise HTTPException(status_code=422, detail=f"{libelle} : montant négatif.")
    return montant


@router.get("/budget")
def budget(request: Request, user: User = ADMIN, db: Session = Depends(get_db)):
    camp = get_campaign(db)
    dossiers = list(
        db.scalars(
            select(Dossier)
            .where(Dossier.campaign_id == camp.id)
            .order_by(Dossier.candidate_ref)
        )
    )
    return templates.TemplateResponse(
        request,
        "admin/budget.html",
        {"user": user, "campaign": camp, "dossiers": dossiers},
    )


@router.post("/budget/{dossier_id}")
async def maj_budget(
    request: Request, dossier_id: int, user: User = ADMIN, db: Session = Depends(get_db)
):
    camp = get_campaign(db)
    dossier = db.get(Dossier, dossier_id)
    if dossier is None or dossier.campaign_id != camp.id:
        raise HTTPException(status_code=404)
    form = await request.form()
    dossier.billet_estime_da = _parse_da(form.get("billet_estime_da"), "Billet estimé")
    dossier.frais_divers_da = _parse_da(form.get("frais_divers_da"), "Frais divers")
    log_event(db, user, "maj_budget", dossier,
              detail=f"billet={dossier.billet_estime_da} frais={dossier.frais_divers_da}")
    db.commit()
    request.session["flash"] = f"Budget enregistré pour {dossier.candidate_ref}."
    return RedirectResponse("/admin/budget", status_code=303)


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
