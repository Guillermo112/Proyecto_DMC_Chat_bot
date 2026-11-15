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


def test_detalle_factura_suma_lineas():
    det = detalle_factura(9, "f001-000212")  # normaliza mayúsculas
    assert det.total == pytest.approx(80240.0)
    assert sum(l.monto for l in det.lineas) == pytest.approx(det.subtotal)


def test_saldo_cliente_9_tiene_vencida():
    s = saldo_pendiente(9)
    assert s.fecha_corte == "2026-12-05"
    assert s.saldo_vencido == pytest.approx(80240.0)
    assert "F001-000212" in {f.numero for f in s.facturas}


def test_saldo_cliente_1_incluye_duplicada():
    s = saldo_pendiente(1)
    assert {"F001-000254", "F001-000255"} <= {f.numero for f in s.facturas}
    assert s.saldo_total == pytest.approx(2 * 218300.0)


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
    assert resp.json() == {"status": "ok", "db": "ok"}
