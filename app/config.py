"""Configuración leída de variables de entorno (con valores por defecto).

Si existe un archivo `.env` en la raíz del proyecto, se carga primero.
Las variables ya definidas en el sistema tienen prioridad sobre el `.env`.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ_PROYECTO / ".env", override=False)

# Ruta de la base SQLite. Relativa a la raíz del proyecto si no es absoluta.
DB_PATH = Path(os.getenv("ANTICIPA_DB_PATH", "db/anticipa.db"))
if not DB_PATH.is_absolute():
    DB_PATH = RAIZ_PROYECTO / DB_PATH

# Paginación de listados.
LIMITE_POR_DEFECTO = int(os.getenv("LIMITE_POR_DEFECTO", "20"))
LIMITE_MAXIMO = int(os.getenv("LIMITE_MAXIMO", "100"))

# Envío de correo (OTP). Puerto 465 = SSL; cualquier otro usa STARTTLS.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_REMITENTE = os.getenv("SMTP_REMITENTE", "") or SMTP_USER
OTP_MINUTOS_VALIDEZ = int(os.getenv("OTP_MINUTOS_VALIDEZ", "10"))
OTP_MAX_INTENTOS = int(os.getenv("OTP_MAX_INTENTOS", "3"))
OTP_ESPERA_REENVIO_SEG = int(os.getenv("OTP_ESPERA_REENVIO_SEG", "60"))

# Clave del HMAC del OTP y de la firma del JWT de sesión.
# Vacío = no se pueden emitir códigos ni tokens (se valida al usarlo, no al importar).
AUTH_SECRET = os.getenv("AUTH_SECRET", "")
# Duración del token de sesión tras verificar el código. Sin logout.
AUTH_MINUTOS_SESION = int(os.getenv("AUTH_MINUTOS_SESION", "30"))

# Entorno: solo "dev" monta el CRUD de desarrollo /api/... (sin autenticación).
# Sin definir = "prod": si falta en el .env, el CRUD queda oculto (seguro por defecto).
ENTORNO = (os.getenv("ENTORNO") or "prod").strip().lower()  # vacío = sin definir

# Aviso por correo al derivar un caso (POST /mi/casos). El caso y el resultado
# del aviso se registran siempre en interaccion_log.
# - NOTIFICAR_DERIVACIONES desactivado: no se envía nada.
# - CORREO_DERIVACIONES definido: se REDIRIGE ahí (pruebas), indicando a quién iba.
# - Sin redirección: va al ejecutivo (y al responsable en CS-06), salvo a dominios
#   reservados (.example, como los de la base de prueba), que no existen.
# Un fallo de SMTP no deshace el caso.
NOTIFICAR_DERIVACIONES = os.getenv("NOTIFICAR_DERIVACIONES", "").strip().lower() in ("1", "true", "si", "sí", "yes")
CORREO_DERIVACIONES = os.getenv("CORREO_DERIVACIONES", "").strip()

# Límite de peticiones a /auth/solicitar-codigo por IP (ventana deslizante).
AUTH_MAX_SOLICITUDES_POR_IP = int(os.getenv("AUTH_MAX_SOLICITUDES_POR_IP", "5"))
AUTH_VENTANA_SOLICITUDES_SEG = int(os.getenv("AUTH_VENTANA_SOLICITUDES_SEG", "900"))
