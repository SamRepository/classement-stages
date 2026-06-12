"""Tests des profils d'établissement (ENSET-Skikda comme cas concret)."""

import pytest

from classement.engine import score_candidate
from classement.grids import find_grid, load_shared_rules
from classement.institutions import (
    allocate_places,
    group_by_for,
    load_institution,
    validate_candidate,
)
from classement.ranking import rank_candidates


@pytest.fixture(scope="module")
def enset():
    return load_institution("enset-skikda")


@pytest.fixture(scope="module")
def u4():
    return find_grid("u4-perfectionnement")


def test_load_profile(enset):
    assert enset["id"] == "enset-skikda"
    assert enset["institution_type"] == "universite"
    assert {d["id"] for d in enset["departements"]} == {
        "technologie",
        "mathematiques-informatique",
        "physique-chimie",
        "sciences-naturelles",
    }


def test_validate_unknown_department(enset, u4):
    candidate = {
        "id": "X",
        "population": "doctorant_non_salarie",
        "grouping": {"departement": "genie-civil"},
    }
    warnings = validate_candidate(enset, candidate, u4)
    assert any("genie-civil" in w for w in warnings)


def test_validate_population_not_in_grid_for_institution(enset):
    u2 = find_grid("u2-personnel-administratif")
    candidate = {"id": "X", "population": "doctorant_non_salarie", "grouping": {}}
    warnings = validate_candidate(enset, candidate, u2)
    assert any("hors du champ" in w for w in warnings)


def test_validate_research_center_grid_flagged(enset):
    rc6 = find_grid("rc6-chercheurs-stages")
    candidate = {"id": "X", "population": "enseignant_chercheur", "grouping": {}}
    warnings = validate_candidate(enset, candidate, rc6)
    assert any("n'est pas applicable" in w for w in warnings)


def test_validate_ok_candidate_has_no_warnings(enset, u4):
    candidate = {
        "id": "X",
        "population": "doctorant_non_salarie",
        "grouping": {"departement": "technologie"},
    }
    assert validate_candidate(enset, candidate, u4) == []


def test_group_by_enset_school_wide_for_everyone(enset):
    # Choix de la commission ENSET : classement à l'échelle de l'école pour toutes
    # les populations, doctorants et maîtres assistants compris.
    assert group_by_for(enset, "u4-perfectionnement", "doctorant_non_salarie") == []
    assert group_by_for(enset, "u4-perfectionnement", "maitre_assistant") == []
    assert group_by_for(enset, "u1-manifestations-internationales", "enseignant_chercheur") == []


def test_group_by_rules_first_match_mechanism():
    # Le mécanisme reste paramétrable : un profil peut classer une population
    # au département (variante conforme à la note de l'annexe u4).
    profile = {
        "id": "test",
        "ranking_rules": [
            {
                "grid": "u4-perfectionnement",
                "population": "doctorant_non_salarie",
                "group_by": ["departement"],
            },
            {"group_by": []},
        ],
    }
    assert group_by_for(profile, "u4-perfectionnement", "doctorant_non_salarie") == ["departement"]
    assert group_by_for(profile, "u4-perfectionnement", "maitre_assistant") == []
    assert group_by_for(profile, "u1-manifestations-internationales", "doctorant_non_salarie") == []


def test_allocate_places_art5(enset):
    allocation = allocate_places(40, enset)
    assert sum(allocation.values()) == 40
    assert allocation["perfectionnement_enseignants_chercheurs_doctorants"] == 32
    assert allocation["perfectionnement_personnel_administratif_technique"] == 4
    assert allocation["residences_et_manifestations"] == 4


def test_allocate_places_rounding(enset):
    allocation = allocate_places(7, enset)
    assert sum(allocation.values()) == 7


def test_end_to_end_enset_doctorants_ranked_school_wide(enset, u4):
    shared = load_shared_rules()
    candidates = [
        {
            "id": "D1",
            "population": "doctorant_non_salarie",
            "grouping": {"departement": "technologie"},
            "entries": {"inscription_doctorat": {"items": [{"item": "inscription", "count": 3}]}},
        },
        {
            "id": "D2",
            "population": "doctorant_non_salarie",
            "grouping": {"departement": "technologie"},
            "entries": {"inscription_doctorat": {"items": [{"item": "inscription", "count": 2}]}},
        },
        {
            "id": "D3",
            "population": "doctorant_non_salarie",
            "grouping": {"departement": "mathematiques-informatique"},
            "entries": {"inscription_doctorat": {"items": [{"item": "inscription", "count": 1}]}},
        },
        {
            "id": "MA1",
            "population": "maitre_assistant",
            "grouping": {"departement": "physique-chimie"},
            "entries": {"polycopie_pedagogique": {"applies": True}},
        },
    ]
    breakdowns = [score_candidate(u4, c, shared, "2026-06-30") for c in candidates]
    resolver = lambda c: group_by_for(enset, u4["id"], c.get("population"))  # noqa: E731
    groups = rank_candidates(candidates, breakdowns, group_by=resolver)

    # Tous les doctorants dans un seul groupe école (départements confondus) ;
    # les maîtres assistants restent classés à part (population distincte).
    keys = set(groups)
    assert ("u4-perfectionnement", "doctorant_non_salarie") in keys
    assert ("u4-perfectionnement", "maitre_assistant") in keys
    assert len(keys) == 2

    doctorants = groups[("u4-perfectionnement", "doctorant_non_salarie")]
    assert [r.candidate_id for r in doctorants] == ["D1", "D2", "D3"]


def test_end_to_end_department_variant_with_custom_profile(u4):
    # La variante département (note de l'annexe u4) reste disponible par simple
    # changement de ranking_rules, sans toucher au code.
    profile = {
        "id": "variante",
        "ranking_rules": [
            {
                "grid": "u4-perfectionnement",
                "population": "doctorant_non_salarie",
                "group_by": ["departement"],
            },
            {"group_by": []},
        ],
    }
    shared = load_shared_rules()
    candidates = [
        {
            "id": "D1",
            "population": "doctorant_non_salarie",
            "grouping": {"departement": "technologie"},
            "entries": {"inscription_doctorat": {"items": [{"item": "inscription", "count": 3}]}},
        },
        {
            "id": "D3",
            "population": "doctorant_non_salarie",
            "grouping": {"departement": "mathematiques-informatique"},
            "entries": {"inscription_doctorat": {"items": [{"item": "inscription", "count": 1}]}},
        },
    ]
    breakdowns = [score_candidate(u4, c, shared, "2026-06-30") for c in candidates]
    resolver = lambda c: group_by_for(profile, u4["id"], c.get("population"))  # noqa: E731
    groups = rank_candidates(candidates, breakdowns, group_by=resolver)
    keys = set(groups)
    assert ("u4-perfectionnement", "doctorant_non_salarie", "technologie") in keys
    assert ("u4-perfectionnement", "doctorant_non_salarie", "mathematiques-informatique") in keys
