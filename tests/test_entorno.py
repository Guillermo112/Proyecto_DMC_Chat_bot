"""El CRUD /api/... solo se monta con ENTORNO=dev.

La app se arma al importar app.main, así que cada entorno se prueba en un
proceso aparte (no se puede re-importar sin afectar a los demás tests).
"""
import json
import os
import subprocess
import sys

import pytest

from app import config

_SCRIPT = """
import json
from app.main import app
print(json.dumps(sorted(app.openapi()["paths"])))
"""


def _rutas(entorno: str) -> list[str]:
    """Rutas de la app levantada con ENTORNO=entorno.

    Se define siempre (aunque sea vacío) porque python-dotenv no pisa variables ya
    definidas: así el .env de quien corre los tests no interfiere. Vacío = sin definir.
    """
    env = {**os.environ, "ENTORNO": entorno}
    salida = subprocess.run(
        [sys.executable, "-c", _SCRIPT], cwd=config.RAIZ_PROYECTO, env=env,
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(salida.strip().splitlines()[-1])


def _api(rutas):
    return [r for r in rutas if r.startswith("/api")]


@pytest.mark.parametrize("entorno", ["dev", " DEV "])
def test_dev_monta_el_crud(entorno):
    rutas = _rutas(entorno)
    assert "/api/clientes/{registro_id}" in rutas
    assert "/api/clientes/por-ruc/{ruc}" in rutas
    assert "/api/ajustes/{ajuste_id}/aprobar" in rutas
    assert "/api/{entidad}/buscar" in rutas


@pytest.mark.parametrize("entorno", ["prod", "produccion", "development", ""])
def test_fuera_de_dev_no_hay_api(entorno):
    """Solo "dev" exacto lo monta; sin definir (vacío) cuenta como prod."""
    rutas = _rutas(entorno)
    assert _api(rutas) == []
    # Lo público sigue disponible.
    for ruta in ("/health", "/auth/solicitar-codigo", "/auth/verificar-codigo", "/auth/sesion", "/mi/saldo"):
        assert ruta in rutas
