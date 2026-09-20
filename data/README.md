# data/

Dossier de travail local pour `SOURCE=csv`. Les .csv sont ignores par git.

## Les trois fichiers attendus

| Fichier | Onglet source | Obligatoire | Colonnes minimales |
|---|---|---|---|
| `referentiel.csv` | Referentiel | oui | `Unique`, `Unique_exercice`, `Sub_group`, `Weight`, `Rating / 10` |
| `historique.csv` | F_exercicesDone | oui | `Date`, `id_exercice`, `serie numero`, `poids`, `RPE like` |
| `activites.csv` | Activites | non | `Date`, `type`, `duree_min`, `rpe`, `ressenti` |

Export : Fichier > Telecharger > Valeurs separees par des virgules (.csv),
avec l'onglet voulu affiche. Renomme le fichier telecharge.

## activites.csv

C'est le journal des AUTRES disciplines : course, crossfit, natation. Il sert
a trois choses, et sans lui le moteur en est aveugle :

1. **Fatigue locale** — une sortie longue fatigue ischios et mollets, donc on
   evite de les charger le lendemain.
2. **Protection prospective** — les dates FUTURES valent planning. Une sortie
   prevue sous 36 h fait ecarter les exercices qui useraient les memes muscles.
3. **Ressenti** — `frais`, `normal`, `fatigue`, `courbatures`. C'est le seul
   moyen de dire au modele que 4 km t'ont mis a plat parce que tu reprends.

Le stimulus qu'il apporte reste volontairement faible : courir ne construit
pas de muscle, ca le fatigue. Confondre les deux ferait croire au moteur que
tes jambes sont entrainees alors qu'elles sont seulement cramees.

Voir `activites.exemple.csv` pour le format. Si le fichier est absent, tout
fonctionne, mais sans protection de course ni effet du ressenti.
