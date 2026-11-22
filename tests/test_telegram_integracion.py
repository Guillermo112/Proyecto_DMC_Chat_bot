"""Bot de Telegram de punta a punta, sin red: API de Telegram simulada → BotTelegram →
Sesiones con el OTP real → ServicioChat con un modelo simulado → base (copia).

Los números entre corchetes son las reglas de docs/telegram_seguridad.md.
"""
import logging
import re
import shutil
import sqlite3
import time

import httpx
import pytest

from app import config
from app.agente import ServicioChat
from app.auth import otp
from app.rag.indice import IndiceConocimiento
from app.telegram import Sesiones
from app.telegram import bot as b
from app.telegram import sesiones as s
from tests.test_chat import RouterFalso, _herramienta, _texto
from tests.test_telegram_bot import TOKEN, TelegramFalso, _mensaje

CHAT = 777001


@pytest.fixture
def base(tmp_path, monkeypatch):
    copia = tmp_path / "anticipa.db"
    shutil.copy(config.DB_PATH, copia)
    monkeypatch.setattr(config, "DB_PATH", copia)
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", False)
    correos = []
    monkeypatch.setattr(otp, "enviar_correo", lambda destino, asunto, cuerpo: correos.append(cuerpo))
    with sqlite3.connect(copia) as con:
        ruc = con.execute("SELECT ruc FROM cliente WHERE id_cliente = 1").fetchone()[0]
    return copia, correos, ruc


def _codigo(correos):
    return re.search(r"\b(\d{6})\b", correos[-1]).group(1)


def _esperar(bot):
    for _ in range(300):
        with bot._candado:
            if not bot._colas:
                return
        time.sleep(0.01)
    raise AssertionError("el bot no terminó de atender")


def test_de_punta_a_punta_registra_el_caso_por_telegram(base, caplog):
    """Identificarse, conversar y registrar un caso: queda con canal telegram [2.2], el
    mensaje del código se borra [1.7] y ni el token ni el código aparecen en los logs
    [4.2] [4.3]."""
    copia, correos, ruc = base
    caplog.set_level(logging.DEBUG)
    router = RouterFalso(
        _herramienta("registrar_caso", {"tipo": "factura_duplicada", "numero_factura": "F001-000255",
                                        "canal": "web"}),
        _texto("Registré tu caso **C-000099**."),
    )
    servicio = ServicioChat(router=router, indice=IndiceConocimiento(fragmentos=[], motor="tfidf"))
    api = TelegramFalso()
    cliente = b.ClienteTelegram(TOKEN, http=httpx.Client(transport=httpx.MockTransport(api)))
    bot = b.BotTelegram(cliente, Sesiones(servicio), permitidos=frozenset({CHAT}), espera_larga=0)
    try:
        bot.recibir(_mensaje("/start", chat=CHAT))
        bot.recibir(_mensaje(ruc, chat=CHAT))
        _esperar(bot)
        codigo = _codigo(correos)
        mensaje_codigo = _mensaje(codigo, chat=CHAT)
        bot.recibir(mensaje_codigo)
        bot.recibir(_mensaje("Me llegaron dos facturas iguales, regístralo", chat=CHAT))
        _esperar(bot)
    finally:
        bot._pool.shutdown(wait=True)

    enviados = api.enviados(CHAT)
    assert enviados[0].startswith("¡Hola! Soy Anticipa") and enviados[1] == s.MENSAJE_ENVIO
    assert enviados[2].startswith("¡Hola")  # saludo del agente tras verificar
    assert enviados[3] == "Registré tu caso <b>C-000099</b>."  # HTML
    borrados = [c for m, c in api.llamadas if m == "deleteMessage"]
    assert borrados == [{"chat_id": CHAT, "message_id": mensaje_codigo["message"]["message_id"]}]

    canal, cliente_id = sqlite3.connect(copia).execute(
        "SELECT canal, id_cliente FROM caso ORDER BY id_caso DESC LIMIT 1").fetchone()
    assert (canal, cliente_id) == ("telegram", 1)
    assert TOKEN not in caplog.text and codigo not in caplog.text


def test_bloqueo_por_intentos_con_el_otp_real(base, monkeypatch):
    """[1.2] Tras OTP_MAX_INTENTOS códigos erróneos, ni el correcto sirve: hay que pedir otro."""
    monkeypatch.setattr(config, "OTP_MAX_INTENTOS", 3)
    _, correos, ruc = base
    sesiones = Sesiones(_ServicioMinimo())
    sesiones.atender(CHAT, ruc)
    codigo = _codigo(correos)
    errado = f"{(int(codigo) + 1) % 10**6:06d}"
    for _ in range(3):
        assert sesiones.atender(CHAT, errado).textos == [s.CODIGO_RECHAZADO]
    assert sesiones.atender(CHAT, codigo).textos == [s.CODIGO_RECHAZADO]  # bloqueado

    sesiones.atender(CHAT, "/start")
    sesiones.atender(CHAT, ruc)
    nuevo = _codigo(correos)
    assert sesiones.atender(CHAT, nuevo).textos == ["¡Hola, cliente 1!"]


def test_ruc_inexistente_no_envia_correo(base):
    """[1.3] Misma respuesta, pero no sale ningún correo y ningún código sirve."""
    _, correos, _ = base
    sesiones = Sesiones(_ServicioMinimo())
    assert sesiones.atender(CHAT, "20999999999").textos == [s.MENSAJE_ENVIO]
    assert correos == []
    assert sesiones.atender(CHAT, "123456").textos == [s.CODIGO_RECHAZADO]


class _ServicioMinimo:
    def saludar(self, cliente_id, conversacion_id):
        return f"¡Hola, cliente {cliente_id}!"

    def reiniciar(self, cliente_id, conversacion_id):
        pass
