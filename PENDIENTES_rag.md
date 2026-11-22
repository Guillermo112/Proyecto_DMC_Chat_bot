# Pendientes: agente, herramientas y RAG

Empezar **después de [`PENDIENTES_datos.md`](PENDIENTES_datos.md)** (capa de
datos del modo A completa al 2026-11-22). Alcance: **solo modo A** (ver
"Alcance" en `docs/capa_datos.md`).

## Principio: qué responde cada parte

| Parte | Responde | Fuente |
|---|---|---|
| **Herramientas** (`app/tools`) | Todo dato del cliente: montos, fechas, estados, anomalías, solicitudes, casos | API `/mi/...` o `app/data` (ver `docs/casuisticas_api.md`) |
| **RAG** | Conocimiento general: políticas, glosario, preguntas frecuentes, tono y qué no decir | `docs/Anticipa_01_*.pdf`, `docs/Anticipa_03_*.pdf`, `faq.json`, `catalogo.json` |

**El RAG nunca es fuente de un monto, fecha o estado del cliente.** Lo dice el
propio `faq.json` (`gen-003`): "todo dato que te doy proviene de una consulta al
sistema". `Anticipa_02_Casuisticas.pdf` sirve para el comportamiento por
casuística, pero sus mensajes modelo mezclan acciones del modo B (ver la
advertencia en `docs/casuisticas_api.md`).

## 1. Alinear `faq.json` con el modo A (bloquea el RAG)

Varias respuestas describen acciones del modo B. Indexadas tal cual, el agente
prometería cosas que el sistema no hace.

| FAQ | Dice | En modo A |
|---|---|---|
| [ ] `com-001` | "Puedo aplicar un gesto comercial de hasta S/ 100" | No se aplican gestos: se registra y deriva (`POST /mi/casos`, `gesto_comercial`) |
| [ ] `aju-002` | "Emito la nota de crédito o débito y te aviso" | No se emiten notas de crédito: se registra y deriva |
| [ ] `aju-001` | Quién aprueba según el tramo | Correcto como política, pero en modo A siempre se deriva al ejecutivo |
| [ ] `der-001` | "Envío un aviso… a quien corresponde según el tramo" | Va al ejecutivo del cliente (y al responsable en CS-06) |
| [ ] Revisar las 30 | Buscar "aplico", "emito", "calculo y aplico", tramos | Reescribir solo las acciones; las políticas pueden quedar como información |

- `faq.json` viene de la rama `faq_json_atorres`: coordinar el cambio con quien la creó.
- Revisar también `catalogo.json` (`casuisticas`, `tramos`) con el mismo criterio.

## 2. Herramientas del agente (`app/tools`)

- [x] Una herramienta por ruta `/mi` útil al agente: perfil, facturas, detalle,
      saldo, comparar, servicios, anomalías, solicitudes, registrar y listar casos.
      Descripciones tomadas de `docs/casuisticas_api.md` (cuándo usar cada una,
      `null` no es 0, `comparable: false`, `caso_abierto`).
- [x] El `cliente_id` lo inyecta el código desde la sesión, **nunca** el modelo
      (mismo principio que `Depends(cliente_actual)`).
- [x] Decidido (2026-11-22): llaman a `app/data` en proceso (las mismas funciones que
      `/mi`). Por HTTP no cambia el costo (todo es local) y suma latencia y código.
- [ ] **Retirar `db/catalogo_sqlite.py`**: prototipo anterior que lee la base
      directo (se salta `/mi`), usa otras variables (`DB_PATH`, `MODO_AGENTE`) e
      incluye `tramo_para` (modo B). Dejaría dos fuentes de verdad.
- [x] Test: ninguna herramienta acepta `cliente_id` como argumento del modelo.

## 3. RAG

- [x] Stack (como sesion7, sin LangChain ni almacén externo): router del curso en
      `app/llm` (copia de `_comun/llm_router.py`), índice en memoria en `app/rag`
      con embeddings locales granite 97M, respaldo TF-IDF, umbral y MMR.
- [ ] Ingesta: PDF 01 y 03, `faq.json` ya alineada y `catalogo.json`. Decidir si
      el PDF 02 se indexa entero o solo las filas "Modo A", "No digas" y "Deriva cuando".
- [ ] `faq.json` **no** entra al índice de documentos: va a su propio clasificador
      (`app/faq`), como en sesion7. El RAG (`app/rag`) indexa PDF y `catalogo.json`.
