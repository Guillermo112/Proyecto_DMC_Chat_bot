# Casuísticas y API: qué llamar según lo que pide el cliente

Guía para quien arme el agente (`app/tools`, el prompt) o pruebe la API a mano.
Parte de **lo que necesita el cliente** y dice qué endpoints llamar, en qué
orden, qué campos leer y qué no decir.

- **Fuente de las reglas:** `docs/Anticipa_02_Casuisticas.pdf`. Esta guía no
  copia sus mensajes modelo; remite a la sección del PDF para el tono y las frases.
- **Detalle de cada función:** `docs/capa_datos.md`.
- **Alcance: solo modo A** (ver "Alcance" en `docs/capa_datos.md`). El agente
  informa, explica, registra y deriva; no calcula ajustes ni aplica notas de crédito.
- `tests/test_casuisticas_api.py` comprueba que toda ruta citada aquí existe en la
  API y que cada ruta `/mi` aparece en la guía.

> **Ojo con los mensajes modelo del PDF.** Varios describen acciones del modo B
> ("lo escalé a gerencia", "ya apliqué la nota de crédito", "envié la corrección
> para su aprobación"). En el modo A vale la fila **Modo A** de cada casuística:
> confirmar lo observado, registrar y derivar al ejecutivo, sin decir que algo ya
> se corrigió o se aplicó.

## Antes de cualquier consulta

1. **Identificar al cliente** (CS-12): `POST /auth/solicitar-codigo` con el RUC y
   `POST /auth/verificar-codigo` con el código. Devuelve `access_token`.
2. Todas las rutas `/mi/...` llevan `Authorization: Bearer <access_token>`. El
   cliente sale **solo** del token: no hay `cliente_id` en ninguna ruta.
3. `GET /auth/sesion` confirma que el token sigue vigente (30 minutos).

**Reglas comunes**

- Los montos salen **siempre** de la API, nunca se calculan ni se suman a mano.
- Montos **sin IGV** salvo los campos `igv` y `total` de las facturas y el saldo.
- La "fecha de hoy" es la de corte ficticia (`fecha_corte`, 2026-12-05), no la del sistema.
- **`null` no es 0.** Un importe en `null` significa "no se puede afirmar"
  (normalmente, facturas duplicadas en el periodo). No se lee como cero ni se
  reemplaza por una suma.
- Facturación **mes vencido**: el periodo 2026-10 se emite el 2026-11-01 y vence a
  los 20 días. "La factura de octubre" es `periodo=2026-10`, no un rango de emisión.

## Entrada rápida: lo que dice el cliente → qué llamar

| Lo que dice el cliente | Casuística | Llamadas, en orden |
|---|---|---|
| "No entiendo mi factura de octubre" | §1 del PDF | `/mi/facturas?periodo=2026-10` → `/mi/facturas/{numero}` |
| "¿Por qué subió mi factura?" | CS-09 | `/mi/comparar?periodo_b=2026-10` |
| "Me cobraron menos (o distinto) por el servicio nuevo" | CS-10 | `/mi/facturas/{numero}` → `/mi/comparar` |
| "Me llegaron dos facturas iguales" | CS-01 | `/mi/anomalias` |
| "Di de baja un servicio y me lo siguen cobrando" | CS-02 | `/mi/anomalias` → `/mi/servicios?estado=baja` |
| "Me cobran más de lo que dice mi contrato" | CS-03 | `/mi/anomalias` → `/mi/servicios` |
| "Me cobraron exceso de datos que no usamos" | CS-04 | `/mi/anomalias` |
| "Nos quedamos sin servicio" | CS-05 / CS-07 | `/mi/anomalias` |
| "Pedí algo hace semanas y nadie responde" | CS-06 | `/mi/solicitudes` |
| "¿Pueden darme un descuento por la demora?" | CS-08 | `POST /mi/casos` (`gesto_comercial`) |
| "¿Tengo facturas pendientes? ¿Cuándo vence?" | CS-11 | `/mi/saldo` |
| "No me llega el código" / RUC que no existe | CS-12 | `/auth/solicitar-codigo` |
| "Quiero bajar mi tarifa" / "pagar en cuotas" | CS-13 | `POST /mi/casos` (`fuera_de_alcance`) |
| "Algo está mal" y no se encuentra anomalía | §1 del PDF | `/mi/anomalias` → `POST /mi/casos` (`consulta_no_resuelta`) |
| "¿Cómo va mi caso?" | FAQ | `GET /mi/casos` |

Casi todas las casuísticas terminan en **registrar y derivar**: ver la sección
"Registrar y derivar un caso" más abajo.

## Explicar una factura (método del PDF, §1)

1. **Ubicar:** `GET /mi/facturas?periodo=AAAA-MM` → `numero`, `periodo`,
   `fecha_emision`, `fecha_vencimiento`, `estado`. Si devuelve dos facturas
   vigentes del mismo periodo, es CS-01.
2. **Resumir el total:** `GET /mi/facturas/{numero}` → `subtotal` (sin IGV),
   `igv` (18 %) y `total`.
3. **Explicar las líneas por tipo:** `lineas[].tipo` = `cargo_mensual`,
   `prorrateo`, `exceso` o `ajuste`, con `cantidad × precio_unitario = monto`.
4. **Responder la duda:** si pregunta por una diferencia, `GET /mi/comparar`
   (CS-09).
5. **Sin anomalía y el cliente insiste:** `GET /mi/anomalias` vacío → no
   discutir, pedir el detalle y registrar `consulta_no_resuelta` con
   `POST /mi/casos`.

Ejemplo: cliente 9, `GET /mi/facturas?periodo=2026-09` → `F001-000161`, total
72 275,00; sus líneas incluyen el prorrateo de Arequipa (3 × 2 250 = 6 750).

## Registrar y derivar un caso

`POST /mi/casos` registra el caso y lo deriva al ejecutivo del cliente (modo A).
Es la única ruta que escribe.

```json
{
  "tipo": "servicio_baja_facturado",
  "canal": "telegram",
  "palabras_cliente": "Dimos de baja el enlace de Cusco y me lo siguen cobrando",
  "resumen": "Cobro posterior a la baja del 30/09",
  "referencias": {"id_servicio": 8}
}
```

- **`tipo`:** de anomalía (`factura_duplicada`, `servicio_baja_facturado`,
  `tarifa_distinta`, `exceso_sin_sustento`, `sla_averia`) o libre
  (`solicitud_fuera_de_plazo`, `gesto_comercial`, `alta_no_solicitada`,
  `fuera_de_alcance`, `consulta_no_resuelta`, `solicitud_datos`,
  `contacto_persona`).
- **`canal`:** `telegram` desde el bot; `web` para pruebas por web o API.
- **`palabras_cliente`:** lo que pidió, tal cual (CS-13 pide no hacerle repetirlo).
- **`referencias`** (opcionales): `numero_factura`, `periodo`, `id_servicio`,
  `id_averia`, `id_solicitud`. Todas deben ser del cliente (si no, 404).
- **Tipos de anomalía:** el servidor busca la anomalía en `/mi/anomalias` y toma
  de ella la referencia y el monto. Si el cliente tiene una sola de ese tipo,
  no hace falta ninguna referencia. Si no hay ninguna, responde 400 y sugiere
  `consulta_no_resuelta`.
- **El monto nunca va en el cuerpo:** `monto_discutido` sale de la anomalía.

**Respuesta:** `numero_caso` (el `{n}` de los mensajes del PDF, p. ej.
`C-000019`), `estado` (`derivado`), `derivado_a_nombre` (el ejecutivo),
`monto_discutido`, `ya_existia` y `aviso`.

- **201** si se creó; **200 con `ya_existia: true`** si ya había un caso abierto
  equivalente (un reintento del bot no duplica: dar el mismo número).
- **`aviso`:** `enviado`, `no_enviado` o `fallido`: si salió el correo al
  ejecutivo (o a la casilla de prueba que lo redirige, `CORREO_DERIVACIONES`).
  El caso queda registrado en los tres casos.
- **Antes de registrar una anomalía**, mirar `caso_abierto` en `/mi/anomalias`:
  si ya tiene número, informarlo en vez de registrar otra vez.
- `GET /mi/casos` lista los casos del cliente con su estado.

## Fichas por casuística

### CS-01 · Factura duplicada

- **Llamar:** `GET /mi/anomalias` → `facturas_duplicadas[]`.
- **Leer:** `periodo`, `facturas[].numero`, `facturas[].subtotal` y `total`, y
  `monto_observado` (el importe de la factura de más, sin IGV).
- **Otras rutas lo marcan sin sumar:** `/mi/saldo` (`saldo_total: null`,
  `periodos_multiples`), `/mi/resumen` (`facturas_multiples`) y `/mi/comparar`
  (`comparable: false`, `motivo: "facturas_multiples"`).
- **Modo A:** confirmar que hay dos facturas iguales, registrar y derivar:
  `POST /mi/casos` con `tipo: "factura_duplicada"` (el caso guarda ambos números).
- **No decir:** cuál se anula, cuál pagar ni que se devolverá algo.
- **Ejemplo:** cliente 1, 2026-11 → `F001-000254` y `F001-000255`, 185 000,00
  (218 300,00 con IGV) cada una.

### CS-02 · Servicio dado de baja que se sigue facturando

- **Llamar:** `GET /mi/anomalias` → `servicios_baja_facturados[]`; si hace falta
  confirmar la baja, `GET /mi/servicios?estado=baja`.
- **Leer:** `servicio.sede`, `servicio.fecha_baja`, `cobros[]` (`periodo`,
  `numero_factura`, `monto_observado`) y `monto_observado` (el total ya sumado).
- **Modo A:** confirmar la fecha de baja, decir qué periodos se cobraron después
  y registrar: `POST /mi/casos` con `tipo: "servicio_baja_facturado"`.
  Si el cliente discute la fecha de baja, también se registra y deriva.
- **No decir:** que se devolverá. El periodo de la baja no cuenta como cobro de
  más (la API ya lo excluye).
- **Ejemplo:** cliente 2, Cusco, baja 2026-09-30, cobrado en 2026-10 y 2026-11:
  24 000,00.

### CS-03 · Tarifa facturada distinta a la pactada

- **Llamar:** `GET /mi/anomalias` → `tarifas_distintas[]`; la tarifa del contrato
  también está en `GET /mi/servicios` (`tarifa_pactada`).
- **Leer:** `tarifa_pactada`, `cobros[]` (`periodo`, `tarifa_facturada`,
  `cantidad`, `monto_observado`) y `monto_observado` total.
- **Modo A:** mostrar ambas tarifas, los periodos afectados y registrar:
  `POST /mi/casos` con `tipo: "tarifa_distinta"`.
- **No decir:** que la tarifa "quedó mal por error"; decir que no coincide con
  el contrato. Si el cliente afirma otra tarifa pactada, derivar.
- **Ejemplo:** cliente 3, MPLS Lima: pactada 10 500,00, facturada 12 000,00 × 3
  enlaces, 2026-09 a 2026-11: 13 500,00.

### CS-04 · Exceso de consumo móvil sin sustento

- **Llamar:** `GET /mi/anomalias` → `excesos_sin_sustento[]`.
- **Leer:** `gb_facturados`, `precio_gb`, `monto_observado` y el consumo
  registrado: `gb_incluidos_registrados`, `gb_usados_registrados`,
  `gb_exceso_registrados` (`null` si no hay consumo del periodo).
- **Modo A:** explicar que el consumo registrado no muestra exceso y registrar:
  `POST /mi/casos` con `tipo: "exceso_sin_sustento"`.
- **Si el exceso sí tiene sustento** (no sale en anomalías): el PDF pide explicar
  el cálculo (GB incluidos, usados, precio por GB). Hoy solo hay
  `gb_incluidos_por_linea` y `precio_gb_exceso` en `GET /mi/servicios`; el
  consumo de ese caso aún no se expone (pendiente en `PENDIENTES_datos.md`).
- **Ejemplo:** cliente 4, 2026-10, `F001-000207`: 150 GB a 2,00 = 300,00;
  registrado 897,5 de 1 200 GB, exceso 0.

### CS-05 · Avería con SLA incumplido (mayor) y CS-07 (menor)

- **Llamar:** `GET /mi/anomalias` → `averias_sla_incumplido[]`.
- **Leer:** `servicio.sede`, `fecha_inicio`, `fecha_fin`, `horas_caida`,
  `tolerancia_horas`, `horas_fuera_de_sla` y `monto_observado`
  (= tarifa pactada × unidades × horas fuera ÷ 720). El SLA está en
  `servicio.sla_pactado` como fracción (0.997 = 99,7 %).
- **Modo A:** informar las horas de caída y que corresponde evaluar una
  compensación; registrar con `POST /mi/casos` (`tipo: "sla_averia"`, y
  `id_averia` si hay más de una). En modo A **no** se dice que
  el descuento ya se aplicó (el mensaje modelo de CS-07 es de modo B).
- **No decir:** la causa técnica (la API no la expone), fechas de reparación,
  ni que el descuento cubre otros perjuicios. Si reclama daños, derivar.
- **Ejemplos:** cliente 5, Trujillo, 30 h (tolerancia 2,16 h): 464,00. Cliente 6,
  Piura, 9 h (tolerancia 3,6 h): 33,75.

### CS-06 · Solicitud fuera del plazo de atención

- **Llamar:** `GET /mi/solicitudes` (o `?estado=abierta`).
- **Leer:** `cantidad_fuera_de_plazo`, `plazo_atencion_dias` y por solicitud
  `tipo`, `estado`, `fecha_registro`, `dias_transcurridos`, `fuera_de_plazo`.
- **Modo A:** informar estado y días, disculparse y avisar al responsable y al
  ejecutivo: `POST /mi/casos` con `tipo: "solicitud_fuera_de_plazo"` e
  `id_solicitud` (rechaza una solicitud que está dentro del plazo).
- **No decir:** una fecha de resolución (la API no la tiene).
- **Ejemplo:** cliente 10, solicitud abierta el 2026-11-14: 21 días con plazo de 10.

### CS-08 · Gesto comercial

- **Modo A:** no se aplican gestos. Registrar el pedido y derivar al ejecutivo:
  `POST /mi/casos` con `tipo: "gesto_comercial"`. Aplicar el gesto es modo B,
  fuera de alcance.

### CS-09 · Variación fuerte de facturación

- **Llamar:** `GET /mi/comparar?periodo_b=AAAA-MM` (compara con el mes anterior;
  `periodo_a` para otro).
- **Leer:** `variacion_subtotal`, `variacion_pct`, `variacion_fuerte` (> 25 %) y
  `lineas[]`: `cambio` (`nueva`, `eliminada`, `cambiada`), `antes`, `despues`,
  `diferencia_monto` y `servicio` (sede, `fecha_activacion`, `fecha_baja`), que da
  la causa.
- **Si `comparable` es `false`:** `motivo = "facturas_multiples"` → es CS-01, no
  explicar como subida; `"periodo_sin_facturas"` → no hay con qué comparar.
- **Modo A:** explicar la causa con las líneas y ofrecer el detalle por correo.
- **No decir:** que la subida "es normal" sin la causa. Si el cliente dice que no
  pidió el alta, `POST /mi/casos` con `tipo: "alta_no_solicitada"`.
- **Ejemplo:** cliente 7, `periodo_b=2026-10` → +24 000,00 (+32,79 %), línea
  nueva "Enlace MPLS Callao" 2 × 12 000, alta el 2026-10-01.

### CS-10 · Consulta de prorrateo

- **Llamar:** `GET /mi/facturas/{numero}` (línea de tipo `prorrateo`) y, para la
  fecha de alta, `GET /mi/comparar` del mes siguiente o `GET /mi/servicios`.
- **Leer:** la línea `prorrateo` (`cantidad`, `precio_unitario`, `monto`) y
  `servicio.fecha_activacion`. En la comparación, el servicio sale como
  `cambiada` de `prorrateo` a `cargo_mensual`.
- **Modo A:** explicar la fórmula con los números de la factura.
- **No decir:** descuentos ni notas de crédito (el prorrateo es correcto). Si la
  fecha de alta no coincide con la que recuerda el cliente, derivar.
- **Ejemplo:** cliente 9, Arequipa, alta 2026-09-15: 3 × 4 500 × 15/30 = 6 750,00
  en septiembre; desde octubre, 13 500,00.

### CS-11 · Saldo y factura vencida

- **Llamar:** `GET /mi/saldo`; para el detalle por periodo,
  `GET /mi/facturas?estado=vencida` o `?periodo=AAAA-MM`.
- **Leer:** `saldo_total`, `saldo_vencido`, `facturas[]` (`numero`, `periodo`,
  `estado`, `total`, `fecha_vencimiento`), `periodos_multiples` y
  `notas_credito_aplicadas` (se informan, **no** se restan).
- **Si `saldo_total` es `null`:** hay un duplicado (CS-01). Informar factura por
  factura, sin dar un saldo total.
- **No decir:** intereses, moras, cortes de servicio ni plazos de pago
  (cobranza). Si pide fraccionar o negociar, derivar.
- **Ejemplo:** cliente 9: `F001-000212` (2026-10) vencida el 2026-11-21 por
  80 240,00; `F001-000263` (2026-11) vence el 2026-12-21.

### CS-12 · Identificación fallida y RUC inexistente

- **Llamar:** `POST /auth/solicitar-codigo` → `POST /auth/verificar-codigo`.
- **Comportamiento:** la respuesta a la solicitud es la misma exista o no el RUC
  (y sin correo si no existe). La verificación devuelve 401 con el mismo mensaje
  si el código es incorrecto, venció (10 min) o se bloqueó (3 intentos). 429 si
  la IP pidió demasiados códigos.
- **No decir:** si el RUC existe, a qué correo se envió ni pistas del código. Si
  no tiene acceso al correo, que contacte a su ejecutivo.
- Detalle en el README, "Identificación por OTP".

### CS-13 · Pedido fuera de alcance

- **Llamar:** `GET /mi/perfil` → `ejecutivo_nombre`, `ejecutivo_correo`.
- **Modo A:** registrar el pedido con las palabras del cliente y derivar:
  `POST /mi/casos` con `tipo: "fuera_de_alcance"`.
- **No decir:** opiniones sobre tarifas futuras ni negociar.

## Preguntas frecuentes del PDF (§4)

| Pregunta | Cómo responder |
|---|---|
| ¿Cuándo se emite mi factura? | Regla fija (mes vencido, vence a los 20 días); las fechas reales en `/mi/facturas` |
| ¿Cuándo recibo la nota de crédito? | Modo A: la gestiona el ejecutivo; ya aplicadas, en `notas_credito_aplicadas` de `/mi/saldo` |
| ¿Por qué cambió el monto? | CS-09: `/mi/comparar` |
| ¿Qué es el prorrateo? | Definición del glosario; con su factura, CS-10 |
| ¿Qué hago si no me llega el código? | CS-12: revisar spam, pedir otro con `/auth/solicitar-codigo` |
| ¿Puedo cambiar el correo de facturación? | `POST /mi/casos` con `tipo: "solicitud_datos"` |
| ¿Me envían copia de la factura? | `POST /mi/casos` con `tipo: "solicitud_datos"` y la factura |
| ¿Puedo hablar con una persona? | `POST /mi/casos` con `tipo: "contacto_persona"`; ejecutivo en `/mi/perfil` |

## Rutas y casuísticas que las usan

| Ruta | Casuísticas |
|---|---|
| `GET /mi/perfil` | CS-13, toda derivación |
| `GET /mi/facturas` | §1, CS-01, CS-11 |
| `GET /mi/facturas/{numero}` | §1, CS-10 |
| `GET /mi/saldo` | CS-11 (y CS-01, que la marca) |
| `GET /mi/resumen` | Evolución de varios meses; CS-01 la marca |
| `GET /mi/comparar` | CS-09, CS-10 |
| `GET /mi/servicios` | CS-02, CS-03, CS-04, CS-05, CS-07, CS-10 |
| `GET /mi/anomalias` | CS-01 a CS-05, CS-07, "consulta no resuelta" |
| `GET /mi/solicitudes` | CS-06 |
| `POST /mi/casos` | CS-01 a CS-09, CS-13, "consulta no resuelta" y FAQ |
| `GET /mi/casos` | FAQ ("¿cómo va mi caso?") |
| `POST /auth/solicitar-codigo`, `POST /auth/verificar-codigo`, `GET /auth/sesion` | CS-12 |
