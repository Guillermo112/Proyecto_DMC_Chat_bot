"""
API FastAPI para probar en Postman todos los métodos públicos de
anticipa_crud_por_entidad.py.

Coloca este archivo como app/main.py.
Se asume que el repositorio está en:
app/repositories/anticipa_crud_por_entidad.py

Ejecutar desde la raíz del proyecto:
    uvicorn app.main:app --reload

Documentación interactiva:
    http://127.0.0.1:8000/docs

IMPORTANTE:
- API de desarrollo. Antes de exponerla fuera de localhost agrega autenticación,
  autorización por rol, límites de uso y validación de propiedad del cliente.
- Los métodos que consultan vistas dependen de que esas vistas existan en SQLite
  y tengan las columnas utilizadas en el repositorio.
"""

from typing import Any

from fastapi import FastAPI, APIRouter, HTTPException, Query, Path as PathParam
from fastapi.responses import JSONResponse
from sqlite3 import IntegrityError, OperationalError, DatabaseError

from app.auth.rutas import router as auth_router
from app.data import get_connection
from app.data.anticipa_crud_por_entidad import (
    PersonalCRUD,
    ProductoCRUD,
    ClienteCRUD,
    ServicioContratadoCRUD,
    FacturaCRUD,
    FacturaLineaCRUD,
    ConsumoCRUD,
    AveriaCRUD,
    SolicitudCRUD,
    CasoCRUD,
    AjusteCRUD,
    InteraccionLogCRUD,
    PoliticaTramoCRUD,
    ParametroCRUD,
)

app = FastAPI(
    title="Chatbot Anticipa API",
    description="Endpoints CRUD y operaciones de negocio para probar el chatbot Anticipa.",
    version="1.0.0",
)

app.include_router(auth_router)


@app.get("/health", tags=["Sistema"])
def health():
    """Verifica que la API y la conexión SQLite estén disponibles."""
    try:
        with get_connection() as con:
            con.execute("SELECT 1").fetchone()
        return {"status": "OK", "db": "OK"}
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"status": "ERROR", "db": str(exc)},
        )


