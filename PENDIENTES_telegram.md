# Pendientes: bot de Telegram

Rama: `feat/telegram` (desde `develop` @ `aa86f63`, con el chat web ya integrado, PR #10).
PR contra `develop`.

**Objetivo:** que un cliente converse con Anticipa desde Telegram con el mismo agente
del chat web (`/chat`): mismo turno (RAG previo + herramientas), misma identificación
(RUC + código OTP al correo) y los casos registrados con `canal = telegram`.

## Decisiones tomadas

- **El bot llama a `ServicioChat` en el mismo proceso**, no a `POST /mi/chat` por HTTP.
  El turno ya no depende del canal: `responder(cliente_id, conversacion_id, mensaje)`.
  La conversación es `(cliente_id, str(chat_id))`.
- **Long polling (`getUpdates`) con `httpx`**, que ya es dependencia. No suma paquetes y
  funciona en local sin URL pública. Un webhook queda fuera de alcance (exige HTTPS público).
- **Hilo dentro de la API**, arrancado en el `lifespan` de `app/main.py` solo si hay
  `TELEGRAM_BOT_TOKEN`. Comparte el índice del RAG ya cargado (un proceso aparte volvería a
  cargar torch y el modelo de embeddings). Sin token, la API queda igual que hoy.
- **Sesión en memoria y con vencimiento** (`AUTH_MINUTOS_SESION`), igual que la web: se
  pierde al reiniciar la API. No se vincula el `chat_id` con el cliente de forma
  permanente: el OTP sigue siendo el factor de identificación.
- **Solo chats privados.** Cualquier mensaje de un grupo o canal se ignora (expondría
  datos de facturación a terceros).
- **Lista de usuarios permitidos para pruebas** (`TELEGRAM_USUARIOS_PERMITIDOS`, IDs
  numéricos separados por coma). Vacía = sin filtro. El bot es público por su usuario:
  con la lista, a los demás no les responde.
- **Un bot por integrante para desarrollo.** Un token admite un solo poller (si no,
  Telegram responde 409); para la demo compartida, uno levanta su entorno y pone los
  correos del equipo en su `.env`.

## Configuración nueva (`app/config.py`, `.env.example`, README)

| Variable | Por defecto | Uso |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | vacío | Token de @BotFather. Vacío = bot apagado. Secreto: solo en `.env` |
| `TELEGRAM_USUARIOS_PERMITIDOS` | vacío | IDs de Telegram que pueden usar el bot (pruebas) |
| `TELEGRAM_MAX_SOLICITUDES` / `TELEGRAM_VENTANA_SEG` | 5 / 900 | Límite de códigos pedidos por chat |
| `TELEGRAM_HILOS` | 4 | Turnos atendidos en paralelo (de chats distintos) |

## Orden de trabajo

1. [x] **Canal en los casos** (hecho). `Herramientas(cliente_id, palabras, canal="web")`
   valida el canal contra `Canal` y lo usa en `registrar_caso`; el que mande el modelo se
   ignora. `ServicioChat.responder(..., canal="web")` lo pasa a las herramientas y al log
   `chat.turno`. La web no cambia. Tests en `test_herramientas.py` y `test_chat.py`.
2. [ ] **Configuración** (tabla de arriba) y `.env.example`.
3. [ ] **Sesiones del bot** (`app/telegram/sesiones.py`): máquina de estados por `chat_id`,
   sin red ni Telegram, fácil de probar.
   - `sin_identificar` → pide el RUC (11 dígitos) → `otp.solicitar_codigo(ruc)`.
   - `esperando_codigo` → pide el código (6 dígitos) → `otp.verificar_codigo(id, codigo)`.
   - Id de conversación `tg-<chat_id>`: así no choca con los ids que genera la web
     (las conversaciones se separan por `(cliente_id, conversacion_id)`).
   - `identificado` (con `cliente_id` y hora de vencimiento) → los mensajes van a
     `ServicioChat.responder(..., canal="telegram")`. Al verificar, `servicio.saludar()`.
   - Sesión vencida → vuelve a `sin_identificar` y lo dice.
   - Mismo mensaje exista o no el RUC (como `app/auth/rutas.py`).
   - Límite de solicitudes por `chat_id`, reutilizando el limitador de `app/auth/limite.py`.
4. [ ] **Cliente de Telegram y despacho** (`app/telegram/bot.py`):
   - Bucle `getUpdates` con `timeout` largo y `offset`. Al arrancar descarta los
     pendientes (Telegram los guarda ~24 h) y llama a `deleteWebhook`.
   - Comandos: `/start` (identificarse), `/nuevo` (borra el historial: `reiniciar`),
     `/salir` (además olvida la sesión).
   - Solo texto: a fotos, audios o stickers responde que solo atiende texto.
   - Pool de `TELEGRAM_HILOS` hilos, **en orden por chat** (el `deque` del historial no
     tiene candado: dos mensajes del mismo chat no pueden procesarse a la vez).
   - `sendChatAction: typing` mientras responde.
   - `ChatNoDisponible` → mensaje amable; nunca quedarse callado.
   - Borra el mensaje con el código (`deleteMessage`) tras verificarlo. El código nunca
     va a los logs.
   - Errores de red de Telegram: reintento con espera, sin tumbar la API.
5. [ ] **Formato de salida:** `parse_mode=HTML`, escapando el texto y convirtiendo
   `**negrita**` a `<b>` (como `formatear()` en `app/static/chat.html`). Cortar en
   mensajes de hasta 4096 caracteres.
6. [ ] **Arranque** en el `lifespan` de `app/main.py` (hilo daemon, solo con token) y
   parada ordenada al cerrar la API.
7. [ ] **Tests** con `httpx.MockTransport` (sin red ni token):
   - Login: RUC inválido, RUC inexistente (mismo mensaje), código erróneo, bloqueo por
     intentos, sesión vencida, límite por chat.
   - Grupo ignorado; usuario fuera de la lista permitida ignorado.
   - Mensaje que no es texto.
   - Caso registrado con `canal = telegram`.
   - Formato HTML (escape y negrita) y corte a 4096.
   - Orden por chat: dos mensajes seguidos del mismo chat no se mezclan.
8. [ ] **Documentación:** README (sección del bot: crear el bot con @BotFather, `.env`,
   cómo probar) y quitar "Bot de Telegram" de pendientes en README y `PENDIENTES_rag.md`.

## Prueba manual (Telegram real)

1. @BotFather → `/newbot` → token en `.env` (`TELEGRAM_BOT_TOKEN`). Si se filtra: `/revoke`.
2. Tu ID de Telegram en `TELEGRAM_USUARIOS_PERMITIDOS`.
3. SMTP configurado y tu correo en `CORREO_PRUEBA_n` (base regenerada).
4. `run.bat`; en Telegram: `/start`, un RUC de `clientes_prueba.bat`, el código del correo.
5. Revisar: login, código erróneo, sesión vencida (`AUTH_MINUTOS_SESION=1`), un caso
   registrado con `canal = telegram`, `/nuevo`, `/salir`, una foto, el bot en un grupo.

Cuidados: un solo poller por token; algunas redes bloquean `api.telegram.org`; los
mensajes pasan por los servidores de Telegram (con datos ficticios no es problema).

## Fuera de alcance

- Webhook y despliegue público.
- Guardar cada turno en `interaccion_log` (sigue pendiente en `PENDIENTES_rag.md`).
- Vincular el `chat_id` con el cliente de forma permanente.
- El panel de traza (herramientas y documentos): en Telegram queda solo en los logs.
