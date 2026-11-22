# Pendientes: autenticación OTP y API

Estado al último push: `feature/servicio-correo` @ `57753c4`, ya integrado en `develop` (PR #3, `ad61f31`).
En pausa mientras se integra la base de datos de `/new`.

**Al terminar estos pasos, seguir con [`PENDIENTES_datos.md`](PENDIENTES_datos.md)** (comparación entre periodos, CS-09).

## Decisiones tomadas (configuración en `.env`, ver `.env.example`)
- `AUTH_SECRET`: un solo secreto para firmar el JWT y como clave del HMAC del OTP. Cambiarlo invalida sesiones y códigos pendientes.
- `AUTH_MINUTOS_SESION=30`: sin logout ni revocación por ahora.
- `ENTORNO=dev`: el CRUD genérico `/api/...` solo se monta en desarrollo.
- `AUTH_MAX_SOLICITUDES_POR_IP=5` en `AUTH_VENTANA_SOLICITUDES_SEG=900`: límite por IP de `/auth/solicitar-codigo`.
- Ya están leídas en `app/config.py`; falta usarlas en el código (pasos siguientes).

## Orden de trabajo
1. Hash del OTP → HMAC (incluye la semilla de `db/generar_datos.py`).
2. Token JWT + dependencia `cliente_actual` y sus tests.
3. ~~Propiedad del cliente~~ → hecho con la opción B: API `/mi/...` sin `cliente_id` en la URL; `/api/...` queda como CRUD de desarrollo.
4. CRUD `/api/...` solo en `ENTORNO=dev` (incluye los PATCH del personal y `clientes/por-ruc`) + limpieza (`VerificacionCRUD`, aviso de `httpx`).
5. Límite de peticiones por IP en `/auth/solicitar-codigo`.

## Seguridad (prioridad alta)
- [x] **Token de sesión** (hecho: `app/auth/sesion.py`, `GET /auth/sesion`, `tests/test_sesion.py`; el caso "otro cliente → 403" queda para el ítem de propiedad): `POST /auth/verificar-codigo` devuelve `cliente_id` pero no emite token, así que nada vincula las siguientes peticiones con el cliente verificado. Diseño propuesto:
  - Al verificar, devolver un JWT firmado (HS256, `PyJWT`) con `sub=cliente_id` y expiración corta. Secreto en `.env` (`AUTH_SECRET`).
  - Dependencia FastAPI `cliente_actual`: lee `Authorization: Bearer <token>` y devuelve el `cliente_id`; 401 si falta, es inválido o expiró.
  - El agente del chatbot recibe `cliente_id` de la sesión, nunca del mensaje del usuario.
  - Tests: sin token → 401, expirado → 401, otro cliente → 403, token válido → solo sus datos.
  - Por decidir: duración de la sesión (30–60 min) y si hace falta revocar (logout). Un JWT no se puede anular antes de expirar; para eso habría que guardar el token en la base.
- [x] **Propiedad del cliente** (hecho, opción B: `app/api/cliente.py` expone `/mi/perfil`, `/mi/facturas`, `/mi/facturas/{numero}`, `/mi/saldo`, `/mi/resumen` con el cliente tomado solo del token; factura ajena = 404; `tests/test_api_cliente.py`. Las rutas `/api/clientes/{cliente_id}/...` no se protegen: se ocultan fuera de dev en el paso 4). Problema original: las rutas con datos de cliente toman `cliente_id` del token; si la URL trae `{cliente_id}` y no coincide → 403. Hoy cualquiera puede pedir datos de cualquier cliente cambiando el número en la URL.
- [x] **CRUD `/api/...` sin autenticación** (hecho: todas las rutas `/api` cuelgan de un router que solo se monta con `ENTORNO=dev`; sin definir = `prod`; `tests/test_entorno.py`). Problema original: clientes, facturas, casos, etc. se leen y modifican sin login. Decidir: solo local (`--host 127.0.0.1`, o desactivarlo fuera de desarrollo) o protegerlo con token y roles.
- [x] **Hash del OTP** (hecho: `hash_codigo` en `app/auth/otp.py`, secreto en `app/auth/secreto.py`, semilla regenerada): SHA-256 sin sal de 6 dígitos se revierte por fuerza bruta. Cambiar a HMAC con un secreto del `.env` (`app/auth/otp.py:22`). La semilla `db/generar_datos.py:483` también usa SHA-256: debe usar la misma función.
- [x] **Rutas sin `cliente_id` en la URL** (resuelto por diseño: `/mi` no recibe IDs de cliente; las de `/api` se ocultan en el paso 4) (`/api/facturas/{id}/lineas`, `/api/servicios/{id}/...`, `/api/casos/{id}/...`, PATCH de solicitudes/casos/ajustes): la propiedad requiere buscar el dueño del recurso antes de responder.
- [x] **Límite por IP en `/auth/solicitar-codigo` (paso 5)** (hecho: `app/auth/limite.py`, ventana deslizante en memoria, 429 + `Retry-After`, cuenta también peticiones mal formadas; `tests/test_limite_ip.py`). Problema original: hoy solo hay espera de reenvío por cliente (60 s) y 3 intentos por código, o sea ~3 códigos probados por minuto y por RUC, sin tope por IP (también permite enumerar RUCs o hacer spam de correos). Contador en memoria por IP con `AUTH_MAX_SOLICITUDES_POR_IP` / `AUTH_VENTANA_SOLICITUDES_SEG` → 429. En memoria basta para un solo proceso de uvicorn; con varios workers habría que guardarlo en la base.

## Limpieza
- [x] (hecho: eliminada, con un comentario para no volver a agregarla) `VerificacionCRUD` sigue en `anticipa_crud_por_entidad.py` aunque ya no se expone. Eliminarla o marcarla como interna para que nadie la vuelva a registrar.
- [ ] Rama local `develop` desactualizada (`9555558` vs `origin/develop` `ad61f31`): `git pull` antes de crear ramas nuevas.
- [ ] Aviso de pytest: `starlette.testclient` pide `httpx2` en vez de `httpx`. **Pendiente de decisión:** instalar `httpx2` fue bloqueado por permisos en la sesión; revisar el paquete antes de cambiar `requirements.txt` (alternativa: filtrar el aviso en la configuración de pytest).

## Al integrar la base de `/new` (revisar que no rompa lo anterior)
- [ ] **Columnas y vistas:** `anticipa_crud_por_entidad.py` pide validar nombres de columnas y vistas contra el DDL real. Revisarlo con la base nueva.
- [ ] **Tabla `verificacion`:** debe mantener `id_cliente`, `ruc_ingresado`, `codigo_hash`, `fecha_envio`, `fecha_expira`, `intentos`, `estado`; si no, `app/auth/otp.py` falla.
- [ ] **Datos fijos en tests:** los tests usan el cliente 1 (`Minera Cordillera Azul S.A.C.`) y su RUC. Ajustarlos si cambian.
- [ ] **Correos reales:** el README de `/new` indica usar `anticipa_publico.db` (o `generar_datos.py --publico`) antes de subir a GitHub. No versionar la base con correos reales.
- [ ] **Correr `pytest -q`** con la base nueva: 53 pruebas pasaban al último push.

## Para el agente (cuando se implemente `app/tools`)
- [ ] Las herramientas reciben el `cliente_id` ya fijado desde la sesión (closure o contexto), nunca como argumento que el modelo pueda elegir. Mismo principio que `/mi`.
- [ ] Decidir si un cliente con `estado` inactivo/baja puede iniciar sesión y ver `/mi` (hoy sí).

## Observaciones nuevas (detectadas en el paso 5)
- [x] **Enumeración por la espera de reenvío** (hecho: el reenvío prematuro responde 200 con un id nuevo que continúa la verificación pendiente; sin `AUTH_SECRET` ambos casos dan 503). Problema original: pedir dos veces el mismo RUC en menos de `OTP_ESPERA_REENVIO_SEG` da 429 si el RUC existe y 200 si no existe, así que revela quién es cliente (el límite por IP lo frena a 5 pruebas cada 15 min). Opción: responder 200 con el mismo mensaje también en el reenvío prematuro, sin enviar correo.
- [ ] **Proxy:** si la API se publica detrás de un proxy, el límite verá la IP del proxy. Configurar `--forwarded-allow-ips` en uvicorn para la IP del proxy, no leer `X-Forwarded-For` a ciegas.
- [ ] **Enumeración por tiempo de respuesta:** el primer pedido de un RUC existente espera al servidor SMTP (segundos) y uno inexistente responde al instante. Opción: enviar el correo en segundo plano (`BackgroundTasks` de FastAPI) para que ambas respuestas tarden lo mismo. Ojo: hoy, si el envío falla, la transacción se revierte y se responde 503; en segundo plano habría que registrar el fallo de otra forma.
