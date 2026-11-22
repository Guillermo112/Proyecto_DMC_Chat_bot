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
# - CORREO_DERIVACIONES definido y ENTORNO=dev: se REDIRIGE ahí (pruebas), indicando a
#   quién iba. Fuera de dev se ignora (ver app/data/casos.py, _redireccion_de_prueba).
# - Sin redirección: va al ejecutivo (y al responsable en CS-06), salvo a dominios
#   reservados (.example, como los de la base de prueba), que no existen.
# Un fallo de SMTP no deshace el caso.
NOTIFICAR_DERIVACIONES = os.getenv("NOTIFICAR_DERIVACIONES", "").strip().lower() in ("1", "true", "si", "sí", "yes")
CORREO_DERIVACIONES = os.getenv("CORREO_DERIVACIONES", "").strip()

# Límite de peticiones a /auth/solicitar-codigo por IP (ventana deslizante).
AUTH_MAX_SOLICITUDES_POR_IP = int(os.getenv("AUTH_MAX_SOLICITUDES_POR_IP", "5"))
AUTH_VENTANA_SOLICITUDES_SEG = int(os.getenv("AUTH_VENTANA_SOLICITUDES_SEG", "900"))

# --- RAG (app/rag) ----------------------------------------------------------
# Fuentes del índice de documentos. faq.json NO entra: va a su propio clasificador.
# Los PDF se nombran uno por uno (el 02 mezcla el modo B y se decide aparte).
RAG_PDFS = [
    RAIZ_PROYECTO / "docs" / nombre.strip()
    for nombre in os.getenv(
        "RAG_PDFS",
        "Anticipa_01_Identidad_y_Atencion.pdf,Anticipa_03_Politicas_Catalogo_Glosario.pdf",
    ).split(",")
    if nombre.strip()
]
RAG_CATALOGO = RAIZ_PROYECTO / os.getenv("RAG_CATALOGO", "catalogo.json")

# Motor de vectores: auto (denso con respaldo TF-IDF) | denso | tfidf.
RAG_MOTOR = (os.getenv("RAG_MOTOR") or "auto").strip().lower()
SENTENCE_TRANSFORMER_MODEL = os.getenv(
    "SENTENCE_TRANSFORMER_MODEL", "ibm-granite/granite-embedding-97m-multilingual-r2"
)
# Similitud mínima para usar un fragmento. Cada motor tiene su escala.
# Medido con granite 97M y filas de tabla (2026-11-22): relevantes 0,83-0,96,
# ajenas 0,74-0,81. Margen fino: calibrar con el set de evaluación.
RAG_UMBRAL = float(os.getenv("RAG_UMBRAL", "0.82"))
RAG_UMBRAL_TFIDF = float(os.getenv("RAG_UMBRAL_TFIDF", "0.08"))
# Se recuperan K_INICIAL candidatos y el MMR elige K_FINAL relevantes y distintos.
RAG_K_INICIAL = int(os.getenv("RAG_K_INICIAL", "8"))
RAG_K_FINAL = int(os.getenv("RAG_K_FINAL", "3"))
RAG_MMR_LAMBDA = float(os.getenv("RAG_MMR_LAMBDA", "0.5"))  # 1 = relevancia, 0 = variedad
# Fragmentación de los PDF (los JSON van un registro por fragmento).
CHUNK_MAX_PALABRAS = int(os.getenv("CHUNK_MAX_PALABRAS", "150"))
CHUNK_OVERLAP_PALABRAS = int(os.getenv("CHUNK_OVERLAP_PALABRAS", "25"))

# --- Chat (app/agente) --------------------------------------------------------
# Cada vuelta es una llamada al modelo: tope para que un error no encadene llamadas.
CHAT_MAX_VUELTAS = int(os.getenv("CHAT_MAX_VUELTAS", "3"))
# Mensajes de la conversación que se reenvían en cada turno (memoria corta).
CHAT_MAX_MENSAJES = int(os.getenv("CHAT_MAX_MENSAJES", "8"))
CHAT_MAX_CONVERSACIONES = int(os.getenv("CHAT_MAX_CONVERSACIONES", "200"))
# Tope de salida por llamada. En los modelos que razonan (deepseek-flash) el razonamiento
# también cuenta: con 600 se cortaban respuestas a la mitad. Solo se cobra lo que se usa.
# Si aun así se corta, el chat reintenta una vez con el doble (app/agente/chat.py).
CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "1500"))
CHAT_TEMPERATURA = float(os.getenv("CHAT_TEMPERATURA", "0.3"))
# Cargar el índice del RAG al arrancar la API (en segundo plano), no en el primer mensaje.
RAG_PRECARGAR = (os.getenv("RAG_PRECARGAR") or "true").strip().lower() in ("1", "true", "si", "sí", "yes")

# --- Bot de Telegram (app/telegram) -------------------------------------------
# Token de @BotFather. Vacío = el bot no arranca y la API queda igual. Es un secreto:
# solo en .env. Un token admite un solo proceso leyendo mensajes (si no, Telegram da 409).
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def leer_ids_telegram(texto: str) -> frozenset[int]:
    """IDs numéricos de Telegram separados por coma. Vacío = sin filtro.

    Un valor mal escrito es un error y no se salta: si todos fueran inválidos, la
    lista quedaría vacía y el bot respondería a cualquiera.
    """
    partes = [p.strip() for p in texto.split(",") if p.strip()]
    invalidos = [p for p in partes if not (p.isascii() and p.isdigit()) or int(p) <= 0]
    if invalidos:
        raise ValueError(f"TELEGRAM_USUARIOS_PERMITIDOS: valores inválidos {invalidos} "
                         "(se esperan IDs numéricos separados por coma)")
    return frozenset(int(p) for p in partes)


# Usuarios que pueden usar el bot (pruebas). Vacío = cualquiera que encuentre el bot.
TELEGRAM_USUARIOS_PERMITIDOS = leer_ids_telegram(os.getenv("TELEGRAM_USUARIOS_PERMITIDOS", ""))
# Límite de códigos pedidos por chat (ventana deslizante), como el límite por IP de la web.
TELEGRAM_MAX_SOLICITUDES = int(os.getenv("TELEGRAM_MAX_SOLICITUDES", "5"))
TELEGRAM_VENTANA_SEG = int(os.getenv("TELEGRAM_VENTANA_SEG", "900"))
# Turnos atendidos en paralelo (de chats distintos; los de un mismo chat van en orden).
TELEGRAM_HILOS = max(1, int(os.getenv("TELEGRAM_HILOS", "4")))
