"""Sesiones del bot de Telegram (app/telegram/sesiones.py), sin red ni Telegram.

Los números entre corchetes son las reglas de docs/telegram_seguridad.md.
"""
import logging
import re
import shutil
import sqlite3

import pytest

from app import config
from app.agente import ChatNoDisponible, Turno
from app.auth import otp
from app.telegram import Estado, Sesiones, conversacion_de
from app.telegram import sesiones as s

CHAT = 555001
RUC = "20123456789"
CODIGO = "123456"


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class ServicioFalso:
    """Registra lo que el bot le pide al agente."""

    def __init__(self, error=None):
        self.llamadas = []
        self.error = error

    def saludar(self, cliente_id, conversacion_id):
        self.llamadas.append(("saludar", cliente_id, conversacion_id))
        return f"¡Hola, cliente {cliente_id}!"

    def responder(self, cliente_id, conversacion_id, mensaje, canal="web"):
        self.llamadas.append(("responder", cliente_id, conversacion_id, mensaje, canal))
        if self.error:
            raise self.error
        return Turno(texto=f"respuesta a {mensaje}")

    def reiniciar(self, cliente_id, conversacion_id):
        self.llamadas.append(("reiniciar", cliente_id, conversacion_id))


class OtpFalso:
    """RUC → cliente; el código correcto es CODIGO."""

    def __init__(self, clientes=None):
        self.clientes = {RUC: 7} if clientes is None else clientes
        self.solicitudes = []
        self.verificaciones = []
        self._pendientes = {}

    def solicitar(self, ruc):
        self.solicitudes.append(ruc)
        id_v = len(self.solicitudes)
        self._pendientes[id_v] = self.clientes.get(ruc)
        return id_v, None

    def verificar(self, id_v, codigo):
        self.verificaciones.append((id_v, codigo))
        return self._pendientes.get(id_v) if codigo == CODIGO else None


@pytest.fixture
def bot():
    servicio, otp_falso, reloj = ServicioFalso(), OtpFalso(), Reloj()
    sesiones = Sesiones(servicio, solicitar=otp_falso.solicitar, verificar=otp_falso.verificar, reloj=reloj)
    return sesiones, servicio, otp_falso, reloj


def _identificar(sesiones, chat=CHAT):
    sesiones.atender(chat, RUC)
    return sesiones.atender(chat, CODIGO)


# -- identificación ----------------------------------------------------------------

def test_flujo_completo(bot):
    sesiones, servicio, otp_falso, _ = bot
    assert sesiones.atender(CHAT, "/start").textos == [s.BIENVENIDA]
    assert sesiones.atender(CHAT, RUC).textos == [s.MENSAJE_ENVIO]
    assert sesiones.estado(CHAT) is Estado.ESPERANDO_CODIGO

    r = sesiones.atender(CHAT, CODIGO)
    assert r.textos == ["¡Hola, cliente 7!"] and r.borrar_mensaje
    assert sesiones.estado(CHAT) is Estado.IDENTIFICADO
    assert servicio.llamadas == [("saludar", 7, f"tg-{CHAT}")]

    assert sesiones.atender(CHAT, "¿Cuánto debo?").textos == ["respuesta a ¿Cuánto debo?"]
    assert servicio.llamadas[-1] == ("responder", 7, "tg-555001", "¿Cuánto debo?", "telegram")  # [2.2] [2.3]


def test_nada_llega_al_agente_sin_identificarse(bot):
    """[1.1] Ni preguntas ni comandos llegan al agente antes del código."""
    sesiones, servicio, _, _ = bot
    for texto in ["¿Cuánto debo?", "/nuevo", "hola", "12345678901234"]:
        sesiones.atender(CHAT, texto)
    sesiones.atender(CHAT, RUC)
    sesiones.atender(CHAT, "no sé el código")
    sesiones.atender(CHAT, "000000")
    assert [ll for ll in servicio.llamadas if ll[0] in ("responder", "saludar")] == []


def test_mismo_mensaje_exista_o_no_el_ruc(bot):
    """[1.3]"""
    sesiones, _, otp_falso, _ = bot
    existe = sesiones.atender(1, RUC).textos
    no_existe = sesiones.atender(2, "20999999999").textos
    assert existe == no_existe == [s.MENSAJE_ENVIO]
    assert sesiones.estado(2) is Estado.ESPERANDO_CODIGO
    assert sesiones.atender(2, CODIGO).textos == [s.CODIGO_RECHAZADO]


@pytest.mark.parametrize("texto", ["2012345678", "201234567890", "20123456abc", "RUC por favor", "２０１２３４５６７８９"])
def test_ruc_invalido_no_pide_codigo(bot, texto):
    sesiones, _, otp_falso, _ = bot
    assert sesiones.atender(CHAT, texto).textos == [s.RUC_INVALIDO]
    assert otp_falso.solicitudes == [] and sesiones.estado(CHAT) is Estado.ESPERANDO_RUC


def test_ruc_con_espacios_o_guiones(bot):
    sesiones, _, otp_falso, _ = bot
    sesiones.atender(CHAT, " 20-123-456 789 ")
    assert otp_falso.solicitudes == [RUC]


