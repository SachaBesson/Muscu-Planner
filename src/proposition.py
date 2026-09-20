"""Construction et lecture de la proposition, à la maille SÉRIE.

La proposition partage le schéma exact de F_exercicesDone : elle y est écrite
directement, avec `RPE like` vide. Ce vide est le signal « pas encore fait ».
Aucun onglet séparé, aucune transformation à l'archivage.

Colonnes (ordre du classeur) :
    Date | id_exercice | Nombre de reps | série numéro | poids | RPE like |
    Ressenti | Colonne 1 | Colonne 2 (ordre) | Colonne 3 (superset) |
    Colonne 4 (note)
"""
import pandas as pd

from .config import REGLES
from . import shortlist

COLONNES = ["Date", "id_exercice", "Nombre de reps", "série numéro", "poids",
            "RPE like", "Ressenti", "Colonne 1", "Colonne 2", "Colonne 3",
            "Colonne 4"]
SE = REGLES["seance"]


def _fr(x):
    """Décimales à la française, comme le reste du classeur."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    s = f"{float(x):g}"
    return s.replace(".", ",")


def construire(selection, hist, jour, reps_defaut="10"):
    """selection : liste de candidats déjà ordonnée. Renvoie les lignes séries."""
    lignes = []
    for ordre, c in enumerate(selection, 1):
        exo = c["id_exercice"]
        charge, note = shortlist.prescrire_charge(hist, exo, jour)
        n = c.get("series", SE["series_par_exo"])
        reps = c.get("reps", reps_defaut)
        for i in range(1, n + 1):
            lignes.append({
                "Date": f"{jour:%d/%m/%Y}",
                "id_exercice": exo,
                "Nombre de reps": reps,
                "série numéro": i,
                "poids": _fr(charge),
                "RPE like": "",                 # <- rempli à la salle
                "Ressenti": "",                 # <- rempli à la salle
                "Colonne 1": "",
                "Colonne 2": ordre,
                "Colonne 3": c.get("superset", ""),
                "Colonne 4": note if i == 1 else "",
            })
    return pd.DataFrame(lignes, columns=COLONNES)


def bloc_en_attente(brut):
    """Les lignes de la dernière date proposée dont le RPE n'est pas rempli.

    Renvoie (DataFrame du bloc, date). Bloc vide = rien en attente.
    """
    from .normalise import est_realisee
    if brut.empty or "Date" not in brut.columns:
        return pd.DataFrame(), None
    d = brut.copy()
    d["_dt"] = pd.to_datetime(d["Date"], dayfirst=True, errors="coerce")
    d = d.dropna(subset=["_dt"])
    if d.empty:
        return pd.DataFrame(), None
    jour = d["_dt"].max()
    bloc = d[d["_dt"] == jour]
    if est_realisee(bloc).all():
        return pd.DataFrame(), jour          # tout est fait, rien en attente
    return bloc, jour


def etat(brut, aujourdhui):
    """A_FAIRE | FAITE | PERIMEE | RIEN — pilote le cycle quotidien."""
    from .normalise import est_realisee
    bloc, jour = bloc_en_attente(brut)
    if jour is None:
        return "RIEN", None
    if bloc.empty:
        return "FAITE", jour
    part = float(est_realisee(bloc).mean())
    if part >= 0.5:
        return "FAITE", jour                 # remplie en partie = séance faite
    age = (aujourdhui - jour).days
    if age > REGLES["seuils"]["peremption_proposition_j"]:
        return "PERIMEE", jour
    return "A_FAIRE", jour
