"""Tests de la couche de normalisation — la plus critique du projet.

Une erreur ici fausse silencieusement tous les calculs en aval.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import normalise as N


def test_cle_absorbe_casse_accents_espaces():
    assert N.cle("  Tirage Vertical  MACHINE ") == "tirage vertical machine"
    assert N.cle("Unilatéral triceps rope") == N.cle("unilateral triceps rope")
    assert N.cle("bench dumbells ") == N.cle("Bench dumbells")


def test_parse_intensite():
    assert N.parse_intensite("RPE 8") == 8
    assert N.parse_intensite("difficile - RIR 2") == 8
    assert N.parse_intensite("Échec") == 10
    assert pd.isna(N.parse_intensite("Échauffement"))


def test_referentiel_ambigu_leve():
    """Mieux vaut un job en échec qu'un calcul sur des données douteuses."""
    ref = pd.DataFrame({
        "Unique": ["Squat", "squat "],
        "Unique_exercice": ["Hack Squat", "Leg Press"],
        "Muscular_group": ["Legs"] * 2,
        "Sub_group": ["Quadriceps"] * 2,
        "Weight": ["1"] * 2,
        "Rating / 10": [7, 8],
    })
    with pytest.raises(ValueError, match="ambigu"):
        N.construire_index(ref)


def test_orphelin_signale_avec_suggestion():
    ref = pd.DataFrame({
        "Unique": ["Leg press"], "Unique_exercice": ["Leg Press"],
        "Muscular_group": ["Legs"], "Sub_group": ["Quadriceps|Fessiers"],
        "Weight": ["1|0.5"], "Rating / 10": [8],
    })
    hist = pd.DataFrame({
        "Date": pd.to_datetime(["2026-09-01", "2026-09-02"]),
        "id_exercice": ["Leg press", "Presse a cuisse"],
    })
    resolu, orph = N.resoudre(hist, ref)
    assert len(resolu) == 1
    assert len(orph) == 1
    assert orph.iloc[0]["libelle"] == "Presse a cuisse"