def test_limite_de_codigos_por_chat(bot, monkeypatch):
    """[1.4] El límite es por chat: otro chat no se ve afectado."""
    monkeypatch.setattr(config, "TELEGRAM_MAX_SOLICITUDES", 2)
    monkeypatch.setattr(config, "TELEGRAM_VENTANA_SEG", 600)
    sesiones, _, otp_falso, reloj = bot
    for _ in range(2):
        sesiones.atender(CHAT, "/start")
        assert sesiones.atender(CHAT, RUC).textos == [s.MENSAJE_ENVIO]
    sesiones.atender(CHAT, "/start")
    r = sesiones.atender(CHAT, RUC)
    assert "Intenta de nuevo en 10 min" in r.textos[0]
    assert len(otp_falso.solicitudes) == 2 and sesiones.estado(CHAT) is Estado.ESPERANDO_RUC
    assert sesiones.atender(CHAT + 1, RUC).textos == [s.MENSAJE_ENVIO]
    reloj.t += 601
    assert sesiones.atender(CHAT, RUC).textos == [s.MENSAJE_ENVIO]


def test_codigo_mal_escrito_no_gasta_intentos(bot):
    sesiones, _, otp_falso, _ = bot
    sesiones.atender(CHAT, RUC)
    r = sesiones.atender(CHAT, "12345")
    assert r.textos == [s.PEDIR_CODIGO] and not r.borrar_mensaje
    assert otp_falso.verificaciones == []


def test_codigo_rechazado_se_borra_y_permite_reintentar(bot):
    """[1.7] El mensaje con el código se borra también si es incorrecto."""
    sesiones, _, _, _ = bot
    sesiones.atender(CHAT, RUC)
    r = sesiones.atender(CHAT, "654321")
    assert r.textos == [s.CODIGO_RECHAZADO] and r.borrar_mensaje
    assert sesiones.estado(CHAT) is Estado.ESPERANDO_CODIGO
    assert sesiones.atender(CHAT, CODIGO).borrar_mensaje
    assert sesiones.estado(CHAT) is Estado.IDENTIFICADO


def test_el_codigo_no_aparece_en_los_logs(bot, caplog):
    """[4.3]"""
    sesiones, _, _, _ = bot
    caplog.set_level(logging.DEBUG)
    sesiones.atender(CHAT, RUC)
    sesiones.atender(CHAT, "654321")
    sesiones.atender(CHAT, CODIGO)
    assert caplog.records
    assert CODIGO not in caplog.text and "654321" not in caplog.text and RUC not in caplog.text


@pytest.mark.parametrize("error", [RuntimeError("smtp caído"), ValueError("x")])
def test_fallo_al_enviar_el_codigo(bot, error):
    sesiones, _, otp_falso, _ = bot

    def falla(ruc):
        raise error

    sesiones._solicitar = falla
    assert sesiones.atender(CHAT, RUC).textos == [s.SIN_ENVIO]
    assert sesiones.estado(CHAT) is Estado.ESPERANDO_RUC


# -- sesión --------------------------------------------------------------------------

def test_sesion_vence(bot, monkeypatch):
    """[1.5] Al vencer, se olvida al cliente y su conversación, y se pide el RUC."""
    monkeypatch.setattr(config, "AUTH_MINUTOS_SESION", 30)
    sesiones, servicio, _, reloj = bot
    _identificar(sesiones)
    reloj.t += 30 * 60 - 1
    sesiones.atender(CHAT, "hola")
    reloj.t += 1
    assert sesiones.atender(CHAT, "hola otra vez").textos == [s.SESION_VENCIDA]
    assert sesiones.estado(CHAT) is Estado.ESPERANDO_RUC
    assert servicio.llamadas[-1] == ("reiniciar", 7, "tg-555001")
    assert [ll[3] for ll in servicio.llamadas if ll[0] == "responder"] == ["hola"]


def test_salir_olvida_la_sesion(bot):
    """[1.6]"""
    sesiones, servicio, _, _ = bot
    _identificar(sesiones)
    assert sesiones.atender(CHAT, "/salir").textos == [s.SALIDA]
    assert sesiones.estado(CHAT) is Estado.ESPERANDO_RUC
    assert servicio.llamadas[-1] == ("reiniciar", 7, "tg-555001")
    sesiones.atender(CHAT, "¿Cuánto debo?")
    assert not [ll for ll in servicio.llamadas if ll[0] == "responder"]


def test_start_identificado_vuelve_a_pedir_ruc(bot):
    sesiones, servicio, _, _ = bot
    _identificar(sesiones)
    assert sesiones.atender(CHAT, "/start").textos == [s.BIENVENIDA]
    assert sesiones.estado(CHAT) is Estado.ESPERANDO_RUC
    assert servicio.llamadas[-1][0] == "reiniciar"


