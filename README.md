# muscu-planner

Génère la prochaine séance de musculation à partir de l'historique Google
Sheets, des déficits par sous-groupe musculaire, de la fatigue, et du
calendrier de course.

## Principe

```
Python  ->  normalise, agrège, calcule déficits / fatigue / charges
            produit une SHORTLIST fermée de candidats éligibles
LLM     ->  choisit dans la shortlist, ORDONNE, écrit la note
Python  ->  valide (shortlist ? équilibre ? quotas ?), 1 rejeu, sinon repli
```

**Le LLM ne produit jamais un nombre.** Pas de charge, pas de volume, pas de
série. Il choisit des identifiants, un ordre, des supersets et du texte.
Tout le reste vient du calcul déterministe.

Trois quantités sont suivies séparément, et c'est le cœur du modèle :

| Quantité | Unité | Rôle | Horizon |
|---|---|---|---|
| stimulus | séries pondérées | pilote le déficit | 12 j, demi-vie 6,5 j |
| fatigue locale | points | bloque des exercices | 24–72 h |
| charge systémique | RPE-minutes | réduit la taille de séance | 72 h |

Courir fatigue les ischios sans les construire. Les confondre ferait croire au
moteur que les jambes sont entraînées alors qu'elles sont seulement cramées.

## Démarrage

```bash
pip install -r requirements.txt
cp .env.example .env          # remplir SHEET_ID et GEMINI_API_KEY
```

Développer sans authentification, sur des CSV locaux dans `data/` :

```bash
SOURCE=csv python -m src.main --force --date 14/09/2026 --dry-run
```

En vrai :

```bash
python -m src.main            # cycle complet
python -m src.main --dry-run  # affiche sans écrire dans Sheets
```

## Prérequis Google

1. Activer **Sheets API** et **Drive API** sur le projet GCP
2. Créer un compte de service, générer une clé JSON
3. **Partager le classeur avec l'email du compte de service, en Éditeur**
   — l'oubli le plus fréquent, il donne une 403 peu bavarde
4. `SHEET_ID` = l'identifiant seul, sans `/edit?...`

## Onglets du classeur

| Onglet | Rôle |
|---|---|
| `Référentiel` | alias → exercice canonique, sous-groupes, poids, notes |
| `F_exercicesDone` | historique **et** proposition, à la maille série |
| `Calendrier` | jours de salle et de course prévus |
| `Activites` | course, crossfit, natation — **dates futures = planning** |
| `Propositions_log` | copie immuable des propositions, pour le diff |
| `Feedback` | journal append-only des corrections |
| `A_normaliser` | libellés inconnus, généré automatiquement |

## La proposition vit dans l'historique

Elle partage le schéma exact de `F_exercicesDone`, donc il n'y a pas d'onglet
séparé : elle est écrite à la suite, avec `RPE like` vide.

```
Date | id_exercice | Nombre de reps | série numéro | poids | RPE like |
Ressenti | Colonne 1 | Colonne 2 (ordre) | Colonne 3 (superset) | Colonne 4 (note)
```

Tu remplis `RPE like` à la salle. C'est tout. Pas d'archivage, pas de pivot
exercice → séries : la ligne proposée devient la ligne réalisée.

**Le piège que ça crée**, et le filtre qui le règle : une ligne proposée a un
numéro de série ≥ 1 sans RPE, donc elle passerait pour une série de travail et
le moteur croirait la séance faite. Une série réalisée est donc définie comme
**ayant un RPE ou un ressenti**. Les 296 lignes anciennes sans RPE mais avec
ressenti restent comptées.

## Boucle quotidienne

```
état de la dernière date de F_exercicesDone
├── A_FAIRE  (RPE vide, < 5 j)   -> ne rien faire
├── FAITE    (RPE rempli >= 50%) -> diff vs Propositions_log, feedback,
│                                   puis générer la séance suivante
└── PERIMEE  (RPE vide, > 5 j)   -> retirer les lignes, régénérer
```

La date de la prochaine séance vient de l'onglet `Calendrier` ; à défaut,
J+2. Sans péremption, une séance sautée bloquerait le système indéfiniment.

## Tests

```bash
SOURCE=csv python -m pytest tests/ -s
```

`test_retro.py` rejoue le moteur sur chaque séance passée et compte les
absurdités. **Ne le saute pas.** Il a déjà trouvé deux bugs réels :

- l'étape de rattrapage de l'équilibre poussée/tirage manquait
- l'équilibre `|poussée − tirage| <= 1` est satisfait par `0 − 0`, ce qui
  autorisait des séances entièrement jambes — d'où `min_par_axe`

Taux d'anomalies après correction : **8 sur 86 séances rejouées**.

## Réglage

Tout est dans `config/*.yaml`. Deux principes tirés de l'expérience :

1. **Une règle nouvelle doit être une contrainte, pas un poids.** Un poids se
   fait toujours battre par un autre : monter `preference` a fait sauter les
   déficits, ajouter `couverture` a empilé les poussées. Ce qui a marché, ce
   sont les places réservées, les quotas et les planchers d'axe.
2. **Après un premier tour qui tourne, gèle les coefficients un mois.** Sinon
   tu règles à vide, sans mesure.

## Ce qui reste à faire

- [ ] colonne `Pattern` dans le référentiel (tirage vertical vs horizontal) :
      `min_par_axe` limite les dégâts, mais deux tirages verticaux restent
      possibles dans une même séance
- [ ] colonnes `Type` (poly/iso) et `Charge_lombaire` : le multiplicateur de
      fatigue est aujourd'hui déduit du nombre de sous-groupes, ce qui est
      une approximation
- [ ] dashboard mobile (onglet `Dashboard_export` publié en CSV)
- [ ] régler les coefficients de `disciplines.yaml` sur du ressenti réel
