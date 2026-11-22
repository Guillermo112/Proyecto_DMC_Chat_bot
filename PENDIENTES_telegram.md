# Pendientes: bot de Telegram

**Estado: completo** (pasos 1 a 9). Probado en Telegram real el 2026-11-22: identificación
por RUC y código, conversación con el agente y caso `C-000021` registrado con
`canal = telegram` y derivado. En el camino se corrigió el corte de respuestas por el tope
de tokens (`CHAT_MAX_TOKENS`, afecta también a la web).

**Para decidir con el equipo (fuera de este trabajo):** un reclamo sobre el propio
ejecutivo (`contacto_persona`) se deriva a ese mismo ejecutivo.

Rama: `feat/telegram` (desde `develop` @ `aa86f63`, con el chat web ya integrado, PR #10).
PR contra `develop`.

**Objetivo:** que un cliente converse con Anticipa desde Telegram con el mismo agente
del chat web (`/chat`): mismo turno (RAG previo + herramientas), misma identificación
(RUC + código OTP al correo) y los casos registrados con `canal = telegram`.

**Reglas de seguridad:** [`docs/telegram_seguridad.md`](docs/telegram_seguridad.md).
Cada paso del plan debe cumplir las reglas que le tocan (están numeradas y dicen en qué
paso se implementan); al terminar un paso, marcarlas ✅ allí.

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
2. [x] **Configuración** (hecho): las variables de la tabla en `app/config.py` y
   `.env.example`. `TELEGRAM_USUARIOS_PERMITIDOS` mal escrita es un error al arrancar (si
   se saltara, una lista que queda vacía abriría el bot a cualquiera). Tests en
   `tests/test_config_telegram.py`.
3. [x] **Sesiones del bot** (hecho): `app/telegram/sesiones.py`, máquina de estados por
   `chat_id` sin red (`ESPERANDO_RUC` → `ESPERANDO_CODIGO` → `IDENTIFICADO`). Reutiliza
   `otp.solicitar_codigo` / `otp.verificar_codigo` y el limitador de `app/auth/limite.py`
   con el chat como clave. Conversación `tg-<chat_id>`, sesión con vencimiento, tope de
   sesiones en memoria y `borrar_mensaje` para el mensaje del código. Los comandos
   (`/start`, `/nuevo`, `/salir`, ayuda) se resolvieron aquí: son lógica, no transporte.
   Tests: `tests/test_telegram_sesiones.py` (incluye uno con el OTP real y la base copiada).
4. [x] **Cliente de Telegram y despacho** (hecho): `app/telegram/bot.py`.
   `ClienteTelegram` (POST con JSON sobre `httpx`; errores sin el token) y `BotTelegram`:
   `deleteWebhook(drop_pending_updates)` al arrancar, `getUpdates` con `offset`, filtros
   (solo privados, lista de permitidos, solo texto), una cola por chat atendida por un
   hilo a la vez en un pool de `TELEGRAM_HILOS` (tope de 10 pendientes por chat),
   `typing`, borrado del código, y un bucle que reintenta con espera creciente (respeta
   `retry_after`), avisa el 409 y se detiene ante un 401. Tests: `tests/test_telegram_bot.py` con `httpx.MockTransport`.
5. [x] **Formato de salida** (hecho): `app/telegram/formato.py`. `a_html` escapa `&`, `<`,
   `>` y convierte `**negrita**` a `<b>` (como `formatear()` de la web); `partir` corta en
   mensajes cuyo HTML cabe en 4096, entre líneas y, si no alcanza, por palabras. El bot
   envía con `parse_mode=HTML` y, si Telegram rechaza el HTML, reenvía esa parte en texto
   plano. Tests: `tests/test_telegram_formato.py` y `tests/test_telegram_bot.py`.
6. [x] **Arranque** (hecho): `arrancar()` en `app/telegram/bot.py` levanta el bot en un
   hilo daemon (solo con token, uno por proceso) y avisa si no hay lista de permitidos;
   el `lifespan` de `app/main.py` lo arranca y lo detiene al cerrar. `run.bat` muestra el
   estado del bot. `tests/conftest.py` vacía el token en todos los tests.
7. [x] **Tests** (hecho): cada paso trajo los suyos (`test_telegram_sesiones.py`,
   `test_telegram_bot.py`, `test_telegram_formato.py`, `test_config_telegram.py`) y
   `tests/test_telegram_integracion.py` prueba la cadena completa sin red: API simulada →
   bot → sesiones con el OTP real → agente con modelo simulado → caso con canal
   `telegram` en una copia de la base; además el bloqueo por intentos y el RUC
   inexistente con el OTP real.
8. [x] **Documentación** (hecho): sección "Bot de Telegram" en el README (crear el bot,
   variables, comandos, un bot por integrante) y pendiente cerrado en `PENDIENTES_rag.md`.
9. [x] **Arranque explícito y candado local** (hecho, después de la prueba manual):
   `run.bat` deja el bot apagado aunque haya token y `run_telegram.bat` lo enciende
   (`TELEGRAM_ACTIVO=1`). `app/telegram/candado.py` bloquea un archivo por token en la
   carpeta temporal: una segunda API de la misma PC arranca sin bot y lo avisa. Ambos
   `.bat` muestran el estado (`apagado`, `sin_token`, `ocupado`, `lista`, `abierto`).
   Tests: `tests/test_telegram_candado.py` (incluye uno entre procesos) y
   `tests/test_telegram_bot.py`.

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
