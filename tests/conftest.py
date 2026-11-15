import pytest

from app import config


@pytest.fixture(scope="session", autouse=True)
def _db_existe():
    if not config.DB_PATH.is_file():
        pytest.exit(
            f"No existe la base de pruebas: {config.DB_PATH}. "
            "Genérala con: python -X utf8 db/generar_datos.py",
            returncode=1,
        )
