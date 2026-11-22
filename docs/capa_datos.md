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
- **Facturas múltiples (sección 4):** si una suma incluiría una factura de un
  periodo con más de una vigente, esa suma es `None` y el periodo va en
  `periodos_multiples`. Se decide por suma: en el cliente 1, `saldo_total`
  es `None` (incluye el duplicado de 2026-11), pero `saldo_vencido` es 0
  porque los duplicados aún no vencen. Las facturas se listan igual, con su
  estado, importe y vencimiento, que es lo que CS-11 pide informar.
- **Uso en el agente:** CS-11 (saldo y factura vencida). Con `saldo_total`
  en `None`, informar factura por factura y no dar un saldo total.

### `resumen_facturacion(cliente_id, fecha_desde, fecha_hasta) -> ResumenFacturacion`

Totales por periodo en un rango de fechas de emisión (ambas obligatorias,
inclusive). Excluye facturas anuladas.

- **Tablas:** `factura`.
- **Devuelve:** lista `periodos` (`periodo`, `cantidad_facturas`,
  `facturas_multiples`, `subtotal`, `igv`, `total`), los totales del rango y
  `periodos_multiples`.
- **Facturas múltiples (sección 4):** el periodo marcado lleva sus importes en
  `None` y, si hay alguno en el rango, también los totales del rango.
  `cantidad_facturas` sí se informa. Se cuentan todas las vigentes del
  periodo, aunque alguna se haya emitido fuera del rango.
- **Errores:** `ValueError` si falta una fecha o `fecha_desde > fecha_hasta`.
- **Uso en el agente:** ver la evolución de varios meses. Para explicar una
  subida concreta (CS-09) usar `comparar_periodos`.

### `obtener_servicios(cliente_id, estado=None) -> ListaServicios`

Servicios contratados del cliente, incluidos los dados de baja.

- **Tablas:** `servicio_contratado`, `producto`.
- **Filtro:** `estado` ∈ `activo`, `baja` (por defecto, todos: CS-02 necesita
  la fecha de baja).
- **Devuelve:** `fecha_corte` y por servicio: `producto`, `unidad`, `sede`,
  `cantidad`, `tarifa_pactada` (por unidad y mes, sin IGV), `sla_pactado`
  (fracción: 0.997 = 99,7 %; `None` en móviles), `gb_incluidos_por_linea` y
  `precio_gb_exceso` (solo móviles), `fecha_activacion`, `fecha_baja` y `estado`.
- **No expone la tarifa de lista** del producto: en CS-03 la referencia es
  la del contrato (cliente 3: pactada 10 500, lista 12 000), y mostrar ambas
  invitaría a dar por buena la facturada.
- **Errores:** `ValueError` por estado o `cliente_id` inválidos.
- **Uso en el agente:** CS-02 (fecha de baja), CS-03 (tarifa pactada), CS-05 y
  CS-07 (SLA), CS-04 (GB incluidos y precio por GB), CS-09 y CS-10 (alta).
  `comparar_periodos` usa la misma consulta para el `servicio` de cada línea.

### `comparar_periodos(cliente_id, periodo_b, periodo_a=None) -> ComparacionPeriodos`

Qué cambió entre dos periodos facturados (`AAAA-MM`). Si falta `periodo_a`, se
usa el mes anterior a `periodo_b`. Excluye facturas anuladas.

- **Tablas:** `factura`, `factura_linea`, `servicio_contratado`, `producto`.
- **Devuelve:** cada periodo con sus facturas y totales; `variacion_subtotal`
  y `variacion_pct` (sin IGV); `variacion_fuerte` si supera
  `UMBRAL_VARIACION_PCT` (25 %, el de `v_variacion_facturacion`); `lineas`
  (solo las que cambiaron) y `lineas_sin_cambio`.
- **Cada línea comparada:** `cambio` (`nueva`, `eliminada`, `cambiada`),
  `antes` y `despues`, `campos_cambiados`, `diferencia_monto` y el `servicio`
  (sede, producto, `fecha_activacion`, `fecha_baja`), que explica la causa.
- **Emparejamiento:** por servicio y clase de cargo. `cargo_mensual` y
  `prorrateo` son la misma clase, así un servicio que pasa de prorrateo a mes
  completo sale como `cambiada` (cliente 9, CS-10); `exceso` y `ajuste` van
  aparte, así un exceso nuevo sale como `nueva` (cliente 4, CS-04).
- **Sin comparación** (`comparable = false`, variación y líneas en `None`):
  `motivo = "facturas_multiples"` si algún periodo tiene más de una factura
  vigente (regla de la sección 4, CS-01) o `"periodo_sin_facturas"`.
- **Errores:** `ValueError` si un periodo está mal formado o
  `periodo_a >= periodo_b`.
- **Uso en el agente:** CS-09; también da señales de CS-04 y CS-10.
- **Limitación:** solo compara lo que cambió entre dos facturas. Un cargo que
  se repite igual cada mes (por ejemplo, el servicio dado de baja de CS-02)
  sale como "sin cambio"; eso lo detectará `detectar_anomalias`.

### `detectar_anomalias(cliente_id) -> AnomaliasCliente`

Anomalías de facturación y SLA del cliente, a partir de las vistas de
detección de `db/schema.sql` (filtradas siempre por `cliente_id`).

