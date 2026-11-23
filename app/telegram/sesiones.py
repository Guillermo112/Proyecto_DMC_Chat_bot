"""Sesiones del bot de Telegram: identificación por chat y paso al agente.

Máquina de estados por `chat_id`, sin red ni Telegram (el bot, `app/telegram/bot.py`,
solo transporta los textos). Reglas en `docs/telegram_seguridad.md`; los números
entre corchetes las citan.

    ESPERANDO_RUC --RUC válido, código enviado--> ESPERANDO_CODIGO
    ESPERANDO_CODIGO --código correcto--> IDENTIFICADO (saludo del agente)
    IDENTIFICADO --sesión vencida, /start o /salir--> ESPERANDO_RUC

- Nada llega al agente antes de verificar el código [1.1]. La identificación es la
  misma de la web: `otp.solicitar_codigo` y `otp.verificar_codigo` [1.2], con el mismo
  mensaje exista o no el RUC [1.3] y un límite de códigos por chat [1.4].
- La sesión vence a los `AUTH_MINUTOS_SESION`, como el token de la web [1.5], y vive
  en memoria: no hay vínculo permanente entre el chat y el cliente [1.6].
- El mensaje con el código se marca para borrarlo [1.7] y su texto no se registra [4.3].
- La conversación del agente es `(cliente_id, "tg-<chat_id>")` [2.3] y los casos se
  registran con `canal = telegram` [2.2].

Los mensajes de un mismo chat deben llegar en orden y de a uno (lo garantiza el bot
[2.4]); el candado de esta clase protege solo el diccionario de sesiones.
"""
from __future__ import annotations

import enum
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

from app import config
from app.agente import ChatNoDisponible
from app.auth import otp
from app.auth.limite import LimitadorPorIP

log = logging.getLogger(__name__)

MAX_MENSAJE = 2000  # como ChatPeticion de la web [3.5]

# Mismo texto exista o no el RUC (como app/auth/rutas.py) [1.3].
MENSAJE_ENVIO = ("Si el RUC está registrado, enviamos un código de 6 dígitos al correo de "
                 "facturación. Escríbelo aquí.")
BIENVENIDA = ("¡Hola! Soy Anticipa, el asistente de facturación para empresas.\n\n"
              "Para ver tu información primero te identifico: escribe el RUC de tu empresa "
              "(11 dígitos) y te enviaré un código al correo de facturación.")
PEDIR_RUC = "Escribe el RUC de tu empresa (11 dígitos) para identificarte."
RUC_INVALIDO = "El RUC tiene 11 dígitos, sin letras. Escríbelo de nuevo, por favor."
PEDIR_CODIGO = ("Escribe el código de 6 dígitos que llegó a tu correo. "
                "Si no te llegó o quieres usar otro RUC, escribe /start.")
CODIGO_RECHAZADO = ("El código no es correcto o ya venció. Revisa el correo y escríbelo de nuevo, "
                    "o escribe /start para pedir otro.")
SESION_VENCIDA = "Tu sesión venció. " + PEDIR_RUC
SALIDA = "Cerraste tu sesión. Cuando quieras volver, escribe /start."
NO_DISPONIBLE = "El asistente no está disponible en este momento. Intenta de nuevo en unos minutos."
SIN_ENVIO = "No pude enviar el código en este momento. Intenta de nuevo en unos minutos."
MUY_LARGO = f"Tu mensaje es muy largo (máximo {MAX_MENSAJE} caracteres). ¿Me lo resumes?"
AYUDA = ("Comandos:\n/start: identificarte (o cambiar de RUC)\n"
         "/nuevo: empezar una conversación nueva\n/salir: cerrar tu sesión")


class Estado(enum.Enum):
    ESPERANDO_RUC = "esperando_ruc"
    ESPERANDO_CODIGO = "esperando_codigo"
    IDENTIFICADO = "identificado"


@dataclass
class Sesion:
    estado: Estado = Estado.ESPERANDO_RUC
    id_verificacion: int | None = None
    cliente_id: int | None = None
    vence: float = 0.0  # reloj monotónico


