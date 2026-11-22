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





# ------------------------------------------------- servicios contratados

EstadoServicio = Literal["activo", "baja"]


class Servicio(BaseModel):
    """Servicio contratado por el cliente.

    `tarifa_pactada` es la del contrato, por unidad y mes, sin IGV; es la
    referencia para CS-03 (no se expone la tarifa de lista del producto, para
    no confundirla con la pactada). `sla_pactado` es una fracción (0.997 =
    99,7 % de disponibilidad); None en móviles. Los GB solo aplican a móviles.
    """
    id_servicio: int
    codigo_producto: str
    producto: str
    unidad: str
    sede: str
    cantidad: int
    tarifa_pactada: float
    sla_pactado: float | None
    gb_incluidos_por_linea: float | None
    precio_gb_exceso: float | None
    fecha_activacion: str
    fecha_baja: str | None
    estado: EstadoServicio


class ListaServicios(BaseModel):
    fecha_corte: str
    servicios: list[Servicio]


# ------------------------------------------------- comparación entre periodos


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


# ------------------------------------------------- anomalías detectadas

class CobroObservado(BaseModel):
    """Un cobro de una factura que forma parte de la anomalía."""
    periodo: str
    numero_factura: str
    monto_observado: float  # sin IGV


class FacturaDuplicada(BaseModel):
    """CS-01: más de una factura vigente del mismo periodo e importe.

    `monto_observado` es el importe de las facturas de más (n - 1), sin IGV.
    No dice cuál de ellas vale: eso lo define el área responsable.
    """
    periodo: str
    facturas: list[FacturaResumen]
    monto_observado: float
    caso_abierto: str | None = None


class ServicioBajaFacturado(BaseModel):
    """CS-02: servicio cobrado en periodos posteriores al de su baja.

    El periodo de la baja no cuenta (se cobra completo).
    """
    servicio: Servicio
    cobros: list[CobroObservado]
    monto_observado: float
    caso_abierto: str | None = None


class CobroTarifa(CobroObservado):
    tarifa_facturada: float
    cantidad: float


class TarifaDistinta(BaseModel):
    """CS-03: precio unitario facturado distinto de la tarifa pactada."""
    servicio: Servicio
    tarifa_pactada: float
    cobros: list[CobroTarifa]
    monto_observado: float
    caso_abierto: str | None = None


class ExcesoSinSustento(BaseModel):
    """CS-04: GB de exceso facturados que el consumo registrado no respalda.

    `gb_*_registrados` son None si no hay consumo registrado del periodo.
    """
    servicio: Servicio
    periodo: str
    numero_factura: str
    gb_facturados: float
    precio_gb: float
    gb_incluidos_registrados: float | None
    gb_usados_registrados: float | None
    gb_exceso_registrados: float | None
    monto_observado: float
    caso_abierto: str | None = None


class AveriaSlaIncumplido(BaseModel):
    """CS-05 / CS-07: caída por encima de la tolerancia del SLA, sin compensación.

    `monto_observado` = tarifa pactada × unidades afectadas × horas fuera ÷ 720.
    No incluye la causa técnica de la avería (el PDF prohíbe comunicarla).
    """
    servicio: Servicio
    id_averia: int
    periodo: str
    fecha_inicio: str
    fecha_fin: str
    unidades_afectadas: int
    horas_caida: float
    tolerancia_horas: float
    horas_fuera_de_sla: float
    monto_observado: float
    caso_abierto: str | None = None


class AnomaliasCliente(BaseModel):
    """Anomalías detectadas con las vistas de `db/schema.sql`, solo del cliente.

    Los montos son sin IGV y describen lo observado: no son una promesa de
    devolución ni un ajuste aprobado. Excluye facturas anuladas y averías que
    ya tienen un ajuste propuesto, aprobado o aplicado.

    `caso_abierto` (en cada anomalía) es el número del caso abierto, derivado o
    escalado que ya la registró (p. ej. "C-000019"): no registrarla de nuevo.
    """
    fecha_corte: str
    cantidad: int
    facturas_duplicadas: list[FacturaDuplicada]
    servicios_baja_facturados: list[ServicioBajaFacturado]
    tarifas_distintas: list[TarifaDistinta]
    excesos_sin_sustento: list[ExcesoSinSustento]
    averias_sla_incumplido: list[AveriaSlaIncumplido]


# ------------------------------------------------- solicitudes

EstadoSolicitud = Literal["abierta", "en_proceso", "cerrada"]


class Solicitud(BaseModel):
    """Solicitud del cliente (CS-06).

    `dias_transcurridos` va hasta la fecha de corte si sigue abierta o en
    proceso, y hasta `fecha_cierre` si está cerrada. `fuera_de_plazo` solo
    puede ser True en las no cerradas (misma regla que v_solicitudes_vencidas).
    """
    id_solicitud: int
    tipo: str
    descripcion: str
    estado: EstadoSolicitud
    fecha_registro: str
    fecha_cierre: str | None
    dias_transcurridos: int
    fuera_de_plazo: bool
    responsable_nombre: str | None


class ListaSolicitudes(BaseModel):
    fecha_corte: str
    plazo_atencion_dias: int
    cantidad_fuera_de_plazo: int
    solicitudes: list[Solicitud]
