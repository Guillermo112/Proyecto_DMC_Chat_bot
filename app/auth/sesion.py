"""Token de sesión (JWT HS256) que se emite tras verificar el código OTP.

- `emitir_token(cliente_id)` -> (token, segundos de validez). `sub` = cliente_id.
- `cliente_actual`: dependencia FastAPI que lee `Authorization: Bearer <token>` y
  devuelve el `cliente_id`; 401 si falta, es inválido o expiró.

El `cliente_id` de una petición sale siempre del token, nunca de lo que escriba el
usuario. Un JWT no se puede anular antes de `exp`: por eso la sesión es corta
(AUTH_MINUTOS_SESION) y no hay logout.
"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import config
from app.auth.secreto import obtener_secreto

ALGORITMO = "HS256"
EMISOR = "anticipa-auth"
TIPO = "sesion"

# auto_error=False: devolvemos nuestro propio 401 (FastAPI daría 403 sin cabecera).
_bearer = HTTPBearer(auto_error=False, description="Token de /auth/verificar-codigo")


def emitir_token(cliente_id: int) -> tuple[str, int]:
    """Firma un token para `cliente_id`. Devuelve (token, segundos hasta que expira)."""
    segundos = config.AUTH_MINUTOS_SESION * 60
    ahora = datetime.now(timezone.utc)
    claims = {
        "sub": str(cliente_id),  # PyJWT exige que `sub` sea texto
        "iss": EMISOR,
        "typ": TIPO,
        "iat": ahora,
        "exp": ahora + timedelta(seconds=segundos),
    }
    return jwt.encode(claims, obtener_secreto(), algorithm=ALGORITMO), segundos


def leer_token(token: str) -> int:
    """Valida firma, emisor, tipo y expiración. Devuelve el cliente_id.

    jwt.InvalidTokenError (o subclase, p. ej. ExpiredSignatureError) si no es válido.
    """
    claims = jwt.decode(
        token,
        obtener_secreto(),
        algorithms=[ALGORITMO],  # fijo: no se acepta "none" ni otro algoritmo
        issuer=EMISOR,
        options={"require": ["sub", "exp", "iat", "iss"]},
    )
    if claims.get("typ") != TIPO:
        raise jwt.InvalidTokenError("Tipo de token inesperado")
    sub = claims["sub"]
    if not (isinstance(sub, str) and sub.isdigit()):
        raise jwt.InvalidTokenError("sub inválido")
    return int(sub)


def _no_autorizado(detalle: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detalle, headers={"WWW-Authenticate": "Bearer"})


def cliente_actual(credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> int:
    """Dependencia: cliente_id de la sesión. 401 si no hay token válido."""
    if credenciales is None or credenciales.scheme.lower() != "bearer":
        raise _no_autorizado("Falta el token de sesión")
    try:
        return leer_token(credenciales.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise _no_autorizado("La sesión expiró; vuelve a verificar tu código") from exc
    except jwt.InvalidTokenError as exc:
        raise _no_autorizado("Token de sesión inválido") from exc
    except RuntimeError as exc:  # AUTH_SECRET no configurado
        raise HTTPException(status_code=503, detail="Autenticación no disponible") from exc
