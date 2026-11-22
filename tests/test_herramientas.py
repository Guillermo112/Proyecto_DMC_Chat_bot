"""Herramientas del agente: el cliente lo pone el código, nunca el modelo."""
import shutil
import sqlite3

import pytest

from app import config
from app.tools import ESQUEMAS, NOMBRES, Herramientas


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Copia de la base: registrar_caso escribe."""
    copia = tmp_path / "anticipa.db"
    shutil.copy(config.DB_PATH, copia)
    monkeypatch.setattr(config, "DB_PATH", copia)
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", False)
    return copia


def test_ningun_esquema_declara_cliente_id():
    for esquema in ESQUEMAS:
        assert "cliente_id" not in esquema["parameters"]["properties"], esquema["name"]
        assert esquema["description"]


def test_cliente_id_del_modelo_se_ignora():
    """El modelo pide la duplicada del cliente 1 diciendo ser el cliente 2: se ignora."""
    h = Herramientas(2)
    assert h.ejecutar("ver_factura", {"numero": "F001-000254", "cliente_id": 1}) == {
        "error": "No encontrado para este cliente."}
    assert Herramientas(1).ejecutar("ver_factura", {"numero": "F001-000254", "cliente_id": 2})["numero"] == "F001-000254"


def test_detectar_anomalias_del_cliente_1():
    r = Herramientas(1).ejecutar("detectar_anomalias", {})
    assert r["cantidad"] >= 1 and r["facturas_duplicadas"]


@pytest.mark.parametrize("nombre, args", [
    ("listar_facturas", {"periodo": "2026-13"}),
    ("ver_servicios", {"estado": "otro"}),
    ("comparar_periodos", {}),          # falta periodo_b
    ("inventada", {}),
])
def test_errores_vuelven_como_mensaje(nombre, args):
    r = Herramientas(1).ejecutar(nombre, args)
    assert set(r) == {"error"} and r["error"]


def test_cada_esquema_tiene_funcion():
    h = Herramientas(1)
    assert set(h._funciones()) == NOMBRES


def test_registrar_caso_usa_canal_web_y_palabras_del_turno(base):
    h = Herramientas(1, palabras_cliente="Me llegaron dos facturas iguales")
    r = h.ejecutar("registrar_caso", {"tipo": "factura_duplicada", "resumen": "Duplicada de noviembre",
                                      "numero_factura": "F001-000255", "canal": "telegram"})
    assert r["numero_caso"] and r["tipo"] == "factura_duplicada"
    con = sqlite3.connect(base)
    canal, = con.execute("SELECT canal FROM caso ORDER BY id_caso DESC LIMIT 1").fetchone()
    assert canal == "web"


def test_registrar_caso_sin_anomalia_explica_el_error(base):
    r = Herramientas(11).ejecutar("registrar_caso", {"tipo": "factura_duplicada"})
    assert "error" in r


def test_cliente_invalido():
    with pytest.raises(ValueError):
        Herramientas(0)
