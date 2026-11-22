"""API /mi/...: el cliente sale solo del token y nunca ve datos de otro."""
import pytest
from fastapi.testclient import TestClient

from app.auth import sesion
from app.data import get_connection, saldo_pendiente
from app.main import app

api = TestClient(app)

CLIENTE_1, CLIENTE_2 = 1, 2
FACTURA_DEL_CLIENTE_1 = "F001-000254"
RUTAS = ["/mi/perfil", "/mi/facturas", f"/mi/facturas/{FACTURA_DEL_CLIENTE_1}", "/mi/saldo",
         "/mi/resumen?fecha_desde=2026-06-01&fecha_hasta=2026-11-30", "/mi/comparar?periodo_b=2026-10", "/mi/servicios"]


def _como(cliente_id: int) -> dict:
    token, _ = sesion.emitir_token(cliente_id)
    return {"Authorization": f"Bearer {token}"}


def _numeros_de(cliente_id: int) -> set[str]:
    with get_connection() as con:
        return {r[0] for r in con.execute("SELECT numero FROM factura WHERE id_cliente = ?", (cliente_id,))}


@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_token_es_401(ruta):
    r = api.get(ruta)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("ruta", RUTAS)
def test_token_invalido_es_401(ruta):
    assert api.get(ruta, headers={"Authorization": "Bearer basura"}).status_code == 401


@pytest.mark.parametrize("cliente_id", [CLIENTE_1, CLIENTE_2])
def test_perfil_es_el_del_token(cliente_id):
    r = api.get("/mi/perfil", headers=_como(cliente_id))
    assert r.status_code == 200 and r.json()["id_cliente"] == cliente_id


def test_facturas_solo_del_cliente():
    r = api.get("/mi/facturas", params={"limite": 100}, headers=_como(CLIENTE_1))
    assert r.status_code == 200
    datos = r.json()
    propias = _numeros_de(CLIENTE_1)
    assert datos["total"] == len(propias)
    assert {f["numero"] for f in datos["items"]} <= propias


def test_cliente_id_en_query_se_ignora():
    """Mandar cliente_id=2 con el token del 1 no cambia nada: el cliente sale del token."""
    r = api.get("/mi/facturas", params={"cliente_id": CLIENTE_2, "limite": 100}, headers=_como(CLIENTE_1))
    assert r.status_code == 200
    numeros = {f["numero"] for f in r.json()["items"]}
    assert numeros and numeros <= _numeros_de(CLIENTE_1)
    assert not numeros & _numeros_de(CLIENTE_2)


def test_detalle_de_factura_propia():
    r = api.get(f"/mi/facturas/{FACTURA_DEL_CLIENTE_1}", headers=_como(CLIENTE_1))
    assert r.status_code == 200
    assert r.json()["numero"] == FACTURA_DEL_CLIENTE_1 and r.json()["lineas"]
    # El número no distingue mayúsculas.
    assert api.get(f"/mi/facturas/{FACTURA_DEL_CLIENTE_1.lower()}", headers=_como(CLIENTE_1)).status_code == 200


def test_factura_de_otro_cliente_es_404_igual_que_inexistente():
    ajena = api.get(f"/mi/facturas/{FACTURA_DEL_CLIENTE_1}", headers=_como(CLIENTE_2))
    inexistente = api.get("/mi/facturas/F999-999999", headers=_como(CLIENTE_2))
    assert ajena.status_code == inexistente.status_code == 404
    assert ajena.json() == inexistente.json()  # no revela si el número existe


def test_saldo_coincide_con_la_capa_de_datos():
    r = api.get("/mi/saldo", headers=_como(CLIENTE_1))
    assert r.status_code == 200
    assert r.json() == saldo_pendiente(CLIENTE_1).model_dump()


def test_saldo_con_duplicado_responde_null_y_no_cero():
    """El cliente 1 tiene un duplicado en 2026-11: el saldo va en null (no 0) y se marca el periodo."""
    datos = api.get("/mi/saldo", headers=_como(CLIENTE_1)).json()
    assert datos["saldo_total"] is None and datos["periodos_multiples"] == ["2026-11"]


def test_resumen_con_duplicado_responde_null():
    r = api.get("/mi/resumen", params={"fecha_desde": "2026-12-01", "fecha_hasta": "2026-12-31"},
                headers=_como(CLIENTE_1))
    datos = r.json()
    assert r.status_code == 200 and datos["total"] is None and datos["periodos_multiples"] == ["2026-11"]


def test_resumen_requiere_fechas_y_rango_valido():
    h = _como(CLIENTE_1)
    assert api.get("/mi/resumen", headers=h).status_code == 422
    r = api.get("/mi/resumen", params={"fecha_desde": "2026-11-30", "fecha_hasta": "2026-06-01"}, headers=h)
    assert r.status_code == 400
    r = api.get("/mi/resumen", params={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-11-30"}, headers=h)
    assert r.status_code == 200 and r.json()["cantidad_facturas"] > 0


def test_facturas_por_periodo():
    r = api.get("/mi/facturas", params={"periodo": "2026-11"}, headers=_como(CLIENTE_1))
    assert r.status_code == 200
    assert {f["numero"] for f in r.json()["items"]} == {"F001-000254", "F001-000255"}


def test_facturas_por_periodo_de_otro_cliente_no_filtra_lo_ajeno():
    r = api.get("/mi/facturas", params={"periodo": "2026-11"}, headers=_como(CLIENTE_2))
    assert r.status_code == 200
    numeros = {f["numero"] for f in r.json()["items"]}
    assert numeros <= _numeros_de(CLIENTE_2) and not numeros & _numeros_de(CLIENTE_1)


@pytest.mark.parametrize("periodo", ["2026-13", "2026-1", "2026-10-01", "x' OR '1'='1"])
def test_periodo_mal_formado_es_422(periodo):
    r = api.get("/mi/facturas", params={"periodo": periodo}, headers=_como(CLIENTE_1))
    assert r.status_code == 422


def test_estado_invalido_es_422():
    r = api.get("/mi/facturas", params={"estado": "x' OR '1'='1"}, headers=_como(CLIENTE_1))
    assert r.status_code == 422


def test_cliente_inexistente_no_ve_nada():
    h = _como(999999)
    assert api.get("/mi/perfil", headers=h).status_code == 404
    r = api.get("/mi/facturas", headers=h)
    assert r.status_code == 200 and r.json()["total"] == 0


def test_todas_las_rutas_mi_exigen_token():
    """Si alguien agrega una ruta /mi sin token, este test lo detecta."""
    rutas_mi = {p: ops for p, ops in app.openapi()["paths"].items() if p.startswith("/mi")}
    assert len(rutas_mi) == len(RUTAS)
    for path, ops in rutas_mi.items():
        for metodo, op in ops.items():
            assert op.get("security"), f"{metodo.upper()} {path} no exige token"
            assert "cliente_id" not in {p["name"] for p in op.get("parameters", [])}, path
