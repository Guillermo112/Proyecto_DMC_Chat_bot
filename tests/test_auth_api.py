"""Endpoints /auth y cierre de /api/verificaciones, sobre una copia de la base."""
import re
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth import otp
from app.main import app


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    copia = tmp_path / "anticipa.db"
    shutil.copy(config.DB_PATH, copia)
    monkeypatch.setattr(config, "DB_PATH", copia)
    enviados = []
    monkeypatch.setattr(otp, "enviar_correo", lambda destino, asunto, cuerpo: enviados.append(cuerpo))
    with sqlite3.connect(copia) as con:
        ruc = con.execute("SELECT ruc FROM cliente WHERE id_cliente = 1").fetchone()[0]
    return TestClient(app), enviados, ruc, copia


def _codigo(enviados):
    return re.search(r"\b(\d{6})\b", enviados[-1]).group(1)


def test_flujo_completo(cliente):
    api, enviados, ruc, _ = cliente
    r = api.post("/auth/solicitar-codigo", json={"ruc": ruc})
    assert r.status_code == 200
    id_v = r.json()["id_verificacion"]
    r = api.post("/auth/verificar-codigo", json={"id_verificacion": id_v, "codigo": _codigo(enviados)})
    assert r.status_code == 200
    datos = r.json()
    assert datos["verificado"] is True and datos["cliente_id"] == 1
    assert datos["token_type"] == "bearer" and datos["expira_en"] == config.AUTH_MINUTOS_SESION * 60
    # El token identifica al cliente verificado en las peticiones siguientes.
    r = api.get("/auth/sesion", headers={"Authorization": f"Bearer {datos['access_token']}"})
    assert r.status_code == 200 and r.json() == {"cliente_id": 1}


def test_codigo_incorrecto_es_401(cliente):
    api, enviados, ruc, _ = cliente
    id_v = api.post("/auth/solicitar-codigo", json={"ruc": ruc}).json()["id_verificacion"]
    malo = "000000" if _codigo(enviados) != "000000" else "111111"
    r = api.post("/auth/verificar-codigo", json={"id_verificacion": id_v, "codigo": malo})
    assert r.status_code == 401


def test_ruc_desconocido_responde_igual(cliente):
    api, enviados, ruc, _ = cliente
    conocido = api.post("/auth/solicitar-codigo", json={"ruc": ruc}).json()
    desconocido = api.post("/auth/solicitar-codigo", json={"ruc": "99999999999"}).json()
    assert conocido.keys() == desconocido.keys()
    assert conocido["mensaje"] == desconocido["mensaje"]
    assert len(enviados) == 1  # al RUC desconocido no se le envía nada


def test_ruc_mal_formado_es_422(cliente):
    api, *_ = cliente
    assert api.post("/auth/solicitar-codigo", json={"ruc": "123"}).status_code == 422


def test_reenvio_no_revela_si_el_ruc_existe(cliente):
    """Pedir dos veces seguidas responde igual para un RUC de cliente y uno inexistente."""
    api, enviados, ruc, _ = cliente

    def dos_veces(r):
        return [api.post("/auth/solicitar-codigo", json={"ruc": r}) for _ in range(2)]

    existente, inexistente = dos_veces(ruc), dos_veces("99999999999")
    for a, b in zip(existente, inexistente):
        assert a.status_code == b.status_code == 200
        assert a.json().keys() == b.json().keys()
        assert a.json()["mensaje"] == b.json()["mensaje"]
    # Siempre un id nuevo, en ambos casos.
    assert existente[0].json()["id_verificacion"] != existente[1].json()["id_verificacion"]
    assert inexistente[0].json()["id_verificacion"] != inexistente[1].json()["id_verificacion"]
    assert len(enviados) == 1  # solo el primer pedido del RUC existente envía correo


def test_reenvio_prematuro_el_codigo_recibido_sirve_con_el_ultimo_id(cliente):
    api, enviados, ruc, _ = cliente
    api.post("/auth/solicitar-codigo", json={"ruc": ruc})
    ultimo = api.post("/auth/solicitar-codigo", json={"ruc": ruc}).json()["id_verificacion"]
    r = api.post("/auth/verificar-codigo", json={"id_verificacion": ultimo, "codigo": _codigo(enviados)})
    assert r.status_code == 200 and r.json()["cliente_id"] == 1


def test_sin_secreto_ruc_existente_e_inexistente_responden_igual(cliente, monkeypatch):
    api, enviados, ruc, _ = cliente
    monkeypatch.setattr(config, "AUTH_SECRET", "")
    a = api.post("/auth/solicitar-codigo", json={"ruc": ruc})
    b = api.post("/auth/solicitar-codigo", json={"ruc": "99999999999"})
    assert a.status_code == b.status_code == 503 and a.json() == b.json()


def test_fallo_de_correo_es_503(cliente, monkeypatch):
    api, _, ruc, copia = cliente

    def falla(*_):
        raise RuntimeError("SMTP caído")

    monkeypatch.setattr(otp, "enviar_correo", falla)
    assert api.post("/auth/solicitar-codigo", json={"ruc": ruc}).status_code == 503
    with sqlite3.connect(copia) as con:  # la transacción se revirtió
        assert con.execute("SELECT COUNT(*) FROM verificacion WHERE ruc_ingresado = ?", (ruc,)).fetchone()[0] == 0


@pytest.mark.parametrize("metodo,ruta", [
    ("get", "/api/verificaciones"),
    ("get", "/api/verificaciones/1"),
    ("put", "/api/verificaciones/1"),
    ("get", "/api/verificaciones/ultima/20100000001"),
    ("patch", "/api/verificaciones/1/bloquear"),
    ("patch", "/api/verificaciones/1/incrementar-intentos"),
    ("post", "/api/verificaciones/buscar"),
])
def test_crud_de_verificaciones_no_expuesto(cliente, metodo, ruta):
    api, *_ = cliente
    r = getattr(api, metodo)(ruta, **({"json": {}} if metodo in ("put", "post") else {}))
    assert r.status_code in (404, 405)


def test_verificar_sin_secreto_es_503(cliente, monkeypatch):
    api, enviados, ruc, _ = cliente
    id_v = api.post("/auth/solicitar-codigo", json={"ruc": ruc}).json()["id_verificacion"]
    monkeypatch.setattr(config, "AUTH_SECRET", "")
    r = api.post("/auth/verificar-codigo", json={"id_verificacion": id_v, "codigo": _codigo(enviados)})
    assert r.status_code == 503
