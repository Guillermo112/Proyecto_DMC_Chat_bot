"""Índice en memoria: fragmentos → vectores → búsqueda con umbral y MMR.

- Motor denso: embeddings locales (`SENTENCE_TRANSFORMER_MODEL`, granite 97M).
  Si no está disponible y `RAG_MOTOR=auto`, cae a TF-IDF: peor calidad, pero
  funciona sin red. Los tests usan TF-IDF o un `embedder` simulado.
- Umbral: si nada lo supera no se devuelve contexto. Es mejor "no está en los
  documentos" que citar un párrafo que no responde.
- MMR: de `RAG_K_INICIAL` candidatos se eligen `RAG_K_FINAL` relevantes y
  distintos entre sí.
"""
from __future__ import annotations

import logging
import threading
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Sequence

import numpy as np

from app import config
from app.rag.ingesta import Fragmento, construir_fragmentos

log = logging.getLogger(__name__)

MOTORES = ("auto", "denso", "tfidf")

# ---------------------------------------------------------------------------
# Embeddings densos (carga perezosa: torch y el modelo solo si se usan)
# ---------------------------------------------------------------------------
_CANDADO_MODELO = threading.Lock()


@lru_cache(maxsize=1)
def _modelo():
    import torch
    from sentence_transformers import SentenceTransformer

    with _CANDADO_MODELO:  # dos hilos cargando el modelo a la vez agotan la memoria
        return SentenceTransformer(config.SENTENCE_TRANSFORMER_MODEL,
                                   model_kwargs={"dtype": torch.float32})


def embed_denso(textos: Sequence[str]) -> np.ndarray:
    matriz = _modelo().encode(list(textos), normalize_embeddings=True,
                              batch_size=32, show_progress_bar=False)
    return np.asarray(matriz, dtype="float32")


# ---------------------------------------------------------------------------
# TF-IDF: palabras vacías en español (sklearn solo trae la lista inglesa)
# ---------------------------------------------------------------------------
_STOPWORDS_BASE = """
de la que el en y a los del se las por un para con no una su al lo como más pero
sus le ya o este sí porque esta entre cuando muy sin sobre también me hasta hay
donde quien desde todo nos durante todos uno les ni contra otros ese eso ante
ellos e esto mí antes algunos qué unos yo otro otras otra él tanto esa estos
mucho quienes nada muchos cual poco ella estar estas algunas algo nosotros mi mis
tú te ti tu tus ellas esos esas estoy estás está estamos están ser soy eres somos
son fue era han has hemos tiene tienen
""".split()


def _sin_acentos(palabra: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", palabra)
                   if unicodedata.category(c) != "Mn")


# El tokenizador quita los acentos: la lista debe ir igual o no coincide.
STOPWORDS_ES = sorted({_sin_acentos(p) for p in _STOPWORDS_BASE})


