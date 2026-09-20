"""Filtres durs, scoring, et sélection déterministe de repli.

Le LLM ne verra QUE ce que ce module produit. Un exercice écarté ici ne peut
pas être choisi : c'est ce qui garantit qu'aucune proposition ne violera les
contraintes de fatigue ou de protection, quoi que raconte le modèle.
"""
import pandas as pd

from .config import CIBLES, REGLES

S, SE, P = REGLES["seuils"], REGLES["seance"], REGLES["poids"]
AXES = REGLES["axes"]


def _note_etalonnee(n):
    lo, hi = REGLES["note_min"], REGLES["note_max"]
    return (min(max(float(n), lo), hi) - lo) / (hi - lo)


def construire(exos, mapping, hist, stim, fat, proteges, jour):
    """Renvoie les candidats éligibles, triés par score décroissant."""
    defs = {sg: max(0.0, c - stim.get(sg, 0)) for sg, c in CIBLES.items()}
    dmax = max(defs.values()) or 1.0
    cmax = sum(sorted(defs.values(), reverse=True)[:3]) or 1.0
    # Surplus : de combien un sous-groupe dépasse son plafond, en séries.
    ratio_max = REGLES.get("plafond_ratio", 1.25)
    surplus = {sg: max(0.0, stim.get(sg, 0) - c * ratio_max)
               for sg, c in CIBLES.items()}
    smax = max(surplus.values()) or 1.0
    derniere = hist.groupby("Unique_exercice")["Date"].max().to_dict()

    # Le délai de repos porte sur la SIGNATURE, pas sur l'exercice : Leg Press
    # et Hack Squat couvrent les mêmes sous-groupes avec les mêmes poids.
    # Bloquer l'un sans l'autre revient à proposer son clone deux jours après.
    sig_de = {}
    for e in exos.itertuples():
        g = mapping[mapping["Unique_exercice"] == e.Unique_exercice]
        if not g.empty:
            sig_de[e.Unique_exercice] = tuple(sorted((x.sous_groupe, x.poids)
                                                     for x in g.itertuples()))
    derniere_sig = {}
    for nom, d in derniere.items():
        k = sig_de.get(nom)
        if k and (k not in derniere_sig or d > derniere_sig[k]):
            derniere_sig[k] = d

    vu = hist[["Date", "Unique_exercice"]].merge(mapping, on="Unique_exercice", how="left")
    dern_sg = vu[vu["poids"] >= 0.5].groupby("sous_groupe")["Date"].max().to_dict()
    urgents = {sg for sg in REGLES["sg_majeurs"] if sg in CIBLES
               and (sg not in dern_sg
                    or (jour - dern_sg[sg]).days >= S["jours_sans_travail_max"])}

    cand = []
    for r in exos.itertuples():
        nom = r.Unique_exercice
        sgs = mapping[mapping["Unique_exercice"] == nom]
        if sgs.empty:
            continue

        sig_k = sig_de.get(nom)
        last = derniere.get(nom)
        last_fam = derniere_sig.get(sig_k)
        jours = 21 if last is None else (jour - last).days
        jours_fam = 21 if last_fam is None else (jour - last_fam).days
        if jours < S["jours_repos_min"]:
            continue
        if jours_fam < S.get("jours_repos_famille", S["jours_repos_min"]):
            continue
        # protection : ne pas charger un muscle dont une course prévue a besoin
        if any(x.sous_groupe in proteges and x.poids >= 0.5 for x in sgs.itertuples()):
            continue

        pilotes = [x for x in sgs.itertuples() if x.sous_groupe in CIBLES]
        if not pilotes:
            continue
        tot = sum(x.poids for x in pilotes)
        somme_d = sum(defs.get(x.sous_groupe, 0) * x.poids for x in pilotes)
        d = somme_d / tot                         # précision du ciblage
        couv = somme_d                            # rendement : étendue couverte
        f = sum(fat.get(x.sous_groupe, 0) * x.poids for x in pilotes) / tot
        sur = sum(surplus.get(x.sous_groupe, 0) * x.poids for x in pilotes) / tot
        if f >= S["fatigue_bloquante"]:
            continue

        score = (P["deficit"] * d / dmax
                 + P["couverture"] * min(couv / cmax, 1.0)
                 + P["fraicheur"] * min(jours, 14) / 14
                 + P["preference"] * _note_etalonnee(r.rating)
                 - P["fatigue"] * f / S["fatigue_bloquante"]
                 - REGLES.get("poids_surplus", 2.0) * sur / smax)

        principal = sgs[sgs["principal"]]["sous_groupe"].iloc[0]
        cand.append({
            "id_exercice": nom,
            "sous_groupe": principal,
            "sous_groupes": sorted({x.sous_groupe for x in sgs.itertuples()}),
            "sgs_prim": {x.sous_groupe for x in sgs.itertuples() if x.poids >= 1.0},
            "couvre": {x.sous_groupe for x in sgs.itertuples() if x.poids >= 1.0} & urgents,
            "axe": AXES.get(principal, "autre"),
            "note": float(r.rating),
            "deficit_couvert": round(couv, 1),
            "fatigue": round(f, 1),
            "jours_depuis": jours,
            "n_sg": int(sgs["n_sg"].iloc[0]),
            "sig": tuple(sorted((x.sous_groupe, x.poids) for x in sgs.itertuples())),
            "score": round(score, 3),
        })

    # Substitution : parmi les exercices de signature identique, un seul
    # survit — celui que tu as le mieux noté. La note tranche, pas la fraîcheur.
    meilleur = {}
    for c in cand:
        cur = meilleur.get(c["sig"])
        if cur is None or (c["note"], c["score"]) > (cur["note"], cur["score"]):
            meilleur[c["sig"]] = c

    tries = sorted(meilleur.values(), key=lambda x: -x["score"])
    return tries[:SE["taille_shortlist"]]