@dataclass
class Respuesta:
    """Lo que el bot debe hacer con un mensaje recibido."""

    textos: list[str] = field(default_factory=list)
    borrar_mensaje: bool = False  # el mensaje recibido tenía el código [1.7]


def conversacion_de(chat_id: int) -> str:
    """Id de conversación del agente: no choca con los que genera la web [2.3]."""
    return f"tg-{chat_id}"


def _solo_digitos(texto: str) -> str:
    """Quita espacios, guiones y puntos ("20 123 456 789" → "20123456789")."""
    return "".join(c for c in texto if c not in " -.\t")


def _minutos(segundos: float) -> int:
    return max(1, -(-int(segundos) // 60))


class Sesiones:
    """Una instancia por bot; las sesiones se separan por `chat_id`."""

    def __init__(self, servicio: Any,
                 solicitar: Callable[[str], tuple[int, str | None]] = otp.solicitar_codigo,
                 verificar: Callable[[int, str], int | None] = otp.verificar_codigo,
                 limitador: LimitadorPorIP | None = None,
                 reloj: Callable[[], float] = time.monotonic,
                 max_sesiones: int | None = None) -> None:
        self._servicio = servicio
        self._solicitar = solicitar
        self._verificar = verificar
        self._reloj = reloj
        # Mismo limitador de la web, con el chat como clave [1.4].
        self._limitador = limitador or LimitadorPorIP(
            maximo=lambda: config.TELEGRAM_MAX_SOLICITUDES,
            ventana_seg=lambda: config.TELEGRAM_VENTANA_SEG,
            reloj=reloj,
        )
        self._max = max_sesiones or config.CHAT_MAX_CONVERSACIONES
        self._sesiones: OrderedDict[int, Sesion] = OrderedDict()
        self._candado = threading.Lock()

    # -- estado -------------------------------------------------------------------
    def _sesion(self, chat_id: int) -> Sesion:
        with self._candado:
            if chat_id not in self._sesiones:
                self._sesiones[chat_id] = Sesion()
                # El bot es público: la memoria no crece sin tope (se olvidan las más viejas).
                while len(self._sesiones) > self._max:
                    self._sesiones.popitem(last=False)
            self._sesiones.move_to_end(chat_id)
            return self._sesiones[chat_id]

    def estado(self, chat_id: int) -> Estado:
        with self._candado:
            sesion = self._sesiones.get(chat_id)
            return sesion.estado if sesion else Estado.ESPERANDO_RUC

    def _cerrar(self, chat_id: int, sesion: Sesion) -> None:
        """Olvida al cliente y su conversación con el agente [1.6]."""
        if sesion.cliente_id is not None:
            self._servicio.reiniciar(sesion.cliente_id, conversacion_de(chat_id))
        sesion.estado, sesion.id_verificacion, sesion.cliente_id, sesion.vence = (
            Estado.ESPERANDO_RUC, None, None, 0.0)

    # -- entrada ------------------------------------------------------------------
    def atender(self, chat_id: int, texto: str) -> Respuesta:
        """Procesa un mensaje de texto de un chat privado y devuelve qué responder."""
        texto = (texto or "").strip()
        sesion = self._sesion(chat_id)

        if texto.startswith("/"):
            return self._comando(chat_id, sesion, texto.split()[0].split("@")[0].lower())

        if sesion.estado is Estado.IDENTIFICADO and self._reloj() >= sesion.vence:
            self._cerrar(chat_id, sesion)
            log.info("telegram.sesion_vencida chat=%s", chat_id)
            return Respuesta([SESION_VENCIDA])

        if sesion.estado is Estado.ESPERANDO_RUC:
            return self._recibir_ruc(chat_id, sesion, texto)
        if sesion.estado is Estado.ESPERANDO_CODIGO:
            return self._recibir_codigo(chat_id, sesion, texto)
        return self._conversar(chat_id, sesion, texto)

    def _comando(self, chat_id: int, sesion: Sesion, comando: str) -> Respuesta:
        if comando == "/start":
            self._cerrar(chat_id, sesion)
            return Respuesta([BIENVENIDA])
        if comando == "/salir":
            identificado = sesion.estado is Estado.IDENTIFICADO
            self._cerrar(chat_id, sesion)
            return Respuesta([SALIDA if identificado else PEDIR_RUC])
        if comando == "/nuevo":
            if sesion.estado is not Estado.IDENTIFICADO:
                return Respuesta([PEDIR_RUC if sesion.estado is Estado.ESPERANDO_RUC else PEDIR_CODIGO])
            if self._reloj() >= sesion.vence:
                self._cerrar(chat_id, sesion)
                return Respuesta([SESION_VENCIDA])
            # El saludo reinicia la conversación y revisa la cuenta (sin modelo).
            return Respuesta([self._servicio.saludar(sesion.cliente_id, conversacion_de(chat_id))])
        return Respuesta([AYUDA])

    def _recibir_ruc(self, chat_id: int, sesion: Sesion, texto: str) -> Respuesta:
        ruc = _solo_digitos(texto)
        if len(ruc) != 11 or not (ruc.isascii() and ruc.isdigit()):
            return Respuesta([RUC_INVALIDO])
        espera = self._limitador.registrar(str(chat_id))
        if espera is not None:
            log.warning("telegram.limite_codigos chat=%s", chat_id)
            return Respuesta([f"Pediste varios códigos seguidos. Intenta de nuevo en "
                              f"{_minutos(espera)} min."])
        try:
            id_verificacion, _ = self._solicitar(ruc)
        except Exception as exc:  # noqa: BLE001 - SMTP caído, sin AUTH_SECRET...
            log.error("telegram.codigo_no_enviado chat=%s %s", chat_id, type(exc).__name__)
            return Respuesta([SIN_ENVIO])
        sesion.estado, sesion.id_verificacion = Estado.ESPERANDO_CODIGO, id_verificacion
        log.info("telegram.codigo_solicitado chat=%s", chat_id)  # sin el RUC: no revela quién es
        return Respuesta([MENSAJE_ENVIO])

    def _recibir_codigo(self, chat_id: int, sesion: Sesion, texto: str) -> Respuesta:
        codigo = _solo_digitos(texto)
        if len(codigo) != 6 or not (codigo.isascii() and codigo.isdigit()):
            return Respuesta([PEDIR_CODIGO])
        # A partir de aquí el texto es el código: no se registra [4.3] y se borra [1.7].
        try:
            cliente_id = self._verificar(sesion.id_verificacion, codigo)
        except Exception as exc:  # noqa: BLE001 - sin AUTH_SECRET o base no disponible
            log.error("telegram.verificacion_fallida chat=%s %s", chat_id, type(exc).__name__)
            return Respuesta([NO_DISPONIBLE], borrar_mensaje=True)
        if cliente_id is None:
            log.info("telegram.codigo_rechazado chat=%s", chat_id)
            return Respuesta([CODIGO_RECHAZADO], borrar_mensaje=True)

        sesion.estado, sesion.id_verificacion = Estado.IDENTIFICADO, None
        sesion.cliente_id = cliente_id
        sesion.vence = self._reloj() + config.AUTH_MINUTOS_SESION * 60
        log.info("telegram.verificado chat=%s cliente=%s", chat_id, cliente_id)
        return Respuesta([self._servicio.saludar(cliente_id, conversacion_de(chat_id))],
                         borrar_mensaje=True)

    def _conversar(self, chat_id: int, sesion: Sesion, texto: str) -> Respuesta:
        if not texto:
            return Respuesta()
        if len(texto) > MAX_MENSAJE:
            return Respuesta([MUY_LARGO])
        try:
            turno = self._servicio.responder(sesion.cliente_id, conversacion_de(chat_id), texto,
                                             canal="telegram")
        except ChatNoDisponible as exc:
            log.error("telegram.chat_no_disponible chat=%s %s", chat_id, exc)
            return Respuesta([NO_DISPONIBLE])
        return Respuesta([turno.texto])
