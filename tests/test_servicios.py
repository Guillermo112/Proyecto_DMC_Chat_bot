"""obtener_servicios y GET /mi/servicios con los datos conocidos de anticipa.db."""
import pytest
from fastapi.testclient import TestClient

from app.auth import sesion
from app.data import get_connection, obtener_servicios
from app.main import app

api = TestClient(app)


def _como(cliente_id: int) -> dict:
    token, _ = sesion.emitir_token(cliente_id)
    return {"Authorization": f"Bearer {token}"}


def _por_sede(cliente_id: int, codigo: str) -> dict:
    return {s.sede: s for s in obtener_servicios(cliente_id).servicios if s.codigo_producto == codigo}


# ------------------------------------------------------------------ capa de datos

def test_cs02_incluye_el_servicio_dado_de_baja():
    cusco = _por_sede(2, "MPLS")["Cusco"]
    assert (cusco.estado, cusco.fecha_baja, cusco.tarifa_pactada) == ("baja", "2026-09-30", 12000.0)


def test_cs03_tarifa_pactada_es_la_del_contrato():
    """El MPLS del cliente 3 está pactado a 10 500; la tarifa de lista (12 000) no se expone."""
    lima = _por_sede(3, "MPLS")["Lima"]
    assert (lima.tarifa_pactada, lima.cantidad) == (10500.0, 3)
    assert "tarifa_mensual" not in lima.model_dump()


def test_cs05_sla_como_fraccion():
    trujillo = _por_sede(5, "MPLS")["Trujillo"]
    assert trujillo.sla_pactado == pytest.approx(0.997) and trujillo.cantidad == 2


def test_cs10_fecha_de_activacion():
    assert _por_sede(9, "INT500")["Arequipa"].fecha_activacion == "2026-09-15"


def test_movil_trae_gb_y_no_sla():
    movil = _por_sede(4, "MOV")["Lima"]
    assert (movil.gb_incluidos_por_linea, movil.precio_gb_exceso, movil.sla_pactado) == (10.0, 2.0, None)
    assert movil.unidad == "línea"


def test_filtro_por_estado():
    assert [s.id_servicio for s in obtener_servicios(2, estado="baja").servicios] == [8]
    activos = obtener_servicios(2, estado="activo").servicios
    assert activos and all(s.estado == "activo" and s.fecha_baja is None for s in activos)
    with pytest.raises(ValueError):
        obtener_servicios(2, estado="x' OR '1'='1")


def test_fecha_corte_es_la_ficticia():
    assert obtener_servicios(1).fecha_corte == "2026-12-05"


@pytest.mark.parametrize("cliente_id", [1, 2, 7, 13])
def test_aislamiento_solo_servicios_propios(cliente_id):
    with get_connection() as con:
        esperados = [r[0] for r in con.execute(
            "SELECT id_servicio FROM servicio_contratado WHERE id_cliente = ? ORDER BY id_servicio", (cliente_id,))]
    assert [s.id_servicio for s in obtener_servicios(cliente_id).servicios] == esperados


def test_cliente_inexistente_no_ve_nada():
    assert obtener_servicios(999_999).servicios == []


@pytest.mark.parametrize("cliente_id", [0, -1, "1", True])
def test_cliente_id_invalido(cliente_id):
    with pytest.raises(ValueError):
        obtener_servicios(cliente_id)


# ------------------------------------------------------------------ API

def test_api_servicios_del_token():
    r = api.get("/mi/servicios", params={"cliente_id": 3}, headers=_como(2))
    assert r.status_code == 200
    datos = r.json()
    assert {s["sede"] for s in datos["servicios"]} >= {"Cusco"}
    assert [s["id_servicio"] for s in datos["servicios"]] == [s.id_servicio for s in obtener_servicios(2).servicios]


def test_api_filtro_estado():
    r = api.get("/mi/servicios", params={"estado": "baja"}, headers=_como(2))
    assert r.status_code == 200 and [s["id_servicio"] for s in r.json()["servicios"]] == [8]
    assert api.get("/mi/servicios", params={"estado": "suspendido"}, headers=_como(2)).status_code == 422


def test_api_servicios_sin_token_es_401():
    assert api.get("/mi/servicios").status_code == 401
