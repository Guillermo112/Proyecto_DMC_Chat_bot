"""Turno del chat y POST /mi/chat con un modelo simulado (sin red, sin clave, sin costo)."""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.agente import ServicioChat
from app.agente.chat import obtener_servicio
from app.auth import sesion
from app.llm import RespuestaLLM, SinProveedores
from app.main import app
from app.rag.indice import IndiceConocimiento
from app.rag.ingesta import Fragmento

CORPUS = [
    Fragmento("prorrateo", "glosario.pdf", "pdf-tabla",
              "Prorrateo: cobro proporcional de un servicio que empezó a mitad de mes.", 3),
    Fragmento("igv", "glosario.pdf", "pdf-tabla", "IGV: impuesto general a las ventas, 18 % del subtotal.", 3),
]


class RouterFalso:
    """Devuelve respuestas guionadas y guarda lo que recibió en cada llamada."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def chat(self, mensajes, tools=None, **_):
        self.llamadas.append({"mensajes": [dict(m) for m in mensajes], "tools": tools})
        r = self.respuestas.pop(0) if self.respuestas else RespuestaLLM(texto="fin")
        if isinstance(r, Exception):
            raise r
        return r


def _herramienta(nombre, argumentos=None, id_="t1"):
    return RespuestaLLM(tool_calls=[{"id": id_, "name": nombre, "arguments": argumentos or {}}],
                        uso={"prompt_tokens": 100, "completion_tokens": 10}, modelo="falso")


def _texto(texto):
    return RespuestaLLM(texto=texto, uso={"prompt_tokens": 120, "completion_tokens": 30,
                                          "prompt_cache_hit_tokens": 64}, modelo="falso")


@pytest.fixture
def indice():
    return IndiceConocimiento(fragmentos=CORPUS, motor="tfidf")


def test_turno_con_herramienta_usa_el_cliente_de_la_sesion(indice):
    router = RouterFalso(_herramienta("detectar_anomalias", {"cliente_id": 2}),
                         _texto("Detecté dos facturas iguales."))
    turno = ServicioChat(router=router, indice=indice).responder(1, "c1", "Me llegaron dos facturas iguales")

    assert turno.texto == "Detecté dos facturas iguales."
    assert turno.llamadas == 2
    assert turno.tokens == {"entrada": 220, "salida": 40, "cache": 64}
    [h] = turno.herramientas
    assert h["nombre"] == "detectar_anomalias" and h["ok"] and h["argumentos"] == {}
    # El resultado que vio el modelo es la duplicada del cliente 1, no del 2.
    tool_msg = router.llamadas[1]["mensajes"][-1]
    assert tool_msg["role"] == "tool" and "F001-000254" in tool_msg["content"]
    assert router.llamadas[0]["mensajes"][0]["role"] == "system"


def test_rag_previo_agrega_contexto_sin_llamada_extra(indice):
    router = RouterFalso(_texto("Es un cobro proporcional."))
    turno = ServicioChat(router=router, indice=indice).responder(1, "c1", "¿Qué es el prorrateo?")

    assert turno.llamadas == 1
    assert [d["id"] for d in turno.documentos][0] == "prorrateo"
    contexto = [m for m in router.llamadas[0]["mensajes"] if m["role"] == "system"][1]
    assert "Contexto de documentos" in contexto["content"] and "Prorrateo" in contexto["content"]


def test_sin_coincidencias_no_hay_contexto(indice):
    router = RouterFalso(_texto("Te ayudo con temas de facturación."))
    turno = ServicioChat(router=router, indice=indice).responder(1, "c1", "receta de pizza con anchoas")
    assert turno.documentos == []
    assert sum(m["role"] == "system" for m in router.llamadas[0]["mensajes"]) == 1


def test_historial_guarda_solo_textos_y_separa_conversaciones(indice):
    router = RouterFalso(_herramienta("ver_saldo"), _texto("Debes S/ 10."), _texto("De nada."))
    servicio = ServicioChat(router=router, indice=indice)
    servicio.responder(1, "c1", "¿Cuánto debo?")
    servicio.responder(1, "c1", "Gracias")
    segunda = router.llamadas[-1]["mensajes"]
    assert [m["role"] for m in segunda] == ["system", "user", "assistant", "user"]
    assert segunda[1]["content"] == "¿Cuánto debo?" and segunda[2]["content"] == "Debes S/ 10."

    router.respuestas = [_texto("Hola")]
    servicio.responder(1, "otra", "Hola")
    assert [m["role"] for m in router.llamadas[-1]["mensajes"]] == ["system", "user"]


def test_tope_de_vueltas_cierra_sin_herramientas(indice, monkeypatch):
    monkeypatch.setattr(config, "CHAT_MAX_VUELTAS", 2)
    router = RouterFalso(_herramienta("ver_perfil", id_="a"), _herramienta("ver_perfil", id_="b"),
                         _texto("Listo."))
    turno = ServicioChat(router=router, indice=indice).responder(1, "c1", "hola")
    assert turno.llamadas == 3 and turno.texto == "Listo."
    assert router.llamadas[-1]["tools"] is None


def test_rag_caido_no_tumba_el_chat():
    class IndiceRoto:
        def buscar(self, _):
            raise OSError("sin modelo")

    turno = ServicioChat(router=RouterFalso(_texto("Hola")), indice=IndiceRoto()).responder(1, "c1", "hola")
    assert turno.texto == "Hola" and turno.aviso


# -- API -------------------------------------------------------------------------
@pytest.fixture
def cliente_api(indice):
    def _usar(router):
        app.dependency_overrides[obtener_servicio] = lambda: ServicioChat(router=router, indice=indice)
        return TestClient(app)
    yield _usar
    app.dependency_overrides.clear()


def _token(cliente_id=1):
    return {"Authorization": f"Bearer {sesion.emitir_token(cliente_id)[0]}"}


def test_api_exige_token(cliente_api):
    c = cliente_api(RouterFalso(_texto("x")))
    assert c.post("/mi/chat", json={"mensaje": "hola"}).status_code == 401


def test_api_responde_con_traza(cliente_api):
    c = cliente_api(RouterFalso(_herramienta("ver_perfil"), _texto("Eres Minera.")))
    r = c.post("/mi/chat", json={"mensaje": "¿quién soy?", "conversacion_id": "abc"}, headers=_token())
    assert r.status_code == 200
    d = r.json()
    assert d["respuesta"] == "Eres Minera." and d["llamadas_modelo"] == 2
    assert d["herramientas"][0]["nombre"] == "ver_perfil" and "Minera" in d["herramientas"][0]["resultado"]


def test_api_sin_modelo_configurado_responde_503(cliente_api):
    c = cliente_api(RouterFalso(SinProveedores("No hay ningún endpoint configurado.")))
    r = c.post("/mi/chat", json={"mensaje": "hola"}, headers=_token())
    assert r.status_code == 503 and "no está disponible" in r.json()["detail"]


@pytest.mark.parametrize("cuerpo", [{"mensaje": ""}, {"mensaje": "x" * 2001},
                                    {"mensaje": "hola", "conversacion_id": "../otro"}])
def test_api_valida_la_peticion(cliente_api, cuerpo):
    c = cliente_api(RouterFalso())
    assert c.post("/mi/chat", json=cuerpo, headers=_token()).status_code == 422


def test_api_reiniciar(cliente_api):
    c = cliente_api(RouterFalso())
    assert c.delete("/mi/chat/abc", headers=_token()).status_code == 204


def test_sirve_la_pagina():
    r = TestClient(app).get("/chat")
    assert r.status_code == 200 and "Anticipa" in r.text
