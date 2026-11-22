"""Modelos de POST /mi/chat."""
from typing import Any

from pydantic import BaseModel, Field


class ChatPeticion(BaseModel):
    mensaje: str = Field(..., min_length=1, max_length=2000)
    conversacion_id: str = Field("principal", pattern=r"^[A-Za-z0-9_-]{1,64}$",
                                 description="Lo genera la página; uno nuevo = conversación nueva")


class HerramientaUsada(BaseModel):
    nombre: str
    argumentos: dict[str, Any]
    ok: bool
    ms: int
    resumen: str
    resultado: str  # JSON recortado, para el panel de traza


class DocumentoUsado(BaseModel):
    id: str
    fuente: str
    pagina: int | None
    seccion: str | None
    score: float
    texto: str


class ChatRespuesta(BaseModel):
    respuesta: str
    herramientas: list[HerramientaUsada]
    documentos: list[DocumentoUsado]
    llamadas_modelo: int
    tokens: dict[str, int]  # entrada, salida y cache (DeepSeek)
    modelo: str
    ms: int
    aviso: str | None = None
