"""Tests du moteur de scoring contre les grilles réelles de data/grids."""

from datetime import date

import pytest

from classement.engine import score_candidate
from classement.grids import find_grid, load_shared_rules

CAMPAIGN = date(2026, 6, 30)


@pytest.fixture(scope="module")
def shared():
    return load_shared_rules()


@pytest.fixture(scope="module")
def u1():
    return find_grid("u1-manifestations-internationales")


@pytest.fixture(scope="module")
def u2():
    return find_grid("u2-personnel-administratif")


@pytest.fixture(scope="module")
def rc5():
    return find_grid("rc5-chercheurs-residences-manifestations")


@pytest.fixture(scope="module")
def rc6():
    return find_grid("rc6-chercheurs-stages")


def _line(breakdown, criterion_id):
    return next(l for l in breakdown.lines if l.criterion_id == criterion_id)


def test_enum_rank(u1, shared):
    candidate = {"id": "X", "entries": {"rang_scientifique": {"value": "professeur"}}}
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    assert _line(b, "rang_scientifique").points == 7


def test_enum_habilitation_bonus_once():
    grid = find_grid("u3-residences-scientifiques")
    candidate = {
        "id": "X",
        "entries": {"rang_scientifique": {"value": "mcb", "option_bonus": True}},
    }
    b = score_candidate(grid, candidate, campaign_date=CAMPAIGN)
    assert _line(b, "rang_scientifique").points == 7  # 3 + 4


def test_author_position_weighting(u1, shared):
    candidate = {
        "id": "X",
        "entries": {
            "publications": {
                "items": [
                    {"item": "classe_a_plus", "count": 1, "author_position": 2, "date": "2025-01-01"}
                ]
            }
        },
    }
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    assert _line(b, "publications").points == pytest.approx(18.0)  # 20 × 0.9


def test_author_position_5_plus(u1, shared):
    candidate = {
        "id": "X",
        "entries": {
            "publications": {
                "items": [
                    {"item": "classe_a", "count": 1, "author_position": 7, "date": "2025-01-01"}
                ]
            }
        },
    }
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    assert _line(b, "publications").points == pytest.approx(7.5)  # 15 × 0.5


def test_item_cap_units(u1, shared):
    candidate = {
        "id": "X",
        "entries": {
            "publications": {
                "items": [
                    {"item": "classe_c", "count": 4, "author_position": 1, "date": "2025-01-01"}
                ]
            }
        },
    }
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    assert _line(b, "publications").points == 10  # 5 × 2 max


def test_item_cap_points_reviewing(u1, shared):
    candidate = {
        "id": "X",
        "entries": {"expertise_reviewing": {"items": [{"item": "revue_a", "count": 6}]}},
    }
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    assert _line(b, "expertise_reviewing").points == 16  # 24 plafonné à 16


def test_window_after_last_benefit_filters_old_works(u1, shared):
    candidate = {
        "id": "X",
        "benefits": [{"date": "2024-09-15", "platform_close_date": "2024-04-30"}],
        "entries": {
            "publications": {
                "items": [
                    {"item": "classe_a", "count": 1, "author_position": 1, "date": "2024-01-15"},
                    {"item": "classe_a", "count": 1, "author_position": 1, "date": "2025-01-15"},
                ]
            }
        },
    }
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    line = _line(b, "publications")
    assert line.points == 15  # seule la publication de 2025 compte
    assert any("ignoré" in w for w in line.warnings)


def test_window_reference_mobilite_ignores_close_date(u1, shared):
    # Décision commission : repère = date de mobilité (clôture saisie ignorée).
    # La publication du 2024-06-15 est entre la clôture (2024-04-30) et la
    # mobilité (2024-09-15) : comptée avec le repère "cloture", écartée avec "mobilite".
    candidate = {
        "id": "X",
        "benefits": [{"date": "2024-09-15", "platform_close_date": "2024-04-30"}],
        "entries": {
            "publications": {
                "items": [
                    {"item": "classe_a", "count": 1, "author_position": 1, "date": "2024-06-15"},
                ]
            }
        },
    }
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    assert _line(b, "publications").points == 15
    b = score_candidate(u1, candidate, shared, CAMPAIGN, window_reference="mobilite")
    assert _line(b, "publications").points == 0


