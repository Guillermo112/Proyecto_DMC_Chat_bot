"""Identificación del cliente (CS-12): RUC + código de 6 dígitos enviado por correo.

Flujo: `solicitar_codigo(ruc)` -> (id de verificación, correo enmascarado);
`verificar_codigo(id, codigo)` -> `cliente_id` verificado o None.
En la base solo se guarda HMAC-SHA256(AUTH_SECRET, código): sin el secreto, un
volcado de la tabla no permite recuperar los códigos probando el millón de opciones.
"""
import hashlib
import hmac
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from app import config
from app.auth.secreto import obtener_secreto
from app.data.conexion import get_connection

_FORMATO = "%Y-%m-%d %H:%M:%S"


def hash_codigo(codigo: str) -> str:
    """HMAC-SHA256 del código con AUTH_SECRET (hex, 64 caracteres).

    También lo usa db/generar_datos.py para los datos de prueba. Cambiar el secreto
    invalida los códigos pendientes (dejan de coincidir).
    """
    return hmac.new(obtener_secreto(), codigo.encode(), hashlib.sha256).hexdigest()


def enviar_correo(destino: str, asunto: str, cuerpo: str) -> None:
    if not (config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD):
        raise RuntimeError("SMTP no configurado: define SMTP_HOST, SMTP_USER y SMTP_PASSWORD en .env")
    msg = EmailMessage()
    msg["From"] = config.SMTP_REMITENTE
    msg["To"] = destino
    msg["Subject"] = asunto
    msg.set_content(cuerpo)
    contexto = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        servidor = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20, context=contexto)
    else:
        servidor = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
        servidor.starttls(context=contexto)
    with servidor:
        servidor.login(config.SMTP_USER, config.SMTP_PASSWORD)
        servidor.send_message(msg)


def enmascarar(correo: str) -> str:
    """'jperez@cordillera.pe' -> 'j*****@cordillera.pe'."""
    usuario, _, dominio = correo.partition("@")
    return f"{usuario[:1]}{'*' * max(len(usuario) - 1, 3)}@{dominio}"


def solicitar_codigo(ruc: str, db_path: Path | None = None) -> tuple[int, str | None]:
    """Envía un código al correo registrado del cliente (nunca a otro).

    Devuelve (id de verificación, correo enmascarado). Si el RUC no existe no se
    envía nada: se registra el intento ('bloqueado') y el correo es None.
    ValueError si el RUC es inválido o si se pide otro código antes de
    OTP_ESPERA_REENVIO_SEG.
    """
    ruc = ruc.strip() if isinstance(ruc, str) else ""
    if len(ruc) != 11 or not ruc.isdigit():
        raise ValueError("El RUC debe tener 11 dígitos")
    ahora = datetime.now()
    with get_connection(db_path, escritura=True) as con:
        with con:  # una transacción: si el envío falla, no queda el registro
            con.execute("BEGIN IMMEDIATE")
            cliente = con.execute(
                "SELECT id_cliente, correo_facturacion FROM cliente WHERE ruc = ?", (ruc,)
            ).fetchone()
            if cliente is None:
                cur = con.execute(
                    "INSERT INTO verificacion (id_cliente, ruc_ingresado, codigo_hash, fecha_envio,"
                    " fecha_expira, intentos, estado) VALUES (NULL, ?, NULL, ?, ?, 0, 'bloqueado')",
                    (ruc, ahora.strftime(_FORMATO), ahora.strftime(_FORMATO)),
                )
                return cur.lastrowid, None

            id_cliente = cliente["id_cliente"]
            ultimo = con.execute(
                "SELECT fecha_envio FROM verificacion WHERE id_cliente = ? AND estado = 'pendiente'"
                " ORDER BY id_verificacion DESC LIMIT 1",
                (id_cliente,),
            ).fetchone()
            espera = timedelta(seconds=config.OTP_ESPERA_REENVIO_SEG)
            if ultimo and ahora - datetime.fromisoformat(ultimo["fecha_envio"]) < espera:
                raise ValueError("Ya se envió un código hace poco; espera un momento antes de pedir otro")

            # Un código nuevo invalida los anteriores.
            con.execute(
                "UPDATE verificacion SET estado = 'expirado' WHERE id_cliente = ? AND estado = 'pendiente'",
                (id_cliente,),
            )
            codigo = f"{secrets.randbelow(10**6):06d}"
            expira = ahora + timedelta(minutes=config.OTP_MINUTOS_VALIDEZ)
            cur = con.execute(
                "INSERT INTO verificacion (id_cliente, ruc_ingresado, codigo_hash, fecha_envio,"
                " fecha_expira, intentos, estado) VALUES (?, ?, ?, ?, ?, 0, 'pendiente')",
                (id_cliente, ruc, hash_codigo(codigo), ahora.strftime(_FORMATO), expira.strftime(_FORMATO)),
            )
            enviar_correo(
                cliente["correo_facturacion"],
                "Tu código de verificación AnticIpA",
                f"Tu código es: {codigo}\n\nVence en {config.OTP_MINUTOS_VALIDEZ} minutos. "
                "Si no lo solicitaste, ignora este correo.",
            )
            return cur.lastrowid, enmascarar(cliente["correo_facturacion"])


def verificar_codigo(id_verificacion: int, codigo: str, db_path: Path | None = None) -> int | None:
    """Devuelve el cliente_id si el código es correcto; None si no (y cuenta el intento).

    Tras OTP_MAX_INTENTOS fallidos la verificación queda 'bloqueado'.
    """
    codigo = codigo.strip() if isinstance(codigo, str) else ""
    with get_connection(db_path, escritura=True) as con:
        with con:
            con.execute("BEGIN IMMEDIATE")  # evita que intentos en paralelo se salten el contador
            fila = con.execute(
                "SELECT id_cliente, codigo_hash, fecha_expira, intentos, estado"
                " FROM verificacion WHERE id_verificacion = ?",
                (id_verificacion,),
            ).fetchone()
            if fila is None or fila["estado"] != "pendiente":
                return None
            if datetime.now() > datetime.fromisoformat(fila["fecha_expira"]):
                con.execute("UPDATE verificacion SET estado = 'expirado' WHERE id_verificacion = ?", (id_verificacion,))
                return None

            intentos = fila["intentos"] + 1
            if hmac.compare_digest(hash_codigo(codigo), fila["codigo_hash"]):
                con.execute(
                    "UPDATE verificacion SET intentos = ?, estado = 'verificado' WHERE id_verificacion = ?",
                    (intentos, id_verificacion),
                )
                return fila["id_cliente"]
            estado = "bloqueado" if intentos >= config.OTP_MAX_INTENTOS else "pendiente"
            con.execute(
                "UPDATE verificacion SET intentos = ?, estado = ? WHERE id_verificacion = ?",
                (intentos, estado, id_verificacion),
            )
            return None
