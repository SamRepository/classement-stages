"""Spécification de formulaire dérivée de la grille (build_form_spec)."""

from classement.grids import find_grid
from webapp.forms.grid_form import build_form_spec


def _section(grid_id: str, criterion_id: str) -> dict:
    spec = next(
        s for s in build_form_spec(find_grid(grid_id)) if s["criterion_id"] == criterion_id
    )
    return spec


def test_doi_url_seulement_publications_communications():
    """DOI/URL (has_reference) sur les critères à référence recommandée seulement."""
    grid = "u3-residences-scientifiques"
    assert _section(grid, "publications")["has_reference"] is True
    assert _section(grid, "communications")["has_reference"] is True
    # Critères sans référence bibliographique : pas de DOI/URL.
    assert _section(grid, "projet_international")["has_reference"] is False
    assert _section(grid, "encadrement_doctoral")["has_reference"] is False
    assert _section(grid, "cours_tronc_commun")["has_reference"] is False


def test_prix_et_encadrement_multi_lignes():
    """Prix et encadrement projet labellisé : saisie multi-lignes (count_detail)."""
    grid = "u3-residences-scientifiques"
    assert _section(grid, "prix_distinctions")["widget"] == "count_detail"
    assert _section(grid, "encadrement_projet_labelise")["widget"] == "count_detail"


def test_elearning_url_moodle():
    """Cours en ligne : champ URL dédié (Moodle), sans DOI."""
    s = _section("u3-residences-scientifiques", "elearning")
    assert s["url_label"] == "Lien du cours (Moodle)"
    assert s["has_reference"] is False
