"""Bot de Telegram (app/telegram/bot.py) con la API simulada: sin red ni token real.

Los números entre corchetes son las reglas de docs/telegram_seguridad.md.
"""
import json
import logging
import threading
import time

import httpx
import pytest

from app.telegram import Respuesta
from app.telegram import bot as b

TOKEN = "123456:TOKEN-DE-PRUEBA-secreto"
CHAT = 555001


class TelegramFalso:
    """API de bots simulada: guarda cada llamada y responde según el método."""

    def __init__(self):
        self.llamadas = []
        self.actualizaciones = []       # lotes que devolverá getUpdates, en orden
        self.errores = {}               # método -> (código, descripción, retry_after)
        self.caer_red = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith(f"/bot{TOKEN}/")
        metodo = request.url.path.rsplit("/", 1)[1]
        cuerpo = json.loads(request.content or b"{}")
        self.llamadas.append((metodo, cuerpo))
        if self.caer_red:
            raise httpx.ConnectError(f"sin red hacia {request.url}", request=request)
        if metodo in self.errores:
            codigo, desc, reintentar = self.errores[metodo]
            datos = {"ok": False, "error_code": codigo, "description": desc}
            if reintentar:
                datos["parameters"] = {"retry_after": reintentar}
            return httpx.Response(200 if codigo is None else codigo, json=datos)
        if metodo == "getUpdates":
            lote = self.actualizaciones.pop(0) if self.actualizaciones else []
            return httpx.Response(200, json={"ok": True, "result": lote})
        return httpx.Response(200, json={"ok": True, "result": True})

    def enviados(self, chat=CHAT):
        return [c["text"] for m, c in self.llamadas if m == "sendMessage" and c["chat_id"] == chat]

    def metodos(self):
        return [m for m, _ in self.llamadas]


class SesionesFalsas:
    """Responde "eco: <texto>"; "código" pide borrar; "lento" tarda; "explota" falla;
    "paralelo" espera a que otros 3 chats lleguen a la vez (prueba el paralelismo)."""

    def __init__(self):
        self.atendidos = []
        self._candado = threading.Lock()
        self.barrera = threading.Barrier(4, timeout=2)

    def atender(self, chat_id, texto):
        with self._candado:
            self.atendidos.append((chat_id, texto))
        if texto == "explota":
            raise RuntimeError("falla interna")
        if texto.startswith("lento"):
            time.sleep(0.05)
        if texto == "paralelo":
            self.barrera.wait()  # BrokenBarrierError si no llegan 4 a la vez
        return Respuesta([f"eco: {texto}"], borrar_mensaje=texto == "código")


_id = iter(range(1, 10_000))


def _mensaje(texto="hola", chat=CHAT, tipo="private", usuario=None, **extra):
    mensaje = {"message_id": next(_id), "chat": {"id": chat, "type": tipo},
               "from": {"id": usuario or chat, "first_name": "Ana"}, **extra}
    if texto is not None:
        mensaje["text"] = texto
    return {"update_id": next(_id), "message": mensaje}


@pytest.fixture
def armar():
    creados = []

    def _armar(permitidos=frozenset(), hilos=4):
        api = TelegramFalso()
        cliente = b.ClienteTelegram(TOKEN, http=httpx.Client(transport=httpx.MockTransport(api)))
        sesiones = SesionesFalsas()
        bot = b.BotTelegram(cliente, sesiones, permitidos=permitidos, hilos=hilos, espera_larga=0)
        creados.append(bot)
        return bot, api, sesiones

    yield _armar
    for bot in creados:
        bot._pool.shutdown(wait=True)


def _esperar(bot):
    """Espera a que el pool termine lo encolado (sin cerrar el cliente)."""
    for _ in range(200):
        with bot._candado:
            if not bot._colas:
                return
        time.sleep(0.01)
    raise AssertionError("el bot no terminó de atender")


# -- cliente ---------------------------------------------------------------------------

def test_cliente_sin_token():
    with pytest.raises(ValueError):
        b.ClienteTelegram("")


def test_error_de_telegram_trae_codigo_y_espera():
    api = TelegramFalso()
    api.errores["sendMessage"] = (429, "Too Many Requests", 7)
    cliente = b.ClienteTelegram(TOKEN, http=httpx.Client(transport=httpx.MockTransport(api)))
    with pytest.raises(b.ErrorTelegram) as e:
        cliente.llamar("sendMessage", chat_id=1, text="x")
    assert e.value.codigo == 429 and e.value.reintentar_en == 7