def test_nuevo_reinicia_la_conversacion_con_el_saludo(bot):
    sesiones, servicio, _, _ = bot
    _identificar(sesiones)
    assert sesiones.atender(CHAT, "/nuevo").textos == ["¡Hola, cliente 7!"]
    assert sesiones.estado(CHAT) is Estado.IDENTIFICADO
    assert servicio.llamadas[-1] == ("saludar", 7, "tg-555001")


def test_nuevo_sin_identificar_o_vencido(bot):
    sesiones, _, _, reloj = bot
    assert sesiones.atender(CHAT, "/nuevo").textos == [s.PEDIR_RUC]
    sesiones.atender(CHAT, RUC)
    assert sesiones.atender(CHAT, "/nuevo").textos == [s.PEDIR_CODIGO]
    sesiones.atender(CHAT, CODIGO)
    reloj.t += config.AUTH_MINUTOS_SESION * 60
    assert sesiones.atender(CHAT, "/nuevo").textos == [s.SESION_VENCIDA]


@pytest.mark.parametrize("comando", ["/ayuda", "/help", "/otro", "/"])
def test_comando_desconocido_muestra_la_ayuda(bot, comando):
    sesiones, _, _, _ = bot
    assert sesiones.atender(CHAT, comando).textos == [s.AYUDA]


def test_comando_con_usuario_del_bot(bot):
    """En Telegram los comandos pueden llegar como /start@nombre_del_bot."""
    sesiones, _, _, _ = bot
    assert sesiones.atender(CHAT, "/START@anticipa_bot").textos == [s.BIENVENIDA]


# -- aislamiento y conversación ------------------------------------------------------

def test_chats_separados(bot):
    """[2.3] Identificarse en un chat no identifica a otro."""
    sesiones, servicio, otp_falso, _ = bot
    otp_falso.clientes["20111111111"] = 9
    _identificar(sesiones, chat=1)
    sesiones.atender(2, "20111111111")
    sesiones.atender(2, CODIGO)
    sesiones.atender(1, "a")
    sesiones.atender(2, "b")
    sesiones.atender(3, "c")
    respondidos = [(ll[1], ll[2]) for ll in servicio.llamadas if ll[0] == "responder"]
    assert respondidos == [(7, "tg-1"), (9, "tg-2")]


def test_conversacion_no_choca_con_la_web():
    assert conversacion_de(12345) == "tg-12345"
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", conversacion_de(9_999_999_999))


def test_mensaje_muy_largo(bot):
    """[3.5]"""
    sesiones, servicio, _, _ = bot
    _identificar(sesiones)
    assert sesiones.atender(CHAT, "x" * (s.MAX_MENSAJE + 1)).textos == [s.MUY_LARGO]
    assert sesiones.atender(CHAT, "x" * s.MAX_MENSAJE).textos[0].startswith("respuesta a")
    assert len([ll for ll in servicio.llamadas if ll[0] == "responder"]) == 1


def test_mensaje_vacio_no_llama_al_agente(bot):
    sesiones, servicio, _, _ = bot
    _identificar(sesiones)
    assert sesiones.atender(CHAT, "   ").textos == []
    assert not [ll for ll in servicio.llamadas if ll[0] == "responder"]


def test_asistente_no_disponible(bot):
    """[5.4]"""
    sesiones, servicio, _, _ = bot
    _identificar(sesiones)
    servicio.error = ChatNoDisponible("sin modelo")
    assert sesiones.atender(CHAT, "hola").textos == [s.NO_DISPONIBLE]
    assert sesiones.estado(CHAT) is Estado.IDENTIFICADO


def test_memoria_con_tope():
    sesiones = Sesiones(ServicioFalso(), solicitar=OtpFalso().solicitar, verificar=OtpFalso().verificar,
                        max_sesiones=3)
    for chat in range(1, 6):
        sesiones.atender(chat, RUC)
    assert len(sesiones._sesiones) == 3 and list(sesiones._sesiones) == [3, 4, 5]


# -- con el OTP real -----------------------------------------------------------------

def test_con_el_otp_real(tmp_path, monkeypatch):
    """Integración con app/auth/otp.py y una copia de la base (el correo se captura)."""
    copia = tmp_path / "anticipa.db"
    shutil.copy(config.DB_PATH, copia)
    monkeypatch.setattr(config, "DB_PATH", copia)
    enviados = []
    monkeypatch.setattr(otp, "enviar_correo", lambda destino, asunto, cuerpo: enviados.append(cuerpo))
    with sqlite3.connect(copia) as con:
        ruc = con.execute("SELECT ruc FROM cliente WHERE id_cliente = 1").fetchone()[0]

    servicio = ServicioFalso()
    sesiones = Sesiones(servicio)
    assert sesiones.atender(CHAT, ruc).textos == [s.MENSAJE_ENVIO]
    codigo = re.search(r"\b(\d{6})\b", enviados[-1]).group(1)
    incorrecto = f"{(int(codigo) + 1) % 10**6:06d}"
    assert sesiones.atender(CHAT, incorrecto).textos == [s.CODIGO_RECHAZADO]
    assert sesiones.atender(CHAT, codigo).textos == ["¡Hola, cliente 1!"]
    assert servicio.llamadas == [("saludar", 1, f"tg-{CHAT}")]
