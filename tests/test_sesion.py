"""Token de sesión (JWT) y dependencia `cliente_actual`, vía GET /auth/sesion."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth import sesion
from app.main import app

api = TestClient(app)


def _get(token: str | None, esquema: str = "Bearer"):
    headers = {"Authorization": f"{esquema} {token}"} if token is not None else {}
    return api.get("/auth/sesion", headers=headers)


def _firmar(secreto: str | None = None, **cambios) -> str:
    """Token con los claims normales salvo los indicados (valor None = quitar el claim).

    Se firma en el momento (no al importar) para usar el secreto de prueba del conftest.
    """
    ahora = datetime.now(timezone.utc)
    claims = {"sub": "1", "iss": sesion.EMISOR, "typ": sesion.TIPO, "iat": ahora,
              "exp": ahora + timedelta(minutes=5)}
    claims.update(cambios)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, secreto or config.AUTH_SECRET, algorithm="HS256")


def test_firmar_sin_cambios_es_valido():
    """Control: los casos inválidos fallan por lo que cambian, no por _firmar."""
    assert _get(_firmar()).status_code == 200


def test_token_valido_devuelve_su_cliente():
    token, segundos = sesion.emitir_token(7)
    assert segundos == config.AUTH_MINUTOS_SESION * 60
    r = _get(token)
    assert r.status_code == 200 and r.json() == {"cliente_id": 7}


def test_sin_token_es_401():
    r = _get(None)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_esquema_distinto_de_bearer_es_401():
    token, _ = sesion.emitir_token(1)
    assert _get(token, esquema="Basic").status_code == 401


def test_token_expirado_es_401():
    pasado = datetime.now(timezone.utc) - timedelta(minutes=1)
    r = _get(_firmar(iat=pasado - timedelta(minutes=30), exp=pasado))
    assert r.status_code == 401
    assert "expiró" in r.json()["detail"]


def test_sesion_dura_lo_configurado(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MINUTOS_SESION", 1)
    token, segundos = sesion.emitir_token(1)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert segundos == 60 and claims["exp"] - claims["iat"] == 60


@pytest.mark.parametrize("cambios", [
    {"secreto": "otro-secreto-que-no-es-el-de-la-app-" + "z" * 16},  # firma con otra clave
    {"iss": "otro-emisor"},
    {"typ": "otro"},
    {"sub": "abc"},
    {"sub": None},
    {"exp": None},
    {"iss": None},
])
def test_token_invalido_es_401(cambios):
    assert _get(_firmar(**cambios)).status_code == 401


def test_texto_que_no_es_jwt_es_401():
    assert _get("no-es-un-jwt").status_code == 401


def test_token_alterado_es_401():
    token, _ = sesion.emitir_token(1)
    cabecera, cuerpo, firma = token.split(".")
    # Cambiar el cliente en el cuerpo sin volver a firmar.
    otro = jwt.encode({"sub": "2"}, "x" * 40, algorithm="HS256").split(".")[1]
    assert _get(f"{cabecera}.{otro}.{firma}").status_code == 401


def test_algoritmo_none_rechazado():
    sin_firma = jwt.encode({"sub": "1", "iss": sesion.EMISOR, "typ": sesion.TIPO,
                            "iat": datetime.now(timezone.utc),
                            "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                           key=None, algorithm="none")
    assert _get(sin_firma).status_code == 401


def test_cambiar_el_secreto_invalida_sesiones(monkeypatch):
    token, _ = sesion.emitir_token(1)
    monkeypatch.setattr(config, "AUTH_SECRET", "secreto-rotado-" + "w" * 32)
    assert _get(token).status_code == 401


def test_sin_secreto_es_503(monkeypatch):
    token, _ = sesion.emitir_token(1)
    monkeypatch.setattr(config, "AUTH_SECRET", "")
    assert _get(token).status_code == 503
