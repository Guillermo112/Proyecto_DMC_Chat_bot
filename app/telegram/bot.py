"""Bot de Telegram: lee mensajes con long polling y los pasa a `Sesiones`.

Este módulo solo transporta: la identificación, los comandos y el paso al agente
están en `app/telegram/sesiones.py`. Reglas en `docs/telegram_seguridad.md`; los
números entre corchetes las citan.

- Solo chats privados [3.1] y, si hay lista, solo usuarios permitidos [3.2]. A los
  demás no se les responde nada.
- Solo texto [3.4]: lo demás recibe una respuesta fija y no se descarga.
- Los mensajes de un mismo chat se atienden en orden y de a uno; chats distintos, en
  paralelo (`TELEGRAM_HILOS`) [2.4].
- El token va en la URL de la API: nunca aparece en logs ni errores [4.2].
- Al arrancar se descartan los mensajes pendientes y se quita el webhook [5.3].
- Un error de red o de Telegram no tumba el bucle ni deja al cliente sin respuesta [5.4];
  un 409 avisa que otro proceso usa el mismo token [5.2].

Las respuestas salen en HTML (negrita) y partidas en mensajes de hasta 4096
caracteres (`app/telegram/formato.py`). `arrancar()` lo levanta en un hilo dentro de
la API (desde el `lifespan` de `app/main.py`), solo si hay `TELEGRAM_BOT_TOKEN` [5.1]
y una sola vez por proceso [5.2].
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx

from app import config
from app.telegram import formato
from app.telegram.sesiones import Sesiones

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
ESPERA_LARGA = 25          # segundos que getUpdates espera mensajes nuevos
MAX_PENDIENTES_POR_CHAT = 10
SOLO_TEXTO = "Por ahora solo atiendo mensajes de texto. Escríbeme tu consulta, por favor."
ERROR_INTERNO = "Tuve un problema al procesar tu mensaje. Intenta de nuevo en unos minutos."


class ErrorTelegram(RuntimeError):
    """Error de la API de Telegram o de la red. El mensaje nunca incluye el token."""

    def __init__(self, metodo: str, descripcion: str, codigo: int | None = None,
                 reintentar_en: int | None = None) -> None:
        super().__init__(f"{metodo}: {descripcion}")
        self.codigo = codigo
        self.reintentar_en = reintentar_en


class _OcultarToken(logging.Filter):
    """httpx registra la URL de cada petición, y la URL lleva el token [4.2]."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        mensaje = record.getMessage()
        if self._token in mensaje:
            record.msg, record.args = mensaje.replace(self._token, "<token>"), ()
        return True


class ClienteTelegram:
    """Llamadas a la API de bots de Telegram (POST con JSON)."""

    def __init__(self, token: str, http: httpx.Client | None = None, api: str = API) -> None:
        if not token:
            raise ValueError("Falta TELEGRAM_BOT_TOKEN")
        self._url = f"{api}/bot{token}/"
        self._http = http or httpx.Client(timeout=httpx.Timeout(10.0, read=ESPERA_LARGA + 10))
        filtro = _OcultarToken(token)
        for nombre in ("httpx", "httpcore"):
            logging.getLogger(nombre).addFilter(filtro)

    def llamar(self, metodo: str, **parametros: Any) -> Any:
        try:
            r = self._http.post(self._url + metodo, json=parametros)
            datos = r.json()
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:  # RuntimeError: cliente cerrado
            # Sin encadenar la excepción: su repr incluye la URL con el token [4.2].
            raise ErrorTelegram(metodo, type(exc).__name__) from None
        if not datos.get("ok"):
            reintentar = (datos.get("parameters") or {}).get("retry_after")
            raise ErrorTelegram(metodo, str(datos.get("description", "sin descripción")),
                                datos.get("error_code"), reintentar)
        return datos.get("result")

    def cerrar(self) -> None:
        self._http.close()


