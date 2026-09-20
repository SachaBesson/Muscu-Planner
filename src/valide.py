"""Contrôles sur la sortie du LLM.

Un échec n'est pas une erreur : c'est prévu. Un seul rejeu, puis repli sur la
sélection déterministe. Le système doit produire une séance même si l'API est
en panne, le quota épuisé ou le modèle en vrille.
"""
from .config import REGLES

SE = REGLES["seance"]
AXES = REGLES["axes"]


def controler(seance, candidats, n_exos):
    """Renvoie la liste des problèmes. Vide = la séance est acceptable."""
    par_id = {c["id_exercice"]: c for c in candidats}
    pbs = []

    ids = [e.id_exercice for e in seance.exercices]
    hors = [i for i in ids if i not in par_id]
    if hors:
        pbs.append(f"exercices hors shortlist : {hors}")

    if len(ids) != n_exos:
        pbs.append(f"{len(ids)} exercices au lieu de {n_exos}")

    if len(set(ids)) != len(ids):
        pbs.append("doublons dans la séance")

    retenus = [par_id[i] for i in ids if i in par_id]

    sigs = [c["sig"] for c in retenus]
    if len(set(sigs)) != len(sigs):
        pbs.append("deux variantes du même mouvement")

    axes = {"poussee": 0, "tirage": 0, "jambes": 0, "autre": 0}
    for c in retenus:
        axes[c["axe"]] += 1
    # L'equilibre poussee/tirage n'est PAS verifie : c'est un KPI, pas une
    # regle. Seul le plafond par region l'est, pour garder la seance complete.
    for axe, maxi in (SE.get("max_par_region") or {}).items():
        if axes.get(axe, 0) > maxi:
            pbs.append(f"{axes[axe]} exercices d'axe {axe} (maximum {maxi})")

    compte = {}
    for c in retenus:
        compte[c["sous_groupe"]] = compte.get(c["sous_groupe"], 0) + 1
    trop = [k for k, v in compte.items() if v > SE["max_par_sous_groupe"]]
    if trop:
        pbs.append(f"plus de {SE['max_par_sous_groupe']} exercices sur : {trop}")

    for sg, n in (SE.get("quotas") or {}).items():
        if sum(1 for c in retenus if sg in c["sgs_prim"]) < n:
            pbs.append(f"quota non respecté : {sg} < {n}")

    ordres = sorted(e.ordre for e in seance.exercices)
    if ordres != list(range(1, len(ordres) + 1)):
        pbs.append("numérotation d'ordre incohérente")

    return pbs


def obtenir_seance(candidats, deficits, fat, prevues, n_exos, log=print):
    """Tente le LLM, contrôle, rejoue une fois, sinon repli déterministe."""
    from . import llm, shortlist

    contexte = ""
    for essai in (1, 2):
        try:
            seance = llm.proposer(candidats, deficits, fat, prevues, n_exos, contexte)
        except Exception as e:
            log(f"[LLM] essai {essai} en échec technique : {e}")
            break
        pbs = controler(seance, candidats, n_exos)
        if not pbs:
            return seance, "llm"
        log(f"[LLM] essai {essai} refusé : {pbs}")
        contexte = ("La proposition précédente a été refusée pour : "
                    + " ; ".join(pbs) + ". Corrige-les.")

    log("[LLM] repli sur la sélection déterministe")
    retenus = shortlist.selection_deterministe(candidats, n_exos)
    retenus.sort(key=lambda x: (-x["n_sg"], -x["score"]))
    return retenus, "deterministe"
