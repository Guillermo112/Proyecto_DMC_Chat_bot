"""OTP por correo: sobre una copia de la base y sin enviar correos reales."""
import hashlib
import hmac
import re
import shutil
import sqlite3

import pytest

from app import config
from app.auth import otp


@pytest.fixture
def db(tmp_path, monkeypatch):
    copia = tmp_path / "anticipa.db"
    shutil.copy(config.DB_PATH, copia)
    enviados = []
    monkeypatch.setattr(otp, "enviar_correo", lambda destino, asunto, cuerpo: enviados.append((destino, cuerpo)))
    with sqlite3.connect(copia) as con:
        ruc = con.execute("SELECT ruc FROM cliente WHERE id_cliente = 1").fetchone()[0]
    return copia, enviados, ruc


def _codigo(enviados):
    return re.search(r"\b(\d{6})\b", enviados[-1][1]).group(1)


def _estado(copia, id_v):
    with sqlite3.connect(copia) as con:
        return con.execute("SELECT estado, intentos FROM verificacion WHERE id_verificacion = ?", (id_v,)).fetchone()


def test_codigo_correcto_devuelve_cliente(db):
    copia, enviados, ruc = db
    id_v, _ = otp.solicitar_codigo(ruc, db_path=copia)
    with sqlite3.connect(copia) as con:
        registrado = con.execute("SELECT correo_facturacion FROM cliente WHERE id_cliente = 1").fetchone()[0]
    assert enviados[0][0] == registrado
    assert otp.verificar_codigo(id_v, _codigo(enviados), db_path=copia) == 1
    assert _estado(copia, id_v) == ("verificado", 1)
    # Un código ya usado no sirve otra vez.
    assert otp.verificar_codigo(id_v, _codigo(enviados), db_path=copia) is None


def test_codigo_no_se_guarda_en_claro(db):
    copia, enviados, ruc = db
    id_v, _ = otp.solicitar_codigo(ruc, db_path=copia)
    with sqlite3.connect(copia) as con:
        guardado = con.execute("SELECT codigo_hash FROM verificacion WHERE id_verificacion = ?", (id_v,)).fetchone()[0]
    assert guardado != _codigo(enviados) and len(guardado) == 64


def test_hash_es_hmac_con_el_secreto(db, monkeypatch):
    copia, enviados, ruc = db
    id_v, _ = otp.solicitar_codigo(ruc, db_path=copia)
    codigo = _codigo(enviados)
    with sqlite3.connect(copia) as con:
        guardado = con.execute("SELECT codigo_hash FROM verificacion WHERE id_verificacion = ?", (id_v,)).fetchone()[0]
    # Un SHA-256 sin clave (lo que se guardaba antes) ya no coincide.
    assert guardado != hashlib.sha256(codigo.encode()).hexdigest()
    esperado = hmac.new(config.AUTH_SECRET.encode(), codigo.encode(), hashlib.sha256).hexdigest()
    assert guardado == esperado


def test_cambiar_el_secreto_invalida_codigos_pendientes(db, monkeypatch):
    copia, enviados, ruc = db
    id_v, _ = otp.solicitar_codigo(ruc, db_path=copia)
    monkeypatch.setattr(config, "AUTH_SECRET", "otro-secreto-distinto-" + "y" * 32)
    assert otp.verificar_codigo(id_v, _codigo(enviados), db_path=copia) is None


@pytest.mark.parametrize("secreto", ["", "corto"])
def test_sin_secreto_no_se_envia_ni_registra_nada(db, monkeypatch, secreto):
    copia, enviados, ruc = db
    monkeypatch.setattr(config, "AUTH_SECRET", secreto)
    with sqlite3.connect(copia) as con:
        antes = con.execute("SELECT COUNT(*) FROM verificacion").fetchone()[0]
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        otp.solicitar_codigo(ruc, db_path=copia)
    assert enviados == []
    with sqlite3.connect(copia) as con:
        assert con.execute("SELECT COUNT(*) FROM verificacion").fetchone()[0] == antes


def test_bloqueo_tras_intentos_fallidos(db):
    copia, enviados, ruc = db
    id_v, _ = otp.solicitar_codigo(ruc, db_path=copia)
    malo = "000000" if _codigo(enviados) != "000000" else "111111"
    for _ in range(config.OTP_MAX_INTENTOS):
        assert otp.verificar_codigo(id_v, malo, db_path=copia) is None
    assert _estado(copia, id_v) == ("bloqueado", config.OTP_MAX_INTENTOS)
    # Bloqueado: ni el código correcto entra.
    assert otp.verificar_codigo(id_v, _codigo(enviados), db_path=copia) is None


def test_codigo_vencido(db, monkeypatch):
    copia, enviados, ruc = db
    monkeypatch.setattr(config, "OTP_MINUTOS_VALIDEZ", -1)
    id_v, _ = otp.solicitar_codigo(ruc, db_path=copia)
    assert otp.verificar_codigo(id_v, _codigo(enviados), db_path=copia) is None
    assert _estado(copia, id_v)[0] == "expirado"


