"""Appel Gemini avec sortie structurée.

Règle absolue : le LLM CHOISIT dans un ensemble fermé, il ne PRODUIT jamais
un nombre qui compte. Pas de charge, pas de volume, pas de série dans le
schéma. Tout cela vient de Python et lui est réinjecté après coup.
"""
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .config import GEMINI_API_KEY, MODEL_ID

TEMPERATURE = 0.2


# ------------------------------------------------- schéma de sortie
# L'ordre des champs compte : si le prompt contient un exemple, ses clés
# doivent apparaître dans le MÊME ordre, sinon la sortie se dégrade.

class ExerciceSeance(BaseModel):
    ordre: int = Field(description="Position dans la séance, à partir de 1")
    id_exercice: str = Field(description="Repris EXACTEMENT de la shortlist")
    reps_cible: str = Field(description="Ex. '8-10' ou '12'")
    superset_avec: Optional[str] = Field(
        default=None, description="id_exercice enchaîné, sinon null")
    justification: str = Field(description="Une phrase, 15 mots maximum")


class Seance(BaseModel):
    exercices: list[ExerciceSeance]
    note_coach: str = Field(description="Deux phrases maximum pour l'athlète")
    axe_principal: Literal["haut", "bas", "full"]


# ------------------------------------------------- prompt

SYSTEME = """Tu es préparateur physique. L'athlète a 25 ans, s'entraîne en full
body 2 à 3 fois par semaine, a repris la course à pied et vise une Hyrox.
Son bas du dos est fragile et il apprend la charnière de hanche.

CONTRAINTES ABSOLUES
- Choisis UNIQUEMENT des id_exercice présents dans la shortlist. Jamais d'ajout.
- Respecte exactement le nombre d'exercices demandé.
- Équilibre poussée et tirage : écart d'au plus 1.
- Pas deux exercices du même sous_groupe principal au-delà de 2.

ORDONNANCEMENT
- Ce qui s'apprend techniquement passe en premier, à froid.
- Polyarticulaires lourds avant isolation.
- À catégorie égale, le sous-groupe le plus déficitaire d'abord.
- Supersets d'antagonistes autorisés en seconde moitié de séance uniquement.
- Isolation et petits muscles en fin.

Tu ne produis aucune charge ni aucun nombre de séries : ils sont déjà calculés.
"""


def construire_prompt(candidats, deficits, fat, prevues, n_exos, contexte=""):
    lignes = []
    for c in candidats:
        lignes.append(
            f"- {c['id_exercice']} | sous-groupes: {', '.join(c['sous_groupes'])}"
            f" | axe: {c['axe']} | note athlète: {c['note']:.0f}/10"
            f" | déficit couvert: {c['deficit_couvert']}"
            f" | dernière fois il y a {c['jours_depuis']} j")

    defs = sorted(deficits.items(), key=lambda x: -x[1])
    d_txt = "\n".join(f"- {k} : manque {v:.1f} séries" for k, v in defs if v > 0)
    f_txt = ", ".join(f"{k} {v:.1f}" for k, v in sorted(fat.items(), key=lambda x: -x[1])[:6])
    p_txt = ("\n".join(f"- {r.Date:%d/%m} {r.type} {r.duree_min} min RPE {r.rpe}"
                       for r in prevues.itertuples()) or "- rien de prévu")

    return f"""DÉFICITS DE LA SEMAINE
{d_txt or "- aucun"}

FATIGUE LOCALE ACTUELLE
{f_txt or "- aucune"}

ACTIVITÉS PRÉVUES SOUS 48 H
{p_txt}

{contexte}

SHORTLIST ({len(candidats)} candidats éligibles)
{chr(10).join(lignes)}

Compose une séance de {n_exos} exercices et ordonne-la."""


# ------------------------------------------------- appel

def proposer(candidats, deficits, fat, prevues, n_exos, contexte="") -> Seance:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = construire_prompt(candidats, deficits, fat, prevues, n_exos, contexte)

    reponse = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEME,
            temperature=TEMPERATURE,
            max_output_tokens=1500,
            response_mime_type="application/json",
            response_schema=Seance,
        ),
    )
    return Seance.model_validate(json.loads(reponse.text))
