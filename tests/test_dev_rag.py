"""Banco de pruebas /dev/rag con un índice pequeño en TF-IDF (sin red ni modelo)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.api import dev_rag
from app.rag.indice import IndiceConocimiento
from app.rag.ingesta import Fragmento

CORPUS = [
    Fragmento("ciclo", "prueba.pdf", "pdf", "La facturación es mes vencido y se emite el día uno.", 1),
    Fragmento("igv", "prueba.pdf", "pdf", "El IGV es 18 por ciento del subtotal de la factura.", 2),
    Fragmento("CS-01", "catalogo.json", "casuisticas", "CS-01 · Factura duplicada: registra y deriva."),
]


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(dev_rag, "_indice", IndiceConocimiento(fragmentos=CORPUS, motor="tfidf"))
    app = FastAPI()
    app.include_router(dev_rag.router)
    return TestClient(app)


def test_info(cliente):
    d = cliente.get("/dev/rag/info").json()
    assert d["fragmentos"] == 3 and d["fuentes"] == ["catalogo.json", "prueba.pdf"]
    assert d["parametros"]["umbral"] == config.RAG_UMBRAL_TFIDF  # escala del motor en uso


def test_buscar_marca_umbral_y_prompt(cliente):
    d = cliente.get("/dev/rag/buscar", params={"q": "¿cuánto es el IGV?", "umbral": 0.05}).json()
    assert d["resultados"][0]["id"] == "igv"
    assert d["resultados"][0]["pasa_umbral"] and d["resultados"][0]["al_prompt"]
    assert d["al_prompt"][0] == "igv"
    # Sin corte por umbral: también se muestran los que no pasan.
    assert any(not r["pasa_umbral"] for r in d["resultados"])
    assert all(not r["al_prompt"] for r in d["resultados"] if not r["pasa_umbral"])


def test_umbral_alto_nada_llega_al_prompt(cliente):
    d = cliente.get("/dev/rag/buscar", params={"q": "IGV", "umbral": 0.99}).json()
    assert d["al_prompt"] == [] and d["resultados"]


def test_valida_parametros(cliente):
    assert cliente.get("/dev/rag/buscar", params={"q": ""}).status_code == 422
    assert cliente.get("/dev/rag/buscar", params={"q": "x", "umbral": 2}).status_code == 422


def test_sirve_la_pagina(cliente):
    r = cliente.get("/dev/rag")
    assert r.status_code == 200 and "Banco de pruebas del RAG" in r.text
