"""Test rétrospectif : rejoue le moteur sur chaque séance passée.

L'objectif n'est PAS 100 % de concordance avec ce que tu as fait. C'est de
repérer les absurdités : une séance sans aucun tirage, un candidat vide, une
charge aberrante. C'est l'étape qui transforme le réglage à l'aveugle en
réglage mesuré. Ne la saute pas.

    SOURCE=csv python -m pytest tests/test_retro.py -s
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import sheets, normalise, etat, shortlist


def test_retrospectif():
    ref = sheets.lire("referentiel")
    if ref.empty:
        import pytest
        pytest.skip("pas de données locales — voir data/README")

    hist, orph = normalise.preparer_historique(sheets.lire("historique"), ref)
    mapping = normalise.eclater(ref)
    exos = (ref.assign(rating=pd.to_numeric(ref["Rating / 10"], errors="coerce"))
              .groupby("Unique_exercice", as_index=False).agg(rating=("rating", "max")))
    vide = pd.DataFrame(columns=["Date", "type", "duree_min", "rpe", "ressenti"])

    jours = sorted(hist["Date"].unique())[10:]
    anomalies = []
    for j in jours:
        j = pd.Timestamp(j)
        passe = hist[hist["Date"] < j]
        stim = etat.stimulus(passe, mapping, vide, j)
        fat = etat.fatigue(passe, mapping, vide, j)
        cand = shortlist.construire(exos, mapping, passe, stim, fat, {}, j)
        if len(cand) < 6:
            anomalies.append((j.date(), f"seulement {len(cand)} candidats"))
            continue
        seance = shortlist.selection_deterministe(cand, 6)
        axes = shortlist.ratio_kpi(seance)

        # L'équilibre poussée/tirage n'est PAS testé : c'est un KPI, pas une
        # règle. Il découle des cibles par sous-groupe.
        for axe, maxi in (shortlist.SE.get("max_par_region") or {}).items():
            if axes.get(axe, 0) > maxi:
                anomalies.append((j.date(), f"{axes[axe]} exos {axe} (max {maxi})"))

        # Une séance doit rester complète : au moins 4 sous-groupes distincts.
        sgs = {c["sous_groupe"] for c in seance}
        if len(sgs) < 4:
            anomalies.append((j.date(), f"seulement {len(sgs)} sous-groupes"))

    print(f"\n{len(jours)} séances rejouées, {len(anomalies)} anomalie(s)")
    for a in anomalies[:20]:
        print("  ", a)
    ratio = len(anomalies) / max(len(jours), 1)
    print(f"taux d'anomalies : {ratio:.1%}")
    assert ratio < 0.15, "plus de 15 % d'anomalies"
