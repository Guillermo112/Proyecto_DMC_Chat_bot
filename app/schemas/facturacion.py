"""Modelos Pydantic que devuelve la capa de datos."""
from typing import Literal

from pydantic import BaseModel

EstadoFactura = Literal["emitida", "pagada", "vencida", "en_disputa", "anulada"]


class Cliente(BaseModel):
    id_cliente: int
    ruc: str
    razon_social: str
    sector: str | None
    segmento: str | None
    correo_facturacion: str
    contacto_nombre: str
    estado: str
    ejecutivo_nombre: str
    ejecutivo_correo: str


class FacturaResumen(BaseModel):
    id_factura: int
    numero: str
    periodo: str
    fecha_emision: str
    fecha_vencimiento: str
    subtotal: float
    igv: float
    total: float
    estado: EstadoFactura


class LineaFactura(BaseModel):
    id_linea: int
    tipo: str
    concepto: str
    cantidad: float
    precio_unitario: float
    monto: float


class FacturaDetalle(FacturaResumen):
    lineas: list[LineaFactura]


class PaginaFacturas(BaseModel):
    items: list[FacturaResumen]
    total: int
    limite: int
    offset: int


class NotaCreditoAplicada(BaseModel):
    numero_factura: str
    motivo: str
    total: float
    fecha_aplicacion: str | None


class SaldoPendiente(BaseModel):
    """Saldo = suma de `total` de facturas emitidas, vencidas o en disputa.

    La base no tiene tabla de pagos y las notas de crédito aplicadas no
    modifican la factura, por eso se informan aparte y no se restan.

    Si una suma incluiría una factura de un periodo con más de una vigente
    (duplicado de CS-01), esa suma es None y el periodo va en
    `periodos_multiples`: no se suman ni se elige una (docs/capa_datos.md §4).
    Las facturas se listan igual, con su estado, importe y vencimiento.
    """
    fecha_corte: str
    saldo_total: float | None
    saldo_vencido: float | None
    cantidad_facturas: int
    facturas: list[FacturaResumen]
    notas_credito_aplicadas: list[NotaCreditoAplicada]
    periodos_multiples: list[str]


class ResumenPeriodo(BaseModel):
    """Totales de un periodo; None si tiene más de una factura vigente."""
    periodo: str
    cantidad_facturas: int
    facturas_multiples: bool
    subtotal: float | None
    igv: float | None
    total: float | None


class ResumenFacturacion(BaseModel):
    """Totales del rango; None si algún periodo tiene más de una factura vigente."""
    fecha_desde: str
    fecha_hasta: str
    periodos: list[ResumenPeriodo]
    cantidad_facturas: int
    subtotal: float | None
    igv: float | None
    total: float | None
    periodos_multiples: list[str]





# ------------------------------------------------- comparación entre periodos

class Servicio(BaseModel):
    """Servicio contratado: explica por qué aparece, cambia o desaparece una línea."""
    id_servicio: int
    codigo_producto: str
    producto: str
    sede: str
    cantidad: int
    tarifa_pactada: float
    sla_pactado: float | None
    fecha_activacion: str
    fecha_baja: str | None
    estado: str


class LineaPeriodo(BaseModel):
    tipo: str
    concepto: str
    cantidad: float
    precio_unitario: float
    monto: float


class LineaComparada(BaseModel):
    """Una línea que cambió entre `periodo_a` (antes) y `periodo_b` (después).

    Se emparejan por servicio y clase de cargo: `cargo_mensual` y `prorrateo` son
    la misma clase, así un servicio que pasa de prorrateo a mes completo sale
    como `cambiada` y no como una eliminada más una nueva.
    """
    cambio: Literal["nueva", "eliminada", "cambiada"]
    servicio: Servicio | None
    antes: LineaPeriodo | None
    despues: LineaPeriodo | None
    campos_cambiados: list[Literal["tipo", "cantidad", "precio_unitario", "monto"]]
    diferencia_monto: float


class PeriodoComparado(BaseModel):
    periodo: str
    facturas: list[FacturaResumen]
    # Solo con exactamente una factura vigente; si no, None (nunca 0).
    subtotal: float | None
    igv: float | None
    total: float | None


class ComparacionPeriodos(BaseModel):
    """Diferencia entre dos periodos facturados (sin IGV, excluye anuladas).

    Si un periodo no tiene facturas o tiene más de una vigente (duplicado de
    CS-01), `comparable` es False, `motivo` lo explica y la variación y las
    líneas quedan en None: no se suman ni se elige una factura.
    """
    periodo_a: PeriodoComparado
    periodo_b: PeriodoComparado
    comparable: bool
    motivo: Literal["facturas_multiples", "periodo_sin_facturas"] | None
    umbral_variacion_pct: float
    variacion_subtotal: float | None
    variacion_pct: float | None
    variacion_fuerte: bool | None
    lineas: list[LineaComparada] | None
    lineas_sin_cambio: int | None
