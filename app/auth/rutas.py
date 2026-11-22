"""Endpoints de identificación por RUC + código OTP enviado por correo.

Única vía HTTP para tocar la tabla `verificacion`: el CRUD genérico no la expone.

Pendiente: tras verificar no se emite todavía un token de sesión; los endpoints
con datos de cliente deberán exigirlo cuando exista.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth import otp

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Autenticación"])

# Misma respuesta exista o no el RUC, para no revelar quién es cliente.
_MENSAJE_ENVIO = "Si el RUC está registrado, enviamos un código al correo de facturación."


class SolicitudCodigo(BaseModel):
    ruc: str = Field(..., pattern=r"^\d{11}$", description="RUC de 11 dígitos")


class RespuestaSolicitud(BaseModel):
    id_verificacion: int
    mensaje: str


class VerificacionCodigo(BaseModel):
    id_verificacion: int = Field(..., gt=0)
    codigo: str = Field(..., pattern=r"^\d{6}$", description="Código de 6 dígitos")


class RespuestaVerificacion(BaseModel):
    verificado: bool
    cliente_id: int


@router.post("/solicitar-codigo", response_model=RespuestaSolicitud)
def solicitar_codigo(body: SolicitudCodigo):
    try:
        id_verificacion, _ = otp.solicitar_codigo(body.ruc)
    except ValueError as exc:
        # El formato del RUC ya lo valida el esquema: aquí solo queda el reenvío prematuro.
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - SMTP caído o no configurado
        log.exception("No se pudo enviar el código OTP")
        raise HTTPException(status_code=503, detail="No se pudo enviar el código; intenta más tarde") from exc
    return RespuestaSolicitud(id_verificacion=id_verificacion, mensaje=_MENSAJE_ENVIO)


@router.post("/verificar-codigo", response_model=RespuestaVerificacion)
def verificar_codigo(body: VerificacionCodigo):
    cliente_id = otp.verificar_codigo(body.id_verificacion, body.codigo)
    if cliente_id is None:
        raise HTTPException(status_code=401, detail="Código incorrecto, vencido o bloqueado")
    return RespuestaVerificacion(verificado=True, cliente_id=cliente_id)
