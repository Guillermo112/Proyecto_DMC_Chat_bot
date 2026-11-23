# Pendientes: capa de datos y API del cliente

## Estado al cierre (2026-11-22): capa de datos del modo A completa

Estado al último push: `feat/use-case-coverage` @ `78b7ff9`.
- Integrado en `develop` (Guillermo112/Proyecto_DMC_Chat_bot#6, merge `b312a61`):
  filtro por periodo, comparación (CS-09), saldo y resumen sin sumar
  duplicados, servicios, anomalías, solicitudes y guía de casuísticas.
- **PR nuevo, pendiente de revisión** (base `develop`, 2 commits): canal `web`
  en `caso.canal` (`c56a0ca`) y registrar y derivar caso (`78b7ff9`). Al
  fusionarlo, cada integrante debe regenerar la base y puede definir
  `NOTIFICAR_DERIVACIONES` y `CORREO_DERIVACIONES` en su `.env`.
- 318 tests en verde. La API `/mi` cubre la lectura y el registro del modo A;
  el modo B queda fuera de alcance (sección 4).
- Referencias: `docs/capa_datos.md` (funciones y reglas) y
  `docs/casuisticas_api.md` (qué llamar según lo que pide el cliente).

**Única tarea abierta de esta etapa:** el consumo del exceso **con** sustento
(CS-04, sección 3). No bloquea lo siguiente.

**Siguiente etapa: [`PENDIENTES_rag.md`](PENDIENTES_rag.md)** (agente, herramientas y RAG).

---

Empezar **después de terminar `PENDIENTES_auth.md`** (pasos 4 y 5). Se trabaja sobre
la API `/mi/...` (`app/api/cliente.py`) y `app/data/facturacion.py`. El cliente
sale siempre del token (`Depends(cliente_actual)`), nunca de un parámetro.

## 1. Comparar facturación entre dos periodos (CS-09)

### Por qué
La pregunta típica es "¿por qué subió mi factura de octubre?". La respuesta útil no
es "subió 33 %", sino **qué líneas cambiaron**. Hoy:
- `/mi/facturas` filtra por **fecha de emisión**, no por periodo. El periodo N se
  emite el día 1 del mes N+1 (el de septiembre sale el 1 de octubre), así que pedir
  "la factura de septiembre" por fecha confunde.
- `/mi/resumen` da los totales por periodo, pero no explica la diferencia.
- Explicarla requiere 4 llamadas (listar y detallar cada mes) y que el modelo de lenguaje
  compare los números, que es donde más fácil se equivoca.

### Ejemplo real (base actual): cliente 7, 2026-09 frente a 2026-10

| Concepto | 2026-09 (`F001-000159`) | 2026-10 (`F001-000210`) |
|---|---|---|
| Internet dedicado 500 Mbps Lima | 4 × 4 500 = 18 000 | 18 000 |
| Enlace MPLS Lima | 3 × 12 000 = 36 000 | 36 000 |
| **Enlace MPLS Callao** | — | **2 × 12 000 = 24 000** |
| Troncal SIP Lima | 12 800 | 12 800 |
| Móvil corporativo Lima | 6 400 | 6 400 |
| **Subtotal** | **73 200** | **97 200 (+32,8 %)** |

`v_variacion_facturacion` (`db/schema.sql`) ya lo detecta con `LAG` sobre el
subtotal y un umbral de 25 %.

### Tareas
- [x] **Filtro `periodo`** (`AAAA-MM`, validado) en `listar_facturas` y en
      `GET /mi/facturas`, además de las fechas de emisión. Validación en
      `_validar_periodo()` de `app/data/facturacion.py`, para reutilizar.
- [x] **`comparar_periodos(cliente_id, periodo_b, periodo_a=None)`** en
      `app/data/facturacion.py`. Siempre filtra por `cliente_id` y excluye las
      facturas `anulada`. Si falta `periodo_a`, usa el mes anterior a `periodo_b`
      (el método del PDF dice "compara con el periodo anterior", y el cliente suele
      nombrar un solo mes: "¿por qué subió octubre?"). Devuelve:
  - los totales de cada periodo y la variación absoluta y porcentual;
  - `variacion_fuerte` si la variación supera el 25 % (mismo umbral que la vista);
  - la diferencia por línea, agrupada por **`id_servicio` y clase de cargo**
    (`cargo_mensual` y `prorrateo` son la misma clase; no se agrupa por concepto ni
    por `tipo`, que también cambia en el prorrateo): **nuevas**, **eliminadas** y **cambiadas** (cantidad, precio
    unitario, monto o tipo). Con el concepto falla el cliente 9 (CS-10): en
    2026-09 la línea es "…Arequipa (prorrateo 15 días)" (`prorrateo`) y en 2026-10
    es "…Arequipa" (`cargo_mensual`). Debe salir como un servicio que pasa de
    prorrateo a mes completo, no como una línea eliminada y otra nueva. Todas las
    líneas tienen `id_servicio`.
  - **la causa** de cada línea nueva o eliminada, tomada de `servicio_contratado`:
    `sede`, `codigo_producto`, `fecha_activacion` y `fecha_baja`. El mensaje modelo
    de CS-09 dice que "se activaron 2 enlaces MPLS en Callao el 1 de octubre", y
    esa fecha no está en la factura (servicio 31, activado el 2026-10-01). También
    permite derivar si el cliente dice que no pidió el alta.
- [x] **Varias facturas en un periodo → aviso, no comparación** (decidido).
      Si `periodo_a` o `periodo_b` tiene más de una factura vigente, la función
      **no suma ni elige una**. Responde 200 con:
  - `comparable: false` y `motivo: "facturas_multiples"`;
  - por periodo, número, subtotal y total de cada factura (lo que CS-01 pide
    confirmar al cliente);
  - variación y diferencia por línea en `null` o vacías, **no en cero**, para que
    no se lean como "no cambió nada".

  **Por qué:** sumar el duplicado del cliente 1 en 2026-11 da +100 %, marca
  `variacion_fuerte` y muestra todas las líneas duplicadas como "cambiadas", y
  el bot explicaría como subida normal (CS-09) lo que es un duplicado (CS-01).
  Además, el total sumado ya da por válidas las dos facturas, y CS-01 prohíbe
  decir cuál se paga. **Límite aceptado:** también bloquea dos facturas
  legítimas en un mismo periodo (por ejemplo, una complementaria). En la base
  actual no hay ninguna; si aparecen, distinguirlas antes de relajar la regla.
  La detección va en una función aparte, que reutiliza la sección 2 (saldo).
- [x] Modelos Pydantic en `app/schemas/facturacion.py`.
- [x] **`GET /mi/comparar?periodo_a=...&periodo_b=...`** en `app/api/cliente.py`.
      Al agregarla, actualizar la lista `RUTAS` de `tests/test_api_cliente.py` (la
      guarda `test_todas_las_rutas_mi_exigen_token` cuenta las rutas `/mi`).

### Tests
- [x] Cliente 7, 2026-09 frente a 2026-10 → `variacion_fuerte` y la línea nueva
      "Enlace MPLS Callao" (2 × 12 000), con `fecha_activacion` 2026-10-01.
- [x] Cliente 7, solo `periodo_b=2026-10` → compara con 2026-09.
- [x] Cliente 9, 2026-09 frente a 2026-10 → el servicio 39 sale como **cambiado**
      (de `prorrateo` 3 × 2 250 a `cargo_mensual` 3 × 4 500), no como eliminado más nuevo.
- [x] Periodo sin facturas.
- [x] Periodo mal formado → 400 o 422.
- [x] Aislamiento: el cliente 2 no ve líneas del cliente 1.
- [x] Periodo con duplicado: el cliente 1, 2026-10 frente a 2026-11 → `comparable`
      falso, `motivo` `facturas_multiples`, `F001-000254` y `F001-000255` con sus
      importes, sin variación (`null`) ni líneas.

### Documentación
- [x] `docs/capa_datos.md`: CS-09 pasa a usar `comparar_periodos`.
- [x] README: agregar `/mi/comparar` y el filtro `periodo` a la tabla `/mi`.

### La misma comparación ayuda en otras casuísticas
Numeración de `docs/Anticipa_02_Casuisticas.pdf`, que **no coincide** con los
comentarios CS-xx de `db/schema.sql`.

| Casuística | Señal en la diferencia |
|---|---|
| CS-02 Servicio dado de baja que se sigue facturando | La línea sigue apareciendo después de `fecha_baja` |
| CS-03 Tarifa distinta a la pactada | `precio_unitario` distinto de `tarifa_pactada` |
| CS-04 Exceso sin sustento | Aparece una línea nueva de tipo `exceso` |
| CS-10 Prorrateo | Una línea pasa de `prorrateo` a `cargo_mensual` |

## 2. Saldo y resumen con facturas duplicadas (CS-01, CS-11)

`saldo_pendiente` del cliente 1 suma `F001-000254` y `F001-000255` (436 600 con IGV).
Si el bot lee ese saldo, le está cobrando el duplicado al cliente, y el PDF prohíbe
decirle si debe pagar una u otra.

- [x] Marcar en `SaldoPendiente` las facturas de un periodo con más de una vigente
      (como en `comparar_periodos`), sin decidir cuál vale. Hecho con
      `periodos_multiples`: cada suma que incluiría el duplicado va en `None`
      (cliente 1: `saldo_total` `None`, `saldo_vencido` 0).
- [x] Test: cliente 1 → aparece la marca y las dos facturas.
- [x] `resumen_facturacion` también suma: el periodo 2026-11 del cliente 1 sale
      con `cantidad_facturas = 2` y el subtotal doble. Aplicar la misma regla:
      marcar el periodo y no presentar su total como si fuera uno solo.

## 3. Casuísticas sin función en `facturacion.py` ni ruta en `/mi`

Hoy existen como vistas o métodos del CRUD (`anticipa_crud_por_entidad.py`), pero
el CRUD no exige `cliente_id`, no tiene modelos Pydantic ni tests de aislamiento.
Cada función nueva sigue las reglas de `docs/capa_datos.md` (solo lectura,
`cliente_id` obligatorio, ruta `/mi/...` con `Depends(cliente_actual)` y su
entrada en `RUTAS` de `tests/test_api_cliente.py`).

| Herramienta del PDF | Casuísticas | Base existente | Dato de prueba |
|---|---|---|---|
| [x] `obtener_servicios` (`GET /mi/servicios`) | CS-02, 03, 05, 09, 10 | `servicio_contratado` (tarifa pactada, SLA, alta y baja) | Cliente 2, Cusco, baja 2026-09-30 |
| [x] `detectar_anomalias` (`GET /mi/anomalias`) | CS-01, 02, 03, 04, 05, 07 | `v_facturas_duplicadas`, `v_servicios_baja_facturados`, `v_tarifa_distinta`, `v_exceso_sin_sustento`, `v_averias_sin_compensar` | Clientes 1 a 6 |
| [ ] Consumo del periodo | CS-04 (explicar el exceso: GB incluidos, usados, precio por GB) | `consumo` | Hecho para el exceso **sin** sustento (va en `detectar_anomalias`: cliente 4, 150 GB facturados, 897,5 de 1 200 usados). Falta el exceso **con** sustento: el PDF pide explicar el cálculo, y hoy esos consumos no se exponen (33 líneas de exceso en la base) |
| [x] `consultar_solicitudes` (`GET /mi/solicitudes`) | CS-06 | `solicitud`, `v_solicitudes_vencidas` | Cliente 10, 21 días con plazo 10 |
| [x] Registrar y derivar caso (`POST` y `GET /mi/casos`) | CS-01…08, CS-13 y "consulta no resuelta" | `caso`, `interaccion_log` (`CasoCRUD`) | — |

Hecho (ver `docs/capa_datos.md`, `registrar_caso`): número `C-000019`, aviso
por correo al ejecutivo (redirigible a `CORREO_DERIVACIONES`, nunca a dominios
reservados) con registro en el historial si no sale,
monto tomado de la anomalía, sin duplicados y `caso_abierto` en
`/mi/anomalias`. `caso.canal` admite `web` para las pruebas.

## 4. Modo B: fuera de alcance

**Decisión:** el proyecto implementa solo el modo A del PDF (ver "Alcance" en
`docs/capa_datos.md`). Estas tareas quedan identificadas por si se retoma; no
se trabajan ahora.

| Tarea | Casuísticas | Qué hay en la base | Dato de prueba | Nota |
|---|---|---|---|---|
| [ ] Tramo y aprobador por monto | CS-01 a CS-05, CS-07 | `politica_tramo`; ya existe `tramo_para()` en `db/catalogo_sqlite.py` y `PoliticaTramoCRUD.obtener_tramo_por_monto` | 185 000 → tramo 4; 24 000 y 13 500 → 3; 300 y 464 → 2; 33,75 → 1 | Montos sin IGV. Reutilizar la lógica existente, con tests de los bordes de cada tramo |
| [ ] `calcular_ajuste` | CS-02 a CS-05, CS-07 | El monto ya sale en `detectar_anomalias` (`monto_observado`) | Mismos montos | Sobre todo une monto, tramo, aprobador e IGV para el sustento |
| [ ] Proponer nota de crédito (escritura) | CS-01 a CS-05 | `ajuste` en estado `propuesto`, ligado a `caso` | — | CS-01 escala a gerencia y finanzas (tramo 4); no prometer el resultado |
| [ ] Aplicar nota de crédito automática (escritura) | CS-07 | `ajuste` en estado `aplicado` | Cliente 6, 33,75 (39,83 con IGV) | Solo tramo 1 (hasta S/ 100) |
| [ ] Excluir anomalías con ajuste en curso | CS-01 a CS-04 | Las vistas no miran `ajuste` (la de averías sí) | — | Sin esto, una anomalía ya propuesta seguiría apareciendo |
| [ ] Gesto comercial P6 | CS-08, CS-06 | `v_gestos_mes_actual`, parámetros `gesto_max_monto` (100) y `gesto_max_por_mes` (1) | Cliente 8: S/ 60 ya aplicado este mes; un segundo pedido se rechaza | La regla P6 está "por validar con el negocio" |

Lo que **no** es modo B y sigue en alcance: el consumo del exceso con sustento
(CS-04 pide explicar el cálculo en ambos modos) y registrar y derivar caso.
