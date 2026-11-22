"""Índice del RAG: umbral, MMR y motores. Sin red ni modelo descargado."""
import numpy as np
import pytest

from app.rag.indice import IndiceConocimiento
from app.rag.ingesta import Fragmento


def _f(id_: str, texto: str) -> Fragmento:
    return Fragmento(id=id_, fuente="prueba.pdf", seccion="pdf", texto=texto, pagina=1)


CORPUS = [
    _f("ciclo", "La facturación es mes vencido: el periodo se emite el día uno del mes siguiente."),
    _f("ciclo-bis", "Facturación mes vencido: cada periodo se emite el día uno del mes siguiente."),
    _f("igv", "El IGV es 18 por ciento y se suma al monto sin IGV de cada línea de la factura."),
    _f("sla", "El SLA define la disponibilidad mínima del enlace y la tolerancia de horas caídas."),
]


def test_tfidf_encuentra_el_fragmento_relevante():
    indice = IndiceConocimiento(fragmentos=CORPUS, motor="tfidf")
    hallazgos = indice.buscar("¿cuándo se emite la facturación del periodo?", k=1)
    assert hallazgos[0]["id"] in ("ciclo", "ciclo-bis")
    assert indice.motor_usado == "tfidf"
    assert {"id", "fuente", "seccion", "pagina", "texto", "score"} <= set(hallazgos[0])


def test_sin_coincidencias_no_hay_contexto():
    indice = IndiceConocimiento(fragmentos=CORPUS, motor="tfidf")
    assert indice.buscar("receta de pizza con anchoas") == []
    assert indice.contexto("receta de pizza con anchoas") == ""


def test_pregunta_vacia_e_indice_vacio():
    assert IndiceConocimiento(fragmentos=CORPUS, motor="tfidf").buscar("  ") == []
    assert IndiceConocimiento(fragmentos=[], motor="tfidf").buscar("facturación") == []


def _embedder_simulado(textos):
    """Vectores fijos: los dos 'ciclo' casi iguales, 'igv' a medio camino."""
    base = {
        "ciclo": [1.0, 0.0, 0.0], "ciclo-bis": [0.99, 0.14, 0.0],
        "igv": [0.6, 0.0, 0.8], "sla": [0.0, 1.0, 0.0],
    }
    por_texto = {f.texto: base[f.id] for f in CORPUS}
    salida = [por_texto.get(t, [1.0, 0.0, 0.3]) for t in textos]  # la consulta
    m = np.asarray(salida, dtype="float32")
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def test_mmr_evita_duplicados():
    indice = IndiceConocimiento(fragmentos=CORPUS, embedder=_embedder_simulado)
    solo_relevancia = [h["id"] for h in indice.buscar("x", k=2, lam=1.0, umbral=0.0)]
    con_variedad = [h["id"] for h in indice.buscar("x", k=2, lam=0.5, umbral=0.0)]
    assert solo_relevancia == ["ciclo", "ciclo-bis"]
    assert con_variedad == ["ciclo", "igv"]


def test_umbral_corta_candidatos():
    indice = IndiceConocimiento(fragmentos=CORPUS, embedder=_embedder_simulado)
    ids = [h["id"] for h in indice.buscar("x", k=4, umbral=0.9)]
    assert "sla" not in ids and ids


def test_contexto_cita_fuente_y_pagina():
    indice = IndiceConocimiento(fragmentos=CORPUS, motor="tfidf")
    assert indice.contexto("¿cuánto es el IGV?", k=1).startswith("[prueba.pdf · pág. 1]")


def test_auto_cae_a_tfidf_sin_embeddings(monkeypatch):
    import app.rag.indice as modulo

    def _sin_modelo(_):
        raise OSError("sin red")

    monkeypatch.setattr(modulo, "embed_denso", _sin_modelo)
    indice = IndiceConocimiento(fragmentos=CORPUS, motor="auto")
    assert indice.buscar("IGV de la factura", k=1)[0]["id"] == "igv"
    assert indice.motor_usado == "tfidf" and "TF-IDF" in indice.aviso


def test_motor_denso_no_degrada(monkeypatch):
    import app.rag.indice as modulo

    def _sin_modelo(_):
        raise OSError("sin red")

    monkeypatch.setattr(modulo, "embed_denso", _sin_modelo)
    with pytest.raises(OSError):
        IndiceConocimiento(fragmentos=CORPUS, motor="denso").indexar()


def test_motor_invalido():
    with pytest.raises(ValueError, match="RAG_MOTOR"):
        IndiceConocimiento(fragmentos=CORPUS, motor="faiss")


def test_info_no_indexa():
    indice = IndiceConocimiento(fragmentos=CORPUS, motor="tfidf")
    assert indice.info()["indexado"] is False and indice.info()["motor"] == "sin indexar"
