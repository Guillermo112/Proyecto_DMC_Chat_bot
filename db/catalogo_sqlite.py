"""
Catálogo de Anticipa conectado a SQLite (reemplaza el catálogo de productos del ejercicio).

Qué cambia respecto a un catálogo de tienda:
  antes:  buscar_producto(nombre) -> precio, stock
  ahora:  consultas por CLIENTE verificado -> facturas, servicios, anomalías, solicitudes
La base se lee en SOLO LECTURA. El modelo nunca recibe el id_cliente de un usuario sin verificar:
lo inyecta el código desde la sesión (ver ejecutar_herramienta).

Configuración en .env (ver .env.example):  DB_PATH, MODO_AGENTE
"""
import os
import sqlite3
from pathlib import Path

try:
    from dotenv import load_dotenv  # pip install python-dotenv
    load_dotenv()
except ImportError:                 # funciona también con variables de entorno del sistema
    pass

AQUI = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", "anticipa.db"))
if not DB_PATH.is_absolute():
    DB_PATH = AQUI / DB_PATH
MODO_AGENTE = os.getenv("MODO_AGENTE", "A").upper()   # A = consultas, B = consultas + prevención


def get_conn() -> sqlite3.Connection:
    """Conexión de solo lectura (el agente escribe solo a través de funciones específicas)."""
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _filas(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


# ---------------------------------------------------------------- consultas
def buscar_cliente_por_ruc(ruc: str) -> dict | None:
    """Solo para el flujo de identificación. Devuelve id, razón social y correo del cliente."""
    f = _filas("SELECT id_cliente, razon_social, correo_facturacion, id_ejecutivo "
               "FROM cliente WHERE ruc = ? AND estado = 'activo'", (ruc.strip(),))
    return f[0] if f else None


def catalogo_productos() -> list[dict]:
    return _filas("SELECT codigo, nombre, descripcion, unidad, tarifa_mensual, sla_disponibilidad "
                  "FROM producto ORDER BY codigo")


def obtener_servicios(id_cliente: int) -> list[dict]:
    return _filas("""SELECT s.id_servicio, p.nombre AS producto, s.sede, s.cantidad, s.tarifa_pactada,
                            s.sla_pactado, s.fecha_activacion, s.fecha_baja, s.estado
                     FROM servicio_contratado s JOIN producto p ON p.codigo = s.codigo_producto
                     WHERE s.id_cliente = ? ORDER BY s.id_servicio""", (id_cliente,))


def listar_facturas(id_cliente: int, limite: int = 6) -> list[dict]:
    return _filas("""SELECT numero, periodo, fecha_emision, fecha_vencimiento, subtotal, igv, total, estado
                     FROM factura WHERE id_cliente = ? ORDER BY periodo DESC, id_factura LIMIT ?""",
                  (id_cliente, limite))


def obtener_factura(id_cliente: int, periodo: str) -> list[dict]:
    """Cabecera y líneas. Puede devolver 2 facturas si el periodo está duplicado."""
    facturas = _filas("""SELECT id_factura, numero, periodo, fecha_emision, fecha_vencimiento,
                                subtotal, igv, total, estado
                         FROM factura WHERE id_cliente = ? AND periodo = ? ORDER BY id_factura""",
                      (id_cliente, periodo))
    for f in facturas:
        f["lineas"] = _filas("""SELECT tipo, concepto, cantidad, precio_unitario, monto
                                FROM factura_linea WHERE id_factura = ?""", (f["id_factura"],))
    return facturas


def consultar_solicitudes(id_cliente: int) -> list[dict]:
    return _filas("""SELECT id_solicitud, tipo, descripcion, fecha_registro, estado,
                            CAST(julianday((SELECT valor FROM parametro WHERE clave='fecha_actual'))
                                 - julianday(fecha_registro) AS INTEGER) AS dias_desde_registro
                     FROM solicitud WHERE id_cliente = ? ORDER BY fecha_registro DESC""", (id_cliente,))


VISTAS = {  # casuística -> vista de detección
    "factura_duplicada": "v_facturas_duplicadas",
    "servicio_baja_facturado": "v_servicios_baja_facturados",
    "tarifa_distinta": "v_tarifa_distinta",
    "exceso_sin_sustento": "v_exceso_sin_sustento",
    "averia_sla": "v_averias_sin_compensar",
    "solicitud_vencida": "v_solicitudes_vencidas",
    "variacion_facturacion": "v_variacion_facturacion",
}


def detectar_anomalias(id_cliente: int) -> list[dict]:
    """Consulta todas las vistas de detección para el cliente. Los montos ya vienen calculados."""
    hallazgos = []
    for tipo, vista in VISTAS.items():
        for fila in _filas(f"SELECT * FROM {vista} WHERE id_cliente = ?", (id_cliente,)):
            fila["tipo_hallazgo"] = tipo
            hallazgos.append(fila)
    return hallazgos


def tramo_para(monto_sin_igv: float) -> dict:
    f = _filas("""SELECT id_tramo, nombre, aprobador_rol FROM politica_tramo
                  WHERE ? > monto_desde AND (monto_hasta IS NULL OR ? <= monto_hasta)
                  ORDER BY id_tramo LIMIT 1""", (monto_sin_igv, monto_sin_igv))
    if not f:  # monto <= 0 o justo en el borde inferior del tramo 1
        f = _filas("SELECT id_tramo, nombre, aprobador_rol FROM politica_tramo WHERE id_tramo = 1")
    return f[0]


# ---------------------------------------------------------------- herramientas para el LLM
HERRAMIENTAS = [  # formato tool use de Anthropic; NO incluyen id_cliente (sale de la sesión)
    {"name": "obtener_servicios",
     "description": "Lista los servicios contratados del cliente verificado: producto, sede, cantidad, "
                    "tarifa pactada, SLA, fecha de alta y de baja.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "listar_facturas",
     "description": "Lista las últimas facturas del cliente verificado con periodo, importes y estado.",
     "input_schema": {"type": "object", "properties": {"limite": {"type": "integer", "default": 6}}}},
    {"name": "obtener_factura",
     "description": "Devuelve la factura de un periodo (AAAA-MM) con todas sus líneas.",
     "input_schema": {"type": "object", "properties": {"periodo": {"type": "string", "description": "AAAA-MM"}},
                      "required": ["periodo"]}},
    {"name": "detectar_anomalias",
     "description": "Busca posibles errores de facturación del cliente verificado (duplicados, bajas "
                    "facturadas, tarifa distinta, exceso sin sustento, averías sin compensar, "
                    "solicitudes vencidas, variaciones). Los montos ya vienen calculados.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "consultar_solicitudes",
     "description": "Lista las solicitudes del cliente y los días transcurridos desde su registro.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "tramo_para",
     "description": "Indica el tramo de aprobación y quién decide para un monto SIN IGV.",
     "input_schema": {"type": "object", "properties": {"monto_sin_igv": {"type": "number"}},
                      "required": ["monto_sin_igv"]}},
]

_DESPACHO = {
    "obtener_servicios": lambda cid, a: obtener_servicios(cid),
    "listar_facturas": lambda cid, a: listar_facturas(cid, int(a.get("limite", 6))),
    "obtener_factura": lambda cid, a: obtener_factura(cid, a["periodo"]),
    "detectar_anomalias": lambda cid, a: detectar_anomalias(cid),
    "consultar_solicitudes": lambda cid, a: consultar_solicitudes(cid),
    "tramo_para": lambda cid, a: tramo_para(float(a["monto_sin_igv"])),
}


def ejecutar_herramienta(nombre: str, argumentos: dict, id_cliente_sesion: int):
    """El id_cliente SIEMPRE viene de la sesión verificada, nunca de lo que escriba el usuario."""
    if nombre not in _DESPACHO:
        return {"error": f"Herramienta desconocida: {nombre}"}
    return _DESPACHO[nombre](id_cliente_sesion, argumentos)


if __name__ == "__main__":  # prueba rápida:  python catalogo_sqlite.py
    print("Base:", DB_PATH, "| Modo:", MODO_AGENTE)
    cli = buscar_cliente_por_ruc("99987168976")
    print("Cliente:", cli["razon_social"])
    for h in detectar_anomalias(cli["id_cliente"]):
        print("Hallazgo:", h["tipo_hallazgo"], h.get("descuento_sin_igv"))
    print("Tramo S/ 464:", tramo_para(464)["nombre"])