| Grupo | Casuística | Vista | Qué trae además |
|---|---|---|---|
| `facturas_duplicadas` | CS-01 | `v_facturas_duplicadas` | Las facturas iguales con número e importes |
| `servicios_baja_facturados` | CS-02 | `v_servicios_baja_facturados` | El servicio (fecha de baja) y un cobro por periodo posterior a la baja |
| `tarifas_distintas` | CS-03 | `v_tarifa_distinta` | Tarifa pactada y, por periodo, la facturada y la cantidad |
| `excesos_sin_sustento` | CS-04 | `v_exceso_sin_sustento` | GB facturados, precio por GB y consumo registrado (incluidos, usados, exceso) |
| `averias_sla_incumplido` | CS-05, CS-07 | `v_averias_sin_compensar` | Fechas de la caída, horas, tolerancia y horas fuera de SLA |

- **Montos:** `monto_observado`, sin IGV. El nombre es neutro a propósito:
  las vistas lo llaman `monto_a_acreditar`, y el PDF prohíbe prometer una
  devolución (CS-01, CS-02). No es un ajuste aprobado.
- **Agrupado por servicio:** CS-02 y CS-03 traen un cobro por periodo y el
  total ya sumado (24 000 y 13 500), para que el agente no sume a mano.
- **CS-01:** `monto_observado` es el importe de las facturas de más
  (subtotal × (n − 1)), sin decir cuál vale.
- **CS-05 frente a CS-07:** la distinción es por monto y tramo, que decide
  `calcular_ajuste` (pendiente); aquí ambas son `averias_sla_incumplido`.
- **No expone la causa técnica** de la avería (`averia.causa`): el PDF prohíbe
  comunicarla.
- **Ya resuelto:** excluye facturas anuladas y averías con un ajuste
  propuesto, aprobado o aplicado. Las demás vistas **no** miran ajustes ni
  casos: cuando exista "registrar caso", una anomalía ya registrada seguirá
  apareciendo (ver `PENDIENTES_datos.md`).
- **Datos sembrados:** clientes 1 a 6, una anomalía cada uno; los controles
  (25, 30 y los duplicados anulados de 15, 24 y 38) no aparecen.
- **Uso en el agente:** paso 3 del método del PDF ("busca anomalías").

### `consultar_solicitudes(cliente_id, estado=None) -> ListaSolicitudes`

Solicitudes del cliente con su antigüedad y si están fuera de plazo.

- **Tablas:** `solicitud`, `personal`, `cliente`, `parametro`.
- **Filtro:** `estado` ∈ `abierta`, `en_proceso`, `cerrada` (por defecto, todas),
  de la más reciente a la más antigua.
- **Devuelve:** `fecha_corte`, `plazo_atencion_dias` (el del cliente, 10 en la
  base), `cantidad_fuera_de_plazo` y por solicitud: `tipo`, `descripcion`,
  `estado`, fechas, `dias_transcurridos`, `fuera_de_plazo` y
  `responsable_nombre`.
- **Días:** misma fórmula que `v_solicitudes_vencidas` (días enteros desde
  `fecha_registro` hasta la fecha de corte ficticia). En las cerradas se
  cuentan hasta `fecha_cierre`, y nunca están fuera de plazo.
- **No da fecha de resolución:** la base no la tiene y el PDF prohíbe
  prometerla.
- **Uso en el agente:** CS-06 (ejemplo: cliente 10, abierta el 2026-11-14,
  21 días con plazo de 10). Avisar al responsable es escritura y queda para
  "registrar y derivar caso".

## 3. Casuísticas y funciones

| Casuística | Función principal | Comentario |
|---|---|---|
| CS-01 Factura duplicada | `detectar_anomalias`, `listar_facturas` | Saldo, resumen y comparación marcan el periodo en `periodos_multiples` / `facturas_multiples` sin sumar. |
| CS-02 a CS-05, CS-07 | `detectar_anomalias`, `obtener_servicios`, `detalle_factura` | Detección y monto observado. El tramo y el aprobador (`calcular_ajuste`) están pendientes. |
| CS-06 Solicitud fuera de plazo | `consultar_solicitudes` | Días y plazo; avisar al responsable queda pendiente (escritura). |
| CS-08 Gesto comercial | — | Pendiente (`v_gestos_mes_actual`). |
| CS-09 Variación de facturación | `comparar_periodos` | Líneas que cambiaron y su servicio (alta o baja). |
| CS-10 Prorrateo | `detalle_factura`, `comparar_periodos` | Línea de tipo `prorrateo`; la fecha de activación viene en el `servicio` de la comparación. |
| CS-11 Saldo y vencida | `saldo_pendiente` | |
| CS-12 Identificación | — | Fuera de esta capa. |
| CS-13 Fuera de alcance | `obtener_cliente` | Datos del ejecutivo para derivar. |

## 4. Particularidades de los datos

- **Un periodo puede tener más de una factura vigente** (duplicado de CS-01:
  cliente 1, 2026-11). Regla para toda función que agregue por periodo: **no
  sumarlas ni elegir una**; devolver un aviso con los números e importes y
  dejar sin calcular lo que dependa del total. Sumarlas presentaría el
  duplicado como una subida explicable (CS-09) y daría por válidas las dos
  facturas, que es lo que CS-01 prohíbe afirmar. La cumplen
  `comparar_periodos`, `saldo_pendiente` y `resumen_facturacion`, con la misma
  detección (`_facturas_vigentes` en `facturacion.py`): los importes que
  dependerían del duplicado van en `None`, nunca en 0.
- No hay tabla de pagos: el saldo se deduce del `estado` de la factura.
- Montos en `REAL`: se redondean a 2 decimales en los totales.
- Los comentarios CS-xx de `schema.sql` usan una numeración distinta a la de
  `Anticipa_Casuisticas.docx`; este documento sigue la del `.docx`.
- `anticipa.db` no se versiona: se genera con
  `python -X utf8 db/generar_datos.py`, que **borra y recrea** el archivo
  y produce siempre los mismos datos. Las pruebas asumen esos datos.