def test_el_token_no_aparece_en_errores(caplog):
    """[4.2] Ni en el mensaje, ni en la causa encadenada, ni en los logs de httpx."""
    caplog.set_level(logging.DEBUG)
    api = TelegramFalso()
    api.caer_red = True
    cliente = b.ClienteTelegram(TOKEN, http=httpx.Client(transport=httpx.MockTransport(api)))
    with pytest.raises(b.ErrorTelegram) as e:
        cliente.llamar("getUpdates")
    assert TOKEN not in str(e.value) and e.value.__cause__ is None and e.value.__suppress_context__
    logging.getLogger("httpx").info("HTTP Request: POST %s", f"https://api.telegram.org/bot{TOKEN}/getMe")
    assert TOKEN not in caplog.text and "<token>" in caplog.text


# -- filtros ---------------------------------------------------------------------------

@pytest.mark.parametrize("tipo", ["group", "supergroup", "channel"])
def test_solo_chats_privados(armar, tipo):
    """[3.1] En un grupo no se responde nada."""
    bot, api, sesiones = armar()
    assert not bot.recibir(_mensaje("20123456789", chat=-100, tipo=tipo, usuario=7))
    _esperar(bot)
    assert sesiones.atendidos == [] and api.llamadas == []


def test_usuarios_permitidos(armar):
    """[3.2] Con lista, a los demás no se les responde nada."""
    bot, api, sesiones = armar(permitidos=frozenset({CHAT}))
    assert not bot.recibir(_mensaje("hola", chat=999, usuario=999))
    assert bot.recibir(_mensaje("hola"))
    _esperar(bot)
    assert sesiones.atendidos == [(CHAT, "hola")]
    assert all(c["chat_id"] == CHAT for _, c in api.llamadas)


def test_sin_lista_responde_a_cualquiera(armar):
    bot, api, sesiones = armar()
    assert bot.recibir(_mensaje("hola", chat=999))
    _esperar(bot)
    assert api.enviados(999) == ["eco: hola"]


def test_solo_texto(armar):
    """[3.4] Una foto recibe la respuesta fija y no llega a las sesiones."""
    bot, api, sesiones = armar()
    bot.recibir(_mensaje(None, photo=[{"file_id": "abc"}]))
    _esperar(bot)
    assert api.enviados() == [b.SOLO_TEXTO] and sesiones.atendidos == []
    assert "getFile" not in api.metodos()


def test_actualizaciones_que_no_son_mensajes(armar):
    bot, api, sesiones = armar()
    assert not bot.recibir({"update_id": 1, "edited_message": {"text": "x"}})
    assert not bot.recibir({"update_id": 2, "callback_query": {}})


# -- atención --------------------------------------------------------------------------

def test_responde_con_escribiendo(armar):
    bot, api, _ = armar()
    bot.recibir(_mensaje("hola"))
    _esperar(bot)
    assert api.metodos() == ["sendChatAction", "sendMessage"]
    assert api.llamadas[0][1] == {"chat_id": CHAT, "action": "typing"}
    assert api.enviados() == ["eco: hola"]


def test_borra_el_mensaje_del_codigo(armar):
    """[1.7]"""
    bot, api, _ = armar()
    act = _mensaje("código")
    bot.recibir(act)
    _esperar(bot)
    [borrado] = [c for m, c in api.llamadas if m == "deleteMessage"]
    assert borrado == {"chat_id": CHAT, "message_id": act["message"]["message_id"]}
    assert api.enviados() == ["eco: código"]


def test_si_no_se_puede_borrar_igual_responde(armar):
    bot, api, _ = armar()
    api.errores["deleteMessage"] = (400, "message can't be deleted", None)
    bot.recibir(_mensaje("código"))
    _esperar(bot)
    assert api.enviados() == ["eco: código"]


def test_error_interno_no_deja_sin_respuesta(armar):
    """[5.4]"""
    bot, api, _ = armar()
    bot.recibir(_mensaje("explota"))
    bot.recibir(_mensaje("hola"))
    _esperar(bot)
    assert api.enviados() == [b.ERROR_INTERNO, "eco: hola"]


