"""Conexión a SQLite en modo solo lectura."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import config


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Abre la base en modo solo lectura (mode=ro) y la cierra al salir."""
    ruta = Path(db_path or config.DB_PATH).resolve()
    if not ruta.is_file():
        raise FileNotFoundError(f"No se encontró la base de datos: {ruta}")
    con = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()
