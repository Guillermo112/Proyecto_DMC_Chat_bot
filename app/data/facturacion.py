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
    ComparacionPeriodos,
    FacturaDetalle,
    FacturaResumen,
    LineaComparada,
    LineaFactura,
    LineaPeriodo,
    NotaCreditoAplicada,
    PaginaFacturas,
    PeriodoComparado,
    ResumenFacturacion,
    ResumenPeriodo,
    SaldoPendiente,
    Servicio,
)

ESTADOS_FACTURA = {"emitida", "pagada", "vencida", "en_disputa", "anulada"}
ESTADOS_PENDIENTES = ("emitida", "vencida", "en_disputa")
# Mismo umbral que la vista v_variacion_facturacion (db/schema.sql).
UMBRAL_VARIACION_PCT = 25.0
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


def _facturas_vigentes(con, cliente_id: int, periodos) -> dict[str, list[FacturaResumen]]:
    """Facturas no anuladas del cliente en esos periodos, agrupadas por periodo.

    Un periodo con más de una es un posible duplicado (CS-01): quien llame no
    debe sumarlas ni elegir una (regla en docs/capa_datos.md, sección 4).
    """
    periodos = list(dict.fromkeys(periodos))  # sin repetidos, en orden
    if not periodos:
        return {}
    marcadores = ", ".join("?" for _ in periodos)  # solo marcadores fijos
    filas = con.execute(
        f"SELECT {_COLUMNAS_FACTURA} FROM factura f "
        f"WHERE f.id_cliente = ? AND f.estado <> 'anulada' AND f.periodo IN ({marcadores}) "
        "ORDER BY f.periodo, f.id_factura",
        [cliente_id, *periodos],
    ).fetchall()
    resultado: dict[str, list[FacturaResumen]] = {p: [] for p in periodos}
    for fila in filas:
        resultado[fila["periodo"]].append(_factura(fila))
    return resultado


def _periodos_multiples(con, cliente_id: int, periodos) -> list[str]:
    """Periodos (de los dados) con más de una factura vigente, ordenados."""
    return sorted(p for p, fs in _facturas_vigentes(con, cliente_id, periodos).items() if len(fs) > 1)


