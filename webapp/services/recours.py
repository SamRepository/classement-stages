"""Phase de recours : dépôt (enseignant) et traitement (responsable).

Un recours conteste une décision de la commission sur un élément (``Entry``),
après publication des résultats provisoires. Il ne porte que du texte (motif dans
une liste de choix + message) : aucune pièce jointe, pour ne pas rouvrir l'ajout
de justificatifs après la clôture. Le responsable tranche ; accepter un recours
n'agit pas sur le score par lui-même — le responsable corrige ensuite l'élément
avec les outils d'examen (re-validation / ajustement), et le moteur recalcule.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from webapp.config import get_settings
from webapp.models import (
    RECOURS_MOTIFS,
    Campaign,
    Dossier,
    Entry,
    Recours,
    User,
)
from webapp.services import mailer
from webapp.services.dossier import log_event

logger = logging.getLogger("webapp.recours")

# Issues possibles d'un recours tranché par le responsable.
DECISIONS = ("accepte", "rejete", "irrecevable")

# Libellés français (source unique pour l'espace enseignant et l'espace
# commission) : la « liste de choix » du motif et l'état du recours.
MOTIF_LABELS = {
    "desaccord_rejet": "Je conteste le rejet de cet élément",
    "sous_evaluation": "Cet élément vaut plus de points que ce qui a été retenu",
    "erreur_appreciation": "Erreur d'appréciation ou de calcul",
    "erreur_saisie": "Erreur matérielle dans ma déclaration",
    "autre": "Autre motif (préciser ci-dessous)",
}
STATUT_LABELS = {
    "ouvert": "En attente de traitement",
    "accepte": "Accepté",
    "rejete": "Rejeté",
    "irrecevable": "Irrecevable",
    "retire": "Retiré",
}


def recours_phase(campaign: Campaign) -> bool:
    """Vrai si la phase de recours est active (résultats provisoires publiés).

    La campagne doit être clôturée (saisie fermée, examen commission fait) et le
    responsable avoir explicitement ouvert la fenêtre de recours.
    """
    return campaign.statut == "cloturee" and bool(campaign.recours_ouverts)


def active_recours(entry: Entry) -> Recours | None:
    """Le recours en cours sur un élément (déposé ou tranché), hors retirés.

    Un seul est possible à la fois : tant qu'il existe, l'enseignant ne peut pas
    en déposer un nouveau. Un recours retiré libère la possibilité d'en redéposer.
    Lecture d'affichage (via la relation ORM) ; le garde-fou du dépôt s'appuie,
    lui, sur une requête directe (``_active_recours_row``) insensible au cache.
    """
    en_cours = [r for r in entry.recours if r.statut != "retire"]
    return en_cours[-1] if en_cours else None


def _active_recours_row(db: Session, entry_id: int) -> Recours | None:
    """Recours actif (non retiré) d'un élément, lu directement en base."""
    return db.scalar(
        select(Recours)
        .where(Recours.entry_id == entry_id, Recours.statut != "retire")
        .order_by(Recours.id.desc())
    )


def _link(path: str) -> str:
    base = get_settings().base_url
    return f"{base}{path}" if base else ""


def _notify_depot(db: Session, recours: Recours) -> None:
    """Prévient le(s) responsable(s) qu'un recours vient d'être déposé.

    Silencieux hors-ligne (SMTP non configuré) et jamais bloquant : une panne
    e-mail ne doit pas empêcher le dépôt. À défaut de responsable, on prévient
    les admins pour ne pas perdre l'information.
    """
    dossier = recours.entry.dossier
    cibles = list(db.scalars(
        select(User).where(User.role == "responsable_commission", User.actif.is_(True))
    )) or list(db.scalars(
        select(User).where(User.role == "admin", User.actif.is_(True))
    ))
    if not cibles:
        return
    candidat = f"{dossier.user.nom} {dossier.user.prenom}".strip()
    lien = _link("/commission/recours")
    corps = (
        "Un recours vient d'être déposé sur la plateforme de classement des mobilités.\n\n"
        f"Candidat : {candidat} (dossier {dossier.candidate_ref})\n"
        f"Motif : {MOTIF_LABELS.get(recours.motif, recours.motif)}\n"
        f"Message : {recours.message}\n\n"
        + (f"Traiter les recours : {lien}\n\n" if lien else "")
        + "— Plateforme de classement des mobilités, ENSET-Skikda"
    )
    sujet = f"Nouveau recours à traiter — {dossier.candidate_ref}"
    for cible in cibles:
        mailer.notify(cible.email, sujet, corps)


def _notify_decision(recours: Recours) -> None:
    """Prévient l'enseignant que son recours a été tranché (silencieux hors-ligne)."""
    enseignant = recours.created_by_user
    nom = f"{enseignant.prenom} {enseignant.nom}".strip() or enseignant.email
    lien = _link("/mon-dossier")
    corps = (
        f"Bonjour {nom},\n\n"
        f"Votre recours (motif : {MOTIF_LABELS.get(recours.motif, recours.motif)}) a été "
        f"traité par la commission : « {STATUT_LABELS.get(recours.statut, recours.statut)} ».\n\n"
        f"Réponse de la commission : {recours.reponse_motif}\n\n"
        + (f"Consulter votre dossier : {lien}\n\n" if lien else "")
        + "— Plateforme de classement des mobilités, ENSET-Skikda"
    )
    mailer.notify(enseignant.email, "Votre recours a été traité", corps)


