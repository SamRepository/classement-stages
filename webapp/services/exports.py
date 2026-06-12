"""Exports officiels (PV, fiches, HTML) et gel du classement.

Les documents sont générés par ``classement.exports`` (réutilisé tel quel) vers
un fichier temporaire renvoyé en téléchargement. Après le gel, les dossiers et
décisions étant immuables, un recalcul donne un résultat identique au snapshot
(conservé en base pour l'audit).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from classement.exports import export_fiches, export_html, export_pv
from webapp.models import Campaign, Dossier, Entry, RankingSnapshot, User
from webapp.services.dossier import log_event
from webapp.services.scoring import RankingResult, compute_ranking, get_grid, get_institution

EXPORT_KINDS = {
    "pv.xlsx": ("PV de classement", ".xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "fiches.xlsx": ("Fiches d'évaluation", ".xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "classement.html": ("Document imprimable", ".html", "text/html"),
}


def snapshot_payload(result: RankingResult) -> dict:
    """Représentation JSON du classement au moment du gel (audit)."""
    return {
        "groups": {
            " / ".join(map(str, key)): [asdict(r) for r in ranked]
            for key, ranked in result.groups.items()
        },
        "breakdowns": [asdict(b) for b in result.breakdowns],
        "candidates": result.candidates,
        "exclusions": {str(k): v for k, v in result.exclusions.items()},
    }


def pending_entries_count(db: Session, campaign: Campaign) -> int:
    """Éléments encore en attente sur les dossiers soumis."""
    return db.scalar(
        select(func.count(Entry.id))
        .join(Dossier, Entry.dossier_id == Dossier.id)
        .where(
            Dossier.campaign_id == campaign.id,
            Dossier.statut == "soumis",
            Entry.statut == "en_attente",
        )
    ) or 0


def freeze_campaign(db: Session, campaign: Campaign, user: User) -> RankingSnapshot:
    """Gèle le classement : tout élément des dossiers soumis doit être décidé."""
    if campaign.statut == "gelee":
        raise HTTPException(status_code=400, detail="Le classement est déjà gelé.")
    pending = pending_entries_count(db, campaign)
    if pending:
        raise HTTPException(
            status_code=403,
            detail=f"Gel impossible : {pending} élément(s) encore en attente de décision "
                   "(la revue exhaustive est exigée par l'art. 14-15).",
        )
    result = compute_ranking(db, campaign, mode="commission")
    snapshot = RankingSnapshot(campaign_id=campaign.id, payload=snapshot_payload(result))
    db.add(snapshot)
    for dossier in result.dossiers:
        dossier.statut = "gele"
    campaign.statut = "gelee"
    campaign.frozen_at = datetime.now(timezone.utc)
    log_event(db, user, "gel_classement", detail=f"{len(result.dossiers)} dossier(s) classé(s)")
    db.commit()
    return snapshot


def export_response(db: Session, campaign: Campaign, kind: str) -> FileResponse:
    """Génère le document demandé et le renvoie en téléchargement."""
    if kind not in EXPORT_KINDS:
        raise HTTPException(status_code=404, detail=f"Export inconnu : {kind!r}.")
    _, suffix, media_type = EXPORT_KINDS[kind]

    result = compute_ranking(db, campaign, mode="commission")
    if not result.dossiers:
        raise HTTPException(status_code=400, detail="Aucun dossier soumis à exporter.")
    grid = get_grid(campaign.grid_id)
    institution = get_institution(campaign.institution_id)
    campaign_date = campaign.campaign_date.isoformat()

    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        if kind == "pv.xlsx":
            export_pv(path, result.groups, result.candidates, grid, institution, campaign_date)
        elif kind == "fiches.xlsx":
            export_fiches(path, result.breakdowns, result.candidates, result.groups,
                          grid, institution, campaign_date)
        else:
            export_html(path, result.groups, result.breakdowns, result.candidates,
                        grid, institution, campaign_date)
    except Exception:
        os.unlink(path)
        raise
    filename = f"{kind.split('.')[0]}-{campaign.grid_id}-{campaign_date}{suffix}"
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=BackgroundTask(os.unlink, path),
    )
