"""consultar_solicitudes y GET /mi/solicitudes (CS-06) con los datos conocidos de anticipa.db."""
import pytest
from fastapi.testclient import TestClient

from app.auth import sesion
from app.data import consultar_solicitudes, get_connection
from app.main import app

api = TestClient(app)


def _como(cliente_id: int) -> dict:
    token, _ = sesion.emitir_token(cliente_id)
    return {"Authorization": f"Bearer {token}"}


def _clientes() -> list[int]:
    with get_connection() as con:
        return [r[0] for r in con.execute("SELECT id_cliente FROM cliente ORDER BY id_cliente")]


def test_cs06_solicitud_fuera_de_plazo():
    """Ejemplo del PDF: abierta desde el 14 de noviembre, 21 días, plazo de 10."""
    r = consultar_solicitudes(10)
    assert (r.fecha_corte, r.plazo_atencion_dias, r.cantidad_fuera_de_plazo) == ("2026-12-05", 10, 1)
    [vencida] = [s for s in r.solicitudes if s.fuera_de_plazo]
    assert (vencida.estado, vencida.fecha_registro, vencida.dias_transcurridos) == ("abierta", "2026-11-14", 21)
    assert vencida.tipo == "actualización de datos" and vencida.responsable_nombre


def test_en_proceso_dentro_de_plazo_y_cerrada_nunca_vencida():
    por_id = {s.id_solicitud: s for s in consultar_solicitudes(10).solicitudes}
    assert (por_id[2].estado, por_id[2].dias_transcurridos, por_id[2].fuera_de_plazo) == ("en_proceso", 5, False)
    # La cerrada cuenta días hasta su cierre (2) y no puede estar fuera de plazo.
    assert (por_id[3].estado, por_id[3].dias_transcurridos, por_id[3].fuera_de_plazo) == ("cerrada", 2, False)


def test_coincide_con_la_vista_para_todos_los_clientes():
    with get_connection() as con:
        vista = {(r[0], r[1]) for r in con.execute("SELECT id_solicitud, dias_abierta FROM v_solicitudes_vencidas")}
    calculado = {(s.id_solicitud, s.dias_transcurridos)
                 for c in _clientes() for s in consultar_solicitudes(c).solicitudes if s.fuera_de_plazo}
    assert calculado == vista == {(1, 21)}


def test_filtro_por_estado():
    assert [s.id_solicitud for s in consultar_solicitudes(10, estado="abierta").solicitudes] == [1]
    assert all(s.estado == "cerrada" for s in consultar_solicitudes(10, estado="cerrada").solicitudes)
    with pytest.raises(ValueError):
        consultar_solicitudes(10, estado="x' OR '1'='1")


def test_orden_mas_reciente_primero():
    fechas = [s.fecha_registro for s in consultar_solicitudes(10).solicitudes]
    assert fechas == sorted(fechas, reverse=True)


@pytest.mark.parametrize("cliente_id", [1, 10, 19, 29])
def test_aislamiento_solo_solicitudes_propias(cliente_id):
    with get_connection() as con:
        propias = {r[0] for r in con.execute("SELECT id_solicitud FROM solicitud WHERE id_cliente = ?", (cliente_id,))}
    assert {s.id_solicitud for s in consultar_solicitudes(cliente_id).solicitudes} == propias


def test_cliente_inexistente_no_ve_nada_y_usa_el_plazo_general():
    r = consultar_solicitudes(999_999)
    assert r.solicitudes == [] and r.plazo_atencion_dias == 10


@pytest.mark.parametrize("cliente_id", [0, -1, "1", True])
def test_cliente_id_invalido(cliente_id):
    with pytest.raises(ValueError):
        consultar_solicitudes(cliente_id)


def test_api_solicitudes_del_token():
    r = api.get("/mi/solicitudes", params={"cliente_id": 10}, headers=_como(1))
    assert r.status_code == 200
    assert r.json()["cantidad_fuera_de_plazo"] == 0
    datos = api.get("/mi/solicitudes", headers=_como(10)).json()
    assert datos["cantidad_fuera_de_plazo"] == 1


def test_api_filtro_estado_invalido_es_422():
    assert api.get("/mi/solicitudes", params={"estado": "vencida"}, headers=_como(10)).status_code == 422


def test_api_solicitudes_sin_token_es_401():
    assert api.get("/mi/solicitudes").status_code == 401
