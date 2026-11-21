"""Conexión a SQLite en modo solo lectura."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import config


@contextmanager
def get_connection(db_path: Path | None = None, escritura: bool = False) -> Iterator[sqlite3.Connection]:
    """Abre la base (solo lectura por defecto) y la cierra al salir.

    `escritura=True` (mode=rw) es solo para app/auth; el agente nunca la usa.
    """
    ruta = Path(db_path or config.DB_PATH).resolve()
    if not ruta.is_file():
        raise FileNotFoundError(f"No se encontró la base de datos: {ruta}")
    modo = "rw" if escritura else "ro"
    con = sqlite3.connect(f"{ruta.as_uri()}?mode={modo}", uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()