def test_mensajes_de_un_chat_en_orden(armar):
    """[2.4] Uno a la vez y en orden, aunque el primero tarde."""
    bot, api, sesiones = armar(hilos=4)
    for texto in ["lento 1", "2", "lento 3", "4"]:
        bot.recibir(_mensaje(texto))
    _esperar(bot)
    assert [t for _, t in sesiones.atendidos] == ["lento 1", "2", "lento 3", "4"]
    assert api.enviados() == ["eco: lento 1", "eco: 2", "eco: lento 3", "eco: 4"]


def test_chats_distintos_en_paralelo(armar):
    """Cuatro chats atendidos a la vez: si fueran en serie, la barrera no se cumpliría."""
    bot, api, sesiones = armar(hilos=4)
    for chat in range(1, 5):
        bot.recibir(_mensaje("paralelo", chat=chat))
    _esperar(bot)
    assert all(api.enviados(chat) == ["eco: paralelo"] for chat in range(1, 5))


def test_cola_por_chat_con_tope(armar):
    bot, _, _ = armar(hilos=1)
    bot.recibir(_mensaje("lento", chat=1))  # ocupa el único hilo
    aceptados = [bot.recibir(_mensaje(str(i), chat=2)) for i in range(b.MAX_PENDIENTES_POR_CHAT + 3)]
    assert aceptados.count(True) == b.MAX_PENDIENTES_POR_CHAT
    _esperar(bot)


# -- lectura y bucle -------------------------------------------------------------------

def test_preparar_descarta_pendientes(armar):
    """[5.3]"""
    bot, api, _ = armar()
    bot.preparar()
    assert api.llamadas == [("deleteWebhook", {"drop_pending_updates": True})]


def test_leer_avanza_el_offset(armar):
    bot, api, _ = armar()
    a, c = _mensaje("a"), _mensaje("c", chat=2)
    api.actualizaciones = [[a, c], []]
    assert bot.leer_una_vez() == 2
    assert bot.leer_una_vez() == 0
    _esperar(bot)
    gets = [c for m, c in api.llamadas if m == "getUpdates"]
    assert "offset" not in gets[0] and gets[1]["offset"] == c["update_id"] + 1
    assert gets[0]["allowed_updates"] == ["message"]


def test_actualizacion_rara_no_frena_las_demas(armar):
    bot, api, _ = armar()
    rara = {"update_id": 900, "message": {"chat": {"type": "private"}}}  # sin id de chat
    api.actualizaciones = [[rara, _mensaje("hola")]]
    assert bot.leer_una_vez() == 2
    _esperar(bot)
    assert api.enviados() == ["eco: hola"]


def _correr(bot, segundos=0.3):
    parar = threading.Event()
    hilo = threading.Thread(target=bot.ejecutar, args=(parar,))
    hilo.start()
    time.sleep(segundos)
    parar.set()
    hilo.join(timeout=2)
    assert not hilo.is_alive()


def test_bucle_atiende_y_se_detiene(armar):
    bot, api, _ = armar()
    api.actualizaciones = [[_mensaje("hola")]]
    _correr(bot)
    _esperar(bot)
    assert api.metodos()[0] == "deleteWebhook"
    assert api.enviados() == ["eco: hola"]


def test_token_invalido_detiene_el_bucle(armar, caplog):
    bot, api, _ = armar()
    api.errores["deleteWebhook"] = (401, "Unauthorized", None)
    parar = threading.Event()
    hilo = threading.Thread(target=bot.ejecutar, args=(parar,))
    hilo.start()
    hilo.join(timeout=2)
    assert not hilo.is_alive() and "token_invalido" in caplog.text


def test_conflicto_avisa_y_reintenta(armar, caplog):
    """[5.2] Otro proceso con el mismo token: se avisa y no se cae."""
    bot, api, _ = armar()
    api.errores["getUpdates"] = (409, "Conflict: terminated by other getUpdates request", None)
    _correr(bot, 0.1)
    assert "otro proceso usa el mismo token" in caplog.text
    assert TOKEN not in caplog.text


def test_red_caida_no_tumba_el_bucle(armar, caplog):
    bot, api, _ = armar()
    api.caer_red = True
    _correr(bot, 0.1)
    assert "telegram.error" in caplog.text and TOKEN not in caplog.text
