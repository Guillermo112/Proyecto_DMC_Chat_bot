# Bot de Telegram: reglas de seguridad

Reglas que debe cumplir el bot (`app/telegram`). Cada una dice **qué protege**, **cómo
se cumple** y **cómo se prueba**. El plan de trabajo está en
[`PENDIENTES_telegram.md`](../PENDIENTES_telegram.md); estas reglas no cambian sin
actualizar este documento.

Estado: ✅ hecho · ⏳ pendiente (paso del plan entre paréntesis).

## Punto de partida

El bot es **público**: cualquiera que conozca o adivine su usuario puede escribirle.
Los mensajes pasan por los servidores de Telegram, y el bot corre en la PC de quien
levanta la API, con **su** base, **su** clave del modelo y **su** SMTP. La base es
ficticia, pero el diseño se hace como si los datos fueran reales.

Lo que se protege, en orden:

1. Los datos de facturación de un cliente: solo los ve quien demuestra ser él.
2. La identificación: que no se pueda adivinar un código ni saber quién es cliente.
3. Los recursos de quien levanta el bot: tokens del modelo, correos enviados y el token
   del bot.

## 1. Identificación

| # | Regla | Cómo se cumple | Estado |
|---|---|---|---|
| 1.1 | **Sin identificarse, no hay datos.** Ningún mensaje llega al agente (y por lo tanto a las herramientas) antes de verificar el código. | Máquina de estados por `chat_id`: solo el estado `identificado` llama a `ServicioChat.responder`. | ✅ (3) |
| 1.2 | **El OTP sigue siendo el factor.** Se usa el mismo flujo que la web: RUC → código al correo de facturación → verificación. | `otp.solicitar_codigo` y `otp.verificar_codigo` de `app/auth/otp.py`, sin copiar su lógica. Hereda el HMAC, el vencimiento (`OTP_MINUTOS_VALIDEZ`), los intentos (`OTP_MAX_INTENTOS`) y la espera de reenvío. | ✅ (3) |
| 1.3 | **No se revela quién es cliente.** Mismo mensaje exista o no el RUC, y también en un reenvío prematuro. | Igual que `app/auth/rutas.py` (`_MENSAJE_ENVIO`). | ✅ (3) |
| 1.4 | **Límite de códigos por chat.** Evita adivinar códigos, enumerar RUC y llenar de correos a un cliente. | Limitador de `app/auth/limite.py` con clave `chat_id`: `TELEGRAM_MAX_SOLICITUDES` en `TELEGRAM_VENTANA_SEG`. | ✅ (2, 3) |
| 1.5 | **La sesión vence.** Igual que el token de la web: `AUTH_MINUTOS_SESION`. Al vencer, el bot lo dice y pide identificarse de nuevo. | Hora de vencimiento guardada con el `cliente_id`. | ✅ (3) |
| 1.6 | **Sin vínculo permanente chat → cliente.** Tener el chat no basta: cada sesión pasa por el OTP. | La sesión vive en memoria (con tope de sesiones); se pierde al reiniciar la API, con `/salir` y con `/start`. | ✅ (3, 4) |
| 1.7 | **El código no queda a la vista.** | `Sesiones` marca `borrar_mensaje` en todo mensaje que se verificó como código (correcto o no); el bot lo borra con `deleteMessage`. | ✅ (3, 4) |

## 2. Aislamiento entre clientes

| # | Regla | Cómo se cumple | Estado |
|---|---|---|---|
| 2.1 | **El cliente sale de la sesión, nunca del mensaje ni del modelo.** | `Herramientas(cliente_id)` lo recibe del código; ningún esquema declara `cliente_id` y, si el modelo lo manda, se ignora. Ya cubierto por `tests/test_herramientas.py` y `tests/test_aislamiento.py`. | ✅ |
| 2.2 | **El canal lo pone el código.** Los casos del bot quedan con `canal = telegram`; el que mande el modelo se ignora. | `Herramientas(..., canal=...)` y `ServicioChat.responder(..., canal=...)`. | ✅ (1) |
| 2.3 | **Conversaciones separadas.** Una conversación del bot no se mezcla con una de la web ni con otro chat. | Clave `(cliente_id, "tg-<chat_id>")`. | ✅ (3) |
| 2.4 | **Mensajes de un mismo chat, en orden.** Dos mensajes seguidos no se procesan a la vez (el historial no tiene candado). | Pool de `TELEGRAM_HILOS` hilos con una cola por chat. | ✅ (4) |

## 3. Quién puede hablar con el bot