class BotTelegram:
    def __init__(self, cliente: ClienteTelegram, sesiones: Sesiones,
                 permitidos: frozenset[int] = frozenset(), hilos: int = 4,
                 espera_larga: int = ESPERA_LARGA) -> None:
        self._cliente = cliente
        self._sesiones = sesiones
        self._permitidos = permitidos
        self._espera_larga = espera_larga
        self._offset: int | None = None
        self._pool = ThreadPoolExecutor(max_workers=max(1, hilos), thread_name_prefix="telegram")
        self._colas: dict[int, deque[tuple[int, str | None]]] = {}
        self._candado = threading.Lock()

    # -- entrada ------------------------------------------------------------------
    def preparar(self) -> None:
        """Quita el webhook y descarta lo recibido con la API apagada [5.3]."""
        self._cliente.llamar("deleteWebhook", drop_pending_updates=True)

    def leer_una_vez(self) -> int:
        """Una llamada a getUpdates; reparte lo recibido. Devuelve cuántos llegaron."""
        parametros: dict[str, Any] = {"timeout": self._espera_larga, "allowed_updates": ["message"]}
        if self._offset is not None:
            parametros["offset"] = self._offset
        actualizaciones = self._cliente.llamar("getUpdates", **parametros) or []
        for act in actualizaciones:
            self._offset = act["update_id"] + 1  # confirmado: Telegram no lo vuelve a enviar
            try:
                self.recibir(act)
            except Exception:  # noqa: BLE001 - una actualización rara no frena las demás
                log.exception("telegram.actualizacion_invalida")
        return len(actualizaciones)

    def recibir(self, actualizacion: dict[str, Any]) -> bool:
        """Filtra y encola un mensaje. Devuelve si se aceptó."""
        mensaje = actualizacion.get("message")
        if not mensaje:
            return False
        chat = mensaje.get("chat") or {}
        if chat.get("type") != "private":  # [3.1]
            log.info("telegram.ignorado motivo=no_privado")
            return False
        usuario = (mensaje.get("from") or {}).get("id")
        if self._permitidos and usuario not in self._permitidos:  # [3.2]
            log.info("telegram.ignorado motivo=no_permitido")
            return False
        chat_id = chat["id"]
        texto = mensaje.get("text")  # None si es foto, audio, sticker... [3.4]
        with self._candado:
            cola = self._colas.get(chat_id)
            if cola is None:
                cola = self._colas[chat_id] = deque()
                activo = False
            else:
                activo = True
            if len(cola) >= MAX_PENDIENTES_POR_CHAT:
                log.warning("telegram.cola_llena chat=%s", chat_id)
                return False
            cola.append((mensaje["message_id"], texto))
        if not activo:
            self._pool.submit(self._drenar, chat_id)
        return True

    # -- atención (en el pool) ----------------------------------------------------
    def _drenar(self, chat_id: int) -> None:
        """Atiende en orden los mensajes de un chat; un solo hilo por chat [2.4]."""
        while True:
            with self._candado:
                cola = self._colas[chat_id]
                if not cola:
                    del self._colas[chat_id]
                    return
                message_id, texto = cola.popleft()
            self._atender(chat_id, message_id, texto)

    def _atender(self, chat_id: int, message_id: int, texto: str | None) -> None:
        if texto is None:
            self._enviar(chat_id, SOLO_TEXTO)
            return
        self._accion(chat_id)
        try:
            respuesta = self._sesiones.atender(chat_id, texto)
        except Exception as exc:  # noqa: BLE001 - nunca quedarse callado [5.4]
            log.error("telegram.error_al_atender chat=%s %s", chat_id, type(exc).__name__)
            self._enviar(chat_id, ERROR_INTERNO)
            return
        if respuesta.borrar_mensaje:  # [1.7]
            try:
                self._cliente.llamar("deleteMessage", chat_id=chat_id, message_id=message_id)
            except ErrorTelegram as exc:
                log.warning("telegram.no_se_borro_el_codigo chat=%s %s", chat_id, exc)
        for t in respuesta.textos:
            self._enviar(chat_id, t)

    def _accion(self, chat_id: int) -> None:
        try:
            self._cliente.llamar("sendChatAction", chat_id=chat_id, action="typing")
        except ErrorTelegram:
            pass  # es solo el "escribiendo..."

    def _enviar(self, chat_id: int, texto: str) -> None:
        """Envía en HTML, partido en mensajes de hasta 4096 caracteres (`formato`).

        Si Telegram rechaza el HTML (no debería: se escapa todo), esa parte se reenvía
        como texto plano: mejor asteriscos a la vista que quedarse callado [5.4].
        """
        for parte in formato.partir(texto):
            try:
                self._cliente.llamar("sendMessage", chat_id=chat_id, text=formato.a_html(parte),
                                     parse_mode="HTML")
                continue
            except ErrorTelegram as exc:
                if exc.codigo != 400:
                    log.error("telegram.no_se_envio chat=%s %s", chat_id, exc)
                    return
                log.warning("telegram.html_rechazado chat=%s %s", chat_id, exc)
            try:
                self._cliente.llamar("sendMessage", chat_id=chat_id, text=parte)
            except ErrorTelegram as exc:
                log.error("telegram.no_se_envio chat=%s %s", chat_id, exc)
                return

    # -- bucle --------------------------------------------------------------------
    def ejecutar(self, parar: threading.Event) -> None:
        """Lee mensajes hasta que `parar` se active. Pensado para un hilo propio."""
        espera = 1.0
        preparado = False
        while not parar.is_set():
            try:
                if not preparado:
                    self.preparar()
                    preparado = True
                    log.info("telegram.bot_listo")
                self.leer_una_vez()
                espera = 1.0
            except ErrorTelegram as exc:
                if exc.codigo == 401:
                    log.error("telegram.token_invalido: revisa TELEGRAM_BOT_TOKEN; el bot se detiene")
                    return
                if exc.codigo == 409:  # [5.2]
                    log.warning("telegram.conflicto: otro proceso usa el mismo token "
                                "(otra API levantada o un webhook). Reintento en %.0f s", espera)
                else:
                    log.warning("telegram.error %s. Reintento en %.0f s", exc, espera)
                parar.wait(exc.reintentar_en or espera)
                espera = min(espera * 2, 60.0)
            except Exception:  # noqa: BLE001 - el bucle no se cae
                log.exception("telegram.error_inesperado")
                parar.wait(espera)
                espera = min(espera * 2, 60.0)

    def detener(self, esperar: bool = True) -> None:
        """Cierra el pool y el cliente. Sin `esperar`, se descarta lo que estaba en cola
        (al apagar la API no tiene sentido retenerla por un turno del modelo)."""
        self._pool.shutdown(wait=esperar, cancel_futures=not esperar)
        self._cliente.cerrar()


