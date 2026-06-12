"""Tests du classement par groupe et de la gestion des ex aequo."""

from classement.models import ScoreBreakdown
from classement.ranking import rank_candidates


def _breakdown(candidate_id, total, grid_id="u1", population="enseignant_chercheur"):
    return ScoreBreakdown(
        candidate_id=candidate_id,
        grid_id=grid_id,
        population=population,
        lines=[],
        total=total,
    )


def test_ranking_orders_by_total_desc():
    candidates = [
        {"id": "A", "population": "enseignant_chercheur"},
        {"id": "B", "population": "enseignant_chercheur"},
        {"id": "C", "population": "enseignant_chercheur"},
    ]
    breakdowns = [_breakdown("A", 10), _breakdown("B", 30), _breakdown("C", 20)]
    groups = rank_candidates(candidates, breakdowns)
    ranked = next(iter(groups.values()))
    assert [r.candidate_id for r in ranked] == ["B", "C", "A"]
    assert [r.rank for r in ranked] == [1, 2, 3]


def test_ranking_competition_style_ties():
    candidates = [{"id": i, "population": "p"} for i in ("A", "B", "C", "D")]
    breakdowns = [
        _breakdown("A", 30, population="p"),
        _breakdown("B", 30, population="p"),
        _breakdown("C", 20, population="p"),
        _breakdown("D", 10, population="p"),
    ]
    groups = rank_candidates(candidates, breakdowns)
    ranked = next(iter(groups.values()))
    assert [r.rank for r in ranked] == [1, 1, 3, 4]
    assert [r.ex_aequo for r in ranked] == [True, True, False, False]


def test_ranking_separates_populations():
    candidates = [
        {"id": "A", "population": "enseignant_chercheur"},
        {"id": "B", "population": "doctorant_non_salarie"},
    ]
    breakdowns = [
        _breakdown("A", 10),
        _breakdown("B", 50, population="doctorant_non_salarie"),
    ]
    groups = rank_candidates(candidates, breakdowns)
    assert len(groups) == 2
    for ranked in groups.values():
        assert ranked[0].rank == 1


def test_ranking_group_by_department():
    candidates = [
        {"id": "A", "population": "doctorant_non_salarie", "grouping": {"departement": "Info"}},
        {"id": "B", "population": "doctorant_non_salarie", "grouping": {"departement": "Info"}},
        {"id": "C", "population": "doctorant_non_salarie", "grouping": {"departement": "Math"}},
    ]
    breakdowns = [
        _breakdown("A", 10, population="doctorant_non_salarie"),
        _breakdown("B", 20, population="doctorant_non_salarie"),
        _breakdown("C", 5, population="doctorant_non_salarie"),
    ]
    groups = rank_candidates(candidates, breakdowns, group_by=["departement"])
    assert len(groups) == 2
    info = next(g for key, g in groups.items() if "Info" in key)
    math = next(g for key, g in groups.items() if "Math" in key)
    assert [r.candidate_id for r in info] == ["B", "A"]
    assert math[0].rank == 1  # seul dans son groupe