| # | Regla | Cómo se cumple | Estado |
|---|---|---|---|
| 3.1 | **Solo chats privados.** En un grupo, los datos de facturación los verían terceros. | Se ignora todo mensaje con `chat.type` distinto de `private`, sin responder. | ✅ (4) |
| 3.2 | **Lista de usuarios permitidos en pruebas.** | `TELEGRAM_USUARIOS_PERMITIDOS`: si tiene IDs, a los demás no se les responde (ni siquiera con un error, para no confirmar que el bot está vivo). | ✅ (2, 4) |
| 3.3 | **Una lista mal escrita no abre el bot.** Si un valor se saltara y todos estuvieran mal, la lista quedaría vacía y el bot respondería a cualquiera. | `config.leer_ids_telegram` falla al arrancar con el valor inválido. `tests/test_config_telegram.py`. | ✅ (2) |
| 3.4 | **Solo texto.** Fotos, audios, archivos o stickers no se procesan ni se descargan. | Respuesta fija: "solo atiendo mensajes de texto". | ✅ (4) |
| 3.5 | **Mensajes acotados.** | Se descarta lo que supere el máximo de la web (2000 caracteres, como `ChatPeticion`). | ✅ (3) |

## 4. Secretos y registros

| # | Regla | Cómo se cumple | Estado |
|---|---|---|---|
| 4.1 | **El token del bot es un secreto.** Con él, cualquiera lee los mensajes que le llegan al bot y responde en su nombre. | Solo en `.env` (no versionado); `.env.example` lo deja vacío (lo comprueba un test). Si se filtra: @BotFather → `/revoke`. | ✅ (2) |
| 4.2 | **El token no aparece en logs ni errores.** Va dentro de la URL de la API de Telegram (`/bot<token>/...`). | `ErrorTelegram` no encadena la excepción de httpx (su `repr` lleva la URL) y un filtro en los loggers `httpx`/`httpcore` cambia el token por `<token>`. | ✅ (4) |
| 4.3 | **El código OTP no aparece en logs.** | Solo se registra el resultado (`verificado` o `rechazado`), nunca el texto del mensaje en el estado `esperando_codigo`. | ✅ (3, 4) |
| 4.4 | **Logs mínimos del turno.** | El log `chat.turno` ya registra canal, cliente, herramientas y tokens, sin el texto del cliente. El bot agrega el `chat_id`, no el nombre ni el usuario de Telegram. | ✅ (1, 4) |

## 5. Funcionamiento

| # | Regla | Cómo se cumple | Estado |
|---|---|---|---|
| 5.1 | **Sin token, no hay bot.** La API funciona igual que antes. | `arrancar()` solo levanta el hilo si `TELEGRAM_BOT_TOKEN` no está vacío; `run.bat` muestra si el bot está activo y si tiene lista de permitidos. Los tests vacían el token (`conftest.py`) para no salir nunca a la red con el `.env` de quien los corre. | ✅ (2, 6) |
| 5.2 | **Un solo proceso por token.** Dos pollers se reparten los mensajes y Telegram responde 409. | `arrancar()` no levanta un segundo bot en el mismo proceso; `run.bat` usa un solo worker. En desarrollo, un bot por integrante. Ante un 409 se registra un aviso claro. | ✅ (4, 6) |
| 5.3 | **No se procesan mensajes viejos.** Telegram guarda unas 24 h los mensajes recibidos con la API apagada; procesarlos de golpe respondería a sesiones y códigos ya vencidos. | Al arrancar se descartan los pendientes y se llama a `deleteWebhook`. | ✅ (4) |
| 5.4 | **Un fallo no deja al cliente sin respuesta ni tumba la API.** | `ChatNoDisponible` → mensaje amable. Error de red con Telegram → reintento con espera, sin propagar. | ✅ (3, 4) |

## Riesgos aceptados

- **Los mensajes pasan por los servidores de Telegram** y quedan en el historial del
  cliente (salvo el código, que se borra). Aceptable con datos ficticios; con datos
  reales habría que evaluarlo.
- **Sesión en memoria:** reiniciar la API cierra todas las sesiones. Es lo esperado.
- **Límite en memoria:** con varios procesos no se compartiría; hoy hay uno solo (5.2).
- **Quien levanta el bot paga los tokens** de quien converse con él. La lista de
  usuarios permitidos (3.2) lo acota en pruebas.

## Cómo se prueba

- **Automático** (`pytest -q`, sin red ni token): cada regla ⏳ tiene su test al
  implementarse, con la API de Telegram simulada (`httpx.MockTransport`).
- **Manual** (Telegram real): la lista de la sección "Prueba manual" de
  [`PENDIENTES_telegram.md`](../PENDIENTES_telegram.md), que incluye grupo, foto,
  código erróneo y sesión vencida.
