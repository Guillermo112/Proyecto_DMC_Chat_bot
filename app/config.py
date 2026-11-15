"""Configuración leída de variables de entorno (con valores por defecto).

Si existe un archivo `.env` en la raíz del proyecto, se carga primero.
Las variables ya definidas en el sistema tienen prioridad sobre el `.env`.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ_PROYECTO / ".env", override=False)

# Ruta de la base SQLite. Relativa a la raíz del proyecto si no es absoluta.
DB_PATH = Path(os.getenv("ANTICIPA_DB_PATH", "db/anticipa.db"))
if not DB_PATH.is_absolute():
    DB_PATH = RAIZ_PROYECTO / DB_PATH

# Paginación de listados.
LIMITE_POR_DEFECTO = int(os.getenv("LIMITE_POR_DEFECTO", "20"))
LIMITE_MAXIMO = int(os.getenv("LIMITE_MAXIMO", "100"))
