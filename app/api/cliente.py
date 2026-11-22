"""API del cliente autenticado: `/mi/...`.

El cliente sale **solo** del token de sesión (`cliente_actual`); ninguna ruta
recibe `cliente_id` por URL, query o cuerpo, así que no hay nada que cambiar para
ver datos de otro cliente. Se apoya en `app/data/facturacion.py`, cuyas consultas
filtran siempre por `cliente_id`.

Una factura de otro cliente responde 404, igual que una inexistente, para no
revelar qué números existen.

Al agregar rutas aquí: tomar el cliente con `Depends(cliente_actual)` y nunca
aceptar un `cliente_id` del usuario. El router ya exige el token para todas.

`POST /mi/casos` es la única ruta que escribe (`app/data/casos.py`).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from app.auth.sesion import cliente_actual
from app.data import casos, facturacion
from app.schemas import (
    AnomaliasCliente,
    CasoRegistrado,
    Cliente,
    ComparacionPeriodos,
    FacturaDetalle,
    ListaCasos,
    ListaServicios,
    ListaSolicitudes,
    NuevoCaso,
    PaginaFacturas,
    ResumenFacturacion,
    SaldoPendiente,
)
from app.schemas.facturacion import EstadoFactura, EstadoServicio, EstadoSolicitud

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


@router.get("/anomalias", response_model=AnomaliasCliente)
def mis_anomalias(cliente_id: int = Depends(cliente_actual)):
    """Anomalías detectadas: duplicados, bajas facturadas, tarifas distintas, excesos y SLA.

    Montos sin IGV y observados: no son una devolución ni un ajuste aprobado.
    """
    return facturacion.detectar_anomalias(cliente_id)


@router.get("/solicitudes", response_model=ListaSolicitudes)
def mis_solicitudes(
    estado: EstadoSolicitud | None = Query(None, description="abierta, en_proceso o cerrada; por defecto, todas"),
    cliente_id: int = Depends(cliente_actual),
):
    """Solicitudes con días transcurridos y si están fuera del plazo de atención (CS-06)."""
    return _400(facturacion.consultar_solicitudes, cliente_id, estado)


@router.post(
    "/casos",
    response_model=CasoRegistrado,
    status_code=201,
    responses={
        200: {"model": CasoRegistrado, "description": "Ya había un caso abierto equivalente: se devuelve ese"},
        400: {"description": "Anomalía no detectada o ambigua, o solicitud dentro del plazo"},
        404: {"description": "Referencia inexistente o de otro cliente"},
    },
)
def registrar_caso(nuevo: NuevoCaso, response: Response, cliente_id: int = Depends(cliente_actual)):
    """Registra el caso y lo deriva al ejecutivo del cliente (modo A).

    Guarda las palabras del cliente y el aviso en el historial. 201 si se creó;
    200 con `ya_existia: true` si ya había uno abierto equivalente (un reintento
    no duplica). Los tipos de anomalía toman la referencia y el monto de
    `/mi/anomalias`, nunca del cuerpo.
    """
    try:
        caso = casos.registrar_caso(cliente_id, nuevo)
    except casos.ReferenciaNoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if caso.ya_existia:
        response.status_code = 200
    return caso


@router.get("/casos", response_model=ListaCasos)
def mis_casos(cliente_id: int = Depends(cliente_actual)):
    """Casos del cliente y su estado, del más reciente al más antiguo."""
    return casos.listar_casos(cliente_id)
