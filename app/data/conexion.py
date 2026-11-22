"""
Conexión a SQLite: solo lectura por defecto, escritura explícita con `escritura=True`.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import config


@contextmanager
def get_connection(db_path: Path | None = None, escritura: bool = False) -> Iterator[sqlite3.Connection]:
    """Abre la base (solo lectura por defecto) y la cierra al salir.

    `escritura=True` (mode=rw) es solo para app/auth y las operaciones de escritura
    del CRUD; el agente nunca la usa. Al salir sin error se confirma la transacción;
    si hay una excepción se revierte.
    """
    ruta = Path(db_path or config.DB_PATH).resolve()
    if not ruta.is_file():
        raise FileNotFoundError(f"No se encontró la base de datos: {ruta}")
    modo = "rw" if escritura else "ro"
    con = sqlite3.connect(f"{ruta.as_uri()}?mode={modo}", uri=True, timeout=30)
    con.row_factory = sqlite3.Row

    try:
        # Habilitar claves foráneas
        con.execute("PRAGMA foreign_keys = ON")

        yield con

        # Confirmar transacciones
        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()