def _suma(valores) -> float:
    return round(sum(valores), 2)


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
    listan aparte las aplicadas sobre esas facturas. Una suma que incluiría
    una factura de un periodo con varias vigentes es None (ver SaldoPendiente).
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
        # Cuenta todas las vigentes del periodo (también pagadas), no solo las pendientes.
        multiples = _periodos_multiples(con, cliente_id, [f.periodo for f in facturas])

    def suma_si_es_segura(grupo: list[FacturaResumen]) -> float | None:
        if any(f.periodo in multiples for f in grupo):
            return None
        return _suma(f.total for f in grupo)

    vencidas = [f for f in facturas if f.estado == "vencida" or f.fecha_vencimiento < fecha_corte]
    return SaldoPendiente(
        fecha_corte=fecha_corte,
        saldo_total=suma_si_es_segura(facturas),
        saldo_vencido=suma_si_es_segura(vencidas),
        cantidad_facturas=len(facturas),
        facturas=facturas,
        notas_credito_aplicadas=[NotaCreditoAplicada(**dict(n)) for n in notas],
        periodos_multiples=multiples,
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
        # Cuenta todas las vigentes del periodo, aunque alguna se emitiera fuera del rango.
        multiples = _periodos_multiples(con, cliente_id, [f["periodo"] for f in filas])

    periodos = []
    for f in filas:
        es_multiple = f["periodo"] in multiples
        periodos.append(ResumenPeriodo(
            periodo=f["periodo"],
            cantidad_facturas=f["cantidad_facturas"],
            facturas_multiples=es_multiple,
            **{k: None if es_multiple else f[k] for k in ("subtotal", "igv", "total")},
        ))
    hay_multiples = bool(multiples)
    return ResumenFacturacion(
        fecha_desde=desde,
        fecha_hasta=hasta,
        periodos=periodos,
        cantidad_facturas=sum(p.cantidad_facturas for p in periodos),
        **{k: None if hay_multiples else _suma(getattr(p, k) for p in periodos)
           for k in ("subtotal", "igv", "total")},
        periodos_multiples=multiples,
    )


# ------------------------------------------------- comparación entre periodos

def _periodo_anterior(periodo: str) -> str:
    anio, mes = int(periodo[:4]), int(periodo[5:])
    return f"{anio - 1}-12" if mes == 1 else f"{anio}-{mes - 1:02d}"


def _lineas_con_servicio(con, cliente_id: int, id_factura: int) -> dict:
    """Líneas de una factura del cliente, indexadas por (servicio, clase de cargo)."""
    filas = con.execute(
        """
        SELECT l.id_linea, l.id_servicio, l.tipo, l.concepto, l.cantidad, l.precio_unitario, l.monto,
               s.codigo_producto, p.nombre AS producto, s.sede, s.cantidad AS s_cantidad,
               s.tarifa_pactada, s.sla_pactado, s.fecha_activacion, s.fecha_baja, s.estado AS s_estado
        FROM factura_linea l
        JOIN factura f ON f.id_factura = l.id_factura
        LEFT JOIN servicio_contratado s ON s.id_servicio = l.id_servicio AND s.id_cliente = f.id_cliente
        LEFT JOIN producto p ON p.codigo = s.codigo_producto
        WHERE l.id_factura = ? AND f.id_cliente = ?
        ORDER BY l.id_linea
        """,
        (id_factura, cliente_id),
    ).fetchall()
    lineas: dict = {}
    for f in filas:
        # cargo_mensual y prorrateo son la misma clase: el prorrateo pasa a mes completo.
        clase = "cargo" if f["tipo"] in ("cargo_mensual", "prorrateo") else f["tipo"]
        clave = (f["id_servicio"], clase)
        if f["id_servicio"] is None or clave in lineas:  # sin servicio o repetida: no se empareja a ciegas
            clave = (f["id_servicio"], clase, f["concepto"], f["id_linea"])
        servicio = None
        if f["codigo_producto"] is not None:
            servicio = Servicio(
                id_servicio=f["id_servicio"], codigo_producto=f["codigo_producto"], producto=f["producto"],
                sede=f["sede"], cantidad=f["s_cantidad"], tarifa_pactada=f["tarifa_pactada"],
                sla_pactado=f["sla_pactado"], fecha_activacion=f["fecha_activacion"],
                fecha_baja=f["fecha_baja"], estado=f["s_estado"],
            )
        linea = LineaPeriodo(**{k: f[k] for k in LineaPeriodo.model_fields})
        lineas[clave] = (linea, servicio)
    return lineas


def _campos_cambiados(antes: LineaPeriodo, despues: LineaPeriodo) -> list[str]:
    campos = ["tipo"] if antes.tipo != despues.tipo else []
    campos += [c for c in ("cantidad", "precio_unitario", "monto")
               if abs(getattr(antes, c) - getattr(despues, c)) > 0.005]
    return campos


def _diferencias(antes: dict, despues: dict) -> tuple[list[LineaComparada], int]:
    """Líneas nuevas, eliminadas o cambiadas, y cuántas quedaron igual."""
    cambiadas: list[LineaComparada] = []
    sin_cambio = 0
    for clave in [*antes, *(k for k in despues if k not in antes)]:
        la, sa = antes.get(clave, (None, None))
        ld, sd = despues.get(clave, (None, None))
        if la is None or ld is None:
            cambio, campos = ("nueva" if la is None else "eliminada"), []
        else:
            campos = _campos_cambiados(la, ld)
            if not campos:
                sin_cambio += 1
                continue
            cambio = "cambiada"
        cambiadas.append(LineaComparada(
            cambio=cambio, servicio=sd or sa, antes=la, despues=ld, campos_cambiados=campos,
            diferencia_monto=round((ld.monto if ld else 0) - (la.monto if la else 0), 2),
        ))
    return cambiadas, sin_cambio


def comparar_periodos(
    cliente_id: int,
    periodo_b: str,
    periodo_a: str | None = None,
    db_path: Path | None = None,
) -> ComparacionPeriodos:
    """Qué cambió entre dos periodos facturados del cliente (CS-09).

    `periodo_a` es el anterior; si falta, se usa el mes previo a `periodo_b`.
    Compara subtotales (sin IGV) y líneas, emparejadas por servicio. Excluye
    facturas anuladas. Si un periodo no tiene facturas o tiene más de una
    vigente, no compara: `comparable=False` y `motivo` (ver ComparacionPeriodos).
    """
    _validar_cliente_id(cliente_id)
    periodo_b = _validar_periodo(periodo_b)
    periodo_a = _periodo_anterior(periodo_b) if periodo_a is None else _validar_periodo(periodo_a)
    if periodo_a >= periodo_b:
        raise ValueError("periodo_a debe ser anterior a periodo_b")

    with get_connection(db_path) as con:
        facturas = _facturas_vigentes(con, cliente_id, [periodo_a, periodo_b])

        def resumen(periodo: str) -> PeriodoComparado:
            fs = facturas[periodo]
            unica = fs[0] if len(fs) == 1 else None
            return PeriodoComparado(
                periodo=periodo, facturas=fs,
                subtotal=unica.subtotal if unica else None,
                igv=unica.igv if unica else None,
                total=unica.total if unica else None,
            )

        a, b = resumen(periodo_a), resumen(periodo_b)
        cantidades = (len(a.facturas), len(b.facturas))
        if max(cantidades) > 1:
            motivo = "facturas_multiples"
        elif min(cantidades) == 0:
            motivo = "periodo_sin_facturas"
        else:
            motivo = None
        base = dict(periodo_a=a, periodo_b=b, umbral_variacion_pct=UMBRAL_VARIACION_PCT)
        if motivo is not None:
            return ComparacionPeriodos(
                **base, comparable=False, motivo=motivo, variacion_subtotal=None, variacion_pct=None,
                variacion_fuerte=None, lineas=None, lineas_sin_cambio=None,
            )

        lineas, sin_cambio = _diferencias(
            _lineas_con_servicio(con, cliente_id, a.facturas[0].id_factura),
            _lineas_con_servicio(con, cliente_id, b.facturas[0].id_factura),
        )

    variacion = round(b.subtotal - a.subtotal, 2)
    pct = round(variacion / a.subtotal * 100, 2) if a.subtotal else None
    return ComparacionPeriodos(
        **base, comparable=True, motivo=None, variacion_subtotal=variacion, variacion_pct=pct,
        variacion_fuerte=None if pct is None else abs(pct) > UMBRAL_VARIACION_PCT,
        lineas=lineas, lineas_sin_cambio=sin_cambio,
    )
