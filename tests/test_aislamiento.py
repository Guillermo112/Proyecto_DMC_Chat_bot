"""Un cliente nunca puede leer datos de otro."""
from datetime import date

import pytest

from app.data import (
    detalle_factura,
    get_connection,
    listar_facturas,
    resumen_facturacion,
    saldo_pendiente,
)

CLIENTE_1, CLIENTE_2 = 1, 2
FACTURA_DEL_CLIENTE_1 = "F001-000254"


def _facturas_de(cliente_id):
    with get_connection() as con:
        return {r[0] for r in con.execute("SELECT numero FROM factura WHERE id_cliente = ?", (cliente_id,))}


def test_detalle_factura_propia_ok():
    det = detalle_factura(CLIENTE_1, FACTURA_DEL_CLIENTE_1)
    assert det is not None and det.numero == FACTURA_DEL_CLIENTE_1
    assert det.lineas


def test_detalle_factura_de_otro_cliente_devuelve_none():
    assert detalle_factura(CLIENTE_2, FACTURA_DEL_CLIENTE_1) is None


def test_ningun_cliente_ve_facturas_ajenas_por_numero():
    ajenas = sorted(_facturas_de(CLIENTE_1))[:10]
    for numero in ajenas:
        assert detalle_factura(CLIENTE_2, numero) is None


def test_listar_facturas_solo_del_cliente():
    pagina = listar_facturas(CLIENTE_1, limite=100)
    assert pagina.total == len(_facturas_de(CLIENTE_1))
    assert {f.numero for f in pagina.items} <= _facturas_de(CLIENTE_1)
    assert not ({f.numero for f in pagina.items} & _facturas_de(CLIENTE_2))


def test_saldo_no_incluye_facturas_de_otro_cliente():
    saldo = saldo_pendiente(CLIENTE_2)
    numeros = {f.numero for f in saldo.facturas}
    assert numeros <= _facturas_de(CLIENTE_2)
    assert FACTURA_DEL_CLIENTE_1 not in numeros


def test_resumen_solo_del_cliente():
    r1 = resumen_facturacion(CLIENTE_1, date(2026, 1, 1), date(2026, 12, 31))
    with get_connection() as con:
        esperado = con.execute(
            "SELECT COUNT(*) FROM factura WHERE id_cliente = ? AND estado <> 'anulada'", (CLIENTE_1,)
        ).fetchone()[0]
    assert r1.cantidad_facturas == esperado


@pytest.mark.parametrize(
    "numero",
    ["' OR 1=1 --", "F001-000254' OR '1'='1", "x'; DROP TABLE factura; --"],
)
def test_inyeccion_en_numero_no_filtra_datos(numero):
    assert detalle_factura(CLIENTE_2, numero) is None


def test_inyeccion_en_estado_es_rechazada():
    with pytest.raises(ValueError):
        listar_facturas(CLIENTE_2, estado="emitida' OR '1'='1")


@pytest.mark.parametrize("cliente_id", [0, -1, "1", None, True, 1.5])
def test_cliente_id_invalido(cliente_id):
    with pytest.raises(ValueError):
        listar_facturas(cliente_id)
