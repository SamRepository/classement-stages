---
description: Vérifier l'intégrité des 9 grilles JSON (structure, libellés, conformité)
allowed-tools: Bash, PowerShell, Read, Grep, Glob
---
Exécute `python scripts/audit_grids.py` depuis la racine du projet et analyse la sortie.

- Si l'audit est propre, confirme-le en une phrase avec le décompte par grille.
- Si des libellés ou champs manquent, corrige-les directement dans les fichiers
  `data/grids/*.json` concernés en t'alignant sur les grilles complètes (u1 et rc5 sont
  les références de style), puis relance l'audit et `python -m pytest -q`.
- Rappel des conventions (voir CLAUDE.md) : `flags` = incertitude non résolue,
  `notes` = lecture confirmée ; ne jamais modifier les valeurs de points sans
  vérification contre le scan `docs/decret_loi/345-1.pdf` (pages de référence dans
  `docs/audit-grilles.md`).
