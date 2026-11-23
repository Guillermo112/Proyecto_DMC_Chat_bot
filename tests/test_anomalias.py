"""detectar_anomalias y GET /mi/anomalias: un caso por casuística del PDF, controles y aislamiento."""
import json

import pytest
from fastapi.testclient import TestClient

from app.auth import sesion
from app.data import detectar_anomalias, get_connection
from app.main import app

api = TestClient(app)
CON_ANOMALIAS = {1, 2, 3, 4, 5, 6}


def _como(cliente_id: int) -> dict:
    token, _ = sesion.emitir_token(cliente_id)
    return {"Authorization": f"Bearer {token}"}


def _clientes() -> list[int]:
    with get_connection() as con:
        return [r[0] for r in con.execute("SELECT id_cliente FROM cliente ORDER BY id_cliente")]


# ------------------------------------------------------------------ una por casuística

def test_cs01_factura_duplicada():
    a = detectar_anomalias(1)
    [d] = a.facturas_duplicadas
    assert d.periodo == "2026-11"
    assert [(f.numero, f.subtotal, f.total) for f in d.facturas] == [
        ("F001-000254", 185000.0, 218300.0), ("F001-000255", 185000.0, 218300.0)]
    assert d.monto_observado == 185000.0


def test_cs02_baja_facturada_sin_el_periodo_de_la_baja():
    [b] = detectar_anomalias(2).servicios_baja_facturados
    assert (b.servicio.sede, b.servicio.fecha_baja) == ("Cusco", "2026-09-30")
    assert [(c.periodo, c.numero_factura, c.monto_observado) for c in b.cobros] == [
        ("2026-10", "F001-000205", 12000.0), ("2026-11", "F001-000256", 12000.0)]
    assert b.monto_observado == 24000.0  # septiembre (mes de la baja) no cuenta


def test_cs03_tarifa_distinta_agrupada_por_servicio():
    [t] = detectar_anomalias(3).tarifas_distintas
    assert t.tarifa_pactada == 10500.0
    assert [(c.periodo, c.tarifa_facturada, c.cantidad, c.monto_observado) for c in t.cobros] == [
        ("2026-09", 12000.0, 3.0, 4500.0), ("2026-10", 12000.0, 3.0, 4500.0), ("2026-11", 12000.0, 3.0, 4500.0)]
    assert t.monto_observado == 13500.0


def test_cs04_exceso_sin_sustento_con_consumo_registrado():
    [e] = detectar_anomalias(4).excesos_sin_sustento
    assert (e.periodo, e.numero_factura, e.gb_facturados, e.precio_gb, e.monto_observado) == (
        "2026-10", "F001-000207", 150.0, 2.0, 300.0)
    # Lo que permite explicar: GB incluidos, usados y exceso registrado.
    assert (e.gb_incluidos_registrados, e.gb_usados_registrados, e.gb_exceso_registrados) == (1200.0, 897.5, 0.0)


def test_cs05_sla_incumplido_mayor():
    [v] = detectar_anomalias(5).averias_sla_incumplido
    assert v.servicio.sede == "Trujillo"
    assert (v.fecha_inicio, v.fecha_fin) == ("2026-10-18 08:00", "2026-10-19 14:00")
    assert (v.horas_caida, v.tolerancia_horas, v.horas_fuera_de_sla, v.monto_observado) == (30.0, 2.16, 27.84, 464.0)


def test_cs07_sla_incumplido_menor():
    [v] = detectar_anomalias(6).averias_sla_incumplido
    assert v.servicio.sede == "Piura"
    assert (v.horas_caida, v.tolerancia_horas, v.horas_fuera_de_sla, v.monto_observado) == (9.0, 3.6, 5.4, 33.75)


# ------------------------------------------------------------------ controles

def test_solo_los_clientes_sembrados_tienen_anomalias():
    """Controles negativos: 25 (baja bien aplicada), 30 (prorrateo legítimo), 15/24/38 (duplicados anulados)."""
    con_anomalias = {c for c in _clientes() if detectar_anomalias(c).cantidad}
    assert con_anomalias == CON_ANOMALIAS
    assert all(detectar_anomalias(c).cantidad == 1 for c in CON_ANOMALIAS)


def test_averias_ya_compensadas_no_aparecen():
    with get_connection() as con:
        compensadas = {r[0] for r in con.execute(
            "SELECT id_averia FROM ajuste WHERE id_averia IS NOT NULL AND estado <> 'rechazado'")}
    vistas = {v.id_averia for c in _clientes() for v in detectar_anomalias(c).averias_sla_incumplido}
    assert compensadas and not compensadas & vistas


def test_no_expone_causa_tecnica_ni_nombres_que_prometan_devolucion():
    texto = json.dumps(detectar_anomalias(5).model_dump(), ensure_ascii=False)
    assert "causa" not in texto and "Corte de fibra" not in texto
    assert "acreditar" not in texto and "devol" not in texto


# ------------------------------------------------------------------ aislamiento

@pytest.mark.parametrize("cliente_id", sorted(CON_ANOMALIAS))
def test_aislamiento_facturas_y_servicios_propios(cliente_id):
    with get_connection() as con:
        facturas = {r[0] for r in con.execute("SELECT numero FROM factura WHERE id_cliente = ?", (cliente_id,))}
        servicios = {r[0] for r in con.execute(
            "SELECT id_servicio FROM servicio_contratado WHERE id_cliente = ?", (cliente_id,))}
    a = detectar_anomalias(cliente_id)
    numeros = {f.numero for d in a.facturas_duplicadas for f in d.facturas}
    numeros |= {c.numero_factura for g in a.servicios_baja_facturados + a.tarifas_distintas for c in g.cobros}
    numeros |= {e.numero_factura for e in a.excesos_sin_sustento}
    ids = {g.servicio.id_servicio for g in
           a.servicios_baja_facturados + a.tarifas_distintas + a.excesos_sin_sustento + a.averias_sla_incumplido}
    assert numeros <= facturas and ids <= servicios


def test_cliente_inexistente_no_ve_nada():
    assert detectar_anomalias(999_999).cantidad == 0


@pytest.mark.parametrize("cliente_id", [0, -1, "1", True])
def test_cliente_id_invalido(cliente_id):
    with pytest.raises(ValueError):
        detectar_anomalias(cliente_id)


# ------------------------------------------------------------------ API

def test_api_anomalias_del_token():
    r = api.get("/mi/anomalias", params={"cliente_id": 1}, headers=_como(2))
    assert r.status_code == 200
    datos = r.json()
    assert datos["facturas_duplicadas"] == [] and len(datos["servicios_baja_facturados"]) == 1


def test_api_anomalias_sin_token_es_401():
    assert api.get("/mi/anomalias").status_code == 401
