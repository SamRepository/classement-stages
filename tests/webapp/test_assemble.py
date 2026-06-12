"""Fidélité de l'assemblage BDD → dict candidat → moteur.

Principe : pour chaque type de critère de la grille u3, on écrit des lignes
``entries`` en base, on assemble, on score, et on compare au score obtenu avec
un dict candidat construit à la main (le format documenté du moteur).
"""

from datetime import date, datetime, timezone

import pytest

from classement.engine import score_candidate
from webapp.models import Benefit, Entry
from webapp.services.scoring import (
    assemble_candidate,
    compute_ranking,
    compute_score,
    get_grid,
    get_shared_rules,
)

GRID = get_grid("u3-residences-scientifiques")
RULES = get_shared_rules()
CAMPAIGN_DATE = date(2026, 6, 30)


def _score_manual(candidate: dict):
    return score_candidate(GRID, candidate, RULES, CAMPAIGN_DATE, "cloture")


def _add_entries(db, dossier, rows):
    for row in rows:
        db.add(Entry(dossier_id=dossier.id, **row))
    db.commit()
    db.refresh(dossier)


def test_parite_enum_count_formula(db_session, dossier, enseignant):
    """Dossier complet (enum + count pondéré/fenêtré + formule) ≡ dict manuel."""
    db_session.add(Benefit(user_id=enseignant.id, date=date(2024, 9, 15),
                           platform_close_date=date(2024, 4, 30)))
    _add_entries(db_session, dossier, [
        {"criterion_id": "rang_scientifique", "payload": {"value": "mcb", "option_bonus": True}},
        {"criterion_id": "penalite_beneficies_3ans", "payload": {}},
        {"criterion_id": "publications", "item_id": "classe_a",
         "payload": {"count": 1, "author_position": 2, "date": "2025-03-10", "doi": "10.1/x"}},
        {"criterion_id": "publications", "item_id": "classe_a",
         "payload": {"count": 1, "author_position": 1, "date": "2024-01-10"}},  # avant clôture
        {"criterion_id": "communications", "item_id": "intl_indexee_scopus_wos",
         "payload": {"count": 2, "date": "2025-06-20", "url": "https://x"}},
        {"criterion_id": "encadrement_master", "item_id": "memoire_master",
         "payload": {"count": 5, "date": "2025-06-30"}},  # cap_points 3
    ])

    breakdown, exclusions = compute_score(db_session, dossier, mode="declare")
    assert exclusions == []

    manual = {
        "id": dossier.candidate_ref,
        "nom": enseignant.nom, "prenom": enseignant.prenom,
        "population": "enseignant_chercheur",
        "grouping": {"departement": "technologie"},
        "benefits": [{"date": "2024-09-15", "platform_close_date": "2024-04-30"}],
        "entries": {
            "rang_scientifique": {"value": "mcb", "option_bonus": True},
            "penalite_beneficies_3ans": {},
            "publications": {"items": [
                {"item": "classe_a", "count": 1, "author_position": 2,
                 "date": "2025-03-10", "doi": "10.1/x"},
                {"item": "classe_a", "count": 1, "author_position": 1, "date": "2024-01-10"},
            ]},
            "communications": {"items": [
                {"item": "intl_indexee_scopus_wos", "count": 2,
                 "date": "2025-06-20", "url": "https://x"},
            ]},
            "encadrement_master": {"items": [
                {"item": "memoire_master", "count": 5, "date": "2025-06-30"},
            ]},
        },
    }
    expected = _score_manual(manual)
    assert breakdown.total == expected.total
    by_id = {l.criterion_id: l.points for l in breakdown.lines}
    expected_by_id = {l.criterion_id: l.points for l in expected.lines}
    assert by_id == expected_by_id
    # Valeurs de contrôle : mcb 3+4 bonus ; pénalité 3-1=2 ; classe_a pondérée
    # position 2 ; publication antérieure à la clôture ignorée.
    assert by_id["rang_scientifique"] == 7.0
    assert by_id["penalite_beneficies_3ans"] == 2.0
    assert by_id["encadrement_master"] == 3.0  # 5 mémoires plafonnés à 3 pts


def test_fixed_et_bonus(db_session, dossier):
    _add_entries(db_session, dossier, [
        {"criterion_id": "polycopie_pedagogique", "payload": {"applies": True, "bonuses": [0]}},
        {"criterion_id": "livre_isbn", "payload": {"applies": True}},
    ])
    breakdown, _ = compute_score(db_session, dossier, mode="declare")
    by_id = {l.criterion_id: l.points for l in breakdown.lines}
    assert by_id["polycopie_pedagogique"] == 5.0  # 3 + bonus anglais 2
    assert by_id["livre_isbn"] == 5.0