def test_reenvio_prematuro_continua_la_verificacion_sin_enviar(db):
    copia, enviados, ruc = db
    primero, _ = otp.solicitar_codigo(ruc, db_path=copia)
    malo = "000000" if _codigo(enviados) != "000000" else "111111"
    assert otp.verificar_codigo(primero, malo, db_path=copia) is None  # gasta 1 intento

    segundo, correo = otp.solicitar_codigo(ruc, db_path=copia)
    assert segundo != primero and correo is not None
    assert len(enviados) == 1  # no se envió otro correo
    assert _estado(copia, primero)[0] == "expirado"
    # Hereda los intentos: reenviar no regala oportunidades.
    assert _estado(copia, segundo) == ("pendiente", 1)
    with sqlite3.connect(copia) as con:
        filas = con.execute(
            "SELECT codigo_hash, fecha_envio, fecha_expira FROM verificacion WHERE id_verificacion IN (?, ?)"
            " ORDER BY id_verificacion", (primero, segundo)).fetchall()
    assert filas[0] == filas[1]  # mismo código, misma fecha de envío y expiración
    # El código que ya llegó sirve con el id nuevo, no con el viejo.
    assert otp.verificar_codigo(primero, _codigo(enviados), db_path=copia) is None
    assert otp.verificar_codigo(segundo, _codigo(enviados), db_path=copia) == 1


def test_reenvio_prematuro_no_reinicia_la_espera(db):
    """La fecha de envío se hereda: insistir no alarga la espera para pedir otro código."""
    copia, enviados, ruc = db
    otp.solicitar_codigo(ruc, db_path=copia)
    with sqlite3.connect(copia) as con:  # simular que el envío fue hace 2 minutos
        con.execute("UPDATE verificacion SET fecha_envio = datetime(fecha_envio, '-120 seconds')"
                    " WHERE estado = 'pendiente'")
    otp.solicitar_codigo(ruc, db_path=copia)
    assert len(enviados) == 2  # pasó la espera: código nuevo


def test_reenvio_prematuro_no_supera_el_maximo_de_intentos(db):
    copia, enviados, ruc = db
    id_v, _ = otp.solicitar_codigo(ruc, db_path=copia)
    malo = "000000" if _codigo(enviados) != "000000" else "111111"
    for _ in range(config.OTP_MAX_INTENTOS - 1):
        otp.verificar_codigo(id_v, malo, db_path=copia)
        id_v, _ = otp.solicitar_codigo(ruc, db_path=copia)
    otp.verificar_codigo(id_v, malo, db_path=copia)
    assert _estado(copia, id_v) == ("bloqueado", config.OTP_MAX_INTENTOS)
    assert otp.verificar_codigo(id_v, _codigo(enviados), db_path=copia) is None


def test_codigo_nuevo_invalida_el_anterior(db, monkeypatch):
    copia, enviados, ruc = db
    primero, _ = otp.solicitar_codigo(ruc, db_path=copia)
    monkeypatch.setattr(config, "OTP_ESPERA_REENVIO_SEG", 0)
    segundo, _ = otp.solicitar_codigo(ruc, db_path=copia)
    assert _estado(copia, primero)[0] == "expirado"
    assert otp.verificar_codigo(segundo, _codigo(enviados), db_path=copia) == 1


def test_ruc_inexistente_no_envia_ni_verifica(db):
    copia, enviados, _ = db
    id_v, correo = otp.solicitar_codigo("99999999999", db_path=copia)
    assert enviados == [] and correo is None
    assert otp.verificar_codigo(id_v, "123456", db_path=copia) is None


@pytest.mark.parametrize("ruc", ["123", "2010000000A", "", None])
def test_ruc_invalido(db, ruc):
    copia, _, _ = db
    with pytest.raises(ValueError):
        otp.solicitar_codigo(ruc, db_path=copia)


def test_devuelve_correo_enmascarado(db):
    copia, enviados, ruc = db
    _, correo = otp.solicitar_codigo(ruc, db_path=copia)
    assert correo == otp.enmascarar(enviados[0][0]) and correo != enviados[0][0]


def test_enmascarar():
    assert otp.enmascarar("jperez@cordillera.pe") == "j*****@cordillera.pe"
    assert otp.enmascarar("a@x.pe") == "a***@x.pe"


def test_fallo_de_envio_no_deja_registro(db, monkeypatch):
    copia, _, ruc = db

    def falla(*_):
        raise RuntimeError("SMTP caído")

    monkeypatch.setattr(otp, "enviar_correo", falla)
    with sqlite3.connect(copia) as con:
        antes = con.execute("SELECT COUNT(*) FROM verificacion").fetchone()[0]
    with pytest.raises(RuntimeError):
        otp.solicitar_codigo(ruc, db_path=copia)
    with sqlite3.connect(copia) as con:
        assert con.execute("SELECT COUNT(*) FROM verificacion").fetchone()[0] == antes
