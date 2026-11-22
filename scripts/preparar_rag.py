"""Construye el índice del RAG una vez: descarga el modelo de embeddings y valida las fuentes.

Uso (desde la raíz):  python -X utf8 -m scripts.preparar_rag

- Descarga `SENTENCE_TRANSFORMER_MODEL` (~195 MB) a la caché de Hugging Face, para
  que el primer uso de /dev/rag (y luego del chat) no espere la descarga.
- Comprueba que los PDF y `catalogo.json` existen y pasan el control de modo B.

Sale con código 1 si falla (sin red, fuente faltante, modo B en un JSON). La API
igual funciona sin el modelo: cae a TF-IDF con peor calidad.
"""
import logging
import os
import time
from collections import Counter

# Sin barras de progreso ni avisos de Hugging Face en la salida del instalador
# (el modelo es público: el aviso de HF_TOKEN no aplica).
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")


class _Contador(logging.Handler):
    """Cuenta los descartes del modo B en vez de imprimir cada uno."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.descartes = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage().startswith("rag.descartado"):
            self.descartes += 1


def main() -> int:
    contador = _Contador()
    logging.getLogger("app.rag").addHandler(contador)
    logging.getLogger("app.rag").propagate = False
    for ruidoso in ("sentence_transformers", "transformers", "huggingface_hub"):
        logging.getLogger(ruidoso).setLevel(logging.ERROR)

    from app.rag import IndiceConocimiento

    inicio = time.perf_counter()
    try:
        indice = IndiceConocimiento(motor="denso")
        indice.indexar()
    except Exception as exc:  # noqa: BLE001 - se informa y se sale con error
        print(f"No se pudo preparar el índice: {type(exc).__name__}: {exc}")
        return 1
    por_fuente = Counter(f.fuente for f in indice.fragmentos)
    print(f"Índice listo en {time.perf_counter() - inicio:.0f} s (motor {indice.motor_usado}): "
          f"{len(indice.fragmentos)} fragmentos, {contador.descartes} descartes de modo B.")
    for fuente, n in sorted(por_fuente.items()):
        print(f"  {fuente}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
