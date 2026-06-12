"""Tests du référentiel des coûts, validés contre le tableau interne « Nouveau »
(docs/Montant Indemnités de stage de courte duree et de participation manif scient
à l etranger.pdf) et l'arrêté du 25/12/2011 (JORA n° 71)."""

import pytest

from classement.budget import simulate_budget
from classement.costs import candidate_cost, indemnite, load_costs, zone_of
from classement.models import RankedCandidate


@pytest.fixture(scope="module")
def costs():
    return load_costs()


# --- Tableau « Nouveau » stages (majoration enseignants ×1,2 incluse) ----------

NOUVEAU_STAGE_ZONE1 = {
    1: 14400, 5: 72000, 10: 144000, 11: 148800, 15: 168000, 20: 192000,
    29: 235200, 30: 240000, 31: 247200, 40: 312000, 45: 348000, 60: 456000,
}
NOUVEAU_STAGE_ZONE2 = {
    1: 12000, 5: 60000, 10: 120000, 11: 123600, 15: 138000, 20: 156000,
    29: 188400, 30: 192000, 31: 198000, 40: 252000, 45: 282000, 60: 372000,
}


@pytest.mark.parametrize("days,expected", sorted(NOUVEAU_STAGE_ZONE1.items()))
def test_nouveau_stage_zone1_enseignant(costs, days, expected):
    montant, _ = indemnite(costs, "perfectionnement", "zone1", days, "enseignant_chercheur")
    assert montant == pytest.approx(expected)


@pytest.mark.parametrize("days,expected", sorted(NOUVEAU_STAGE_ZONE2.items()))
def test_nouveau_stage_zone2_enseignant(costs, days, expected):
    montant, _ = indemnite(costs, "perfectionnement", "zone2", days, "enseignant_chercheur")
    assert montant == pytest.approx(expected)


# --- Tableau « Nouveau » manifestations (×1,4, sans majoration) ------------------

NOUVEAU_MANIF_ZONE1 = {1: 16800, 5: 84000, 7: 117600, 10: 168000, 11: 173600}
NOUVEAU_MANIF_ZONE2 = {1: 14000, 5: 70000, 7: 98000, 10: 140000, 11: 144200}


@pytest.mark.parametrize("days,expected", sorted(NOUVEAU_MANIF_ZONE1.items()))
def test_nouveau_manifestation_zone1(costs, days, expected):
    montant, _ = indemnite(costs, "manifestation_scientifique", "zone1", days, "enseignant_chercheur")
    assert montant == pytest.approx(expected)


@pytest.mark.parametrize("days,expected", sorted(NOUVEAU_MANIF_ZONE2.items()))
def test_nouveau_manifestation_zone2(costs, days, expected):
    montant, _ = indemnite(costs, "manifestation_scientifique", "zone2", days, "doctorant_non_salarie")
    assert montant == pytest.approx(expected)


# --- Barème de base (personnel administratif, sans majoration) -------------------


def test_bareme_base_personnel_administratif(costs):
    montant, detail = indemnite(costs, "perfectionnement", "zone1", 10, "personnel_administratif")
    assert montant == 120000  # 12 000 × 10, sans majoration
    assert "barème de base" in detail
    montant, _ = indemnite(costs, "perfectionnement", "zone2", 15, "personnel_technique")
    assert montant == 115000  # 100 000 + 3 000 × 5


def test_majoration_maitre_assistant(costs):
    montant, _ = indemnite(costs, "residence_scientifique", "zone1", 7, "maitre_assistant")
    assert montant == pytest.approx(12000 * 7 * 1.2)


# --- Zones -----------------------------------------------------------------------


def test_zones(costs):
    # Liste révisée le 11/06/2026
    assert zone_of("France", costs) == ("zone1", True)
    assert zone_of("Jordanie", costs) == ("zone1", True)
    assert zone_of("Roumanie", costs)[0] == "zone1"          # ajouté (UE)
    assert zone_of("Portugal", costs)[0] == "zone1"          # ajouté (UE)
    assert zone_of("Irlande", costs)[0] == "zone1"           # ajouté (UE)
    assert zone_of("Koweït", costs)[0] == "zone1"            # alias avec accent
    assert zone_of("USA", costs)[0] == "zone1"               # alias
    assert zone_of("Russie", costs)[0] == "zone2"            # passé en Zone II
    assert zone_of("Grande-Bretagne", costs)[0] == "zone2"   # passé en Zone II
    assert zone_of("Canada", costs)[0] == "zone2"
    assert zone_of("Qatar", costs)[0] == "zone2"
    assert zone_of("Tunisie", costs)[0] == "zone2"
    assert zone_of(None, costs) == ("zone2", False)


# --- Coût d'un dossier -------------------------------------------------------------


def _grid():
    return {"id": "u4-perfectionnement", "mobility_type": "perfectionnement"}


def test_candidate_cost_with_billet_cap(costs):
    candidate = {
        "id": "C1",
        "population": "enseignant_chercheur",
        "mobilite": {"pays": "Japon", "duree_jours": 15, "billet_estime_da": 450000,
                     "frais_divers_da": 30000},
    }
    cost = candidate_cost(candidate, _grid(), costs, plafond_billet=250000)
    assert cost["indemnite"] == pytest.approx(168000)  # tableau Nouveau ZI 15 j
    assert cost["billet_retenu"] == 250000
    assert cost["total"] == pytest.approx(168000 + 250000 + 30000)
    assert any("plafonné" in w for w in cost["warnings"])


