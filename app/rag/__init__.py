"""RAG de conocimiento general (modo A): políticas, catálogo y glosario.

- `ingesta`: fuentes → fragmentos, con lista blanca y control de modo B.
- `indice`: vectores, umbral y MMR.

Nunca es fuente de datos del cliente: esos salen de las herramientas (`app/tools`).
"""
from app.rag.indice import IndiceConocimiento
from app.rag.ingesta import (
    ContenidoModoB,
    Fragmento,
    construir_fragmentos,
    fragmentos_catalogo,
    fragmentos_pdf,
    marcas_modo_b,
)

__all__ = [
    "ContenidoModoB",
    "Fragmento",
    "IndiceConocimiento",
    "construir_fragmentos",
    "fragmentos_catalogo",
    "fragmentos_pdf",
    "marcas_modo_b",
]
