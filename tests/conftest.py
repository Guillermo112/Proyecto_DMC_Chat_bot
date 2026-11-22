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


@pytest.fixture(autouse=True)
def _secreto_de_prueba(monkeypatch):
    """Los tests no dependen del AUTH_SECRET del .env de cada integrante."""
    monkeypatch.setattr(config, "AUTH_SECRET", "secreto-de-prueba-" + "x" * 32)


@pytest.fixture(autouse=True)
def _limite_por_ip_limpio():
    """Cada test empieza sin solicitudes contadas (TestClient usa siempre la misma IP)."""
    from app.auth.limite import limitador_solicitudes

    limitador_solicitudes.reiniciar()
    yield
    limitador_solicitudes.reiniciar()


@pytest.fixture(autouse=True)
def _sin_bot_de_telegram(monkeypatch):
    """Los tests nunca levantan el bot real con el token del .env de quien los corre
    (el lifespan de la app lo arrancaría y saldría a la red)."""
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_USUARIOS_PERMITIDOS", frozenset())
