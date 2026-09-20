"""
normalise.py — le référentiel comme unique point de vérité.

Toute lecture de l'historique passe par ici. Rien d'autre dans le projet ne
doit manipuler un libellé brut : ni le calcul de déficit, ni les dashboards.

Deux responsabilités :
  1. résoudre libellé saisi -> exercice canonique (via une clé tolérante)
  2. signaler dans le classeur ce qui n'a pas pu être résolu
"""

import re
import unicodedata
import difflib

import pandas as pd

ONGLET_A_NORMALISER = "A_normaliser"
JAUNE = {"red": 1.0, "green": 0.92, "blue": 0.6}
ROUGE = {"red": 1.0, "green": 0.80, "blue": 0.80}


# ---------------------------------------------------------------- clé

def cle(libelle) -> str:
    """Clé de rapprochement : minuscules, sans accents, espaces normalisés.

    Absorbe 45 des 255 alias actuels, qui ne sont que des variantes de
    saisie. Vérifié sans ambiguïté sur le référentiel : aucune clé ne
    pointe vers deux exercices canoniques différents.
    """
    s = str(libelle).strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ---------------------------------------------------- résolution

def construire_index(ref: pd.DataFrame) -> dict:
    """clé -> ligne canonique. Lève si le référentiel est ambigu."""
    ref = ref.copy()
    ref["_k"] = ref["Unique"].apply(cle)

    ambigus = ref.groupby("_k")["Unique_exercice"].nunique()
    ambigus = ambigus[ambigus > 1]
    if len(ambigus):
        details = {k: ref.loc[ref._k == k, "Unique_exercice"].unique().tolist()
                   for k in ambigus.index}
        raise ValueError(f"Référentiel ambigu, à corriger avant tout calcul : {details}")

    index = (ref.drop_duplicates("_k")
                .set_index("_k")[["Unique_exercice", "Muscular_group",
                                  "Sub_group", "Weight", "Rating / 10"]]
                .to_dict("index"))

    # Tout nom canonique est automatiquement son propre alias. Sans ça, saisir
    # "Military Dumbells" au lieu de "Développé militaire" produit un orphelin
    # alors que l'exercice existe : le canonique n'est pas toujours dans Unique.
    for r in ref.drop_duplicates("Unique_exercice").itertuples():
        k = cle(r.Unique_exercice)
        if k and k not in index:
            index[k] = {"Unique_exercice": str(r.Unique_exercice).strip(),
                        "Muscular_group": r.Muscular_group,
                        "Sub_group": r.Sub_group, "Weight": r.Weight,
                        "Rating / 10": getattr(r, "_6", None) or r[-1]}
    return index


def resoudre(hist: pd.DataFrame, ref: pd.DataFrame):
    """Renvoie (historique enrichi et résolu, tableau des orphelins).

    Les orphelins sont retirés des calculs — mais jamais silencieusement :
    ils repartent dans le second DataFrame pour être écrits dans le classeur.
    """
    index = construire_index(ref)
    hist = hist.copy()
    hist["_k"] = hist["id_exercice"].apply(cle)

    connu = hist["_k"].isin(index)
    resolu = hist[connu].copy()
    for col in ["Unique_exercice", "Muscular_group", "Sub_group", "Weight"]:
        resolu[col] = resolu["_k"].map(lambda k: index[k][col])
    resolu["rating"] = resolu["_k"].map(lambda k: index[k]["Rating / 10"])

    inconnus = hist[~connu & hist["_k"].astype(bool) & (hist["_k"] != "nan")]
    if inconnus.empty:
        return resolu, pd.DataFrame()

    cles_connues = list(index.keys())
    orphelins = (inconnus.groupby("_k")
                 .agg(libelle=("id_exercice", "first"),
                      occurrences=("id_exercice", "size"),
                      premiere=("Date", "min"),
                      derniere=("Date", "max"))
                 .reset_index())

    def suggerer(k):
        p = difflib.get_close_matches(k, cles_connues, n=1, cutoff=0.72)
        return index[p[0]]["Unique_exercice"] if p else ""

    orphelins["suggestion"] = orphelins["_k"].apply(suggerer)
    orphelins["bloquant"] = orphelins["derniere"] >= (
        pd.Timestamp.now().normalize() - pd.Timedelta(days=7))
    return resolu, orphelins.sort_values("derniere", ascending=False)