# -- arranque dentro de la API ------------------------------------------------------

@dataclass
class BotEnMarcha:
    bot: BotTelegram
    hilo: threading.Thread
    parar: threading.Event

    def detener(self, espera: float = 2.0) -> None:
        global _en_marcha
        self.parar.set()
        # Cerrar el cliente corta la espera larga de getUpdates; el bucle ve `parar` y sale.
        self.bot.detener(esperar=False)
        self.hilo.join(timeout=espera)
        with _candado_arranque:
            if _en_marcha is self:
                _en_marcha = None
        log.info("telegram.bot_detenido")


_en_marcha: BotEnMarcha | None = None
_candado_arranque = threading.Lock()


def arrancar(servicio: Any = None, http: httpx.Client | None = None) -> BotEnMarcha | None:
    """Levanta el bot en un hilo daemon. None si no hay token [5.1] o si ya está en marcha
    en este proceso [5.2] (un token admite un solo lector)."""
    global _en_marcha
    if not config.TELEGRAM_BOT_TOKEN:
        log.info("telegram.sin_token: el bot no arranca")
        return None
    with _candado_arranque:
        if _en_marcha is not None:
            log.warning("telegram.ya_en_marcha: no se arranca un segundo bot en este proceso")
            return None
        if servicio is None:
            from app.agente import obtener_servicio

            servicio = obtener_servicio()
        bot = BotTelegram(ClienteTelegram(config.TELEGRAM_BOT_TOKEN, http=http), Sesiones(servicio),
                          permitidos=config.TELEGRAM_USUARIOS_PERMITIDOS, hilos=config.TELEGRAM_HILOS)
        parar = threading.Event()
        hilo = threading.Thread(target=bot.ejecutar, args=(parar,), daemon=True, name="telegram-bot")
        _en_marcha = BotEnMarcha(bot, hilo, parar)
        hilo.start()
    if config.TELEGRAM_USUARIOS_PERMITIDOS:
        log.warning("telegram.bot_activo: solo responde a %s usuario(s) permitido(s)",
                    len(config.TELEGRAM_USUARIOS_PERMITIDOS))
    else:
        log.warning("telegram.bot_activo SIN lista de usuarios permitidos: responde a cualquiera "
                    "que encuentre el bot (ver TELEGRAM_USUARIOS_PERMITIDOS)")
    return _en_marcha
