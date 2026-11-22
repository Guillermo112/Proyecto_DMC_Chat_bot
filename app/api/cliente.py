"""API del cliente autenticado: `/mi/...`.

El cliente sale **solo** del token de sesión (`cliente_actual`); ninguna ruta
recibe `cliente_id` por URL, query o cuerpo, así que no hay nada que cambiar para
ver datos de otro cliente. Se apoya en `app/data/facturacion.py`, cuyas consultas
filtran siempre por `cliente_id`.

Una factura de otro cliente responde 404, igual que una inexistente, para no
revelar qué números existen.

Al agregar rutas aquí: tomar el cliente con `Depends(cliente_actual)` y nunca
aceptar un `cliente_id` del usuario. El router ya exige el token para todas.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.auth.sesion import cliente_actual
from app.data import facturacion
from app.schemas import (
    Cliente,
    ComparacionPeriodos,
    FacturaDetalle,
    ListaServicios,
    PaginaFacturas,
    ResumenFacturacion,
    SaldoPendiente,
)
from app.schemas.facturacion import EstadoFactura, EstadoServicio

router = APIRouter(
    prefix="/mi",
    tags=["Cliente autenticado"],
    # Red de seguridad: aunque una ruta nueva olvide pedir el cliente, exige token.
    dependencies=[Depends(cliente_actual)],
    responses={401: {"description": "Falta el token de sesión, es inválido o expiró"}},
)


PATRON_PERIODO = r"^[0-9]{4}-(0[1-9]|1[0-2])$"  # AAAA-MM; [0-9] y no \d (dígitos Unicode)


def _400(func, *args, **kwargs):
    """Errores de validación de la capa de datos -> 400."""
    try:
        return func(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/perfil", response_model=Cliente)
def mi_perfil(cliente_id: int = Depends(cliente_actual)):
    """Datos del cliente y su ejecutivo de cuenta."""
    cliente = facturacion.obtener_cliente(cliente_id)
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.get("/facturas", response_model=PaginaFacturas)
def mis_facturas(
    cliente_id: int = Depends(cliente_actual),
    periodo: str | None = Query(
        None,
        pattern=PATRON_PERIODO,
        description="Mes facturado (AAAA-MM). La factura de 2026-09 se emite el 2026-10-01",
    ),
    fecha_desde: date | None = Query(None, description="Emisión desde (AAAA-MM-DD)"),
    fecha_hasta: date | None = Query(None, description="Emisión hasta (AAAA-MM-DD)"),
    estado: EstadoFactura | None = None,
    limite: int | None = Query(None, ge=1, description="Se recorta a LIMITE_MAXIMO"),
    offset: int = Query(0, ge=0),
):
    """Facturas propias, de la más reciente a la más antigua, paginadas."""
    return _400(
        facturacion.listar_facturas, cliente_id, fecha_desde, fecha_hasta, estado, limite, offset, periodo=periodo
    )


@router.get("/facturas/{numero}", response_model=FacturaDetalle, responses={404: {"description": "No existe o no es tuya"}})
def mi_factura(
    numero: str = Path(..., max_length=20, description="Número de factura, p. ej. F001-000254"),
    cliente_id: int = Depends(cliente_actual),
):
    """Cabecera y líneas de una factura propia."""
    detalle = _400(facturacion.detalle_factura, cliente_id, numero)
    if detalle is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return detalle


@router.get("/saldo", response_model=SaldoPendiente)
def mi_saldo(cliente_id: int = Depends(cliente_actual)):
    """Saldo pendiente (emitidas, vencidas y en disputa) y notas de crédito aplicadas."""
    return facturacion.saldo_pendiente(cliente_id)


@router.get("/resumen", response_model=ResumenFacturacion)
def mi_resumen(
    fecha_desde: date = Query(..., description="AAAA-MM-DD"),
    fecha_hasta: date = Query(..., description="AAAA-MM-DD"),
    cliente_id: int = Depends(cliente_actual),
):
    """Totales por periodo entre dos fechas de emisión (excluye anuladas)."""
    return _400(facturacion.resumen_facturacion, cliente_id, fecha_desde, fecha_hasta)


@router.get("/comparar", response_model=ComparacionPeriodos)
def mi_comparacion(
    periodo_b: str = Query(..., pattern=PATRON_PERIODO, description="Periodo a explicar (AAAA-MM)"),
    periodo_a: str | None = Query(
        None, pattern=PATRON_PERIODO, description="Periodo de referencia (AAAA-MM); por defecto, el mes anterior"
    ),
    cliente_id: int = Depends(cliente_actual),
):
    """Qué cambió entre dos periodos facturados: totales sin IGV y líneas nuevas, eliminadas o cambiadas.

    Si un periodo no tiene facturas o tiene más de una vigente (posible duplicado),
    responde `comparable: false` con el `motivo` y sin variación: no suma ni elige una.
    """
    return _400(facturacion.comparar_periodos, cliente_id, periodo_b, periodo_a)


@router.get("/servicios", response_model=ListaServicios)
def mis_servicios(
    estado: EstadoServicio | None = Query(None, description="activo o baja; por defecto, todos"),
    cliente_id: int = Depends(cliente_actual),
):
    """Servicios contratados: tarifa pactada (sin IGV), SLA, fecha de alta y de baja."""
    return _400(facturacion.obtener_servicios, cliente_id, estado)
