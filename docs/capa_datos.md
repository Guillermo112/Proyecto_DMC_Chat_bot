# Capa de datos (`app/data`)

Documentación de las funciones de acceso a `anticipa.db` que usará el
chatbot (y, más adelante, las herramientas de LangChain en `app/tools`).

## 1. Reglas de seguridad

| Regla | Cómo se cumple |
|---|---|
| Solo lectura por defecto | `get_connection()` abre `file:<ruta>?mode=ro` con `uri=True`. Cualquier `INSERT/UPDATE/DELETE` lanza `sqlite3.OperationalError`. Solo `app/auth` y el `_run` del CRUD (`anticipa_crud_por_entidad.py`) piden `escritura=True` (`mode=rw`). |
| Consultas parametrizadas | Todo valor externo va como parámetro `?`. Los f-strings solo insertan fragmentos SQL fijos definidos en el código (lista de columnas, condiciones de filtro, marcadores `?`). |
| Un cliente por consulta | Toda función recibe `cliente_id` y lo aplica en el `WHERE`. Las líneas de factura y los ajustes, que no tienen `id_cliente`, se filtran con un JOIN a `factura`. |
| Entradas validadas | `cliente_id` debe ser `int` positivo; `estado` debe estar en la lista permitida; las fechas deben ser `datetime.date`. Si no, `ValueError`. |
| Paginación con tope | `limite` se recorta al rango `1..LIMITE_MAXIMO` (100 por defecto). |

La identificación del cliente (RUC + código, ver casuística CS-12) **no** es
parte de esta capa: quien llama debe pasar un `cliente_id` ya verificado.

## 2. Funciones

Todas aceptan además `db_path` opcional (útil para pruebas); por defecto usan
`ANTICIPA_DB_PATH`.

### `obtener_cliente(cliente_id) -> Cliente | None`

Datos del cliente y de su ejecutivo de cuenta.

- **Tablas:** `cliente` JOIN `personal`.
- **Devuelve:** `id_cliente`, `ruc`, `razon_social`, `sector`, `segmento`,
  `correo_facturacion`, `contacto_nombre`, `estado`, `ejecutivo_nombre`,
  `ejecutivo_correo`. `None` si no existe.
- **Uso en el agente:** saludar al cliente y derivar al ejecutivo
  (CS-06, CS-11, CS-13).

### `listar_facturas(cliente_id, fecha_desde=None, fecha_hasta=None, estado=None, limite=None, offset=0, *, periodo=None) -> PaginaFacturas`

Facturas del cliente, de la más reciente a la más antigua.

- **Tablas:** `factura`.
- **Filtros:** `periodo` (`AAAA-MM`, mes facturado; solo por nombre);
  `fecha_desde` / `fecha_hasta` sobre `fecha_emision` (inclusive);
  `estado` ∈ `emitida`, `pagada`, `vencida`, `en_disputa`, `anulada`.
  Se combinan con AND.
- **Paginación:** `limite` (por defecto 20, máximo 100) y `offset`.
- **Devuelve:** `items` (cabeceras), `total` (filas que cumplen el filtro),
  `limite` aplicado y `offset`.
- **Errores:** `ValueError` por estado, periodo o `cliente_id` inválidos.
- **Nota:** la facturación es mes vencido; la factura del periodo `2026-10`
  se emite el `2026-11-01`. Para "la factura de octubre" usar
  `periodo="2026-10"`, no un rango de emisión. Un periodo puede tener más de
  una factura vigente (duplicado de CS-01).

### `detalle_factura(cliente_id, numero) -> FacturaDetalle | None`

Cabecera y líneas de una factura identificada por su número (`F001-000123`).
El número se normaliza (espacios y mayúsculas).

- **Tablas:** `factura`, `factura_linea`.
- **Devuelve:** la cabecera más `lineas` (`tipo`, `concepto`, `cantidad`,
  `precio_unitario`, `monto`). `None` si la factura no existe **o pertenece
  a otro cliente** (no se distingue, para no revelar números ajenos).
- **Uso en el agente:** explicar cargos (CS-03, CS-04, CS-09, CS-10).

### `saldo_pendiente(cliente_id) -> SaldoPendiente`

Lo que el cliente tiene por pagar.

- **Tablas:** `factura`, `ajuste`, `parametro`.
- **Cálculo:** suma de `total` (con IGV) de las facturas en estado
  `emitida`, `vencida` o `en_disputa`.
  `saldo_vencido` = las que están en estado `vencida` o cuyo
  `fecha_vencimiento` es anterior a la fecha de corte.
- **Fecha de corte:** `parametro.fecha_actual` (2026-12-05, ficticia), no la
  fecha real del sistema.
- **Notas de crédito:** se listan en `notas_credito_aplicadas` pero **no se
  restan**, porque la base no las refleja en la factura (decisión de diseño).
- **Uso en el agente:** CS-11 (saldo y factura vencida).

### `resumen_facturacion(cliente_id, fecha_desde, fecha_hasta) -> ResumenFacturacion`

Totales por periodo en un rango de fechas de emisión (ambas obligatorias,
inclusive). Excluye facturas anuladas.

- **Tablas:** `factura`.
- **Devuelve:** lista `periodos` (`periodo`, `cantidad_facturas`,
  `subtotal`, `igv`, `total`) y los totales del rango.
- **Errores:** `ValueError` si falta una fecha o `fecha_desde > fecha_hasta`.
- **Uso en el agente:** CS-09 (variación fuerte entre periodos).

## 3. Casuísticas y funciones

| Casuística | Función principal | Comentario |
|---|---|---|
| CS-01 Factura duplicada | `listar_facturas`, `detalle_factura` | El saldo del cliente 1 suma ambas facturas. La detección está en `v_facturas_duplicadas` (aún sin función). |
| CS-02 a CS-05, CS-07 | `detalle_factura` | El cálculo de ajustes usa las vistas de detección; pendiente. |
| CS-06 Solicitud fuera de plazo | — | Pendiente (`solicitud`, `v_solicitudes_vencidas`). |
| CS-08 Gesto comercial | — | Pendiente (`v_gestos_mes_actual`). |
| CS-09 Variación de facturación | `resumen_facturacion` | |
| CS-10 Prorrateo | `detalle_factura` | Línea de tipo `prorrateo`. |
| CS-11 Saldo y vencida | `saldo_pendiente` | |
| CS-12 Identificación | — | Fuera de esta capa. |
| CS-13 Fuera de alcance | `obtener_cliente` | Datos del ejecutivo para derivar. |

## 4. Particularidades de los datos

- No hay tabla de pagos: el saldo se deduce del `estado` de la factura.
- Montos en `REAL`: se redondean a 2 decimales en los totales.
- Los comentarios CS-xx de `schema.sql` usan una numeración distinta a la de
  `Anticipa_Casuisticas.docx`; este documento sigue la del `.docx`.
- `anticipa.db` no se versiona: se genera con
  `python -X utf8 db/generar_datos.py`, que **borra y recrea** el archivo
  y produce siempre los mismos datos. Las pruebas asumen esos datos.
