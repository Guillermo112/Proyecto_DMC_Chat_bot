"""Comportamiento de la capa de datos con valores conocidos de anticipa.db."""
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import config
from app.data import (
    detalle_factura,
    get_connection,
    listar_facturas,
    obtener_cliente,
    resumen_facturacion,
    saldo_pendiente,
)
from app.main import app


def test_conexion_es_solo_lectura():
    with get_connection() as con:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("UPDATE factura SET total = 0 WHERE id_factura = 1")


def test_obtener_cliente():
    c = obtener_cliente(1)
    assert c.razon_social == "Minera Cordillera Azul S.A.C."
    assert c.ejecutivo_nombre
    assert obtener_cliente(9999) is None


def test_limite_se_recorta_al_maximo():
    pagina = listar_facturas(1, limite=10_000)
    assert pagina.limite == config.LIMITE_MAXIMO


def test_paginacion():
    p1 = listar_facturas(1, limite=2, offset=0)
    p2 = listar_facturas(1, limite=2, offset=2)
    assert len(p1.items) == 2 and len(p2.items) == 2
    assert not ({f.numero for f in p1.items} & {f.numero for f in p2.items})
    assert p1.total == p2.total == 7


def test_filtro_fechas_y_estado():
    pagina = listar_facturas(9, fecha_desde=date(2026, 11, 1), fecha_hasta=date(2026, 11, 30))
    assert [f.periodo for f in pagina.items] == ["2026-10"]
    vencidas = listar_facturas(9, estado="vencida")
    assert [f.numero for f in vencidas.items] == ["F001-000212"]


def test_filtro_periodo_es_el_mes_facturado():
    """El periodo 2026-09 se emite el 2026-10-01: filtrar por periodo no por emisión."""
    pagina = listar_facturas(7, periodo="2026-09")
    assert [(f.numero, f.periodo, f.fecha_emision) for f in pagina.items] == [
        ("F001-000159", "2026-09", "2026-10-01")
    ]


def test_filtro_periodo_con_duplicado_devuelve_ambas():
    pagina = listar_facturas(1, periodo="2026-11")
    assert {f.numero for f in pagina.items} == {"F001-000254", "F001-000255"}
    assert pagina.total == 2


def test_filtro_periodo_se_combina_con_los_demas():
    assert listar_facturas(9, periodo="2026-10", estado="vencida").total == 1
    assert listar_facturas(9, periodo="2026-10", estado="pagada").total == 0
    # Periodo 2026-10 emitido en noviembre: un rango de emisión de octubre lo excluye.
    assert listar_facturas(9, periodo="2026-10", fecha_hasta=date(2026, 10, 31)).total == 0


def test_filtro_periodo_sin_facturas_y_aislamiento():
    assert listar_facturas(1, periodo="2020-01").items == []
    assert {f.numero for f in listar_facturas(2, periodo="2026-11").items}.isdisjoint(
        {"F001-000254", "F001-000255"}
    )


@pytest.mark.parametrize("periodo", ["2026-13", "2026-00", "2026-1", "26-10", "2026/10", "2026-10-01",
                                     "", "2026-10' OR '1'='1", "٢٠٢٦-١٠", 202610])
def test_filtro_periodo_mal_formado(periodo):
    with pytest.raises(ValueError):
        listar_facturas(1, periodo=periodo)


def test_detalle_factura_suma_lineas():
    det = detalle_factura(9, "f001-000212")  # normaliza mayúsculas
    assert det.total == pytest.approx(80240.0)
    assert sum(l.monto for l in det.lineas) == pytest.approx(det.subtotal)


def test_saldo_cliente_9_tiene_vencida():
    s = saldo_pendiente(9)
    assert s.fecha_corte == "2026-12-05"
    assert s.saldo_vencido == pytest.approx(80240.0)
    assert "F001-000212" in {f.numero for f in s.facturas}


def test_saldo_cliente_1_con_duplicado_no_suma_ni_elige():
    """CS-01: lista las dos facturas, pero no da un saldo que las sume (capa_datos.md §4)."""
    s = saldo_pendiente(1)
    assert {"F001-000254", "F001-000255"} <= {f.numero for f in s.facturas}
    assert s.periodos_multiples == ["2026-11"]
    assert s.saldo_total is None
    # Los duplicados vencen el 2026-12-21 (corte 2026-12-05): el saldo vencido no depende de ellos.
    assert s.saldo_vencido == 0.0


def test_saldo_sin_duplicados_no_cambia():
    s = saldo_pendiente(9)
    assert s.periodos_multiples == []
    assert s.saldo_total == pytest.approx(sum(f.total for f in s.facturas))


def test_resumen_con_duplicado_no_suma_el_periodo():
    r = resumen_facturacion(1, date(2026, 10, 1), date(2026, 12, 31))  # periodos 2026-09 a 2026-11
    por_periodo = {p.periodo: p for p in r.periodos}
    nov = por_periodo["2026-11"]
    assert nov.cantidad_facturas == 2 and nov.facturas_multiples is True
    assert nov.subtotal is None and nov.igv is None and nov.total is None
    assert por_periodo["2026-10"].facturas_multiples is False and por_periodo["2026-10"].subtotal == 185000.0
    assert r.periodos_multiples == ["2026-11"]
    assert r.subtotal is None and r.igv is None and r.total is None
    assert r.cantidad_facturas == 4  # el conteo sí es seguro


def test_resumen_sin_duplicado_en_el_rango_suma_normal():
    r = resumen_facturacion(1, date(2026, 10, 1), date(2026, 11, 30))  # periodos 2026-09 y 2026-10
    assert r.periodos_multiples == [] and r.total == pytest.approx(2 * 218300.0)


def test_saldo_informa_nota_credito_sin_restarla():
    s = saldo_pendiente(8)
    assert len(s.notas_credito_aplicadas) == 1
    assert s.notas_credito_aplicadas[0].total == pytest.approx(70.8)
    assert s.saldo_total == pytest.approx(sum(f.total for f in s.facturas))


def test_resumen_excluye_anuladas_y_valida_rango():
    r = resumen_facturacion(15, date(2026, 8, 1), date(2026, 8, 31))  # periodo 2026-07
    assert r.cantidad_facturas == 1
    with pytest.raises(ValueError):
        resumen_facturacion(15, date(2026, 9, 1), date(2026, 8, 1))


def test_health():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "OK", "db": "OK"}


def test_la_base_admite_el_canal_web():
    """`caso.canal` admite 'web' (pruebas por web o API) desde que se agregó al schema.

    Si falla, la base es anterior al cambio: regenerarla con
    `python -X utf8 db/generar_datos.py`.
    """
    with get_connection() as con:
        sql = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'caso'").fetchone()[0]
    assert "'web'" in sql, "anticipa.db es anterior al canal 'web': regenerar con db/generar_datos.py"
