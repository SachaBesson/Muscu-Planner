"""Les trois quantités qui décrivent l'état de l'athlète.

  stimulus   : ce qui fait progresser      -> pilote le déficit
  fatigue    : ce qui empêche de charger   -> bloque des exercices
  systemique : coût global                 -> réduit la taille de la séance

Elles sont volontairement séparées : courir fatigue les ischios sans les
construire. Les confondre ferait croire au moteur que les jambes sont
entraînées alors qu'elles sont seulement cramées.
"""
from datetime import timedelta

import pandas as pd

from .config import CIBLES, DISCIPLINES, RESSENTI, REGLES

F = REGLES["fenetres"]


def _echelle(duree, rpe):
    return (float(duree) / 30.0) * (float(rpe) / 7.0)


def _decroissance(jours, demi_vie_j):
    return 0.5 ** (jours / demi_vie_j)


def stimulus(hist, mapping, activites, jour):
    """Séries pondérées par sous-groupe, décroissantes avec l'ancienneté."""
    debut = jour - timedelta(days=F["stimulus_jours"])
    r = hist[(hist["Date"] > debut) & (hist["Date"] <= jour)]
    out = {}
    if not r.empty:
        n = r.groupby(["Unique_exercice", "Date"]).size().rename("n").reset_index()
        v = n.merge(mapping, on="Unique_exercice", how="left")
        age = (jour - v["Date"]).dt.days
        v["s"] = (v["n"] * v["poids"]
                  * _decroissance(age, F["demi_vie_stimulus_j"]) / F["norm_stimulus"])
        out = v.groupby("sous_groupe")["s"].sum().to_dict()

    for a in activites[(activites.Date > debut) & (activites.Date <= jour)].itertuples():
        if a.type not in DISCIPLINES:
            continue
        f = _echelle(a.duree_min, a.rpe)
        d = _decroissance((jour - a.Date).days, F["demi_vie_stimulus_j"]) / F["norm_stimulus"]
        for sg, k in DISCIPLINES[a.type]["stimulus"].items():
            out[sg] = out.get(sg, 0) + k * f * d
    return out


def fatigue(hist, mapping, activites, jour):
    """Fatigue locale par sous-groupe, demi-vie 24 h, modulée par le ressenti."""
    out = {}
    debut = jour - timedelta(days=5)
    r = hist[(hist["Date"] > debut) & (hist["Date"] <= jour)]
    if not r.empty:
        n = r.groupby(["Unique_exercice", "Date"]).size().rename("n").reset_index()
        v = n.merge(mapping, on="Unique_exercice", how="left")
        for x in v.itertuples():
            mult = 1.3 if x.n_sg >= 3 else 1.0   # un poly fatigue plus qu'une isolation
            d = _decroissance((jour - x.Date).days * 24 / F["demi_vie_fatigue_h"], 1)
            out[x.sous_groupe] = out.get(x.sous_groupe, 0) + x.n * x.poids * mult * d

    for a in activites[(activites.Date > debut) & (activites.Date <= jour)].itertuples():
        if a.type not in DISCIPLINES:
            continue
        f = _echelle(a.duree_min, a.rpe)
        r_mult = RESSENTI.get(str(getattr(a, "ressenti", "normal")).strip().lower(), 1.0)
        d = _decroissance((jour - a.Date).days * 24 / F["demi_vie_fatigue_h"], 1)
        for sg, k in DISCIPLINES[a.type]["fatigue"].items():
            out[sg] = out.get(sg, 0) + k * f * r_mult * d
    return out


def charge_systemique(hist, activites, jour):
    """RPE-minutes sur 72 h, normalisé : 1.0 = semaine type."""
    debut = jour - timedelta(days=F["systemique_jours"])
    m = hist[(hist["Date"] > debut) & (hist["Date"] <= jour)]
    total = len(m) * 3 * m["rpe"].fillna(7).mean() if len(m) else 0.0
    for a in activites[(activites.Date > debut) & (activites.Date <= jour)].itertuples():
        if a.type in DISCIPLINES:
            total += float(a.duree_min) * float(a.rpe) * DISCIPLINES[a.type]["systemique"]
    return total / 900.0


def muscles_proteges(activites, jour):
    """Sous-groupes dont une activité PRÉVUE a besoin sous peu.

    Sans le prévisionnel, le moteur ne peut que réagir après coup : il faut
    savoir que la sortie longue arrive pour ne pas vider les jambes la veille.
    """
    S = REGLES["seuils"]
    fin = jour + timedelta(hours=S["horizon_protection_h"])
    prevues = activites[(activites.Date > jour) & (activites.Date <= fin)]
    besoins = {}
    for a in prevues.itertuples():
        if a.type not in DISCIPLINES:
            continue
        f = _echelle(a.duree_min, a.rpe)
        for sg, k in DISCIPLINES[a.type]["fatigue"].items():
            if k * f >= S["seuil_protection"]:
                besoins[sg] = max(besoins.get(sg, 0), k * f)
    return besoins, prevues


def deficits(stim):
    return {sg: max(0.0, c - stim.get(sg, 0)) for sg, c in CIBLES.items()}
