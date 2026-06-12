---
description: Lancer une campagne de classement complète (score + PV + fiches + HTML)
argument-hint: <grille> <fichier-candidats.xlsx|.json> <date-cloture AAAA-MM-JJ>
allowed-tools: Bash, PowerShell, Read, Glob
---

Lance une campagne de classement pour l'ENSET-Skikda avec les arguments : $ARGUMENTS

Étapes :

1. Si un argument manque (grille, fichier candidats, date de clôture), demande-le —
   la date de clôture du dépôt est la référence des fenêtres de pénalité, ne jamais
   la deviner.
2. Crée le dossier `out/` si besoin, puis exécute :
   ```
   python -m classement score --grid <grille> --institution enset-skikda
       --candidates <fichier> --campaign-date <date>
       --export-pv out/pv-<grille>.xlsx --export-fiches out/fiches-<grille>.xlsx
       --export-html out/classement-<grille>.html --format markdown
   ```
3. Si des erreurs d'import sont rapportées (feuille!ligne), liste-les clairement et
   propose les corrections à apporter au classeur — ne corrige PAS le classeur
   toi-même, c'est le document du service.
4. Présente le classement par groupe et signale les ex aequo (départage = décision
   de la commission) ainsi que tout avertissement notable des fiches (pièces hors
   fenêtre, plafonnements importants).
