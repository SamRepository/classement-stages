---
description: Vérification complète du projet (tests + audit des grilles + validité JSON)
allowed-tools: Bash, PowerShell, Read, Grep, Glob
---

Vérifie l'état de santé du projet :

1. `python -m pytest -q` — la suite complète doit passer.
2. `python scripts/audit_grids.py` — aucune anomalie attendue.
3. Valide la syntaxe JSON des profils `data/institutions/*.json`.

Rapporte un verdict en une ligne par contrôle. En cas d'échec, diagnostique et corrige
(sauf si la correction touche les valeurs de points des grilles — dans ce cas, signale
et demande confirmation, la référence étant le scan `docs/345-1.pdf`).
