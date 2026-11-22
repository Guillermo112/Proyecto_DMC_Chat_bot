"""Consultas de facturación, siempre acotadas a un único cliente.

Reglas:
- Solo consultas parametrizadas (`?`); los filtros opcionales agregan
  fragmentos SQL fijos, nunca valores concatenados.
- Toda función recibe `cliente_id` y lo aplica en el WHERE.
"""
import re
from datetime import date
from pathlib import Path

from app import config
from app.data.conexion import get_connection
from app.schemas import (
    Cliente,
    FacturaDetalle,
    FacturaResumen,
    LineaFactura,
    NotaCreditoAplicada,
    PaginaFacturas,
    ResumenFacturacion,
    ResumenPeriodo,
    SaldoPendiente,
)

ESTADOS_FACTURA = {"emitida", "pagada", "vencida", "en_disputa", "anulada"}
ESTADOS_PENDIENTES = ("emitida", "vencida", "en_disputa")
_PATRON_PERIODO = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")  # [0-9], no \d: \d acepta dígitos Unicode

_COLUMNAS_FACTURA = """
    f.id_factura, f.numero, f.periodo, f.fecha_emision, f.fecha_vencimiento,
    f.subtotal, f.igv, f.total, f.estado
"""


def _validar_cliente_id(cliente_id: int) -> int:
    if not isinstance(cliente_id, int) or isinstance(cliente_id, bool) or cliente_id <= 0:
        raise ValueError("cliente_id debe ser un entero positivo")
    return cliente_id


def _fecha_iso(valor: date | None) -> str | None:
    if valor is None:
        return None
    if not isinstance(valor, date):
        raise ValueError("Las fechas deben ser datetime.date")
    return valor.isoformat()


def _validar_periodo(periodo: str) -> str:
    """Periodo facturado en formato AAAA-MM (mes 01 a 12)."""
    if not isinstance(periodo, str) or not _PATRON_PERIODO.fullmatch(periodo.strip()):
        raise ValueError("periodo debe tener el formato AAAA-MM, p. ej. '2026-10'")
    return periodo.strip()


def _fecha_actual(con) -> str:
    """Fecha de sistema ficticia guardada en la tabla parametro."""
    fila = con.execute("SELECT valor FROM parametro WHERE clave = ?", ("fecha_actual",)).fetchone()
    return fila["valor"] if fila else date.today().isoformat()


def _factura(fila) -> FacturaResumen:
    return FacturaResumen(**{k: fila[k] for k in FacturaResumen.model_fields})


def obtener_cliente(cliente_id: int, db_path: Path | None = None) -> Cliente | None:
    _validar_cliente_id(cliente_id)
    sql = """
        SELECT c.id_cliente, c.ruc, c.razon_social, c.sector, c.segmento,
               c.correo_facturacion, c.contacto_nombre, c.estado,
               p.nombre AS ejecutivo_nombre, p.correo AS ejecutivo_correo
        FROM cliente c
        JOIN personal p ON p.id_personal = c.id_ejecutivo
        WHERE c.id_cliente = ?
    """
    with get_connection(db_path) as con:
        fila = con.execute(sql, (cliente_id,)).fetchone()
    return Cliente(**dict(fila)) if fila else None


def listar_facturas(
    cliente_id: int,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    estado: str | None = None,
    limite: int | None = None,
    offset: int = 0,
    db_path: Path | None = None,
    *,
    periodo: str | None = None,
) -> PaginaFacturas:
    """Facturas del cliente filtradas por periodo, fecha de emisión y estado, paginadas.

    `periodo` (AAAA-MM) es el mes facturado, no el de emisión: la factura de
    2026-09 se emite el 2026-10-01. Se combina con los demás filtros (AND).
    """
    _validar_cliente_id(cliente_id)
    if periodo is not None:
        periodo = _validar_periodo(periodo)
    if estado is not None and estado not in ESTADOS_FACTURA:
        raise ValueError(f"Estado inválido. Permitidos: {sorted(ESTADOS_FACTURA)}")
    limite = config.LIMITE_POR_DEFECTO if limite is None else limite
    limite = max(1, min(int(limite), config.LIMITE_MAXIMO))
    offset = max(0, int(offset))

    condiciones = ["f.id_cliente = ?"]
    params: list = [cliente_id]
    if periodo is not None:
        condiciones.append("f.periodo = ?")
        params.append(periodo)
    if fecha_desde is not None:
        condiciones.append("f.fecha_emision >= ?")
        params.append(_fecha_iso(fecha_desde))
    if fecha_hasta is not None:
        condiciones.append("f.fecha_emision <= ?")
        params.append(_fecha_iso(fecha_hasta))
    if estado is not None:
        condiciones.append("f.estado = ?")
        params.append(estado)
    where = " AND ".join(condiciones)  # solo fragmentos fijos

    with get_connection(db_path) as con:
        total = con.execute(f"SELECT COUNT(*) FROM factura f WHERE {where}", params).fetchone()[0]
        filas = con.execute(
            f"SELECT {_COLUMNAS_FACTURA} FROM factura f WHERE {where} "
            "ORDER BY f.fecha_emision DESC, f.id_factura DESC LIMIT ? OFFSET ?",
            [*params, limite, offset],
        ).fetchall()
    return PaginaFacturas(items=[_factura(f) for f in filas], total=total, limite=limite, offset=offset)


