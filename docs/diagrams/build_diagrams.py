"""Génère les diagrammes Excalidraw de présentation du projet.

Sortie : deux fichiers .excalidraw dans ce dossier, ouvrables sur
https://excalidraw.com ou rendus en PNG via le skill excalidraw-diagram :

    python docs/diagrams/build_diagrams.py

Les couleurs suivent .claude/skills/excalidraw-diagram/references/color-palette.md.
Modifier ce script puis le relancer pour régénérer les diagrammes.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

# --- Palette (cf. color-palette.md) -----------------------------------------
PRIMARY = ("#3b82f6", "#1e3a5f")
SECONDARY = ("#60a5fa", "#1e3a5f")
TERTIARY = ("#93c5fd", "#1e3a5f")
START = ("#fed7aa", "#c2410c")
SUCCESS = ("#a7f3d0", "#047857")
DECISION = ("#fef3c7", "#b45309")
AI = ("#ddd6fe", "#6d28d9")

TITLE = "#1e40af"
SUBTITLE = "#3b82f6"
BODY = "#64748b"
ON_LIGHT = "#374151"
CODE_BG = "#1e293b"
CODE_GREEN = "#22c55e"

FONT_SANS = 2  # Helvetica
FONT_CODE = 3  # monospace


class Diagram:
    def __init__(self) -> None:
        self.elements: list[dict] = []
        self._seed = itertools.count(1000)
        self._id = itertools.count(1)

    def nid(self) -> str:
        return f"el{next(self._id)}"

    def _seedv(self) -> int:
        return next(self._seed)

    def text(self, x, y, s, *, color=BODY, size=16, w=None, align="left",
             font=FONT_SANS):
        lines = s.split("\n")
        h = int(len(lines) * size * 1.25)
        if w is None:
            w = int(max(len(ln) for ln in lines) * size * 0.6)
        eid = self.nid()
        self.elements.append({
            "type": "text", "id": eid, "x": x, "y": y, "width": w, "height": h,
            "text": s, "originalText": s, "fontSize": size, "fontFamily": font,
            "textAlign": align, "verticalAlign": "top", "strokeColor": color,
            "backgroundColor": "transparent", "fillStyle": "solid",
            "strokeWidth": 1, "strokeStyle": "solid", "roughness": 0,
            "opacity": 100, "angle": 0, "seed": self._seedv(), "version": 1,
            "versionNonce": self._seedv(), "isDeleted": False, "groupIds": [],
            "boundElements": None, "link": None, "locked": False,
            "containerId": None, "lineHeight": 1.25,
        })
        return eid

    def box(self, x, y, w, h, palette, label, *, sublabel=None, size=18,
            text_color=ON_LIGHT, dashed=False, font=FONT_SANS):
        fill, stroke = palette
        bid = self.nid()
        tid = self.nid()
        self.elements.append({
            "type": "rectangle", "id": bid, "x": x, "y": y, "width": w,
            "height": h, "strokeColor": stroke, "backgroundColor": fill,
            "fillStyle": "solid", "strokeWidth": 2,
            "strokeStyle": "dashed" if dashed else "solid", "roughness": 0,
            "opacity": 100, "angle": 0, "seed": self._seedv(), "version": 1,
            "versionNonce": self._seedv(), "isDeleted": False, "groupIds": [],
            "boundElements": [{"id": tid, "type": "text"}], "link": None,
            "locked": False, "roundness": {"type": 3},
        })
        full = label if sublabel is None else f"{label}\n{sublabel}"
        self.elements.append({
            "type": "text", "id": tid, "x": x + 8, "y": y + h / 2 - size,
            "width": w - 16, "height": int(size * 1.25 * (full.count(chr(10)) + 1)),
            "text": full, "originalText": full, "fontSize": size,
            "fontFamily": font, "textAlign": "center", "verticalAlign": "middle",
            "strokeColor": text_color, "backgroundColor": "transparent",
            "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid",
            "roughness": 0, "opacity": 100, "angle": 0, "seed": self._seedv(),
            "version": 1, "versionNonce": self._seedv(), "isDeleted": False,
            "groupIds": [], "boundElements": None, "link": None,
            "locked": False, "containerId": bid, "lineHeight": 1.25,
        })
        return bid

    def diamond(self, x, y, w, h, palette, label, *, size=16,
                text_color="#7c2d12"):
        fill, stroke = palette
        bid = self.nid()
        tid = self.nid()
        self.elements.append({
            "type": "diamond", "id": bid, "x": x, "y": y, "width": w,
            "height": h, "strokeColor": stroke, "backgroundColor": fill,
            "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid",
            "roughness": 0, "opacity": 100, "angle": 0, "seed": self._seedv(),
            "version": 1, "versionNonce": self._seedv(), "isDeleted": False,
            "groupIds": [], "boundElements": [{"id": tid, "type": "text"}],
            "link": None, "locked": False,
        })
        self.elements.append({
            "type": "text", "id": tid, "x": x + w * 0.2, "y": y + h / 2 - size,
            "width": w * 0.6,
            "height": int(size * 1.25 * (label.count(chr(10)) + 1)),
            "text": label, "originalText": label, "fontSize": size,
            "fontFamily": FONT_SANS, "textAlign": "center",
            "verticalAlign": "middle", "strokeColor": text_color,
            "backgroundColor": "transparent", "fillStyle": "solid",
            "strokeWidth": 1, "strokeStyle": "solid", "roughness": 0,
            "opacity": 100, "angle": 0, "seed": self._seedv(), "version": 1,
            "versionNonce": self._seedv(), "isDeleted": False, "groupIds": [],
            "boundElements": None, "link": None, "locked": False,
            "containerId": bid, "lineHeight": 1.25,
        })
        return bid

    def code(self, x, y, w, h, s):
        """Artefact de preuve : extrait de code/JSON sur fond sombre."""
        bid = self.nid()
        tid = self.nid()
        self.elements.append({
            "type": "rectangle", "id": bid, "x": x, "y": y, "width": w,
            "height": h, "strokeColor": "#0f172a", "backgroundColor": CODE_BG,
            "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid",
            "roughness": 0, "opacity": 100, "angle": 0, "seed": self._seedv(),
            "version": 1, "versionNonce": self._seedv(), "isDeleted": False,
            "groupIds": [], "boundElements": [{"id": tid, "type": "text"}],
            "link": None, "locked": False, "roundness": {"type": 3},
        })
        self.elements.append({
            "type": "text", "id": tid, "x": x + 12, "y": y + 10,
            "width": w - 24, "height": h - 20, "text": s, "originalText": s,
            "fontSize": 13, "fontFamily": FONT_CODE, "textAlign": "left",
            "verticalAlign": "middle", "strokeColor": CODE_GREEN,
            "backgroundColor": "transparent", "fillStyle": "solid",
            "strokeWidth": 1, "strokeStyle": "solid", "roughness": 0,
            "opacity": 100, "angle": 0, "seed": self._seedv(), "version": 1,
            "versionNonce": self._seedv(), "isDeleted": False, "groupIds": [],
            "boundElements": None, "link": None, "locked": False,
            "containerId": bid, "lineHeight": 1.4,
        })
        return bid

    def arrow(self, x1, y1, x2, y2, *, color=BODY, start=None, end=None,
              dashed=False):
        eid = self.nid()
        el = {
            "type": "arrow", "id": eid, "x": x1, "y": y1,
            "width": x2 - x1, "height": y2 - y1, "strokeColor": color,
            "backgroundColor": "transparent", "fillStyle": "solid",
            "strokeWidth": 2, "strokeStyle": "dashed" if dashed else "solid",
            "roughness": 0, "opacity": 100, "angle": 0, "seed": self._seedv(),
            "version": 1, "versionNonce": self._seedv(), "isDeleted": False,
            "groupIds": [], "boundElements": None, "link": None,
            "locked": False, "points": [[0, 0], [x2 - x1, y2 - y1]],
            "startArrowhead": None, "endArrowhead": "arrow",
        }
        if start:
            el["startBinding"] = {"elementId": start, "focus": 0, "gap": 4}
        if end:
            el["endBinding"] = {"elementId": end, "focus": 0, "gap": 4}
        self.elements.append(el)
        return eid

    def dump(self, path: Path) -> None:
        doc = {
            "type": "excalidraw", "version": 2, "source": "classement-stages",
            "elements": self.elements,
            "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
            "files": {},
        }
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(path)


# === Diagramme 1 : Architecture ============================================
def architecture(out: Path) -> None:
    d = Diagram()
    d.text(40, 24, "Moteur de classement — architecture pilotée par les données",
           color=TITLE, size=28)
    d.text(40, 66, "Arrêté MESRS n° 345 du 09/03/2026  ·  ENSET-Skikda  ·  "
                   "conçu multi-établissements", color=BODY, size=16)

    # En-têtes de colonnes
    d.text(60, 150, "ENTRÉES", color=SUBTITLE, size=18)
    d.text(600, 150, "MOTEUR", color=SUBTITLE, size=18)
    d.text(1010, 150, "CLASSEMENT", color=SUBTITLE, size=18)
    d.text(1430, 150, "SORTIES", color=SUBTITLE, size=18)

    # Entrées (fan-in)
    g = d.box(40, 200, 280, 80, TERTIARY, "Grilles JSON",
              sublabel="9 grilles · u1–u4, rc5–rc9")
    p = d.box(40, 320, 280, 80, TERTIARY, "Profil établissement",
              sublabel="départements · populations · quotas")
    c = d.box(40, 440, 280, 80, START, "Dossiers candidats",
              sublabel="JSON  ou  Excel (.xlsx)")

    # Moteur
    eng = d.box(560, 250, 340, 170, PRIMARY,
                "engine.score_candidate()",
                sublabel="6 types de critères\nplafonds · fenêtres · formules\n"
                         "→ ScoreBreakdown",
                text_color="#ffffff", size=18)

    # Classement
    rk = d.box(990, 270, 320, 130, SECONDARY,
               "ranking.rank_candidates()",
               sublabel="groupes (grille, population)\nrang compétition 1, 2, 2, 4",
               text_color="#ffffff", size=18)

    # Sorties (fan-out)
    o1 = d.box(1380, 200, 280, 80, SUCCESS, "PV de classement", sublabel=".xlsx")
    o2 = d.box(1380, 320, 280, 80, SUCCESS, "Fiches d'évaluation",
               sublabel=".xlsx")
    o3 = d.box(1380, 440, 280, 80, SUCCESS, "Document HTML",
               sublabel="imprimable → PDF")

    # Flèches
    for src in (g, p, c):
        d.arrow(320, {g: 240, p: 360, c: 480}[src], 560, 335,
                color=PRIMARY[1], start=src, end=eng)
    d.arrow(900, 335, 990, 335, color=PRIMARY[1], start=eng, end=rk)
    for dst in (o1, o2, o3):
        d.arrow(1310, 335, 1380, {o1: 240, o2: 360, o3: 480}[dst],
                color=SECONDARY[1], start=rk, end=dst)

    # Bannière « principe clé »
    d.box(40, 600, 1620, 90, DECISION,
          "Principe clé — les barèmes ne sont JAMAIS codés en dur en Python.",
          sublabel="data/grids/*.json est la source de vérité ; faire évoluer un "
                   "barème = éditer le JSON, pas le moteur.",
          text_color="#7c2d12", size=18)

    # Artefact de preuve : extrait de grille
    d.code(560, 460, 340, 110,
           '// extrait data/grids/u3.json\n'
           '{ "type": "count",\n'
           '  "id": "publications",\n'
           '  "points": 6, "cap_units": 6 }')

    d.dump(out)


# === Diagramme 2 : Notation d'un dossier ===================================
def scoring(out: Path) -> None:
    d = Diagram()
    d.text(40, 24, "Notation d'un dossier candidat",
           color=TITLE, size=28)
    d.text(40, 66, "engine.score_candidate() — du dossier au rang, en toute "
                   "traçabilité", color=BODY, size=16)

    dossier = d.box(40, 360, 220, 100, START, "Dossier candidat",
                    sublabel="activités datées\n+ bénéfices", size=18)

    # 6 types de critères (fan-out)
    crit = [
        ("enum", "choix barémé (ex. rang du diplôme)"),
        ("count", "quantité × points (publications…)"),
        ("fixed", "points forfaitaires"),
        ("capped", "plafonné (cap_points)"),
        ("manual_scores", "notes saisies par la commission"),
        ("formula", "calcul (ex. pénalité 3−n)"),
    ]
    ys = list(range(150, 150 + 90 * len(crit), 90))
    boxes = []
    for (name, gloss), y in zip(crit, ys):
        b = d.box(360, y, 360, 70, TERTIARY, name, sublabel=gloss, size=16)
        boxes.append((b, y))
        d.arrow(260, 410, 360, y + 35, color=START[1], start=dossier, end=b)

    # Plafonds & fenêtres (fan-in)
    plaf = d.box(800, 330, 250, 150, DECISION, "Plafonds & fenêtres",
                 sublabel="cap_units · shared_caps\nblock_caps\nafter_last_benefit",
                 text_color="#7c2d12", size=17)
    for b, y in boxes:
        d.arrow(720, y + 35, 800, 405, color=DECISION[1], start=b, end=plaf)

    # ScoreBreakdown
    sb = d.box(1130, 335, 270, 140, PRIMARY, "ScoreBreakdown",
               sublabel="lignes + détails\n+ warnings", text_color="#ffffff",
               size=18)
    d.arrow(1050, 405, 1130, 405, color=PRIMARY[1], start=plaf, end=sb)

    # Classement
    rang = d.box(1480, 350, 250, 110, SUCCESS, "Classement",
                 sublabel="rang compétition 1, 2, 2, 4\n(pas de départage)",
                 size=17)
    d.arrow(1400, 405, 1480, 405, color=PRIMARY[1], start=sb, end=rang)

    # Note de traçabilité
    d.text(1130, 500, "Les warnings tracent les rejets motivés pour la\n"
                      "commission (art. 14–15) — jamais supprimés.",
           color=BODY, size=14)

    d.dump(out)


# === Diagramme 3 : Circuit Excel ===========================================
def circuit_excel(out: Path) -> None:
    d = Diagram()
    d.text(40, 24, "Circuit Excel — un seul plan de colonnes, deux sens",
           color=TITLE, size=28)
    d.text(40, 66, "classement/excel_io.py — la génération du modèle et l'import "
                   "partagent la même source de vérité", color=BODY, size=16)

    # --- Boucle du haut : génération <-> import ---------------------------
    grille = d.box(40, 240, 220, 90, TERTIARY, "Grille JSON",
                   sublabel="data/grids/*.json")
    cp = d.box(330, 215, 300, 140, AI, "column_plan(grid)",
               sublabel="plan de colonnes\nSOURCE DE VÉRITÉ UNIQUE",
               text_color="#4c1d95", size=18)
    wt = d.box(720, 150, 250, 80, PRIMARY, "write_template()",
               sublabel="génère le modèle", text_color="#ffffff", size=17)
    rc = d.box(720, 350, 250, 80, SECONDARY, "read_candidates()",
               sublabel="relit le classeur rempli", text_color="#ffffff",
               size=17)
    wb = d.box(1080, 195, 300, 200, START, "Classeur .xlsx",
               sublabel="Candidats · Activites\nHistorique\nListes · Referentiel",
               size=18)
    op = d.box(1110, 50, 240, 80, DECISION, "Opérateur",
               sublabel="saisit les dossiers", text_color="#7c2d12", size=16)
    eng = d.box(330, 470, 300, 80, SUCCESS, "Dossiers candidats",
                sublabel="→ engine.score_candidate()", size=17)

    d.arrow(260, 285, 330, 285, color=PRIMARY[1], start=grille, end=cp)
    d.arrow(630, 265, 720, 190, color=AI[1], start=cp, end=wt)
    d.arrow(630, 305, 720, 390, color=AI[1], start=cp, end=rc)
    d.arrow(970, 190, 1080, 250, color=PRIMARY[1], start=wt, end=wb)
    d.arrow(1230, 130, 1230, 195, color=DECISION[1], start=op, end=wb)
    d.arrow(1080, 360, 970, 395, color=SECONDARY[1], start=wb, end=rc)
    d.arrow(800, 430, 560, 470, color=SECONDARY[1], start=rc, end=eng)

    # Libellés de flèches
    d.text(985, 158, "génère", color=BODY, size=13)
    d.text(1245, 150, "saisie", color=BODY, size=13)
    d.text(985, 400, "import", color=BODY, size=13)

    # --- Bandeau du bas : routage automatique des critères count ---------
    d.text(40, 590, "Routage automatique des critères « count »",
           color=SUBTITLE, size=18)
    cnt = d.box(40, 660, 200, 80, PRIMARY, "Critère count",
                text_color="#ffffff", size=16)
    dia = d.diamond(310, 610, 320, 180, DECISION,
                    "date · position\nbonus · shared_cap ?", size=15)
    oui = d.box(720, 615, 360, 90, TERTIARY, "Feuille « Activites »",
                sublabel="format long — 1 ligne / élément\n(date, position, bonus)",
                size=16)
    non = d.box(720, 730, 360, 80, SECONDARY,
                "Colonne « (qte) » — feuille « Candidats »",
                sublabel="saisie simple", text_color="#ffffff", size=15)

    d.arrow(240, 700, 310, 700, color=PRIMARY[1], start=cnt, end=dia)
    d.arrow(630, 670, 720, 645, color=SUCCESS[1], start=dia, end=oui)
    d.arrow(630, 730, 720, 760, color=BODY, start=dia, end=non)
    d.text(648, 628, "oui", color="#047857", size=14)
    d.text(648, 735, "non", color=BODY, size=14)

    # Note sur les listes déroulantes
    d.text(1130, 645, "Menus déroulants = libellés (label_fr).\n"
                      "À l'import : libellé OU identifiant accepté.\n"
                      "Le même column_plan garantit l'aller-retour.",
           color=BODY, size=14)

    d.dump(out)


# === Diagramme 4 : Pipeline de déploiement =================================
def deployment(out: Path) -> None:
    d = Diagram()
    d.text(40, 24, "Du prompt au déploiement — pipeline de livraison",
           color=TITLE, size=28)
    d.text(40, 66, "Claude Code (VS Code) → tests locaux → GitHub → Coolify "
                   "(Docker) · projet classement-stages", color=BODY, size=16)

    # Bandeaux de phase (niveau 2)
    d.text(40, 165, "DÉVELOPPEMENT (local)", color=SUBTITLE, size=16)
    d.text(528, 165, "VALIDATION", color=SUBTITLE, size=16)
    d.text(1012, 165, "GITHUB", color=SUBTITLE, size=16)
    d.text(1286, 165, "DÉPLOIEMENT — COOLIFY (serveur)", color=SUBTITLE, size=16)

    cy = 290  # centre vertical de la rangée principale

    prompt = d.box(40, 240, 220, 100, START, "Prompt dans Claude Code",
                   sublabel="(VS Code)", size=17)
    claude = d.box(300, 240, 220, 100, AI, "Claude édite le code",
                   sublabel="fichiers du dépôt", text_color="#ffffff", size=17)
    dia = d.diamond(560, 200, 200, 180, DECISION, "pytest\npasse ?", size=17)
    git = d.box(810, 240, 220, 100, PRIMARY, "git commit",
                sublabel="+ git push origin main", text_color="#ffffff", size=16)
    github = d.box(1070, 240, 240, 100, SECONDARY, "Dépôt GitHub",
                   sublabel="SamRepository /\nclassement-stages",
                   text_color="#ffffff", size=16)
    coolify = d.box(1360, 240, 230, 100, START, "Coolify · clic « Deploy »",
                    sublabel="déclenchement MANUEL", size=15)
    docker = d.box(1640, 240, 240, 100, PRIMARY, "Build + Run Docker",
                   sublabel="Dockerfile → uvicorn :8000", text_color="#ffffff",
                   size=15)
    live = d.box(1930, 240, 240, 100, SUCCESS, "Application en ligne",
                 sublabel="stages.panel.enset-skikda.dz", size=15)

    # Flux principal (niveau 1)
    d.arrow(260, cy, 300, cy, color=START[1], start=prompt, end=claude)
    d.arrow(520, cy, 560, cy, color=AI[1], start=claude, end=dia)
    d.arrow(760, cy, 810, cy, color=SUCCESS[1], start=dia, end=git)
    d.text(770, 258, "oui", color="#047857", size=14)
    d.arrow(1030, cy, 1070, cy, color=PRIMARY[1], start=git, end=github)
    d.arrow(1310, cy, 1360, cy, color=SECONDARY[1], start=github, end=coolify)
    d.arrow(1590, cy, 1640, cy, color=START[1], start=coolify, end=docker)
    d.arrow(1880, cy, 1930, cy, color=PRIMARY[1], start=docker, end=live)

    # Boucle de correction (pytest échoue → retour à Claude)
    d.arrow(600, 215, 430, 240, color=BODY, start=dia, end=claude, dashed=True)
    d.text(470, 196, "non → corriger", color=BODY, size=13)

    # Artefacts de preuve (niveau 3)
    d.code(560, 420, 300, 70,
           "$ python -m pytest -q\n182 passed")
    d.arrow(660, 380, 700, 420, color=BODY, dashed=True)

    d.code(940, 420, 360, 70,
           "$ git push origin main\n  4bccad4..4fa88f5  main -> main")
    d.arrow(1110, 340, 1110, 420, color=BODY, dashed=True)

    d.code(1500, 420, 470, 150,
           "# Dockerfile\n"
           "FROM python:3.12-slim\n"
           "RUN pip install -e .[webapp]\n"
           "EXPOSE 8000\n"
           "CMD alembic upgrade head &&\n"
           "    uvicorn webapp.main:app\n"
           "      --host 0.0.0.0 --port 8000")
    d.arrow(1740, 340, 1735, 420, color=BODY, dashed=True)

    # Flux résumé (niveau 1, rappel en bas)
    d.text(40, 620, "Résumé :  Prompt  →  Code  →  Tests ✓  →  Push GitHub  →  "
                    "Deploy Coolify (manuel)  →  Conteneur Docker  →  En ligne",
           color=SUBTITLE, size=16)

    d.dump(out)


if __name__ == "__main__":
    here = Path(__file__).parent
    architecture(here / "architecture.excalidraw")
    scoring(here / "notation-dossier.excalidraw")
    circuit_excel(here / "circuit-excel.excalidraw")
    deployment(here / "deploiement.excalidraw")
