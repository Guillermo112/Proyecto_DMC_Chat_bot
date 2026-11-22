# Chatbot de facturación (AnticIpA)

Backend en Python + FastAPI sobre la base SQLite de `db/anticipa.db`
(datos ficticios). Miniproyecto de certificación; más adelante se integrará
LangChain usando las funciones de `app/data` como herramientas.

## Estructura

```
app/
  main.py      # FastAPI: /health, /auth, /mi y CRUD de desarrollo (/api/...)
  api/         # rutas del cliente autenticado (/mi/...)
  config.py    # settings desde variables de entorno
  data/        # acceso a SQLite (solo lectura, filtrado por cliente)
  schemas/     # modelos Pydantic
  tools/       # herramientas del agente (pendiente)
tests/         # pytest
db/            # schema.sql, generar_datos.py y la base generada (anticipa.db)
docs/          # casuísticas y documentación de la capa de datos
```

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

## Generar la base de datos

`anticipa.db` no se versiona (está en `.gitignore`): se genera de forma
reproducible desde `db/schema.sql` con datos fijos. Antes define `AUTH_SECRET`
en `.env` (ver `.env.example`): los códigos OTP de prueba se guardan con ese HMAC.

```bash
python -X utf8 db/generar_datos.py
```

Crea `db/anticipa.db` (y `db/casos_datos.json`) y termina con 17
validaciones `OK`. **Borra la base existente** antes de recrearla.
`-X utf8` evita un `UnicodeEncodeError` en consolas Windows al imprimir las
validaciones.

## Variables de entorno

Se leen de un archivo `.env` en la raíz del proyecto (opcional; no se
versiona). Parte de la plantilla:

```bash
copy .env.example .env        # Linux/macOS: cp .env.example .env
```

Si una variable también está definida en el sistema, gana la del sistema.

| Variable | Por defecto | Uso |
|---|---|---|
| `ANTICIPA_DB_PATH` | `db/anticipa.db` | Ruta de la base (relativa a la raíz o absoluta) |
| `LIMITE_POR_DEFECTO` | `20` | Tamaño de página de `listar_facturas` |
| `LIMITE_MAXIMO` | `100` | Tope de página; valores mayores se recortan |

## Ejecutar

```bash
uvicorn app.main:app --reload
```

`GET http://127.0.0.1:8000/health` → `{"status": "OK", "db": "OK"}`

```bash
pytest -q
```

## Identificación por OTP (`app/auth`)

`solicitar_codigo(ruc)` envía un código de 6 dígitos **solo** al correo
registrado del cliente (vence en 10 min, se espera 60 s entre envíos) y
devuelve `(id_verificacion, correo_enmascarado)`; `verificar_codigo(id, codigo)`
devuelve el `cliente_id` o `None` (3 intentos fallidos = bloqueado). Solo se
guarda HMAC-SHA256(`AUTH_SECRET`, código) en `verificacion`; sin `AUTH_SECRET`
(mínimo 32 caracteres) no se envían códigos (503). Cambiarlo invalida los pendientes.

Por HTTP (`app/auth/rutas.py`):

- `POST /auth/solicitar-codigo` `{"ruc": "..."}` → `{"id_verificacion", "mensaje"}`.
  La respuesta es la misma exista o no el RUC. 422 si el RUC no tiene 11 dígitos,
  429 si se pide otro código antes de tiempo, 503 si falla el correo.
- `POST /auth/verificar-codigo` `{"id_verificacion", "codigo"}` →
  `{"verificado": true, "cliente_id", "access_token", "token_type": "bearer", "expira_en"}`
  o 401. `access_token` es un JWT (HS256, firmado con `AUTH_SECRET`) que vence en
  `AUTH_MINUTOS_SESION` minutos (30 por defecto). No hay logout: un token no se puede
  anular antes de vencer, salvo cambiando `AUTH_SECRET` (cierra todas las sesiones).
- `GET /auth/sesion` con `Authorization: Bearer <access_token>` → `{"cliente_id"}`,
  o 401 si falta, es inválido o expiró.

En el código, las rutas con datos de cliente toman el cliente de la sesión con
`cliente_id: int = Depends(cliente_actual)` (`app/auth/sesion.py`), nunca de lo que
escriba el usuario.

### API del cliente autenticado (`/mi/...`)

Todas exigen `Authorization: Bearer <access_token>` (401 si falta o venció). El
cliente sale **solo** del token: ninguna ruta recibe `cliente_id`, así que no se
pueden pedir datos de otro cliente (`app/api/cliente.py`, sobre `app/data/facturacion.py`).

| Ruta | Devuelve |
|---|---|
| `GET /mi/perfil` | Datos del cliente y su ejecutivo |
| `GET /mi/facturas?fecha_desde&fecha_hasta&estado&limite&offset` | Facturas propias paginadas |
| `GET /mi/facturas/{numero}` | Cabecera y líneas; 404 si no existe **o es de otro cliente** |
| `GET /mi/saldo` | Saldo pendiente y notas de crédito aplicadas |
| `GET /mi/resumen?fecha_desde&fecha_hasta` | Totales por periodo (excluye anuladas) |

Las rutas `/api/...` son el CRUD de desarrollo para Postman: no usan token y no
deben exponerse fuera de localhost.

La tabla `verificacion` no está en el CRUD de `/api/...`: solo se toca vía `/auth`.

Prueba en vivo:

1. En `.env`: `AUTH_SECRET`, `SMTP_*` (con Gmail, una
   [contraseña de aplicación](https://myaccount.google.com/apppasswords)) y tu correo
   en tu slot `CORREO_PRUEBA_1`..`CORREO_PRUEBA_5`. Clientes por slot: 1 → 1, 6, 11;
   2 → 2, 7, 12; 3 → 3, 8, 13; 4 → 4, 9; 5 → 5, 10.
2. Regenera la base: `python -X utf8 db/generar_datos.py`.
3. `python -X utf8 -m scripts.demo_otp` e ingresa un RUC de esos clientes, p. ej.
   `99813998698` (cliente 1, slot 1) o `99309114170` (cliente 2, slot 2).

## Capa de datos (`app/data`)

Todas las funciones reciben `cliente_id` y lo aplican en el `WHERE`; ninguna
devuelve datos de otro cliente. La conexión se abre con `mode=ro` y todas las
consultas son parametrizadas.

| Función | Descripción |
|---|---|
| `obtener_cliente(cliente_id)` | Datos del cliente y su ejecutivo, o `None` |
| `listar_facturas(cliente_id, fecha_desde, fecha_hasta, estado, limite, offset)` | Filtra por fecha de emisión y estado; paginado con tope |
| `detalle_factura(cliente_id, numero)` | Cabecera + líneas; `None` si la factura es de otro cliente |
| `saldo_pendiente(cliente_id)` | Suma de facturas emitidas/vencidas/en disputa |
| `resumen_facturacion(cliente_id, fecha_desde, fecha_hasta)` | Totales por periodo (excluye anuladas) |

### Notas sobre los datos

- La fecha de sistema es ficticia (`parametro.fecha_actual` = 2026-12-05); el
  saldo vencido se calcula contra ella, no contra la fecha real.
- No hay tabla de pagos: el saldo se deriva del estado de la factura.
- Las notas de crédito aplicadas no modifican la factura; `saldo_pendiente`
  no las resta y las informa aparte en `notas_credito_aplicadas`.
- La factura duplicada F001-000254/255 (casuística CS-01) está a propósito
  en la base y suma dos veces en el saldo del cliente 1.
- Detalle de cada función y su relación con las casuísticas:
  [docs/capa_datos.md](docs/capa_datos.md).
