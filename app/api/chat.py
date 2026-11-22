"""Chat del cliente autenticado: `POST /mi/chat` y la página `/chat`.

Como el resto de `/mi`, el cliente sale **solo** del token (`cliente_actual`) y se
ata a las herramientas del turno: el modelo no puede consultar otro cliente.
La página `/chat` es estática: hace el login (RUC + código) y conversa con esta API.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Response
from fastapi.responses import FileResponse

from app.agente import ChatNoDisponible, ServicioChat, obtener_servicio
from app.auth.sesion import cliente_actual
from app.schemas.chat import ChatPeticion, ChatRespuesta

router = APIRouter(prefix="/mi", tags=["Chat"], dependencies=[Depends(cliente_actual)])
paginas = APIRouter()

PAGINA = Path(__file__).resolve().parent.parent / "static" / "chat.html"


@paginas.get("/chat", include_in_schema=False)
def pagina_chat():
    return FileResponse(PAGINA)


@router.post("/chat", response_model=ChatRespuesta)
def chat(peticion: ChatPeticion, cliente_id: int = Depends(cliente_actual),
         servicio: ServicioChat = Depends(obtener_servicio)):
    """Un turno: RAG previo, modelo con herramientas del cliente y traza de lo usado."""
    try:
        turno = servicio.responder(cliente_id, peticion.conversacion_id, peticion.mensaje)
    except ChatNoDisponible as exc:
        raise HTTPException(status_code=503, detail=f"El asistente no está disponible: {exc}")
    return ChatRespuesta(
        respuesta=turno.texto, herramientas=turno.herramientas, documentos=turno.documentos,
        llamadas_modelo=turno.llamadas, tokens=turno.tokens, modelo=turno.modelo,
        ms=turno.ms, aviso=turno.aviso,
    )


@router.delete("/chat/{conversacion_id}", status_code=204)
def reiniciar_chat(conversacion_id: str = PathParam(..., pattern=r"^[A-Za-z0-9_-]{1,64}$"),
                   cliente_id: int = Depends(cliente_actual),
                   servicio: ServicioChat = Depends(obtener_servicio)):
    """Olvida la conversación (solo la del cliente del token)."""
    servicio.reiniciar(cliente_id, conversacion_id)
    return Response(status_code=204)