# ---------------------------------------------------- signalement

def publier_orphelins(classeur, orphelins: pd.DataFrame) -> str:
    """Écrit l'onglet A_normaliser et renvoie un message de synthèse.

    L'onglet est recréé à chaque exécution : il reflète l'état courant, ce
    n'est pas un journal. Une ligne qui disparaît = un exercice documenté.
    """
    try:
        ws = classeur.worksheet(ONGLET_A_NORMALISER)
        ws.clear()
    except Exception:
        ws = classeur.add_worksheet(ONGLET_A_NORMALISER, rows=200, cols=8)

    entete = ["libellé saisi", "occurrences", "première", "dernière",
              "suggestion", "→ Unique_exercice", "Sub_group", "Weight"]

    if orphelins.empty:
        ws.update([entete, ["Rien à normaliser."] + [""] * 7])
        return ""

    lignes = [entete]
    for o in orphelins.itertuples():
        lignes.append([o.libelle, o.occurrences,
                       f"{o.premiere:%d/%m/%Y}", f"{o.derniere:%d/%m/%Y}",
                       o.suggestion, "", "", ""])
    ws.update(lignes)

    # surbrillance : rouge si l'exercice a été fait dans les 7 derniers jours
    # (les calculs de la semaine sont alors faux), jaune sinon
    for i, o in enumerate(orphelins.itertuples(), start=2):
        ws.format(f"A{i}:H{i}",
                  {"backgroundColor": ROUGE if o.bloquant else JAUNE})

    ws.format("A1:H1", {"textFormat": {"bold": True}})

    n_bloq = int(orphelins["bloquant"].sum())
    msg = (f"{len(orphelins)} libellé(s) hors référentiel — "
           f"voir l'onglet {ONGLET_A_NORMALISER}")
    if n_bloq:
        msg += (f". {n_bloq} concerne(nt) les 7 derniers jours : "
                "le volume de la semaine est sous-estimé.")
    return msg


# ---------------------------------------------------- intensité

def parse_intensite(v):
    """'RPE 8' -> 8 ; 'difficile - RIR 2' -> 8 ; 'Échec' -> 10 ; sinon NaN."""
    import numpy as np
    s = str(v).lower()
    m = re.search(r"rpe\s*(\d+)", s)
    if m:
        return float(m.group(1))
    m = re.search(r"rir\s*(\d+)", s)
    if m:
        return 10.0 - float(m.group(1))
    if "chec" in s and "chauff" not in s:
        return 10.0
    return np.nan


def to_float(v):
    import numpy as np
    try:
        return float(str(v).replace(",", ".").strip())
    except (ValueError, TypeError):
        return np.nan


COLONNES_HISTORIQUE = ["Date", "id_exercice", "série numéro", "poids", "RPE like"]
COLONNES_REFERENTIEL = ["Unique", "Unique_exercice", "Sub_group", "Weight", "Rating / 10"]


def verifier_colonnes(df, attendues, quoi):
    """Message lisible plutôt qu'une KeyError pandas trois niveaux plus bas."""
    if df is None or df.empty:
        raise SystemExit(
            f"\n[X] {quoi} est vide ou introuvable.\n"
            f"    En mode SOURCE=csv, attendu : data/{quoi}.csv\n"
            f"    Exporte l'onglet correspondant depuis Google Sheets "
            f"(Fichier > Telecharger > CSV).\n")
    manquantes = [c for c in attendues if c not in df.columns]
    if manquantes:
        raise SystemExit(
            f"\n[X] {quoi} : colonnes manquantes {manquantes}\n"
            f"    Colonnes trouvees : {list(df.columns)}\n"
            f"    Verifie que la premiere ligne du CSV est bien l'en-tete.\n")


