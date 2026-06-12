# Couche harness Claude Code du projet

Mise en place le 10/06/2026. Cette couche configure Claude Code pour travailler
efficacement sur ce repo : contexte chargé automatiquement, permissions pré-approuvées
et commandes projet. Tout est versionné dans le projet (rien dans la configuration
personnelle), donc partageable tel quel avec une équipe.

## Composants

### 1. [CLAUDE.md](../CLAUDE.md) — contexte automatique

Chargé au démarrage de chaque session Claude Code dans ce repo. Contient ce qui demande
du temps à redécouvrir :

- les commandes essentielles (tests, test unique, audit, CLI, régénération des exemples) ;
- le principe directeur : **les barèmes ne sont jamais codés en dur** — les JSON de
  `data/grids/` sont la source de vérité, le moteur les interprète génériquement ;
- les subtilités du moteur : ordre d'application des plafonds, fenêtre
  `after_last_benefit`, et le piège de l'inférence de fenêtre des formules (la regex
  `(\d)ans` lit le **nom** du critère — renommer `penalite_beneficies_3ans` casse le
  calcul de `n`) ;
- `column_plan()` comme source unique de vérité du circuit Excel (modèle ↔ import) ;
- les conventions des grilles (`flags` = incertitude non résolue, `notes` = lecture
  confirmée) et la décision de la commission ENSET (classement à l'échelle de l'école) ;
- la méthode de relecture du scan arabe `docs/decret_loi/345-1.pdf` (rendu 300 DPI via PyMuPDF).

### 2. [.claude/settings.json](../.claude/settings.json) — permissions du projet

Allowlist strictement limité aux commandes du projet, exécutées sans invite de
permission :

| Commande | Usage |
|---|---|
| `python -m pytest [...]` | Suite de tests |
| `python -m classement [...]` | CLI du moteur (score, template, places) |
| `python scripts/audit_grids.py` | Audit des grilles |
| `python scripts/make_example_xlsx.py` | Régénération des exemples Excel |
| `python -m pip install openpyxl` | La seule dépendance |

Pas de wildcard général sur `python` ni de `pip` libre. Les règles existent en double
(outils `Bash` et `PowerShell`) pour couvrir les deux shells sous Windows.
Un fichier de permissions créé en cours de session prend effet à la session suivante.

### 3. [.claude/commands/](../.claude/commands/) — commandes projet (slash commands)

| Commande | Rôle | Garde-fous |
|---|---|---|
| `/audit-grilles` | Lance l'audit des 9 grilles et corrige les libellés manquants (références de style : u1 et rc5). | Interdiction de modifier les **valeurs de points** sans vérification contre le scan (`docs/audit-grilles.md` donne les pages). |
| `/campagne <grille> <fichier> <date>` | Campagne complète : score + PV + fiches + HTML dans `out/`. | Ne devine jamais la date de clôture (référence des pénalités) ; ne corrige pas le classeur du service — rapporte les erreurs `feuille!ligne`. |
| `/verifier` | Bilan de santé : tests + audit + validité JSON des profils. | Toute correction touchant les points des grilles exige confirmation. |

## Utilisation

Dans une session Claude Code ouverte sur ce repo :

```
/verifier
/audit-grilles
/campagne u4-perfectionnement examples/enset/dossiers-u4.xlsx 2026-06-30
```

## Étendre le harness

- **Nouvelle commande projet** : créer `.claude/commands/<nom>.md` avec un frontmatter
  (`description`, `argument-hint`, `allowed-tools`) suivi des instructions ; elle devient
  `/<nom>` à la session suivante.
- **Nouvelle permission** : ajouter la règle dans `permissions.allow` de
  `.claude/settings.json` (syntaxe `"Bash(commande *)"` / `"PowerShell(commande *)"`).
  Garder l'allowlist minimal — pas de wildcards larges.
- **Préférences personnelles** (non partagées) : utiliser `.claude/settings.local.json`,
  qui surcharge le fichier projet.
- **Faits durables sur le projet** : les ajouter à `CLAUDE.md` (pas dans les commandes) ;
  les décisions réglementaires restent documentées dans `data/grids/README.md` et
  `docs/audit-grilles.md`.