def test_formula_3_minus_n_from_benefits(u1, shared):
    candidate = {
        "id": "X",
        "benefits": [
            {"date": "2024-09-15"},
            {"date": "2025-06-15"},
            {"date": "2019-01-01"},  # hors fenêtre
        ],
        "entries": {"penalite_beneficies_3ans": {}},
    }
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    assert _line(b, "penalite_beneficies_3ans").points == 1  # 3 - 2


def test_formula_minus_5_per_stage(u2, shared):
    candidate = {
        "id": "X",
        "benefits": [{"date": "2023-05-02"}, {"date": "2021-03-10"}],
        "entries": {"penalite_stages_6ans": {}},
    }
    b = score_candidate(u2, candidate, shared, CAMPAIGN)
    assert _line(b, "penalite_stages_6ans").points == -10  # -5 × 2


def test_formula_rc6_requires_explicit_n_and_caps(rc6, shared):
    candidate = {"id": "X", "entries": {"penalite_stages_recents": {"n": 0, "N": 4}}}
    b = score_candidate(rc6, candidate, shared, CAMPAIGN)
    assert _line(b, "penalite_stages_recents").points == 3  # 4-0 plafonné à N-1 = 3

    candidate = {"id": "X", "entries": {"penalite_stages_recents": {"n": 2, "N": 5}}}
    b = score_candidate(rc6, candidate, shared, CAMPAIGN)
    assert _line(b, "penalite_stages_recents").points == 3  # 5-2


def test_shared_cap_keeps_best_units(rc5, shared):
    candidate = {
        "id": "X",
        "entries": {
            "communications": {
                "items": [
                    {"item": "intl_orale", "count": 3, "date": "2025-01-01"},
                    {"item": "intl_poster", "count": 3, "date": "2025-01-01"},
                ]
            }
        },
    }
    b = score_candidate(rc5, candidate, shared, CAMPAIGN)
    # 6 unités pour un plafond partagé de 4 : on garde 3 orales (4) + 1 poster (2) = 14
    assert _line(b, "communications").points == 14


def test_block_cap_points_70(rc5, shared):
    candidate = {
        "id": "X",
        "entries": {
            "publications_internationales": {
                "items": [
                    {"item": "wos_if", "count": 8, "author_position": 1, "date": "2025-01-01"}
                ]
            }
        },
    }
    b = score_candidate(rc5, candidate, shared, CAMPAIGN)
    assert _line(b, "publications_internationales").points == 70  # 96 plafonnés


def test_count_item_leader_bonus(rc5, shared):
    candidate = {
        "id": "X",
        "entries": {
            "projets": {
                "items": [
                    {
                        "item": "projet_national_prfu_pnr",
                        "count": 2,
                        "leader_count": 1,
                        "date": "2025-01-01",
                    }
                ]
            }
        },
    }
    b = score_candidate(rc5, candidate, shared, CAMPAIGN)
    assert _line(b, "projets").points == 5  # 2×2 + 1 (porteur)


def test_manual_scores_clamped(u2, shared):
    candidate = {
        "id": "X",
        "entries": {
            "evaluation_superieur": {
                "scores": {"assiduite": 5, "competence": 2, "initiative": 1, "disponibilite": 0}
            }
        },
    }
    b = score_candidate(u2, candidate, shared, CAMPAIGN)
    assert _line(b, "evaluation_superieur").points == 6  # 3 (plafonné) + 2 + 1 + 0


def test_capped_criterion(u2, shared):
    candidate = {"id": "X", "entries": {"projets_internationaux": {"points": 9}}}
    b = score_candidate(u2, candidate, shared, CAMPAIGN)
    assert _line(b, "projets_internationaux").points == 2


def test_fixed_with_bonuses(u1, shared):
    candidate = {
        "id": "X",
        "entries": {"polycopie_pedagogique": {"applies": True, "bonuses": [0, 1]}},
    }
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    assert _line(b, "polycopie_pedagogique").points == 7  # 3 + 2 + 2


def test_unknown_entry_warns(u1, shared):
    candidate = {"id": "X", "entries": {"critere_inexistant": {"applies": True}}}
    b = score_candidate(u1, candidate, shared, CAMPAIGN)
    assert any("critere_inexistant" in w for w in b.warnings)


def test_population_out_of_scope_warns(u2, shared):
    candidate = {"id": "X", "population": "enseignant_chercheur", "entries": {}}
    b = score_candidate(u2, candidate, shared, CAMPAIGN)
    assert any("hors du champ" in w for w in b.warnings)