- [x] Filtro de ingesta de `catalogo.json` (decidido 2026-11-22), en `app/rag/ingesta.py`:
      **lista blanca** de campos por sección (un campo nuevo no entra hasta autorizarlo)
      y un fragmento por registro, con metadatos `fuente`, `seccion` e `id`.

      | Sección | Entra | Fuera |
      |---|---|---|
      | `casuisticas` | `codigo`, `nombre`, `categoria`, `opcion_a` | `opcion_b`, `decide`, `tramo_referencial`, `genera_ajuste`, `vista_deteccion`, `faq_relacionadas` |
      | `servicios` | `nombre`, `specs`, `unidad_cobro`, `sla_pct`, `tolerancia_horas_mes`, `nota` | `precio` (la tarifa del cliente sale de la herramienta) |
      | `tramos` | `nombre`, rango sin IGV, `aprueba` (solo información) | `accion_agente` |
      | `agente` | `politicas`, una por fragmento, salvo `gesto_comercial` | `descripcion` y `categorias` (van al prompt del sistema); `politicas.gesto_comercial` (P6 es solo modo B; responde la FAQ `com-001` reescrita) |

- [x] **Control de modo B** tras la lista blanca (`MARCAS_MODO_B`): "opción B",
      "modo B", "emite/aplicas la nota", "propone/calcula/aplicas el ajuste",
      `calcular_ajuste`, "aplica el gesto", "puedo aplicar", "según el tramo".
      En los JSON la ingesta falla con el id; en los PDF el fragmento se descarta y
      se registra (`rag.descartado`, documento y página).
- [x] Tests (`tests/test_rag_ingesta.py`, `tests/test_rag_indice.py`, sin red ni modelo).
- [x] Tablas de los PDF (2026-11-22): `app/rag/pdf.py` lee el modo `layout` de pypdf y
      separa prosa y tablas con regex (celdas a 3+ espacios, filas con un espacio inicial).
      Cada fila es un fragmento con el título de su sección. El filtro de modo B actúa por
      **oración** (prosa y celdas) y por **columna** (encabezado "Modo B" o "Tarifa de
      lista", igual que `precio` en `catalogo.json`). Resultado: 107 fragmentos de PDF
      (87 filas) y la columna modo A de las tablas se conserva.
- [ ] Revisar lo que aún pasa el filtro y es del modo B o interno:
  - P7, "Cómo derivas" (01 p3) y `catalogo.json` → `agente.politicas.derivacion` asignan
    destinatario por tramo; en modo A va al ejecutivo.
  - Tabla de herramientas del 01 (p5) y nombres como `registrar_caso`: instrucción interna.
  - Huérfanos menores: "P6." sin texto, "Si no sabes cuál es, actúa en modo A.".
  - El PDF 01 es en buena parte instrucción para el agente: encaja mejor en el prompt del
    sistema que en el RAG.
- [x] Banco de pruebas (solo `ENTORNO=dev`): página `/dev/rag` y endpoints
      `/dev/rag/buscar` y `/dev/rag/info` (`app/api/dev_rag.py`, `app/static/rag.html`).
      Muestra puntajes, qué pasa el umbral y qué llegaría al prompt; el historial se
      copia como CSV para calibrar.
- [ ] Calibrar `RAG_UMBRAL` con el set de evaluación. Medición con granite y filas de
      tabla: relevantes 0,83-0,96, ajenas 0,74-0,81 (por defecto 0,82; el 0,35 de sesion7
      no filtra). El umbral solo no separa lo fuera de tema: lo cubre el prompt.
- [x] Prompt del sistema (`app/agente/prompt.py`, ~490 palabras): alcance modo A,
      montos solo desde herramientas, `null` no es 0, no prometer devoluciones ni fechas,
      registrar y derivar. Resume el PDF 01 (que sigue también en el RAG).
- [x] Chat (`POST /mi/chat`, página `/chat`, 2026-11-22): RAG previo al modelo (sin
      llamada extra), 10 herramientas, tope de vueltas, memoria corta en memoria y panel
      de traza con tokens. Modelo: DeepSeek por `LLM_*`.
- [ ] Probar el chat con DeepSeek real (la clave del `.env` dio 401) y ajustar el prompt
      con lo que se vea en las casuísticas.
- [ ] Evaluación: una pregunta por casuística con los datos sembrados
      (ejemplos en `docs/casuisticas_api.md`), comprobando herramienta llamada,
      monto citado y frases prohibidas.

## 4. Pendientes menores (no bloquean)

- [ ] Consumo del exceso **con** sustento (CS-04): exponerlo para explicar el
      cálculo (detalle en `PENDIENTES_datos.md`, sección 3).
- [ ] Historial de la conversación: hoy `interaccion_log` solo se escribe al
      registrar un caso. Decidir si el bot guarda cada turno y quién lo escribe.
- [ ] Bot de Telegram: no existe aún. El RAG y las herramientas se pueden
      desarrollar y probar sin él (canal `web`).
