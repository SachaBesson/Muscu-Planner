"""Accès Google Sheets. Seul module qui parle au réseau côté données.

Un mode CSV local est prévu pour développer sans authentification :
    export SOURCE=csv   ->  lit data/*.csv
"""
import json
import os
from pathlib import Path

import pandas as pd

from .config import SHEET_ID, SA_KEY_PATH, SA_KEY_JSON, ONGLETS, RACINE

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.readonly"]


def _client():
    import gspread
    from google.oauth2.service_account import Credentials
    if SA_KEY_JSON:                       # CI : le JSON est dans un secret
        info = json.loads(SA_KEY_JSON)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:                                 # local : un fichier
        creds = Credentials.from_service_account_file(SA_KEY_PATH, scopes=SCOPES)
    return gspread.authorize(creds)


def classeur():
    return _client().open_by_key(SHEET_ID)


def _local(nom):
    p = RACINE / "data" / f"{nom}.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    df.columns = [c.strip() for c in df.columns]
    return df


def lire(nom_logique: str) -> pd.DataFrame:
    """Lit un onglet. Renvoie un DataFrame vide si l'onglet n'existe pas."""
    if os.getenv("SOURCE") == "csv":
        return _local(nom_logique)
    try:
        ws = classeur().worksheet(ONGLETS[nom_logique])
    except Exception:
        return pd.DataFrame()
    valeurs = ws.get_all_values()
    if len(valeurs) < 2:
        return pd.DataFrame()
    entete = [c.strip() for c in valeurs[0]]
    return pd.DataFrame(valeurs[1:], columns=entete)


def ecrire(nom_logique: str, df: pd.DataFrame, effacer=True):
    """Remplace le contenu d'un onglet, en le créant au besoin."""
    if os.getenv("SOURCE") == "csv":
        df.to_csv(RACINE / "data" / f"{nom_logique}.csv", index=False)
        return
    cl = classeur()
    titre = ONGLETS[nom_logique]
    try:
        ws = cl.worksheet(titre)
        if effacer:
            ws.clear()
    except Exception:
        ws = cl.add_worksheet(titre, rows=max(200, len(df) + 10),
                              cols=max(12, len(df.columns)))
    ws.update([df.columns.tolist()] + df.astype(str).values.tolist())


def ajouter(nom_logique: str, lignes: list[list], colonnes=None):
    """Append-only : Feedback, et proposition écrite dans l'historique."""
    if os.getenv("SOURCE") == "csv":
        p = RACINE / "data" / f"{nom_logique}.csv"
        df = pd.DataFrame(lignes, columns=colonnes) if colonnes else pd.DataFrame(lignes)
        if p.exists():
            entete = [c.strip() for c in pd.read_csv(p, nrows=0).columns]
            # Aligne sur la largeur du fichier cible : on tronque le surplus
            # et on complète les colonnes manquantes par du vide.
            df = df.iloc[:, :len(entete)]
            for i in range(df.shape[1], len(entete)):
                df[i] = ""
            df.columns = entete
        df.to_csv(p, mode="a", header=not p.exists(), index=False)
        return
    classeur().worksheet(ONGLETS[nom_logique]).append_rows(
        lignes, value_input_option="USER_ENTERED")


def ajouter_proposition(df):
    """Écrit la proposition à la suite de F_exercicesDone, RPE vide.

    Pas d'onglet séparé : la proposition A le schéma de l'historique. Une
    copie immuable part dans Propositions_log pour que le diff ait un point
    de comparaison même après que tu aies écrasé reps et poids.
    """
    lignes = df.astype(str).values.tolist()
    cols = df.columns.tolist()
    ajouter("historique", lignes)
    # Copie immuable : le diff en a besoin puisque tu écraseras reps et poids.
    ajouter("propositions_log", lignes, colonnes=cols)


def supprimer_bloc(nom_logique: str, dates: set):
    """Retire les lignes d'une proposition périmée. gspread n'a pas de
    suppression par filtre : on relit, on filtre, on réécrit."""
    df = lire(nom_logique)
    if df.empty:
        return 0
    garde = ~df["Date"].astype(str).str.strip().isin({str(d) for d in dates})
    n = int((~garde).sum())
    if n:
        ecrire(nom_logique, df[garde])
    return n
