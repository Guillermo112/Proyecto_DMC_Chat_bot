# Anticipa – Base de datos SQLite (datos ficticios)

Base de datos del chatbot de interacción con clientes y prevención de reclamos de facturación B2B.
Todo es ficticio: RUC con prefijo 99 y fecha de sistema **2026-12-05**.

> **Correos de prueba:** los clientes 1-13 reciben el OTP en los correos del equipo definidos en
> `CORREO_PRUEBA_1`..`CORREO_PRUEBA_5` del `.env` de la raíz (no se versionan), en rotación:
>
> | Slot | Clientes |
> |---|---|
> | 1 | 1, 6, 11 |
> | 2 | 2, 7, 12 |
> | 3 | 3, 8, 13 |
> | 4 | 4, 9 |
> | 5 | 5, 10 |
>
> Un slot vacío, o `python3 generar_datos.py --publico`, deja esos clientes con `facturacion@clienteNN.example`.

## 1. Instalar SQLite
Para la consola y una interfaz gráfica:

- **Windows:** descarga `sqlite-tools-win-x64` desde https://www.sqlite.org/download.html, descomprime en `C:\sqlite` y agrega esa carpeta al PATH. Verifica con `sqlite3 --version`.
- **macOS:** ya viene instalado; si no, `brew install sqlite`.
- **Linux (Ubuntu/Debian):** `sudo apt install sqlite3`.
- **Interfaz gráfica (recomendada):** DB Browser for SQLite, https://sqlitebrowser.org. Abre el archivo `anticipa.db` con *Open Database*.

## 2. Usar la base

```bash
sqlite3 anticipa.db          # abre la consola
.tables                      # lista tablas y vistas
.schema cliente              # ver una tabla
.headers on
.mode column
SELECT * FROM v_resumen_facturacion;
.quit
```

## 3. Crearla desde cero

Opción A, solo con el esquema (queda vacía de datos de negocio):

```bash
sqlite3 nueva.db < schema.sql
```

Opción B, con todos los datos ficticios:

```bash
python3 generar_datos.py     # crea anticipa.db y valida; debe terminar en "Base creada"
```

Desde Python:

```python
import sqlite3
con = sqlite3.connect("anticipa.db")
con.execute("PRAGMA foreign_keys = ON")   # actívalo en cada conexión
con.row_factory = sqlite3.Row
for r in con.execute("SELECT * FROM v_averias_sin_compensar"):
    print(dict(r))
```

## 4. Modelo (resumen)

- **Maestros:** `producto`, `cliente`, `personal`, `servicio_contratado`
- **Facturación:** `factura`, `factura_linea`, `consumo`
- **Operación:** `averia`, `solicitud`
- **Agente:** `caso`, `ajuste`, `verificacion`, `interaccion_log`. `caso.canal`:
  `telegram` (el bot), `correo`, `manual` (cargado por una persona) o `web`
  (pruebas por web o API).
- **Reglas:** `parametro`, `politica_tramo`
- **Vistas de detección:** una por casuística (ver tabla siguiente)

| Casuística | Vista |
|---|---|
| CS-01 Factura duplicada | `v_facturas_duplicadas` |
| CS-02 Servicio de baja facturado | `v_servicios_baja_facturados` |
| CS-03 Tarifa distinta a la pactada | `v_tarifa_distinta` |
| CS-04 Exceso de consumo sin sustento | `v_exceso_sin_sustento` |
| CS-05 y CS-07 Avería con SLA incumplido | `v_averias_sin_compensar` |
| CS-06 Solicitud fuera de plazo | `v_solicitudes_vencidas` |
| CS-08 Gesto comercial (P6) | `v_gestos_mes_actual` |
| CS-09 Variación fuerte entre periodos | `v_variacion_facturacion` |

## 5. Consultas útiles

```sql
-- Facturación por mes
SELECT * FROM v_resumen_facturacion;

-- Datos de un cliente por RUC (identificación)
SELECT id_cliente, razon_social, correo_facturacion FROM cliente WHERE ruc = '<RUC>';

-- Detalle de una factura
SELECT l.tipo, l.concepto, l.cantidad, l.precio_unitario, l.monto
FROM factura_linea l JOIN factura f USING (id_factura)
WHERE f.numero = 'F001-000254';

-- Qué tramo corresponde a un monto sin IGV
SELECT nombre, aprobador_rol FROM politica_tramo
WHERE 4500 > monto_desde AND (monto_hasta IS NULL OR 4500 <= monto_hasta);
```

## 6. Reglas a respetar

- Los montos de los tramos van **sin IGV** (18 %).
- Facturación **mes vencido**: el periodo `2026-11` se emite el 2026-12-01 y vence 20 días después.
- Mes comercial de 30 días y 720 horas.
- El agente **no calcula montos con el modelo**: usa estas vistas y funciones determinísticas.
- No guardar códigos de verificación en claro: solo `codigo_hash`.
