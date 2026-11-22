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
    """
    fecha_corte: str
    saldo_total: float
    saldo_vencido: float
    cantidad_facturas: int
    facturas: list[FacturaResumen]
    notas_credito_aplicadas: list[NotaCreditoAplicada]


class ResumenPeriodo(BaseModel):
    periodo: str
    cantidad_facturas: int
    subtotal: float
    igv: float
    total: float


class ResumenFacturacion(BaseModel):
    fecha_desde: str
    fecha_hasta: str
    periodos: list[ResumenPeriodo]
    cantidad_facturas: int
    subtotal: float
    igv: float
    total: float



