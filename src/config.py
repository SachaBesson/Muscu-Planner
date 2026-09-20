"""Chargement de la configuration. Aucun seuil en dur ailleurs dans le projet."""
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent
load_dotenv(RACINE / ".env")


def _yaml(nom):
    return yaml.safe_load((RACINE / "config" / nom).read_text(encoding="utf-8"))


CIBLES_CFG = _yaml("cibles.yaml")
CIBLES = CIBLES_CFG["cibles"]
SUIVIS_SANS_CIBLE = CIBLES_CFG["suivis_sans_cible"]
DISCIPLINES = _yaml("disciplines.yaml")
RESSENTI = DISCIPLINES.pop("ressenti")
REGLES = _yaml("regles.yaml")

SHEET_ID = os.getenv("SHEET_ID", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.5-flash-lite")
PROJECT_ID = os.getenv("PROJECT_ID", "call-gym-508516")
SA_KEY_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
SA_KEY_JSON = os.getenv("GCP_SA_KEY", "")   # utilisé en CI

ONGLETS = {
    "referentiel": "Référentiel",
    "historique": "F_exercicesDone",
    "proposition": "Proposition",
    "activites": "Activites",
    "feedback": "Feedback",
    "a_normaliser": "A_normaliser",
    "dashboard": "Dashboard_export",
    "propositions_log": "Propositions_log",
    "calendrier": "Calendrier",
}
