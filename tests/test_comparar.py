"""comparar_periodos (CS-09) con los datos conocidos de anticipa.db."""
import pytest
from fastapi.testclient import TestClient

from app.auth import sesion
from app.data import comparar_periodos, get_connection
from app.main import app

api = TestClient(app)


def _como(cliente_id: int) -> dict:
    token, _ = sesion.emitir_token(cliente_id)
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ capa de datos

def test_cs09_alta_de_mpls_callao():
    r = comparar_periodos(7, "2026-10", "2026-09")
    assert r.comparable and r.motivo is None
    assert (r.periodo_a.subtotal, r.periodo_b.subtotal) == (73200.0, 97200.0)
    assert r.variacion_subtotal == 24000.0 and r.variacion_pct == 32.79
    assert r.variacion_fuerte is True
    assert r.lineas_sin_cambio == 4
    [linea] = r.lineas
    assert linea.cambio == "nueva" and linea.antes is None
    assert (linea.despues.concepto, linea.despues.cantidad, linea.despues.precio_unitario) == (
        "Enlace MPLS Callao", 2.0, 12000.0)
    assert linea.diferencia_monto == 24000.0
    # La causa: el servicio se activó ese mes (mensaje modelo de CS-09).
    assert (linea.servicio.sede, linea.servicio.fecha_activacion) == ("Callao", "2026-10-01")


def test_periodo_a_por_defecto_es_el_mes_anterior():
    r = comparar_periodos(7, "2026-10")
    assert r.periodo_a.periodo == "2026-09" and r.variacion_subtotal == 24000.0


def test_periodo_anterior_cruza_el_anio():
    assert comparar_periodos(7, "2027-01").periodo_a.periodo == "2026-12"


def test_cs10_prorrateo_a_mes_completo_es_un_cambio():
    """Cliente 9: Arequipa pasa de prorrateo (15 días) a cargo mensual; no es eliminada + nueva."""
    r = comparar_periodos(9, "2026-10", "2026-09")
    [linea] = r.lineas
    assert linea.cambio == "cambiada"
    assert (linea.antes.tipo, linea.antes.monto) == ("prorrateo", 6750.0)
    assert (linea.despues.tipo, linea.despues.monto) == ("cargo_mensual", 13500.0)
    assert linea.campos_cambiados == ["tipo", "precio_unitario", "monto"]
    assert linea.servicio.fecha_activacion == "2026-09-15"
    assert r.variacion_fuerte is False


def test_cs04_exceso_aparece_como_linea_nueva():
    r = comparar_periodos(4, "2026-10")
    [linea] = r.lineas
    assert linea.cambio == "nueva" and linea.despues.tipo == "exceso"
    assert (linea.despues.cantidad, linea.diferencia_monto) == (150.0, 300.0)


def test_cs01_facturas_multiples_es_aviso_y_no_comparacion():
    """Regla de docs/capa_datos.md §4: no sumar ni elegir; sin variación ni líneas."""
    r = comparar_periodos(1, "2026-11", "2026-10")
    assert r.comparable is False and r.motivo == "facturas_multiples"
    assert [(f.numero, f.subtotal, f.total) for f in r.periodo_b.facturas] == [
        ("F001-000254", 185000.0, 218300.0), ("F001-000255", 185000.0, 218300.0)]
    assert r.periodo_b.subtotal is None and r.periodo_b.total is None
    assert r.periodo_a.subtotal == 185000.0  # el otro periodo sí se informa
    assert r.variacion_subtotal is None and r.variacion_pct is None and r.variacion_fuerte is None
    assert r.lineas is None and r.lineas_sin_cambio is None


def test_facturas_multiples_en_periodo_a_tambien_bloquea():
    r = comparar_periodos(1, "2026-12", "2026-11")
    assert r.motivo == "facturas_multiples"


def test_periodo_sin_facturas():
    r = comparar_periodos(1, "2020-02")
    assert r.comparable is False and r.motivo == "periodo_sin_facturas"
    assert r.periodo_b.facturas == [] and r.variacion_subtotal is None


def test_anuladas_no_cuentan():
    """Cliente 15 tiene un duplicado legado anulado en 2026-07: el periodo se compara normal."""
    r = comparar_periodos(15, "2026-07")
    assert r.comparable is True
    assert [f.numero for f in r.periodo_b.facturas] == ["F001-000065"]  # F001-000066 está anulada


def test_aislamiento_cliente_2_no_ve_lineas_del_1():
    with get_connection() as con:
        propias = {f for (f,) in con.execute("SELECT numero FROM factura WHERE id_cliente = 2")}
        servicios_propios = {s for (s,) in con.execute(
            "SELECT id_servicio FROM servicio_contratado WHERE id_cliente = 2")}
    for periodo_b in ("2026-09", "2026-10", "2026-11"):
        r = comparar_periodos(2, periodo_b)
        numeros = {f.numero for f in r.periodo_a.facturas + r.periodo_b.facturas}
        assert numeros and numeros <= propias
        assert {l.servicio.id_servicio for l in r.lineas or []} <= servicios_propios


@pytest.mark.parametrize("periodo_b, periodo_a", [
    ("2026-13", None), ("2026-1", None), ("2026-10", "2026-10"), ("2026-09", "2026-10"),
    ("2026-10", "x' OR '1'='1"),
])
def test_periodos_invalidos(periodo_b, periodo_a):
    with pytest.raises(ValueError):
        comparar_periodos(7, periodo_b, periodo_a)


# ------------------------------------------------------------------ API

def test_api_comparar_cliente_7():
    r = api.get("/mi/comparar", params={"periodo_b": "2026-10"}, headers=_como(7))
    assert r.status_code == 200
    datos = r.json()
    assert datos["variacion_fuerte"] is True and datos["lineas"][0]["servicio"]["sede"] == "Callao"


def test_api_comparar_duplicado_responde_200_con_aviso():
    r = api.get("/mi/comparar", params={"periodo_b": "2026-11"}, headers=_como(1))
    assert r.status_code == 200
    datos = r.json()
    assert datos["comparable"] is False and datos["motivo"] == "facturas_multiples"
    assert datos["variacion_pct"] is None and datos["lineas"] is None


def test_api_comparar_el_cliente_sale_del_token():
    r = api.get("/mi/comparar", params={"periodo_b": "2026-11", "cliente_id": 1}, headers=_como(2))
    assert r.status_code == 200
    assert r.json()["motivo"] != "facturas_multiples"


@pytest.mark.parametrize("params, codigo", [
    ({}, 422),
    ({"periodo_b": "2026-13"}, 422),
    ({"periodo_b": "2026-10", "periodo_a": "2026-1"}, 422),
    ({"periodo_b": "2026-09", "periodo_a": "2026-10"}, 400),
])
def test_api_comparar_entradas_invalidas(params, codigo):
    assert api.get("/mi/comparar", params=params, headers=_como(7)).status_code == codigo


def test_api_comparar_sin_token_es_401():
    assert api.get("/mi/comparar", params={"periodo_b": "2026-10"}).status_code == 401