def test_rejet_exclu_avec_trace(db_session, dossier, membre_commission):
    _add_entries(db_session, dossier, [
        {"criterion_id": "publications", "item_id": "classe_a_plus",
         "payload": {"count": 1, "author_position": 1, "date": "2025-01-01"}},
        {"criterion_id": "publications", "item_id": "classe_b",
         "payload": {"count": 1, "author_position": 1, "date": "2025-02-01"},
         "statut": "rejete", "decision_motif": "Justificatif illisible",
         "decided_by": membre_commission.id,
         "decided_at": datetime(2026, 6, 1, tzinfo=timezone.utc)},
    ])

    declare, excl_declare = compute_score(db_session, dossier, mode="declare")
    commission, excl_commission = compute_score(db_session, dossier, mode="commission")

    # Provisoire : tout compté, pas d'exclusion.
    assert excl_declare == []
    assert {l.criterion_id: l.points for l in declare.lines}["publications"] == 30.0
    # Commission : l'élément rejeté est exclu mais tracé avec son motif.
    assert {l.criterion_id: l.points for l in commission.lines}["publications"] == 20.0
    assert len(excl_commission) == 1
    assert excl_commission[0]["motif"] == "Justificatif illisible"
    assert excl_commission[0]["criterion_id"] == "publications"
    assert excl_commission[0]["item_id"] == "classe_b"


def test_en_attente_compte_en_mode_commission(db_session, dossier):
    _add_entries(db_session, dossier, [
        {"criterion_id": "projet_international", "item_id": "projet_intl",
         "payload": {"count": 1}, "statut": "en_attente"},
        {"criterion_id": "projet_national", "item_id": "projet_national",
         "payload": {"count": 1}, "statut": "valide"},
    ])
    breakdown, _ = compute_score(db_session, dossier, mode="commission")
    by_id = {l.criterion_id: l.points for l in breakdown.lines}
    assert by_id["projet_international"] == 10.0
    assert by_id["projet_national"] == 5.0


def test_benefices_fenetre_et_penalite(db_session, dossier, enseignant):
    """2 bénéfices en 3 ans → n=2 → pénalité 1 ; fenêtre = clôture la plus récente."""
    db_session.add_all([
        Benefit(user_id=enseignant.id, date=date(2024, 9, 15),
                platform_close_date=date(2024, 4, 30)),
        Benefit(user_id=enseignant.id, date=date(2025, 7, 1),
                platform_close_date=date(2025, 2, 28)),
    ])
    _add_entries(db_session, dossier, [
        {"criterion_id": "penalite_beneficies_3ans", "payload": {}},
        {"criterion_id": "publications", "item_id": "classe_b",
         "payload": {"count": 1, "author_position": 1, "date": "2025-01-15"}},  # < 2025-02-28
        {"criterion_id": "publications", "item_id": "classe_b",
         "payload": {"count": 1, "author_position": 1, "date": "2025-06-01"}},  # comptée
    ])
    breakdown, _ = compute_score(db_session, dossier, mode="declare")
    by_id = {l.criterion_id: l.points for l in breakdown.lines}
    assert by_id["penalite_beneficies_3ans"] == 1.0
    assert by_id["publications"] == 10.0


def test_compute_ranking_groupe_ecole(db_session, campaign, dossier, enseignant, admin):
    """enset u3 : group_by [] → un seul groupe (grille, population)."""
    from webapp.models import Dossier, User
    from webapp.security import hash_password

    autre = User(email="autre@test.dz", password_hash=hash_password("x"),
                 nom="Autre", prenom="E", role="enseignant")
    db_session.add(autre)
    db_session.commit()
    d2 = Dossier(campaign_id=campaign.id, user_id=autre.id,
                 candidate_ref="DC-2026-002", departement="mathematiques-informatique")
    db_session.add(d2)
    dossier.statut = "soumis"
    db_session.commit()
    d2.statut = "soumis"
    db_session.commit()

    _add_entries(db_session, dossier, [
        {"criterion_id": "rang_scientifique", "payload": {"value": "professeur"}},
    ])
    _add_entries(db_session, d2, [
        {"criterion_id": "rang_scientifique", "payload": {"value": "mca"}},
    ])

    result = compute_ranking(db_session, campaign, mode="commission")
    assert len(result.groups) == 1
    key, ranked = next(iter(result.groups.items()))
    assert key == ("u3-residences-scientifiques", "enseignant_chercheur")
    assert [r.candidate_id for r in ranked] == ["DC-2026-001", "DC-2026-002"]
    assert [r.rank for r in ranked] == [1, 2]
