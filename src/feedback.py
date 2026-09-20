"""Ajustement des notes à partir des corrections observées.

Le référentiel n'est pas figé : une note encode une décision qui se révise.
Le deadlift noté 6 après une période de réticence en est l'exemple type.

Garde-fous : ±0,2 par ajustement, à partir de 3 occurrences seulement, et
plafond cumulé par exercice et par mois. Un imprévu d'un soir (machine
occupée) ne doit pas déformer le référentiel.
"""
from datetime import timedelta

import pandas as pd

from .config import REGLES

FB = REGLES["feedback"]
SENS = {"ajoute": +1, "remplace": -1, "saute": -1, "garde": 0}


def calculer_ajustements(historique_feedback: pd.DataFrame, jour):
    """Renvoie {id_exercice: delta} à appliquer au référentiel."""
    if historique_feedback.empty:
        return {}

    f = historique_feedback.copy()
    f["date"] = pd.to_datetime(f["date"], dayfirst=True, errors="coerce")
    f = f.dropna(subset=["date"])

    recent = f[f["date"] > jour - timedelta(days=60)]
    deja = f[f["date"] > jour - timedelta(days=30)]
    plafond_atteint = (deja.assign(a=deja["delta_note"].astype(float).abs())
                       .groupby("id_exercice")["a"].sum())

    ajust = {}
    for (exo, evt), grp in recent.groupby(["id_exercice", "evenement"]):
        sens = SENS.get(evt, 0)
        if sens == 0 or len(grp) < FB["occurrences_min"]:
            continue
        if plafond_atteint.get(exo, 0) >= FB["plafond_mensuel"]:
            continue
        ajust[exo] = ajust.get(exo, 0) + sens * FB["delta"]
    return ajust


def lignes_journal(evts, jour, notes_avant):
    """Prépare les lignes à ajouter à l'onglet Feedback (append-only)."""
    out = []
    for e in evts:
        exo = e["id_exercice"]
        avant = notes_avant.get(exo, "")
        out.append([f"{jour:%d/%m/%Y}", exo, e["evenement"], 0, avant, avant,
                    e.get("commentaire", "")])
    return out