def detalle_factura(cliente_id: int, numero: str, db_path: Path | None = None) -> FacturaDetalle | None:
    """Cabecera y líneas de una factura. None si no existe o es de otro cliente."""
    _validar_cliente_id(cliente_id)
    if not isinstance(numero, str):
        raise ValueError("numero debe ser texto, p. ej. 'F001-000123'")
    numero = numero.strip().upper()
    with get_connection(db_path) as con:
        cabecera = con.execute(
            f"SELECT {_COLUMNAS_FACTURA} FROM factura f WHERE f.numero = ? AND f.id_cliente = ?",
            (numero, cliente_id),
        ).fetchone()
        if cabecera is None:
            return None
        lineas = con.execute(
            """
            SELECT l.id_linea, l.tipo, l.concepto, l.cantidad, l.precio_unitario, l.monto
            FROM factura_linea l
            JOIN factura f ON f.id_factura = l.id_factura
            WHERE l.id_factura = ? AND f.id_cliente = ?
            ORDER BY l.id_linea
            """,
            (cabecera["id_factura"], cliente_id),
        ).fetchall()
    return FacturaDetalle(**_factura(cabecera).model_dump(), lineas=[LineaFactura(**dict(l)) for l in lineas])


def saldo_pendiente(cliente_id: int, db_path: Path | None = None) -> SaldoPendiente:
    """Suma de facturas emitidas, vencidas o en disputa del cliente.

    No resta notas de crédito (la base no las refleja en la factura); se
    listan aparte las aplicadas sobre esas facturas.
    """
    _validar_cliente_id(cliente_id)
    marcadores = ",".join("?" for _ in ESTADOS_PENDIENTES)
    with get_connection(db_path) as con:
        fecha_corte = _fecha_actual(con)
        filas = con.execute(
            f"SELECT {_COLUMNAS_FACTURA} FROM factura f "
            f"WHERE f.id_cliente = ? AND f.estado IN ({marcadores}) "
            "ORDER BY f.fecha_vencimiento, f.id_factura",
            (cliente_id, *ESTADOS_PENDIENTES),
        ).fetchall()
        notas = con.execute(
            f"""
            SELECT f.numero AS numero_factura, j.motivo, j.total, j.fecha_aplicacion
            FROM ajuste j
            JOIN factura f ON f.id_factura = j.id_factura
            WHERE f.id_cliente = ? AND f.estado IN ({marcadores})
              AND j.tipo_documento = 'nota_credito' AND j.estado = 'aplicado'
            ORDER BY j.id_ajuste
            """,
            (cliente_id, *ESTADOS_PENDIENTES),
        ).fetchall()

    facturas = [_factura(f) for f in filas]
    vencidas = [f for f in facturas if f.estado == "vencida" or f.fecha_vencimiento < fecha_corte]
    return SaldoPendiente(
        fecha_corte=fecha_corte,
        saldo_total=round(sum(f.total for f in facturas), 2),
        saldo_vencido=round(sum(f.total for f in vencidas), 2),
        cantidad_facturas=len(facturas),
        facturas=facturas,
        notas_credito_aplicadas=[NotaCreditoAplicada(**dict(n)) for n in notas],
    )


def resumen_facturacion(
    cliente_id: int, fecha_desde: date, fecha_hasta: date, db_path: Path | None = None
) -> ResumenFacturacion:
    """Totales por periodo según fecha de emisión (excluye anuladas)."""
    _validar_cliente_id(cliente_id)
    desde, hasta = _fecha_iso(fecha_desde), _fecha_iso(fecha_hasta)
    if desde is None or hasta is None:
        raise ValueError("fecha_desde y fecha_hasta son obligatorias")
    if desde > hasta:
        raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

    with get_connection(db_path) as con:
        filas = con.execute(
            """
            SELECT periodo, COUNT(*) AS cantidad_facturas,
                   ROUND(SUM(subtotal), 2) AS subtotal,
                   ROUND(SUM(igv), 2) AS igv,
                   ROUND(SUM(total), 2) AS total
            FROM factura
            WHERE id_cliente = ? AND estado <> 'anulada'
              AND fecha_emision BETWEEN ? AND ?
            GROUP BY periodo
            ORDER BY periodo
            """,
            (cliente_id, desde, hasta),
        ).fetchall()

    periodos = [ResumenPeriodo(**dict(f)) for f in filas]
    return ResumenFacturacion(
        fecha_desde=desde,
        fecha_hasta=hasta,
        periodos=periodos,
        cantidad_facturas=sum(p.cantidad_facturas for p in periodos),
        subtotal=round(sum(p.subtotal for p in periodos), 2),
        igv=round(sum(p.igv for p in periodos), 2),
        total=round(sum(p.total for p in periodos), 2),
    )
