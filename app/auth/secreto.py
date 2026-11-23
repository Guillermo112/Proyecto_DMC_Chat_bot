"""Secreto de autenticación (AUTH_SECRET): clave del HMAC del OTP y, más adelante, del JWT.

Se lee de `config` en cada uso (no al importar) para que la app y los tests
arranquen sin él y solo falle lo que realmente lo necesita.
"""
from app import config

LONGITUD_MINIMA = 32


def obtener_secreto() -> bytes:
    """Devuelve AUTH_SECRET en bytes; RuntimeError si falta o es demasiado corto."""
    secreto = (config.AUTH_SECRET or "").strip()
    if len(secreto) < LONGITUD_MINIMA:
        raise RuntimeError(
            f"AUTH_SECRET no configurado o con menos de {LONGITUD_MINIMA} caracteres. Genera uno con: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))" y ponlo en .env'
        )
    return secreto.encode()
