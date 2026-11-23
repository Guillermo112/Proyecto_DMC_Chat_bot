"""docs/casuisticas_api.md no se desincroniza de la API.

- Toda ruta `/mi/...` o `/auth/...` citada existe (con su método, si se indica).
- Los parámetros de consulta citados (`?periodo_b=...`) existen en esa ruta.
- Toda ruta `/mi` y `/auth` de la API aparece en la guía.
"""
import re
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from app.main import app

GUIA = Path(__file__).resolve().parents[1] / "docs" / "casuisticas_api.md"
# `GET /mi/comparar?periodo_b=2026-10`, `/mi/facturas/{numero}`, `POST /auth/verificar-codigo`
_CITA = re.compile(r"`(?:(GET|POST) )?(/(?:mi|auth)(?:/[^`\s?,]*)?)(?:\?([^`\s]*))?`")


def _openapi() -> dict[str, dict]:
    return {p: ops for p, ops in app.openapi()["paths"].items() if p.startswith(("/mi", "/auth"))}


def _plantilla(path: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$")


def _ruta_de(path_citado: str) -> str | None:
    for path in _openapi():
        if _plantilla(path).match(path_citado):
            return path
    return None


def _citas() -> list[tuple[str | None, str, str | None]]:
    """Rutas citadas; ignora menciones genéricas como `/mi` o `/mi/...`."""
    return [c for c in _CITA.findall(GUIA.read_text(encoding="utf-8"))
            if c[1] not in ("/mi", "/auth") and "..." not in c[1]]


def test_la_guia_cita_rutas():
    assert len(_citas()) > 20


@pytest.mark.parametrize("metodo, path, query", sorted(set(_citas()), key=str))
def test_cada_ruta_citada_existe(metodo, path, query):
    ruta = _ruta_de(path)
    assert ruta, f"{path} no existe en la API"
    ops = _openapi()[ruta]
    if metodo:
        assert metodo.lower() in ops, f"{metodo} {path} no existe"
    if query:
        op = ops.get((metodo or "get").lower())
        assert op, f"{path} no tiene GET para los parámetros {query}"
        permitidos = {p["name"] for p in op.get("parameters", []) if p["in"] == "query"}
        citados = set(parse_qs(query, keep_blank_values=True)) or {query.split("=")[0]}
        assert citados <= permitidos, f"{path}?{query}: {citados - permitidos} no son parámetros de la ruta"


def test_toda_ruta_mi_y_auth_esta_en_la_guia():
    citadas = {_ruta_de(path) for _, path, _ in _citas()}
    faltan = set(_openapi()) - citadas
    assert not faltan, f"Rutas sin documentar en {GUIA.name}: {sorted(faltan)}"
