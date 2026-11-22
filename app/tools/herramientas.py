"""Herramientas del agente: los datos del cliente, nunca del modelo.

Cada herramienta envuelve una función de `app/data` (las mismas que usa la API
`/mi`). Se llaman en el mismo proceso: no hay costo de red ni de tokens extra.

Reglas (ver `PENDIENTES_rag.md`, sección 2, y `docs/casuisticas_api.md`):

- El `cliente_id` lo pone el código desde la sesión (`Herramientas(cliente_id)`),
  **nunca** el modelo: ningún esquema lo declara y, si el modelo lo manda, se ignora.
- Los argumentos que el modelo envía se filtran a los del esquema.
- Un error (dato inválido, factura de otro cliente, caso sin anomalía) vuelve como
  `{"error": ...}` para que el modelo lo explique, sin romper el turno.
- `registrar_caso` usa siempre el canal `web` y, si el modelo no las pasa, las
  palabras del cliente del turno actual.
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from app.data import casos, facturacion
from app.schemas.casos import NuevoCaso

# Esquemas en el formato del router (nombre, descripción, parámetros JSON Schema).
# Descripciones cortas: cada palabra se paga en cada llamada al modelo.
_PERIODO = {"type": "string", "description": "Mes facturado, AAAA-MM (2026-10 = octubre)"}

ESQUEMAS: list[dict[str, Any]] = [
    {
        "name": "ver_perfil",
        "description": "Datos de la empresa del cliente y de su ejecutivo de cuenta.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "listar_facturas",
        "description": "Facturas del cliente, de la más reciente a la más antigua. "
                       "Para 'la factura de octubre' usar periodo=2026-10.",
        "parameters": {"type": "object", "properties": {
            "periodo": _PERIODO,
            "estado": {"type": "string", "enum": ["emitida", "pagada", "vencida", "en_disputa", "anulada"]},
        }},
    },
    {
        "name": "ver_factura",
        "description": "Cabecera y líneas de una factura por su número (p. ej. F001-000254).",
        "parameters": {"type": "object", "properties": {
            "numero": {"type": "string"}}, "required": ["numero"]},
    },
    {
        "name": "ver_saldo",
        "description": "Saldo pendiente: facturas emitidas, vencidas o en disputa, con vencimientos (CS-11).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "detectar_anomalias",
        "description": "Cobros que no corresponden: factura duplicada, servicio de baja facturado, "
                       "tarifa distinta, exceso sin sustento, avería con SLA incumplido "
                       "(CS-01 a CS-05, CS-07). Montos observados sin IGV.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "ver_servicios",
        "description": "Servicios contratados con tarifa pactada, SLA, fecha de alta y de baja.",
        "parameters": {"type": "object", "properties": {
            "estado": {"type": "string", "enum": ["activo", "baja"]}}},
    },
    {
        "name": "comparar_periodos",
        "description": "Qué cambió entre dos meses facturados (por qué subió la factura, CS-09/CS-10). "
                       "Si comparable=false, explicar el motivo y no comparar.",
        "parameters": {"type": "object", "properties": {
            "periodo_b": _PERIODO,
            "periodo_a": {"type": "string", "description": "Mes anterior a comparar; por defecto el previo"},
        }, "required": ["periodo_b"]},
    },
    {
        "name": "consultar_solicitudes",
        "description": "Solicitudes del cliente con días transcurridos y si están fuera de plazo (CS-06).",
        "parameters": {"type": "object", "properties": {
            "estado": {"type": "string", "enum": ["abierta", "en_proceso", "cerrada"]}}},
    },
    {
        "name": "registrar_caso",
        "description": "Registra el caso y lo deriva al ejecutivo (modo A). Usar cuando hay una "
                       "anomalía confirmada, el cliente pide algo fuera de alcance, un descuento o "
                       "hablar con una persona. Devuelve el número de caso para dárselo al cliente.",
        "parameters": {"type": "object", "properties": {
            "tipo": {"type": "string", "enum": [
                "factura_duplicada", "servicio_baja_facturado", "tarifa_distinta",
                "exceso_sin_sustento", "sla_averia", "solicitud_fuera_de_plazo",
                "gesto_comercial", "alta_no_solicitada", "fuera_de_alcance",
                "consulta_no_resuelta", "solicitud_datos", "contacto_persona"]},
            "resumen": {"type": "string", "description": "Qué entendiste, en una o dos frases"},
            "numero_factura": {"type": "string"},
            "periodo": _PERIODO,
            "id_servicio": {"type": "integer"},
            "id_averia": {"type": "integer"},
            "id_solicitud": {"type": "integer"},
        }, "required": ["tipo"]},
    },
    {
        "name": "listar_casos",
        "description": "Casos registrados del cliente y su estado ('¿cómo va mi caso?').",
        "parameters": {"type": "object", "properties": {}},
    },
]

NOMBRES = frozenset(e["name"] for e in ESQUEMAS)
_PERMITIDOS = {e["name"]: set(e["parameters"]["properties"]) for e in ESQUEMAS}
_REFERENCIAS = ("numero_factura", "periodo", "id_servicio", "id_averia", "id_solicitud")


def _json(valor: Any) -> Any:
    if isinstance(valor, BaseModel):
        return valor.model_dump(mode="json")
    return valor


class Herramientas:
    """Herramientas atadas a un cliente ya verificado."""

    def __init__(self, cliente_id: int, palabras_cliente: str = "") -> None:
        if not isinstance(cliente_id, int) or cliente_id <= 0:
            raise ValueError("cliente_id inválido")
        self._cliente_id = cliente_id
        self._palabras = palabras_cliente

    def _registrar_caso(self, tipo: str, resumen: str | None = None, **referencias: Any) -> Any:
        nuevo = NuevoCaso(
            tipo=tipo, canal="web",
            palabras_cliente=(self._palabras or resumen or tipo)[:2000],
            resumen=resumen,
            referencias={k: v for k, v in referencias.items() if k in _REFERENCIAS and v not in (None, "")},
        )
        return casos.registrar_caso(self._cliente_id, nuevo)

    def _funciones(self) -> dict[str, Callable[..., Any]]:
        c = self._cliente_id
        return {
            "ver_perfil": lambda: facturacion.obtener_cliente(c),
            "listar_facturas": lambda periodo=None, estado=None:
                facturacion.listar_facturas(c, estado=estado, limite=6, periodo=periodo),
            "ver_factura": lambda numero: facturacion.detalle_factura(c, numero),
            "ver_saldo": lambda: facturacion.saldo_pendiente(c),
            "detectar_anomalias": lambda: facturacion.detectar_anomalias(c),
            "ver_servicios": lambda estado=None: facturacion.obtener_servicios(c, estado),
            "comparar_periodos": lambda periodo_b, periodo_a=None:
                facturacion.comparar_periodos(c, periodo_b, periodo_a),
            "consultar_solicitudes": lambda estado=None: facturacion.consultar_solicitudes(c, estado),
            "registrar_caso": self._registrar_caso,
            "listar_casos": lambda: casos.listar_casos(c),
        }

    def ejecutar(self, nombre: str, argumentos: dict[str, Any] | None) -> dict[str, Any]:
        """Ejecuta una herramienta. Siempre devuelve un dict serializable."""
        if nombre not in NOMBRES:
            return {"error": f"Herramienta desconocida: {nombre}"}
        # Solo los argumentos del esquema: un 'cliente_id' del modelo se descarta aquí.
        args = {k: v for k, v in (argumentos or {}).items() if k in _PERMITIDOS[nombre]}
        try:
            resultado = self._funciones()[nombre](**args)
        except (ValueError, LookupError, TypeError, ValidationError) as exc:
            return {"error": str(exc).splitlines()[0][:300]}
        if resultado is None:
            return {"error": "No encontrado para este cliente."}
        datos = _json(resultado)
        return datos if isinstance(datos, dict) else {"resultado": datos}