def ejecutar(func, *args, **kwargs):
    """Convierte errores del repositorio en respuestas HTTP entendibles."""
    try:
        return func(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Conflicto de integridad: {exc}")
    except OperationalError as exc:
        raise HTTPException(status_code=500, detail=f"Error SQL/SQLite: {exc}")
    except DatabaseError as exc:
        raise HTTPException(status_code=500, detail=f"Error de base de datos: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Instancias: se crean por proceso de API.
# ---------------------------------------------------------------------------

personal = PersonalCRUD()
producto = ProductoCRUD()
cliente = ClienteCRUD()
servicio = ServicioContratadoCRUD()
factura = FacturaCRUD()
factura_linea = FacturaLineaCRUD()
consumo = ConsumoCRUD()
averia = AveriaCRUD()
solicitud = SolicitudCRUD()
caso = CasoCRUD()
ajuste = AjusteCRUD()
interaccion_log = InteraccionLogCRUD()
politica_tramo = PoliticaTramoCRUD()
parametro = ParametroCRUD()


# ---------------------------------------------------------------------------
# CRUD estándar: POST /, GET /, GET /{id}, PUT /{id}, DELETE /{id}.
# Se crea un router por entidad para mantener URLs claras en Postman.
# ---------------------------------------------------------------------------

def registrar_crud(
    prefijo: str,
    tag: str,
    repo,
    permite_desactivar: bool = False,
):
    router = APIRouter(prefix=prefijo, tags=[tag])

    @router.post("", status_code=201, name=f"crear_{tag}")
    def crear(datos: dict[str, Any]):
        nuevo_id = ejecutar(repo.crear, datos)
        return {"id": nuevo_id, "mensaje": "Registro creado"}

    @router.get("", name=f"listar_{tag}")
    def listar(
        limite: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        ordenar_por: str | None = None,
        descendente: bool = False,
    ):
        return ejecutar(
            repo.listar,
            filtros=None,
            limite=limite,
            offset=offset,
            ordenar_por=ordenar_por,
            descendente=descendente,
        )

    @router.get("/{registro_id}", name=f"obtener_{tag}")
    def obtener(registro_id: str):
        resultado = ejecutar(repo.obtener, registro_id)
        if resultado is None:
            raise HTTPException(status_code=404, detail="Registro no encontrado")
        return resultado

    @router.put("/{registro_id}", name=f"actualizar_{tag}")
    def actualizar(registro_id: str, datos: dict[str, Any]):
        actualizado = ejecutar(repo.actualizar, registro_id, datos)
        if not actualizado:
            raise HTTPException(status_code=404, detail="Registro no encontrado")
        return {"actualizado": True}

    @router.delete("/{registro_id}", name=f"eliminar_{tag}")
    def eliminar(registro_id: str):
        eliminado = ejecutar(repo.eliminar, registro_id)
        if not eliminado:
            raise HTTPException(status_code=404, detail="Registro no encontrado")
        return {"eliminado": True}

    if permite_desactivar:
        @router.patch("/{registro_id}/desactivar", name=f"desactivar_{tag}")
        def desactivar(registro_id: str, estado: str = Query("inactivo")):
            ok = ejecutar(repo.desactivar, registro_id, estado)
            if not ok:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
            return {"desactivado": True, "estado": estado}

    app.include_router(router)


registrar_crud("/api/personal", "Personal", personal)
registrar_crud("/api/productos", "Productos", producto)
registrar_crud("/api/clientes", "Clientes", cliente, True)
registrar_crud("/api/servicios", "Servicios contratados", servicio, True)
registrar_crud("/api/facturas", "Facturas", factura)
registrar_crud("/api/factura-lineas", "Líneas de factura", factura_linea)
registrar_crud("/api/consumos", "Consumos", consumo)
registrar_crud("/api/averias", "Averías", averia)
registrar_crud("/api/solicitudes", "Solicitudes", solicitud)
registrar_crud("/api/casos", "Casos", caso)
registrar_crud("/api/ajustes", "Ajustes", ajuste)
# "verificacion" no se expone aquí: solo se maneja vía /auth (app/auth/rutas.py).
registrar_crud("/api/interacciones", "Interacciones", interaccion_log)
registrar_crud("/api/politicas-tramo", "Políticas por tramo", politica_tramo)
registrar_crud("/api/parametros", "Parámetros", parametro)


# ---------------------------------------------------------------------------
# Filtros del listado. Endpoint separado para no mezclar con el GET general.
# ---------------------------------------------------------------------------

@app.post("/api/{entidad}/buscar", tags=["Búsquedas"])
def buscar_registros(
    entidad: str,
    filtros: dict[str, Any],
    limite: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    repos = {
        "personal": personal, "productos": producto, "clientes": cliente,
        "servicios": servicio, "facturas": factura,
        "factura-lineas": factura_linea, "consumos": consumo,
        "averias": averia, "solicitudes": solicitud, "casos": caso,
        "ajustes": ajuste,
        "interacciones": interaccion_log, "politicas-tramo": politica_tramo,
        "parametros": parametro,
    }
    repo = repos.get(entidad)
    if repo is None:
        raise HTTPException(status_code=404, detail="Entidad no reconocida")
    return ejecutar(repo.listar, filtros, limite, offset)


# ---------------------------------------------------------------------------
# Métodos adicionales de PersonalCRUD
# ---------------------------------------------------------------------------

@app.get("/api/personal/por-rol/{rol}", tags=["Personal - métodos adicionales"])
def personal_por_rol(rol: str):
    return ejecutar(personal.obtener_por_rol, rol)


@app.get("/api/personal/por-correo/{correo}", tags=["Personal - métodos adicionales"])
def personal_por_correo(correo: str):
    result = ejecutar(personal.obtener_por_correo, correo)
    if result is None:
        raise HTTPException(404, "Personal no encontrado")
    return result


# ClienteCRUD
@app.get("/api/clientes/por-ruc/{ruc}", tags=["Clientes - métodos adicionales"])
def cliente_por_ruc(ruc: str):
    result = ejecutar(cliente.obtener_por_ruc, ruc)
    if result is None:
        raise HTTPException(404, "Cliente no encontrado")
    return result


@app.get("/api/clientes/{cliente_id}/contacto-facturacion", tags=["Clientes - métodos adicionales"])
def cliente_contacto(cliente_id: int):
    result = ejecutar(cliente.obtener_contacto_facturacion, cliente_id)
    if result is None:
        raise HTTPException(404, "Contacto no encontrado")
    return result


@app.get("/api/clientes/{cliente_id}/ejecutivo", tags=["Clientes - métodos adicionales"])
def cliente_ejecutivo(cliente_id: int):
    result = ejecutar(cliente.obtener_ejecutivo, cliente_id)
    if result is None:
        raise HTTPException(404, "Ejecutivo no encontrado")
    return result


# ServicioContratadoCRUD
@app.get("/api/clientes/{cliente_id}/servicios", tags=["Servicios - métodos adicionales"])
def servicios_cliente(cliente_id: int):
    return ejecutar(servicio.listar_servicios_cliente, cliente_id)


@app.get("/api/servicios/{servicio_id}/tarifa-sla", tags=["Servicios - métodos adicionales"])
def servicio_tarifa_sla(servicio_id: int):
    result = ejecutar(servicio.obtener_tarifa_y_sla, servicio_id)
    if result is None:
        raise HTTPException(404, "Servicio no encontrado")
    return result


@app.get("/api/clientes/{cliente_id}/anomalias/servicios-baja-facturados", tags=["Detección de anomalías"])
def servicios_baja_facturados(cliente_id: int):
    return ejecutar(servicio.detectar_baja_facturada, cliente_id)


# FacturaCRUD
@app.get("/api/clientes/{cliente_id}/facturas/periodo/{periodo}", tags=["Facturas - métodos adicionales"])
def facturas_periodo(cliente_id: int, periodo: str):
    return ejecutar(factura.obtener_por_periodo, cliente_id, periodo)


@app.get("/api/clientes/{cliente_id}/facturas/periodo/{periodo}/detalle", tags=["Facturas - métodos adicionales"])
def facturas_periodo_detalle(cliente_id: int, periodo: str):
    return ejecutar(factura.obtener_factura_con_lineas, cliente_id, periodo)


@app.get("/api/clientes/{cliente_id}/saldo", tags=["Facturas - métodos adicionales"])
def saldo_cliente(cliente_id: int):
    return ejecutar(factura.consultar_saldo, cliente_id)


@app.get("/api/clientes/{cliente_id}/facturas/duplicadas", tags=["Detección de anomalías"])
def facturas_duplicadas(cliente_id: int):
    return ejecutar(factura.detectar_duplicadas, cliente_id)


@app.get("/api/clientes/{cliente_id}/facturacion/variaciones", tags=["Detección de anomalías"])
def variacion_facturacion(cliente_id: int):
    return ejecutar(factura.detectar_variacion_facturacion, cliente_id)


# FacturaLineaCRUD
@app.get("/api/facturas/{factura_id}/lineas", tags=["Facturas - métodos adicionales"])
def lineas_factura(factura_id: int):
    return ejecutar(factura_linea.listar_por_factura, factura_id)


@app.get("/api/clientes/{cliente_id}/anomalias/tarifas-distintas", tags=["Detección de anomalías"])
def tarifas_distintas(cliente_id: int):
    return ejecutar(factura_linea.detectar_tarifas_distintas, cliente_id)


@app.get("/api/clientes/{cliente_id}/anomalias/excesos-sin-sustento", tags=["Detección de anomalías"])
def excesos_sin_sustento(cliente_id: int):
    return ejecutar(factura_linea.detectar_excesos_sin_sustento, cliente_id)


# ConsumoCRUD
@app.get("/api/servicios/{servicio_id}/consumo/{periodo}", tags=["Consumos - métodos adicionales"])
def consumo_servicio(servicio_id: int, periodo: str):
    result = ejecutar(consumo.obtener_consumo, servicio_id, periodo)
    if result is None:
        raise HTTPException(404, "Consumo no encontrado")
    return result


# AveriaCRUD
@app.get("/api/clientes/{cliente_id}/averias", tags=["Averías - métodos adicionales"])
def averias_cliente(cliente_id: int):
    return ejecutar(averia.listar_averias_cliente, cliente_id)


@app.get("/api/clientes/{cliente_id}/anomalias/averias-sin-compensar", tags=["Detección de anomalías"])
def averias_sin_compensar(cliente_id: int):
    return ejecutar(averia.detectar_sin_compensar, cliente_id)


# SolicitudCRUD
@app.get("/api/clientes/{cliente_id}/solicitudes", tags=["Solicitudes - métodos adicionales"])
def solicitudes_cliente(cliente_id: int):
    return ejecutar(solicitud.listar_solicitudes_cliente, cliente_id)


@app.get("/api/clientes/{cliente_id}/solicitudes/vencidas", tags=["Solicitudes - métodos adicionales"])
def solicitudes_vencidas(cliente_id: int):
    return ejecutar(solicitud.detectar_vencidas, cliente_id)


@app.patch("/api/solicitudes/{solicitud_id}/estado", tags=["Solicitudes - métodos adicionales"])
def actualizar_estado_solicitud(solicitud_id: int, body: dict[str, str]):
    estado = body.get("estado")
    if not estado:
        raise HTTPException(400, "El campo estado es obligatorio")
    ok = ejecutar(solicitud.actualizar_estado, solicitud_id, estado)
    if not ok:
        raise HTTPException(404, "Solicitud no encontrada")
    return {"actualizado": True, "estado": estado}


# CasoCRUD
@app.get("/api/clientes/{cliente_id}/casos", tags=["Casos - métodos adicionales"])
def casos_cliente(cliente_id: int):
    return ejecutar(caso.listar_casos_cliente, cliente_id)


@app.patch("/api/casos/{caso_id}/derivar", tags=["Casos - métodos adicionales"])
def derivar_caso(caso_id: int, body: dict[str, int]):
    responsable_id = body.get("responsable_id")
    if responsable_id is None:
        raise HTTPException(400, "responsable_id es obligatorio")
    ok = ejecutar(caso.derivar_caso, caso_id, responsable_id)
    if not ok:
        raise HTTPException(404, "Caso no encontrado")
    return {"derivado": True, "responsable_id": responsable_id}


@app.patch("/api/casos/{caso_id}/cerrar", tags=["Casos - métodos adicionales"])
def cerrar_caso(caso_id: int, body: dict[str, Any] | None = None):
    sustento = (body or {}).get("sustento")
    ok = ejecutar(caso.cerrar_caso, caso_id, sustento)
    if not ok:
        raise HTTPException(404, "Caso no encontrado")
    return {"cerrado": True}


# AjusteCRUD
@app.get("/api/casos/{caso_id}/ajustes", tags=["Ajustes - métodos adicionales"])
def ajustes_caso(caso_id: int):
    return ejecutar(ajuste.listar_por_caso, caso_id)


@app.get("/api/clientes/{cliente_id}/gestos-comerciales/{periodo}", tags=["Ajustes - métodos adicionales"])
def validar_gesto(cliente_id: int, periodo: str):
    return ejecutar(ajuste.validar_gesto_mensual, cliente_id, periodo)


@app.patch("/api/ajustes/{ajuste_id}/aprobar", tags=["Ajustes - métodos adicionales"])
def aprobar_ajuste(ajuste_id: int, body: dict[str, int]):
    aprobador_id = body.get("aprobador_id")
    if aprobador_id is None:
        raise HTTPException(400, "aprobador_id es obligatorio")
    ok = ejecutar(ajuste.aprobar_ajuste, ajuste_id, aprobador_id)
    if not ok:
        raise HTTPException(404, "Ajuste no encontrado")
    return {"aprobado": True}


@app.patch("/api/ajustes/{ajuste_id}/rechazar", tags=["Ajustes - métodos adicionales"])
def rechazar_ajuste(ajuste_id: int, body: dict[str, int]):
    aprobador_id = body.get("aprobador_id")
    if aprobador_id is None:
        raise HTTPException(400, "aprobador_id es obligatorio")
    ok = ejecutar(ajuste.rechazar_ajuste, ajuste_id, aprobador_id)
    if not ok:
        raise HTTPException(404, "Ajuste no encontrado")
    return {"rechazado": True}


@app.patch("/api/ajustes/{ajuste_id}/aplicar", tags=["Ajustes - métodos adicionales"])
def aplicar_ajuste(ajuste_id: int, body: dict[str, str]):
    fecha = body.get("fecha_aplicacion")
    if not fecha:
        raise HTTPException(400, "fecha_aplicacion es obligatoria (YYYY-MM-DD)")
    ok = ejecutar(ajuste.aplicar_ajuste, ajuste_id, fecha)
    if not ok:
        raise HTTPException(404, "Ajuste no encontrado")
    return {"aplicado": True, "fecha_aplicacion": fecha}


# InteraccionLogCRUD
@app.get("/api/clientes/{cliente_id}/historial", tags=["Interacciones - métodos adicionales"])
def historial_cliente(cliente_id: int, limite: int = Query(50, ge=1, le=500)):
    return ejecutar(interaccion_log.obtener_historial_cliente, cliente_id, limite)


@app.get("/api/casos/{caso_id}/interacciones", tags=["Interacciones - métodos adicionales"])
def interacciones_caso(caso_id: int):
    return ejecutar(interaccion_log.listar_por_caso, caso_id)


# PoliticaTramoCRUD
@app.get("/api/politicas-tramo/calcular/{monto}", tags=["Políticas - métodos adicionales"])
def obtener_tramo(monto: float = PathParam(..., ge=0)):
    result = ejecutar(politica_tramo.obtener_tramo_por_monto, monto)
    if result is None:
        raise HTTPException(404, "No se encontró un tramo para ese monto")
    return result


# ParametroCRUD
@app.get("/api/parametros/{clave}/valor", tags=["Parámetros - métodos adicionales"])
def obtener_parametro(clave: str, default: str | None = None):
    return {"clave": clave, "valor": ejecutar(parametro.obtener_valor, clave, default)}


@app.get("/api/parametros/fecha-sistema/actual", tags=["Parámetros - métodos adicionales"])
def fecha_sistema():
    return {"fecha_actual": ejecutar(parametro.obtener_fecha_sistema)}


# Evita respuestas HTML ante excepciones no controladas.
@app.exception_handler(Exception)
async def error_general(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Error interno de la API"})
