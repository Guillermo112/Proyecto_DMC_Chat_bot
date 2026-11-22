"""Cliente de modelos de lenguaje (`app/llm/router.py`).

Lee `LLM_BASE_URL`, `LLM_API_KEY` y `LLM_MODEL` (y respaldos `LLM_2_*` ...
`LLM_9_*`) del entorno. Se importa `app.config` primero para que el `.env` de la
raíz ya esté cargado cuando el router lea las variables.

Esta capa solo habla con el modelo: no conoce clientes, facturas ni documentos.
"""
from app import config as _config  # noqa: F401  (carga el .env)
from app.llm.router import (
    Endpoint,
    RespuestaLLM,
    Router,
    SinProveedores,
    crear_router,
    listar_endpoints,
)

__all__ = [
    "Endpoint",
    "RespuestaLLM",
    "Router",
    "SinProveedores",
    "crear_router",
    "listar_endpoints",
]
