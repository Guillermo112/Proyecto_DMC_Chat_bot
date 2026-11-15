# Chatbot de facturación (AnticIpA)

Backend en Python + FastAPI sobre la base SQLite de `db/anticipa.db`
(datos ficticios). Miniproyecto de certificación; más adelante se integrará
LangChain usando las funciones de `app/data` como herramientas.

## Estructura

```
app/
  main.py      # FastAPI (por ahora solo /health)
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
reproducible desde `db/schema.sql` con datos fijos.

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

`GET http://127.0.0.1:8000/health` → `{"status": "ok", "db": "ok"}`

```bash
pytest -q
```

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
