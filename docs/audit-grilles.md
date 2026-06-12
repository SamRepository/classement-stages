# Audit des grilles — décompte vérifié par grille

Audit du 10/06/2026 : re-vérification des neuf grilles JSON de
[data/grids/](../data/grids/) contre le scan de l'arrêté n° 345 du 09/03/2026
([345-1.pdf](decret_loi/345-1.pdf)), incluant les pages relues en haute résolution (300 DPI),
notamment les pages 13, 15, 18, 19, 25 et 29 qui n'avaient été contrôlées qu'en 200 DPI
lors de la transcription initiale.

**Verdict : aucun critère ne manque dans aucune grille.**

## Décompte vérifié par grille

| Grille | Critères | Items | Conformité au scan |
|---|---:|---:|---|
| u1 manifestations | 22 | 29 | ✓ p10–13 |
| u2 personnel administratif | 9 | 8 | ✓ p14–15 (y compris formulaire de rejet motivé) |
| u3 résidences scientifiques | 22 | 29 | ✓ p16–19 — **structurellement identique à u1**, seuls les rangs éligibles diffèrent (4 rangs + bonus habilitation MCB, sans maîtres assistants ni doctorants) |
| u4 perfectionnement | 14 | 16 | ✓ p20–21 |
| rc5 chercheurs résidences | 14 | 37 | ✓ p22–25 |
| rc6 chercheurs stages | 14 | 33 | ✓ p26–29 — les 4 items de moins que rc5 sont réels (pas de Proceeding, pas de dépôt de brevet, pas de lignes thèses), documentés dans `notes` |
| rc7 admin centres | 8 | 2 | ✓ p30 |
| rc8 techniciens ingénierie | 10 | 10 | ✓ p31–32 |
| rc9 techniciens dév. techno | 12 | 11 | ✓ p33–34 |

## Points notables

- **u4 n'a pas de critère de rang** : conforme au décret — l'annexe 4 (perfectionnement)
  n'attribue aucun point au grade. Le rang se saisit dans les grilles u1 et u3 (et u2 pour
  les catégories du personnel administratif).
- Les populations absentes de u3 (maîtres assistants, doctorants) sont conformes à
  l'annexe 3 ; ces populations passent par u1 et u4.
- Les écarts entre rc5 et rc6 (Proceeding, dépôt de brevet, encadrement de thèses présents
  uniquement dans rc5) reflètent fidèlement les annexes 5 et 6.

## Corrections apportées lors de l'audit

Aucun critère manquant, mais des **libellés** (`label_fr`/`label_ar`) absents au niveau
des options et items dans u2, u3, u4 et rc6 ont été complétés (ils alimentent les fiches
d'évaluation et la feuille Referentiel des modèles Excel). Dans la foulée, les menus
déroulants des modèles Excel affichent désormais les libellés français (« Professeur
émérite »…) au lieu des identifiants techniques, l'import acceptant les deux formes.

## Rejouer l'audit

```powershell
python scripts/audit_grids.py
```

Le script contrôle la structure des neuf grilles et signale tout libellé ou champ
manquant. Sortie attendue : « Aucun libellé manquant : toutes les grilles sont complètes
et homogènes. »
