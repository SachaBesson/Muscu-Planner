"""Comparaison entre la séance proposée et la séance réellement faite.

C'est ce qui rend le système capable d'apprendre. Sans stockage de la
proposition, aucune correction n'est observable.
"""
import pandas as pd

from .config import REGLES


def seance_faite(proposition: pd.DataFrame) -> bool:
    """Une séance est faite si les colonnes de retour sont remplies."""
    if proposition.empty:
        return False
    for col in ("reps_faites", "rpe_fait"):
        if col not in proposition.columns:
            return False
    rempli = proposition[["reps_faites", "rpe_fait"]].replace("", pd.NA).notna().any(axis=1)
    return bool(rempli.sum() >= max(1, len(proposition) // 2))


def perimee(proposition: pd.DataFrame, jour) -> bool:
    """Une proposition trop vieille est régénérée, pas attendue.

    Sans péremption, une séance sautée bloque le système indéfiniment.
    """
    if proposition.empty or "date_proposee" not in proposition.columns:
        return True
    d = pd.to_datetime(proposition["date_proposee"].iloc[0], dayfirst=True, errors="coerce")
    if pd.isna(d):
        return True
    return (jour - d).days > REGLES["seuils"]["peremption_proposition_j"]


def comparer(proposition: pd.DataFrame, realise: pd.DataFrame, mapping: pd.DataFrame):
    """Renvoie les événements observés : garde / remplace / saute / ajoute."""
    propose = set(proposition["id_exercice"].astype(str).str.strip())
    fait = set(realise["Unique_exercice"].astype(str).str.strip())

    sg = mapping[mapping["principal"]].set_index("Unique_exercice")["sous_groupe"].to_dict()
    evts = []

    for e in propose & fait:
        evts.append({"id_exercice": e, "evenement": "garde", "commentaire": ""})

    non_faits = propose - fait
    ajouts = fait - propose
    ajouts_par_sg = {}
    for a in ajouts:
        ajouts_par_sg.setdefault(sg.get(a), []).append(a)

    for e in non_faits:
        remplacants = ajouts_par_sg.get(sg.get(e), [])
        if remplacants:
            r = remplacants.pop(0)
            evts.append({"id_exercice": e, "evenement": "remplace",
                         "commentaire": f"remplacé par {r}"})
            evts.append({"id_exercice": r, "evenement": "ajoute",
                         "commentaire": f"à la place de {e}"})
        else:
            evts.append({"id_exercice": e, "evenement": "saute", "commentaire": ""})

    for restants in ajouts_par_sg.values():
        for r in restants:
            evts.append({"id_exercice": r, "evenement": "ajoute", "commentaire": "hors proposition"})

    return evts
