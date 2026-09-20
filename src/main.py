"""Orchestration. Un cycle par exécution, idempotent.

    python -m src.main                     # cycle complet
    python -m src.main --dry-run           # affiche sans écrire
    SOURCE=csv python -m src.main          # sur CSV locaux, sans auth

Le cycle, piloté par l'état de la dernière date de F_exercicesDone :

    RIEN / FAITE  -> archiver le diff, apprendre, générer la suivante
    PERIMEE       -> effacer la proposition, en générer une neuve
    A_FAIRE       -> ne rien faire

La proposition est écrite directement dans F_exercicesDone avec RPE vide.
Remplir RPE à la salle suffit à déclencher la génération suivante.
"""
import argparse
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import sheets, normalise, etat, shortlist, proposition, valide, diff, feedback
from .config import CIBLES, REGLES, SUIVIS_SANS_CIBLE

SE = REGLES["seance"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _activites(df, log=print):
    cols = ["Date", "type", "duree_min", "rpe", "ressenti"]
    if df is None or df.empty or "type" not in df.columns:
        log("[i] pas d'activités : ni protection de course, ni effet du ressenti")
        return pd.DataFrame(columns=cols)
    a = df.copy()
    a["Date"] = pd.to_datetime(a["Date"], dayfirst=True, errors="coerce")
    a = a.dropna(subset=["Date"])
    a["type"] = a["type"].astype(str).str.strip().str.lower()
    a["duree_min"] = pd.to_numeric(a["duree_min"], errors="coerce").fillna(45)
    a["rpe"] = pd.to_numeric(a["rpe"], errors="coerce").fillna(7)
    if "ressenti" not in a:
        a["ressenti"] = "normal"
    return a


def _prochaine_date(cal, apres):
    """Prochaine séance muscu du calendrier, sinon dans 2 jours."""
    if cal is not None and not cal.empty and "type" in cal.columns:
        c = cal.copy()
        c["Date"] = pd.to_datetime(c["Date"], dayfirst=True, errors="coerce")
        f = c[(c["type"].astype(str).str.lower() == "muscu") & (c["Date"] > apres)]
        if not f.empty:
            r = f.sort_values("Date").iloc[0]
            duree = pd.to_numeric(r.get("duree_min"), errors="coerce")
            return r["Date"], int(duree) if pd.notna(duree) else 60
    return apres + timedelta(days=2), 60


def generer(jour, duree_min, dry, log=print):
    ref = sheets.lire("referentiel")
    brut = sheets.lire("historique")
    act = _activites(sheets.lire("activites"), log)

    hist, orph = normalise.preparer_historique(brut, ref)
    if not orph.empty:
        log(f"[!] {len(orph)} libellé(s) hors référentiel : "
            f"{orph['libelle'].tolist()[:5]}")
        if not dry and os.getenv("SOURCE") != "csv":
            normalise.publier_orphelins(sheets.classeur(), orph)

    mapping = normalise.eclater(ref)          # valide aussi le vocabulaire
    exos = (ref.assign(rating=pd.to_numeric(ref["Rating / 10"], errors="coerce"))
              .groupby("Unique_exercice", as_index=False).agg(rating=("rating", "max")))

    stim = etat.stimulus(hist, mapping, act, jour)
    fat = etat.fatigue(hist, mapping, act, jour)
    cs = etat.charge_systemique(hist, act, jour)
    proteges, prevues = etat.muscles_proteges(act, jour)

    n_exos = max(4, int(duree_min * 0.8 // SE["min_par_exo"]))
    if cs > 1.3:
        n_exos = max(4, n_exos - 2)
        log(f"[i] charge systémique {cs:.2f} — séance réduite à {n_exos} exercices")

    cand = shortlist.construire(exos, mapping, hist, stim, fat, proteges, jour)
    if not cand:
        log("[!] aucun candidat éligible — vérifie fatigue et protections")
        return None
    log(f"[i] {len(cand)} candidats éligibles")
    if len(prevues):
        log(f"[i] course sous 36 h — on épargne {', '.join(sorted(proteges))}")

    seance, origine = valide.obtenir_seance(cand, etat.deficits(stim), fat,
                                            prevues, n_exos, log)
    if origine == "llm":
        par_id = {c["id_exercice"]: c for c in cand}
        sel = []
        for e in sorted(seance.exercices, key=lambda x: x.ordre):
            c = dict(par_id[e.id_exercice])
            c["reps"] = e.reps_cible
            c["superset"] = e.superset_avec or ""
            sel.append(c)
    else:
        sel = seance
        sel.sort(key=lambda x: (-x["n_sg"], -x["score"]))
    log(f"[i] séance produite par : {origine}")

    prop = proposition.construire(sel, hist, jour)

    log(f"\n  {JOURS[jour.weekday()].upper()} {jour:%d/%m} — "
        f"{len(sel)} exercices, {len(prop)} séries")
    for c in sel:
        charge, note = shortlist.prescrire_charge(hist, c["id_exercice"], jour)
        ct = f"{charge:g} kg" if charge else "—"
        log(f"    {c['id_exercice']:28s} {c['sous_groupe']:18s} {ct:>9s}  {note}")

    if not dry:
        sheets.ajouter_proposition(prop)
        log(f"\n[i] {len(prop)} lignes écrites dans F_exercicesDone (RPE vide)")
    return prop


def cycle(aujourdhui=None, dry=False, log=print):
    aujourdhui = aujourdhui or pd.Timestamp(datetime.now().date())
    brut = sheets.lire("historique")
    statut, jour = proposition.etat(brut, aujourdhui)
    log(f"[i] état : {statut}" + (f" (proposition du {jour:%d/%m})" if jour is not None else ""))

    if statut == "A_FAIRE":
        log("[i] proposition en cours, non remplie — rien à faire")
        return None

    if statut == "PERIMEE":
        log(f"[i] proposition du {jour:%d/%m} périmée — le contexte a changé")
        if not dry:
            n = sheets.supprimer_bloc("historique", {f"{jour:%d/%m/%Y}"})
            log(f"[i] {n} lignes retirées")

    if statut == "FAITE":
        ref = sheets.lire("referentiel")
        mapping = normalise.eclater(ref)
        prop_log = sheets.lire("propositions_log")
        if not prop_log.empty:
            attendu = prop_log[prop_log["Date"].astype(str).str.strip()
                               == f"{jour:%d/%m/%Y}"]
            realise, _ = normalise.preparer_historique(
                brut[brut["Date"].astype(str).str.strip() == f"{jour:%d/%m/%Y}"], ref)
            if not attendu.empty:
                evts = diff.comparer(attendu, realise, mapping)
                log(f"[i] écarts : " + (", ".join(
                    f"{e['evenement']} {e['id_exercice']}" for e in evts
                    if e["evenement"] != "garde") or "aucun"))
                if not dry and evts:
                    notes = dict(zip(ref["Unique_exercice"], ref["Rating / 10"]))
                    sheets.ajouter("feedback",
                                   feedback.lignes_journal(evts, aujourdhui, notes))

    prochaine, duree = _prochaine_date(sheets.lire("calendrier"),
                                       jour if jour is not None else aujourdhui)
    return generer(prochaine, duree, dry, log)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", help="JJ/MM/AAAA — forcer la date générée")
    ap.add_argument("--duree", type=int, default=60)
    ap.add_argument("--force", action="store_true",
                    help="générer sans regarder l'état")
    a = ap.parse_args()
    j = pd.to_datetime(a.date, dayfirst=True) if a.date else None
    if a.force:
        generer(j or pd.Timestamp(datetime.now().date()), a.duree, a.dry_run)
    else:
        cycle(j, a.dry_run)