# ---------------------------------------------------------------------------
# Índice
# ---------------------------------------------------------------------------
@dataclass
class IndiceConocimiento:
    """Fragmentos + matriz de vectores. `fragmentos=None` lee las fuentes configuradas."""

    fragmentos: list[Fragmento] | None = None
    motor: str = field(default_factory=lambda: config.RAG_MOTOR)
    embedder: Callable[[Sequence[str]], np.ndarray] | None = None
    aviso: str = ""
    _matriz: Any = field(default=None, repr=False)
    _tfidf: Any = field(default=None, repr=False)
    _motor_usado: str = ""
    _candado: Any = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.motor not in MOTORES:
            raise ValueError(f"RAG_MOTOR inválido: {self.motor!r} (usa {', '.join(MOTORES)})")
        if self.fragmentos is None:
            self.fragmentos = construir_fragmentos()

    # -- vectores ------------------------------------------------------------
    def _vectorizar_corpus(self, textos: Sequence[str]) -> Any:
        if self.embedder is not None:
            self._motor_usado = "denso"
            return np.asarray(self.embedder(list(textos)), dtype="float32")
        if self.motor in ("auto", "denso"):
            try:
                matriz = embed_denso(textos)
                self._motor_usado = "denso"
                return matriz
            except Exception as exc:  # noqa: BLE001 - sin paquetes, sin modelo o sin red
                if self.motor == "denso":
                    raise
                self.aviso = (f"Embeddings locales no disponibles ({type(exc).__name__}); "
                              "se usa TF-IDF.")
                log.warning("rag.degradacion %s", self.aviso)
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._tfidf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True,
                                      strip_accents="unicode", stop_words=STOPWORDS_ES)
        self._motor_usado = "tfidf"
        return self._tfidf.fit_transform(textos)

    def _vectorizar_consulta(self, texto: str) -> Any:
        if self._motor_usado == "tfidf":
            return self._tfidf.transform([texto])
        if self.embedder is not None:
            return np.asarray(self.embedder([texto]), dtype="float32")
        return embed_denso([texto])

    def indexar(self) -> int:
        """Calcula la matriz una sola vez (seguro entre hilos). Devuelve los fragmentos."""
        if self._matriz is None and self.fragmentos:
            with self._candado:
                if self._matriz is None:
                    self._matriz = self._vectorizar_corpus([f.texto for f in self.fragmentos])
        return len(self.fragmentos)

    @property
    def motor_usado(self) -> str:
        return self._motor_usado or "sin indexar"

    # -- similitudes ---------------------------------------------------------
    def _similitudes(self, pregunta: str) -> np.ndarray:
        consulta = self._vectorizar_consulta(pregunta)
        if self._motor_usado == "tfidf":
            from sklearn.metrics.pairwise import cosine_similarity

            return cosine_similarity(consulta, self._matriz)[0]
        return self._matriz @ consulta[0]

    def _similitud_entre(self, indices: Sequence[int]) -> np.ndarray:
        sub = self._matriz[list(indices)]
        if self._motor_usado == "tfidf":
            from sklearn.metrics.pairwise import cosine_similarity

            return cosine_similarity(sub)
        return sub @ sub.T

    # -- búsqueda ------------------------------------------------------------
    def buscar(self, pregunta: str, k: int | None = None, inicial: int | None = None,
               lam: float | None = None, umbral: float | None = None) -> list[dict[str, Any]]:
        """Hasta `k` fragmentos sobre el umbral, elegidos con MMR. Vacío = sin contexto."""
        if not pregunta.strip() or not self.indexar():
            return []
        k = k or config.RAG_K_FINAL
        inicial = max(inicial or config.RAG_K_INICIAL, k)
        lam = config.RAG_MMR_LAMBDA if lam is None else lam
        if umbral is None:
            umbral = config.RAG_UMBRAL if self._motor_usado == "denso" else config.RAG_UMBRAL_TFIDF

        sim = self._similitudes(pregunta)
        candidatos = [int(i) for i in np.argsort(-sim)[:inicial] if float(sim[i]) >= umbral]
        if not candidatos:
            return []

        entre = self._similitud_entre(candidatos)
        pos = {indice: p for p, indice in enumerate(candidatos)}
        elegidos: list[int] = []
        while candidatos and len(elegidos) < k:
            if not elegidos:
                mejor = max(candidatos, key=lambda i: float(sim[i]))
            else:
                def puntaje(i: int) -> float:
                    redundancia = max(float(entre[pos[i], pos[j]]) for j in elegidos)
                    return lam * float(sim[i]) - (1 - lam) * redundancia

                mejor = max(candidatos, key=puntaje)
            elegidos.append(mejor)
            candidatos.remove(mejor)

        return [{**self.fragmentos[i].to_dict(), "score": round(float(sim[i]), 4)}
                for i in elegidos]

    def contexto(self, pregunta: str, k: int | None = None) -> str:
        """Fragmentos listos para el prompt, cada uno con su cita. Vacío = sin contexto."""
        return "\n\n".join(
            f"[{h['fuente']}" + (f" · pág. {h['pagina']}" if h["pagina"] else f" · {h['id']}")
            + f"]\n{h['texto']}"
            for h in self.buscar(pregunta, k=k)
        )

    def umbral(self) -> float:
        """Umbral configurado para el motor en uso (cada motor tiene su escala)."""
        return config.RAG_UMBRAL if self._motor_usado == "denso" else config.RAG_UMBRAL_TFIDF

    def info(self) -> dict[str, Any]:
        """Estado sin forzar la indexación (no hace esperar al modelo)."""
        return {
            "fuentes": sorted({f.fuente for f in self.fragmentos}),
            "fragmentos": len(self.fragmentos),
            "motor": self.motor_usado,
            "indexado": self._matriz is not None,
            "aviso": self.aviso or None,
        }


# ---------------------------------------------------------------------------
# Instancia única por proceso (la comparten el chat y /dev/rag)
# ---------------------------------------------------------------------------
_indice_global: IndiceConocimiento | None = None
_candado_global = threading.Lock()


def obtener_indice() -> IndiceConocimiento:
    """Índice construido e indexado una sola vez (leer PDF y cargar el modelo tarda ~10 s)."""
    global _indice_global
    if _indice_global is None:
        with _candado_global:
            if _indice_global is None:
                indice = IndiceConocimiento()
                indice.indexar()
                _indice_global = indice
    return _indice_global
