"""Banco de pruebas del RAG: `/dev/rag/...` (solo con ENTORNO=dev).

Sirve para mirar qué recupera el índice y calibrar el umbral y el MMR sin LLM ni
clave. No toca datos de clientes (el RAG nunca los tiene), por eso no pide sesión;
aun así se monta solo en desarrollo, igual que el CRUD `/api/...` (ver app/main.py).

El índice es el mismo del chat (`app.rag.indice.obtener_indice`): se construye la
primera vez que se usa (~10 s) y se reutiliza mientras el proceso viva.
"""
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app import config
from app.rag.indice import IndiceConocimiento, obtener_indice

router = APIRouter(prefix="/dev/rag", tags=["Desarrollo - RAG"])

PAGINA = Path(__file__).resolve().parent.parent / "static" / "rag.html"


def _umbral_por_defecto(indice: IndiceConocimiento) -> float:
    return indice.umbral()


@router.get("", include_in_schema=False)
def pagina():
    """Página web del banco de pruebas."""
    return FileResponse(PAGINA)


@router.get("/info")
def info():
    """Fuentes, fragmentos, motor y parámetros vigentes (construye el índice si falta)."""
    try:
        indice = obtener_indice()
    except Exception as exc:  # fuentes faltantes, contenido modo B en JSON, etc.
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
    return {
        **indice.info(),
        "secciones": sorted({f.seccion for f in indice.fragmentos}),
        "parametros": {
            "umbral": _umbral_por_defecto(indice),
            "k_inicial": config.RAG_K_INICIAL,
            "k_final": config.RAG_K_FINAL,
            "mmr_lambda": config.RAG_MMR_LAMBDA,
        },
    }


@router.get("/buscar")
def buscar(
    q: str = Query(..., min_length=1, max_length=500, description="Pregunta"),
    k: int = Query(8, ge=1, le=20, description="Cuántos fragmentos mostrar"),
    umbral: float | None = Query(None, ge=0, le=1, description="Vacío = el configurado"),
    lam: float | None = Query(None, ge=0, le=1, description="MMR: 1 relevancia, 0 variedad"),
):
    """Fragmentos elegidos con MMR **sin cortar por umbral**, marcando cuáles lo pasan.

    Así se ve qué quedaría fuera con el umbral actual y qué tan cerca estuvo.
    """
    indice = obtener_indice()
    corte = _umbral_por_defecto(indice) if umbral is None else umbral
    inicio = time.perf_counter()
    hallazgos = indice.buscar(q, k=k, inicial=max(k, config.RAG_K_INICIAL), lam=lam, umbral=0.0)
    # Lo que de verdad llegaría al prompt: RAG_K_FINAL fragmentos sobre el umbral.
    al_prompt = [h["id"] for h in indice.buscar(q, lam=lam, umbral=corte)]
    ms = round((time.perf_counter() - inicio) * 1000)
    return {
        "pregunta": q,
        "motor": indice.motor_usado,
        "umbral": corte,
        "mmr_lambda": config.RAG_MMR_LAMBDA if lam is None else lam,
        "ms": ms,
        "al_prompt": al_prompt,
        "resultados": [{**h, "pasa_umbral": h["score"] >= corte, "al_prompt": h["id"] in al_prompt}
                       for h in hallazgos],
    }