def file_recours(
    db: Session, entry: Entry, user: User, motif: str, message: str
) -> Recours:
    """Dépose un recours de l'enseignant sur l'un de ses éléments."""
    dossier = entry.dossier
    if dossier.user_id != user.id:
        raise HTTPException(status_code=403, detail="Cet élément n'est pas dans votre dossier.")
    if not recours_phase(dossier.campaign):
        raise HTTPException(
            status_code=403,
            detail="La période de recours n'est pas ouverte.",
        )
    if motif not in RECOURS_MOTIFS:
        raise HTTPException(status_code=422, detail=f"Motif de recours inconnu : {motif!r}.")
    message = (message or "").strip()
    if not message:
        raise HTTPException(
            status_code=422,
            detail="Merci de préciser votre recours (le message est obligatoire).",
        )
    if _active_recours_row(db, entry.id) is not None:
        raise HTTPException(
            status_code=409,
            detail="Un recours est déjà en cours sur cet élément.",
        )
    recours = Recours(
        entry_id=entry.id, created_by=user.id, motif=motif, message=message, statut="ouvert"
    )
    db.add(recours)
    log_event(db, user, "recours_depose", dossier,
              detail=f"entry={entry.id} {entry.criterion_id}/{entry.item_id or '-'} motif={motif}")
    db.commit()
    db.refresh(recours)
    _notify_depot(db, recours)
    return recours


def withdraw_recours(db: Session, recours: Recours, user: User) -> None:
    """Retrait par l'enseignant, possible tant que le recours n'est pas tranché."""
    if recours.created_by != user.id:
        raise HTTPException(status_code=403, detail="Ce recours n'est pas le vôtre.")
    if recours.statut != "ouvert":
        raise HTTPException(
            status_code=409,
            detail="Ce recours a déjà été traité : il ne peut plus être retiré.",
        )
    recours.statut = "retire"
    log_event(db, user, "recours_retire", recours.entry.dossier,
              detail=f"recours={recours.id} entry={recours.entry_id}")
    db.commit()


def decide_recours(
    db: Session, recours: Recours, responsable: User, decision: str, reponse_motif: str
) -> Recours:
    """Le responsable tranche un recours (accepté / rejeté / irrecevable).

    La motivation est toujours obligatoire (art. 14-15). Cette décision ne touche
    pas au score : si le recours est accepté, le responsable corrige ensuite
    l'élément avec les outils d'examen (re-validation / ajustement de quantité,
    de rang, de valeur…), ce qui déclenche le recalcul.
    """
    if recours.statut != "ouvert":
        raise HTTPException(status_code=409, detail="Ce recours a déjà été traité.")
    if decision not in DECISIONS:
        raise HTTPException(status_code=422, detail=f"Décision de recours inconnue : {decision!r}.")
    reponse_motif = (reponse_motif or "").strip()
    if not reponse_motif:
        raise HTTPException(
            status_code=422,
            detail="La réponse au recours doit être motivée (art. 14-15 de l'arrêté).",
        )
    recours.statut = decision
    recours.reponse_motif = reponse_motif
    recours.decided_by = responsable.id
    recours.decided_at = datetime.now(timezone.utc)
    log_event(db, responsable, f"recours_{decision}", recours.entry.dossier,
              detail=f"recours={recours.id} entry={recours.entry_id}")
    db.commit()
    db.refresh(recours)
    _notify_decision(recours)
    return recours


def _campaign_recours_query(campaign: Campaign, *, only_open: bool):
    stmt = (
        select(Recours)
        .join(Entry, Recours.entry_id == Entry.id)
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(Dossier.campaign_id == campaign.id)
    )
    if only_open:
        stmt = stmt.where(Recours.statut == "ouvert")
    return stmt


def open_recours_count(db: Session, campaign: Campaign) -> int:
    """Nombre de recours encore ouverts sur la campagne (garde-fou du gel)."""
    stmt = (
        select(func.count(Recours.id))
        .join(Entry, Recours.entry_id == Entry.id)
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(Dossier.campaign_id == campaign.id, Recours.statut == "ouvert")
    )
    return db.scalar(stmt) or 0


def list_open_recours(db: Session, campaign: Campaign) -> list[Recours]:
    """File des recours ouverts à traiter par le responsable (plus anciens d'abord)."""
    return list(
        db.scalars(_campaign_recours_query(campaign, only_open=True).order_by(Recours.id))
    )


def open_recours_window(
    db: Session, campaign: Campaign, user: User, deadline_raw: str | None
) -> None:
    """Ouvre la période de recours (publie le classement provisoire).

    Réservé aux campagnes clôturées (résultats provisoires disponibles). La date
    limite est facultative et purement indicative. Utilisé par le responsable
    (espace commission) comme par l'admin (espace campagne).
    """
    if campaign.statut != "cloturee":
        raise HTTPException(
            status_code=422,
            detail="Ouvrir les recours exige une campagne clôturée "
                   "(saisie fermée, résultats provisoires disponibles).",
        )
    raw = (deadline_raw or "").strip()
    if raw:
        try:
            campaign.recours_deadline = date.fromisoformat(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail="Date limite invalide (AAAA-MM-JJ).")
    else:
        campaign.recours_deadline = None
    campaign.recours_ouverts = True
    log_event(db, user, "recours_ouverts", detail=f"deadline={campaign.recours_deadline or '-'}")
    db.commit()


def close_recours_window(db: Session, campaign: Campaign, user: User) -> None:
    """Ferme la période de recours (les enseignants ne peuvent plus contester)."""
    campaign.recours_ouverts = False
    log_event(db, user, "recours_fermes")
    db.commit()