def test_candidate_cost_missing_data_warns(costs):
    cost = candidate_cost({"id": "C2", "mobilite": {}}, _grid(), costs)
    assert cost["total"] == 0
    assert any("pays" in w for w in cost["warnings"])
    assert any("durée" in w for w in cost["warnings"])


# --- Simulation budgétaire -----------------------------------------------------------


def test_simulate_budget_cutoff_strict_by_rank(costs):
    grid = _grid()
    candidates = [
        {"id": "A", "population": "enseignant_chercheur",
         "mobilite": {"pays": "France", "duree_jours": 15, "billet_estime_da": 80000}},
        {"id": "B", "population": "enseignant_chercheur",
         "mobilite": {"pays": "Tunisie", "duree_jours": 15, "billet_estime_da": 30000}},
        {"id": "C", "population": "enseignant_chercheur",
         "mobilite": {"pays": "Tunisie", "duree_jours": 15, "billet_estime_da": 20000}},
    ]
    groups = {
        ("u4-perfectionnement", "enseignant_chercheur"): [
            RankedCandidate("A", 50, 1, False),   # coût 168 000 + 80 000 = 248 000
            RankedCandidate("B", 40, 2, False),   # coût 138 000 + 30 000 = 168 000
            RankedCandidate("C", 30, 3, False),   # coût 138 000 + 20 000 = 158 000
        ]
    }
    simulation = simulate_budget(candidates, groups, grid, costs, budget=420000)
    statuts = {l["candidate_id"]: l["statut"] for l in simulation["lignes"]}
    # A (248k) financé, B (168k) financé → reste 4 000 ; C non finançable,
    # même si un dossier moins cher existait : le rang prime, coupure stricte.
    assert statuts == {"A": "financé", "B": "financé", "C": "non finançable"}
    assert simulation["reste"] == pytest.approx(420000 - 248000 - 168000)
    assert simulation["totaux"]["demande"] == pytest.approx(248000 + 168000 + 158000)
    assert not simulation["tous_financables"]


def test_simulate_exercice_chains_campaigns_by_priority(costs):
    from classement.budget import simulate_exercice

    # campagne 1 (prioritaire) : 2 dossiers perfectionnement peu coûteux ;
    # campagne 2 : 3 résidences — le reliquat détermine combien passent.
    perfectionnement = {
        "grid": {"id": "u4-perfectionnement", "mobility_type": "perfectionnement"},
        "candidates": [
            {"id": "P1", "population": "doctorant_non_salarie",
             "mobilite": {"pays": "Tunisie", "duree_jours": 15, "billet_estime_da": 30000}},
            {"id": "P2", "population": "doctorant_non_salarie",
             "mobilite": {"pays": "Tunisie", "duree_jours": 15, "billet_estime_da": 30000}},
        ],
        "groups": {("u4", "doctorant_non_salarie"): [
            RankedCandidate("P1", 30, 1, False),   # 115 000 + 30 000 = 145 000
            RankedCandidate("P2", 20, 2, False),   # 145 000
        ]},
    }
    residences = {
        "grid": {"id": "u3-residences-scientifiques", "mobility_type": "residence_scientifique"},
        "candidates": [
            {"id": f"R{i}", "population": "enseignant_chercheur",
             "mobilite": {"pays": "France", "duree_jours": 7, "billet_estime_da": 70000}}
            for i in (1, 2, 3)
        ],
        "groups": {("u3", "enseignant_chercheur"): [
            RankedCandidate("R1", 60, 1, False),   # 12 000×7×1,2 + 70 000 = 170 800
            RankedCandidate("R2", 50, 2, False),
            RankedCandidate("R3", 40, 3, False),
        ]},
    }
    exercice = simulate_exercice([perfectionnement, residences], budget=650000, costs=costs)

    # Priorité respectée : tout le perfectionnement financé (290 000),
    # reliquat 360 000 → 2 résidences sur 3 (2 × 170 800 = 341 600).
    assert exercice["campagnes"][0]["tous_financables"]
    statuts = {l["candidate_id"]: l["statut"] for l in exercice["campagnes"][1]["lignes"]}
    assert statuts == {"R1": "financé", "R2": "financé", "R3": "non finançable"}
    assert exercice["reste"] == pytest.approx(650000 - 290000 - 2 * 170800)
    parts = {p["grid_id"]: p for p in exercice["repartition_proposee"]}
    assert parts["u4-perfectionnement"]["dossiers_finances"] == 2
    assert parts["u3-residences-scientifiques"]["dossiers_finances"] == 2


def test_simulate_budget_all_funded(costs):
    grid = _grid()
    candidates = [{"id": "A", "population": "personnel_administratif",
                   "mobilite": {"pays": "Tunisie", "duree_jours": 10,
                                "billet_estime_da": 40000, "frais_divers_da": 10000}}]
    groups = {("g", "personnel_administratif"): [RankedCandidate("A", 20, 1, False)]}
    simulation = simulate_budget(candidates, groups, grid, costs, budget=1_000_000)
    assert simulation["tous_financables"]
    # PAT : barème de base ZII 10 j = 100 000
    assert simulation["lignes"][0]["indemnite"] == pytest.approx(100000)
    assert simulation["lignes"][0]["total"] == pytest.approx(150000)