def est_realisee(df):
    """Masque des lignes effectivement exécutées (par opposition à proposées)."""
    rpe = df["RPE like"].fillna("").astype(str).str.strip() != ""
    res = df.get("Ressenti", pd.Series("", index=df.index))
    res = res.fillna("").astype(str).str.strip() != ""
    return rpe | res


def preparer_historique(hist, ref):
    """Pipeline complet : dates, intensités, résolution, séries de travail.

    Renvoie (historique propre, orphelins). Une série de travail est une
    ligne hors échauffement dont le numéro de série est >= 1.
    """
    verifier_colonnes(ref, COLONNES_REFERENTIEL, "referentiel")
    h = hist.copy()
    h.columns = [c.strip() for c in h.columns]
    verifier_colonnes(h, COLONNES_HISTORIQUE, "historique")
    h["Date"] = pd.to_datetime(h["Date"], dayfirst=True, errors="coerce")
    h = h.dropna(subset=["Date"])
    h["poids"] = h["poids"].apply(to_float)
    h["rpe"] = h["RPE like"].apply(parse_intensite)

    resolu, orphelins = resoudre(h, ref)
    if resolu.empty:
        return resolu, orphelins

    ech = resolu["RPE like"].astype(str).str.lower().str.contains("chauff")
    serie = pd.to_numeric(resolu["série numéro"], errors="coerce")

    # Une série RÉALISÉE porte une trace : un RPE ou un ressenti. Sans ce
    # filtre, une proposition écrite d'avance (série remplie, RPE vide)
    # serait comptée comme du volume et le moteur croirait la séance faite.
    return resolu[~ech & (serie.fillna(1) >= 1) & est_realisee(resolu)], orphelins


VOCABULAIRE = {
    "Pectoraux", "Dorsaux", "Milieu du dos", "Trapezes", "Arriere d'epaule",
    "Epaules laterales", "Epaules anterieures", "Triceps", "Biceps",
    "Brachial", "Avant-bras", "Quadriceps", "Ischios", "Fessiers",
    "Moyen fessier", "Adducteurs", "Mollets", "Lombaires",
}


def verifier_vocabulaire(mapping):
    """Un sous-groupe mal orthographié ne lève aucune erreur : il disparaît
    simplement des calculs. 'Adductors' au lieu d'Adducteurs a fait croire
    pendant une semaine que le sous-groupe n'avait jamais été travaillé.
    """
    inconnus = sorted(set(mapping["sous_groupe"]) - VOCABULAIRE)
    if inconnus:
        exemples = {i: mapping.loc[mapping.sous_groupe == i, "Unique_exercice"]
                    .unique()[:3].tolist() for i in inconnus}
        raise SystemExit(
            f"\n[X] Sous-groupes hors vocabulaire : {inconnus}\n"
            f"    Exercices concernes : {exemples}\n"
            f"    Corrige le referentiel : ces series ne comptent nulle part.\n")
    return True


def eclater(ref):
    """Une ligne par (exercice canonique, sous-groupe) avec sa pondération."""
    vus, lignes = set(), []
    for r in ref.itertuples():
        nom = str(r.Unique_exercice).strip()
        if nom in vus:
            continue
        vus.add(nom)
        sgs = [s.strip() for s in str(r.Sub_group).split("|") if s.strip()]
        pds = [float(p) for p in str(r.Weight).split("|") if p.strip()]
        for i, s in enumerate(sgs):
            lignes.append({"Unique_exercice": nom, "sous_groupe": s,
                           "poids": pds[i] if i < len(pds) else 0.5,
                           "principal": i == 0, "n_sg": len(sgs)})
    df = pd.DataFrame(lignes)
    verifier_vocabulaire(df)
    return df
