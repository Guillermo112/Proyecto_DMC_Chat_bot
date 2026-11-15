-- =====================================================================
-- ANTICIPA - Esquema SQLite (datos 100% ficticios)
-- Agente de interacción con clientes y prevención de reclamos de facturación
-- Fecha de sistema ficticia: 2026-12-05 (ver tabla parametro)
-- =====================================================================
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 1. PARAMETROS Y POLITICAS
-- ---------------------------------------------------------------------
CREATE TABLE parametro (
    clave        TEXT PRIMARY KEY,
    valor        TEXT NOT NULL,
    descripcion  TEXT NOT NULL
);

CREATE TABLE politica_tramo (
    id_tramo       INTEGER PRIMARY KEY,
    nombre         TEXT NOT NULL,
    monto_desde    REAL NOT NULL,          -- exclusivo (monto > desde), salvo tramo 1
    monto_hasta    REAL,                   -- inclusivo; NULL = sin tope
    accion         TEXT NOT NULL,
    aprobador_rol  TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- 2. PERSONAL INTERNO
-- ---------------------------------------------------------------------
CREATE TABLE personal (
    id_personal  INTEGER PRIMARY KEY,
    nombre       TEXT NOT NULL,
    rol          TEXT NOT NULL CHECK (rol IN
                 ('Ejecutivo de cuenta','Jefatura de facturación','Gerencia y Finanzas','Área técnica')),
    correo       TEXT NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------
-- 3. CATALOGO Y CLIENTES
-- ---------------------------------------------------------------------
CREATE TABLE producto (
    codigo                   TEXT PRIMARY KEY,
    nombre                   TEXT NOT NULL,
    descripcion              TEXT,
    unidad                   TEXT NOT NULL,          -- enlace, troncal, línea
    tarifa_mensual           REAL NOT NULL CHECK (tarifa_mensual > 0),
    sla_disponibilidad       REAL CHECK (sla_disponibilidad BETWEEN 0 AND 1),  -- fracción, ej. 0.995
    gb_incluidos_por_linea   REAL,                   -- solo móvil
    precio_gb_exceso         REAL                    -- solo móvil
);

CREATE TABLE cliente (
    id_cliente          INTEGER PRIMARY KEY,
    ruc                 TEXT NOT NULL UNIQUE CHECK (length(ruc) = 11),
    razon_social        TEXT NOT NULL,
    sector              TEXT,
    segmento            TEXT CHECK (segmento IN ('Grande','Mediano','Pequeño')),
    correo_facturacion  TEXT NOT NULL,
    contacto_nombre     TEXT NOT NULL,
    id_ejecutivo        INTEGER NOT NULL REFERENCES personal(id_personal),
    plazo_atencion_dias INTEGER NOT NULL DEFAULT 10,
    estado              TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo','suspendido','baja'))
);

CREATE TABLE servicio_contratado (
    id_servicio      INTEGER PRIMARY KEY,
    id_cliente       INTEGER NOT NULL REFERENCES cliente(id_cliente),
    codigo_producto  TEXT NOT NULL REFERENCES producto(codigo),
    sede             TEXT NOT NULL,
    cantidad         INTEGER NOT NULL CHECK (cantidad > 0),   -- enlaces / troncales / líneas
    tarifa_pactada   REAL NOT NULL CHECK (tarifa_pactada > 0),-- por unidad y mes
    sla_pactado      REAL,
    fecha_activacion TEXT NOT NULL,                           -- AAAA-MM-DD
    fecha_baja       TEXT,                                    -- NULL si sigue activo
    estado           TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo','baja'))
);
CREATE INDEX ix_serv_cliente ON servicio_contratado(id_cliente);

-- ---------------------------------------------------------------------
-- 4. FACTURACION
-- ---------------------------------------------------------------------
CREATE TABLE factura (
    id_factura        INTEGER PRIMARY KEY,
    numero            TEXT NOT NULL UNIQUE,                   -- F001-000123
    id_cliente        INTEGER NOT NULL REFERENCES cliente(id_cliente),
    periodo           TEXT NOT NULL CHECK (periodo GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    fecha_emision     TEXT NOT NULL,
    fecha_vencimiento TEXT NOT NULL,
    subtotal          REAL NOT NULL,                          -- sin IGV
    igv               REAL NOT NULL,
    total             REAL NOT NULL,
    estado            TEXT NOT NULL CHECK (estado IN ('emitida','pagada','vencida','en_disputa','anulada'))
);
CREATE INDEX ix_fact_cliente_periodo ON factura(id_cliente, periodo);

CREATE TABLE factura_linea (
    id_linea         INTEGER PRIMARY KEY,
    id_factura       INTEGER NOT NULL REFERENCES factura(id_factura),
    id_servicio      INTEGER REFERENCES servicio_contratado(id_servicio),
    tipo             TEXT NOT NULL CHECK (tipo IN ('cargo_mensual','prorrateo','exceso','ajuste')),
    concepto         TEXT NOT NULL,
    cantidad         REAL NOT NULL,
    precio_unitario  REAL NOT NULL,
    monto            REAL NOT NULL                            -- cantidad x precio_unitario
);
CREATE INDEX ix_linea_factura  ON factura_linea(id_factura);
CREATE INDEX ix_linea_servicio ON factura_linea(id_servicio);

CREATE TABLE consumo (
    id_consumo    INTEGER PRIMARY KEY,
    id_servicio   INTEGER NOT NULL REFERENCES servicio_contratado(id_servicio),
    periodo       TEXT NOT NULL,
    gb_incluidos  REAL NOT NULL,
    gb_usados     REAL NOT NULL,
    exceso_gb     REAL NOT NULL,
    monto_exceso  REAL NOT NULL,
    UNIQUE (id_servicio, periodo)
);

-- ---------------------------------------------------------------------
-- 5. OPERACION: AVERIAS Y SOLICITUDES
-- ---------------------------------------------------------------------
CREATE TABLE averia (
    id_averia           INTEGER PRIMARY KEY,
    id_servicio         INTEGER NOT NULL REFERENCES servicio_contratado(id_servicio),
    unidades_afectadas  INTEGER NOT NULL CHECK (unidades_afectadas > 0),
    fecha_inicio        TEXT NOT NULL,                        -- AAAA-MM-DD HH:MM
    fecha_fin           TEXT NOT NULL,
    horas_caida         REAL NOT NULL CHECK (horas_caida >= 0),
    causa               TEXT,
    estado              TEXT NOT NULL DEFAULT 'cerrada' CHECK (estado IN ('abierta','cerrada'))
);

CREATE TABLE solicitud (
    id_solicitud    INTEGER PRIMARY KEY,
    id_cliente      INTEGER NOT NULL REFERENCES cliente(id_cliente),
    id_servicio     INTEGER REFERENCES servicio_contratado(id_servicio),
    tipo            TEXT NOT NULL,                            -- cambio de datos, baja, información, etc.
    descripcion     TEXT NOT NULL,
    fecha_registro  TEXT NOT NULL,
    fecha_cierre    TEXT,
    estado          TEXT NOT NULL CHECK (estado IN ('abierta','en_proceso','cerrada')),
    id_responsable  INTEGER REFERENCES personal(id_personal)
);

-- ---------------------------------------------------------------------
-- 6. CASOS DEL AGENTE, AJUSTES Y SEGURIDAD
-- ---------------------------------------------------------------------
CREATE TABLE caso (
    id_caso          INTEGER PRIMARY KEY,
    id_cliente       INTEGER NOT NULL REFERENCES cliente(id_cliente),
    canal            TEXT NOT NULL CHECK (canal IN ('telegram','correo','manual')),
    opcion           TEXT CHECK (opcion IN ('A','B')),
    tipo_caso        TEXT NOT NULL,
    id_factura       INTEGER REFERENCES factura(id_factura),
    id_averia        INTEGER REFERENCES averia(id_averia),
    id_solicitud     INTEGER REFERENCES solicitud(id_solicitud),
    monto_discutido  REAL,                                    -- sin IGV
    tramo            INTEGER REFERENCES politica_tramo(id_tramo),
    estado           TEXT NOT NULL CHECK (estado IN ('abierto','derivado','escalado','resuelto','cerrado')),
    id_derivado_a    INTEGER REFERENCES personal(id_personal),
    sustento         TEXT,
    fecha_creacion   TEXT NOT NULL,
    fecha_cierre     TEXT
);

CREATE TABLE ajuste (
    id_ajuste        INTEGER PRIMARY KEY,
    id_caso          INTEGER REFERENCES caso(id_caso),
    id_factura       INTEGER NOT NULL REFERENCES factura(id_factura),
    id_averia        INTEGER REFERENCES averia(id_averia),
    tipo_documento   TEXT NOT NULL CHECK (tipo_documento IN ('nota_credito','nota_debito')),
    motivo           TEXT NOT NULL CHECK (motivo IN
                     ('duplicado','baja_facturada','tarifa_distinta','exceso_sin_sustento','sla_averia','gesto_comercial')),
    monto_sin_igv    REAL NOT NULL CHECK (monto_sin_igv > 0),
    igv              REAL NOT NULL,
    total            REAL NOT NULL,
    estado           TEXT NOT NULL CHECK (estado IN ('propuesto','aprobado','aplicado','rechazado')),
    id_aprobador     INTEGER REFERENCES personal(id_personal),
    fecha_creacion   TEXT NOT NULL,
    fecha_aplicacion TEXT
);

CREATE TABLE verificacion (
    id_verificacion INTEGER PRIMARY KEY,
    id_cliente      INTEGER REFERENCES cliente(id_cliente),   -- NULL si el RUC no existe
    ruc_ingresado   TEXT NOT NULL,
    codigo_hash     TEXT,
    fecha_envio     TEXT NOT NULL,
    fecha_expira    TEXT NOT NULL,
    intentos        INTEGER NOT NULL DEFAULT 0,
    estado          TEXT NOT NULL CHECK (estado IN ('pendiente','verificado','bloqueado','expirado'))
);

CREATE TABLE interaccion_log (
    id_log      INTEGER PRIMARY KEY,
    id_cliente  INTEGER REFERENCES cliente(id_cliente),
    id_caso     INTEGER REFERENCES caso(id_caso),
    fecha       TEXT NOT NULL,
    rol         TEXT NOT NULL CHECK (rol IN ('cliente','agente','sistema')),
    mensaje     TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- 7. DATOS DE REFERENCIA
-- ---------------------------------------------------------------------
INSERT INTO parametro VALUES
 ('fecha_actual','2026-12-05','Fecha de sistema ficticia para reproducir los casos'),
 ('igv','0.18','Tasa de IGV'),
 ('horas_mes','720','Horas del mes comercial (30 días x 24 h)'),
 ('dias_mes_comercial','30','Días del mes comercial para prorrateo'),
 ('plazo_atencion_dias','10','Plazo máximo de atención de solicitudes (días)'),
 ('max_intentos_codigo','3','Intentos permitidos del código de verificación'),
 ('vigencia_codigo_min','10','Vigencia del código de verificación (minutos)'),
 ('sesion_vigencia_min','30','Vigencia de la sesión verificada (minutos)'),
 ('gesto_max_monto','100','P6 (por validar): tope del gesto comercial, sin IGV (S/)'),
 ('gesto_max_por_mes','1','P6 (por validar): gestos por cliente y mes');

INSERT INTO politica_tramo VALUES
 (1,'Tramo 1: automático',          0,     100,   'Nota de crédito/débito automática, el agente informa al cliente','Sistema'),
 (2,'Tramo 2: ejecutivo',         100,    1000,   'Propuesta de ajuste; aprueba el ejecutivo de cuenta','Ejecutivo de cuenta'),
 (3,'Tramo 3: jefatura',         1000,   50000,   'Propuesta de ajuste; aprueba la jefatura de facturación','Jefatura de facturación'),
 (4,'Tramo 4: gerencia y finanzas',50000,  NULL,  'Escalamiento a gerencia y finanzas; el agente no promete nada','Gerencia y Finanzas');

-- ---------------------------------------------------------------------
-- 8. VISTAS DE DETECCION (una por casuística; reglas deterministas)
-- ---------------------------------------------------------------------

-- CS-01 / CS-02: factura duplicada (mismo cliente, periodo e importe)
CREATE VIEW v_facturas_duplicadas AS
SELECT f.id_cliente, f.periodo, f.subtotal,
       COUNT(*) AS n_facturas,
       MIN(f.id_factura) AS id_original,
       MAX(f.id_factura) AS id_duplicada,
       f.subtotal AS monto_a_acreditar
FROM factura f
WHERE f.estado <> 'anulada'
GROUP BY f.id_cliente, f.periodo, f.subtotal
HAVING COUNT(*) > 1;

-- CS-03: servicio dado de baja que se sigue facturando
CREATE VIEW v_servicios_baja_facturados AS
SELECT s.id_cliente, s.id_servicio, s.sede, s.fecha_baja,
       f.id_factura, f.periodo,
       SUM(l.monto) AS monto_a_acreditar
FROM servicio_contratado s
JOIN factura_linea l ON l.id_servicio = s.id_servicio
                    AND l.tipo IN ('cargo_mensual','prorrateo','exceso')
JOIN factura f ON f.id_factura = l.id_factura AND f.estado <> 'anulada'
WHERE s.fecha_baja IS NOT NULL
  AND f.periodo > substr(s.fecha_baja,1,7)
GROUP BY s.id_cliente, s.id_servicio, s.sede, s.fecha_baja, f.id_factura, f.periodo;

-- CS-04: tarifa facturada distinta a la pactada
CREATE VIEW v_tarifa_distinta AS
SELECT s.id_cliente, s.id_servicio, s.sede, f.id_factura, f.periodo,
       s.tarifa_pactada, l.precio_unitario AS tarifa_facturada, l.cantidad,
       ROUND((l.precio_unitario - s.tarifa_pactada) * l.cantidad, 2) AS diferencia
FROM factura_linea l
JOIN servicio_contratado s ON s.id_servicio = l.id_servicio
JOIN factura f ON f.id_factura = l.id_factura AND f.estado <> 'anulada'
WHERE l.tipo = 'cargo_mensual'
  AND ABS(l.precio_unitario - s.tarifa_pactada) > 0.005;

-- CS-05: exceso de consumo móvil sin sustento
CREATE VIEW v_exceso_sin_sustento AS
SELECT s.id_cliente, s.id_servicio, f.id_factura, f.periodo,
       l.cantidad AS gb_facturados, c.exceso_gb AS gb_reales,
       l.monto AS monto_a_acreditar
FROM factura_linea l
JOIN servicio_contratado s ON s.id_servicio = l.id_servicio
JOIN factura f ON f.id_factura = l.id_factura AND f.estado <> 'anulada'
LEFT JOIN consumo c ON c.id_servicio = l.id_servicio AND c.periodo = f.periodo
WHERE l.tipo = 'exceso'
  AND (c.exceso_gb IS NULL OR c.exceso_gb <= 0 OR ABS(l.cantidad - c.exceso_gb) > 0.05);

-- CS-06 / CS-07: avería con SLA incumplido sin compensación
CREATE VIEW v_averias_sin_compensar AS
WITH calc AS (
  SELECT a.id_averia, s.id_cliente, a.id_servicio, s.sede,
         a.unidades_afectadas, a.horas_caida, s.tarifa_pactada, s.sla_pactado,
         (1 - s.sla_pactado) * CAST((SELECT valor FROM parametro WHERE clave='horas_mes') AS REAL) AS tolerancia_h,
         substr(a.fecha_inicio,1,7) AS periodo
  FROM averia a
  JOIN servicio_contratado s ON s.id_servicio = a.id_servicio
  WHERE s.sla_pactado IS NOT NULL
)
SELECT id_averia, id_cliente, id_servicio, sede, periodo, unidades_afectadas,
       horas_caida, ROUND(tolerancia_h,2) AS tolerancia_h,
       ROUND(horas_caida - tolerancia_h,2) AS horas_fuera,
       ROUND(tarifa_pactada * unidades_afectadas *
             (horas_caida - tolerancia_h) /
             CAST((SELECT valor FROM parametro WHERE clave='horas_mes') AS REAL), 2) AS descuento_sin_igv
FROM calc c
WHERE horas_caida > tolerancia_h
  AND NOT EXISTS (SELECT 1 FROM ajuste j
                  WHERE j.id_averia = c.id_averia
                    AND j.estado IN ('propuesto','aprobado','aplicado'));

-- CS-08: solicitudes fuera de plazo
CREATE VIEW v_solicitudes_vencidas AS
SELECT * FROM (
  SELECT so.id_solicitud, so.id_cliente, so.tipo, so.estado, so.fecha_registro,
         CAST(julianday((SELECT valor FROM parametro WHERE clave='fecha_actual'))
              - julianday(so.fecha_registro) AS INTEGER) AS dias_abierta,
         c.plazo_atencion_dias, so.id_responsable
  FROM solicitud so
  JOIN cliente c ON c.id_cliente = so.id_cliente
  WHERE so.estado IN ('abierta','en_proceso')
) t
WHERE dias_abierta > plazo_atencion_dias;

-- CS-09: variación fuerte de facturación entre periodos (> 25 %)
CREATE VIEW v_variacion_facturacion AS
SELECT * FROM (
  SELECT id_cliente, periodo, subtotal,
         LAG(subtotal) OVER (PARTITION BY id_cliente ORDER BY periodo) AS subtotal_anterior
  FROM factura WHERE estado <> 'anulada'
) t
WHERE subtotal_anterior IS NOT NULL
  AND ABS(subtotal - subtotal_anterior) / subtotal_anterior > 0.25;

-- CS-12: gestos comerciales del mes actual (control de la política P6)
CREATE VIEW v_gestos_mes_actual AS
SELECT j.id_ajuste, c.id_cliente, j.monto_sin_igv, j.fecha_creacion
FROM ajuste j
JOIN factura f ON f.id_factura = j.id_factura
JOIN cliente c ON c.id_cliente = f.id_cliente
WHERE j.motivo = 'gesto_comercial'
  AND j.estado <> 'rechazado'
  AND substr(j.fecha_creacion,1,7) = (SELECT substr(valor,1,7) FROM parametro WHERE clave='fecha_actual');

-- Resumen mensual de facturación (para validar volumen)
CREATE VIEW v_resumen_facturacion AS
SELECT periodo, COUNT(*) AS facturas, ROUND(SUM(subtotal),2) AS subtotal, ROUND(SUM(total),2) AS total
FROM factura WHERE estado <> 'anulada' GROUP BY periodo;