def _plafond_atteint(retenus, candidat):
    """Une seule contrainte de forme : aucune région ne monopolise la séance."""
    plafonds = SE.get("max_par_region") or {}
    axe = candidat["axe"]
    if axe not in plafonds:
        return False
    return sum(1 for x in retenus if x["axe"] == axe) >= plafonds[axe]


def ratio_kpi(retenus):
    """Poussée/tirage : suivi comme indicateur, jamais comme contrainte."""
    a = {"poussee": 0, "tirage": 0, "jambes": 0, "autre": 0}
    for x in retenus:
        a[x["axe"]] += 1
    return a


def selection_deterministe(cand, n_exos):
    """Repli si le LLM échoue deux fois. Doit toujours produire une séance."""
    quotas = SE.get("quotas") or {}
    retenus, compte = [], {}

    for sg, n in quotas.items():
        elig = sorted((c for c in cand if sg in c["sgs_prim"]),
                      key=lambda x: (-x["note"], -x["score"]))
        for c in elig:
            if compte.get(sg, 0) >= n or len(retenus) >= n_exos:
                break
            if _plafond_atteint(retenus, c):
                continue
            retenus.append(c)
            compte[sg] = compte.get(sg, 0) + 1

    reserve = max(1, n_exos // 3) + sum(quotas.values())
    pris = set()
    for c in cand:
        if len(retenus) >= reserve:
            break
        nouveau = c["couvre"] - pris
        if not nouveau or c in retenus:
            continue
        if _plafond_atteint(retenus, c):
            continue
        retenus.append(c)
        pris |= nouveau
        compte[c["sous_groupe"]] = compte.get(c["sous_groupe"], 0) + 1

    # Remplissage au score pur. Seule contrainte de forme : le plafond par
    # region, qui garde la seance complete.
    for c in cand:
        if c in retenus or len(retenus) >= n_exos:
            continue
        if compte.get(c["sous_groupe"], 0) >= SE["max_par_sous_groupe"]:
            continue
        if _plafond_atteint(retenus, c):
            continue
        retenus.append(c)
        compte[c["sous_groupe"]] = compte.get(c["sous_groupe"], 0) + 1

    return retenus


def prescrire_charge(hist, exo, jour):
    """Charge cible d'après la dernière perf, avec décote d'ancienneté.

    Reprendre à 95 % d'une performance vieille de quatre mois est irréaliste :
    -2 % par semaine au-delà de trois semaines, plafonné à -25 %.
    """
    p = hist[(hist["Unique_exercice"] == exo) & hist["poids"].notna()]
    if p.empty:
        return None, "jamais chargé, pars léger"
    d = p["Date"].max()
    s = p[p["Date"] == d]
    top = s.loc[s["poids"].idxmax()]
    charge, rpe = float(top["poids"]), top["rpe"]

    if pd.isna(rpe):
        base, note = charge, "maintien"
    elif rpe <= 7:
        base, note = charge + 2.5, f"+2,5 kg (dernier RPE {rpe:g})"
    elif rpe <= 8:
        base, note = charge, f"maintien (dernier RPE {rpe:g})"
    else:
        base, note = charge * 0.95, f"-5 % (dernier RPE {rpe:g})"

    semaines = max(0, ((jour - d).days - 21) / 7)
    decote = min(0.25, 0.02 * semaines)
    if decote > 0:
        base *= (1 - decote)
        note += f", décote {decote:.0%} ({(jour - d).days} j d'inactivité)"
    return round(base * 2) / 2, note
