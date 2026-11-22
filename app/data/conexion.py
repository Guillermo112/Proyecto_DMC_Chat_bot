"""
Conexión a SQLite en modo lectura y escritura.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import config


@contextmanager
def get_connection(
    db_path: Path | None = None
) -> Iterator[sqlite3.Connection]:

    """Abre la base de datos en modo lectura y escritura."""

    ruta = Path(db_path or config.DB_PATH).resolve()

    if not ruta.exists():
        raise FileNotFoundError(
            f"No se encontró la base de datos: {ruta}"
        )

    # Conexión en modo lectura y escritura
    con = sqlite3.connect(
        str(ruta),
        timeout=30
    )

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