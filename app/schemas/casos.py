"""Modelos de registrar y derivar caso (modo A): POST y GET /mi/casos."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Tipos que vienen de una anomalía detectada (/mi/anomalias): el servidor la busca,
# toma de ella la referencia y el monto, y rechaza el registro si no existe.
TipoCasoAnomalia = Literal[
    "factura_duplicada",        # CS-01
    "servicio_baja_facturado",  # CS-02
    "tarifa_distinta",          # CS-03
    "exceso_sin_sustento",      # CS-04
    "sla_averia",               # CS-05 / CS-07
]
# Tipos sin anomalía: se registran con las palabras del cliente y referencias opcionales.
TipoCasoLibre = Literal[
    "solicitud_fuera_de_plazo",  # CS-06 (exige id_solicitud fuera de plazo)
    "gesto_comercial",           # CS-08: en modo A no se aplica, se registra y deriva
    "alta_no_solicitada",        # CS-09: el cliente dice que no pidió el alta
    "fuera_de_alcance",          # CS-13
    "consulta_no_resuelta",      # §1: sin anomalía y el cliente insiste
    "solicitud_datos",           # FAQ: cambiar correo de facturación, copia de factura
    "contacto_persona",          # FAQ: "¿puedo hablar con una persona?"
]
TipoCaso = Literal[TipoCasoAnomalia, TipoCasoLibre]
Canal = Literal["telegram", "web"]
EstadoCaso = Literal["abierto", "derivado", "escalado", "resuelto", "cerrado"]
ResultadoAviso = Literal["enviado", "no_enviado", "fallido"]


class ReferenciasCaso(BaseModel):
    """A qué se refiere el caso. Todo se valida contra el cliente del token."""
    numero_factura: str | None = Field(None, max_length=20, description="p. ej. F001-000254")
    periodo: str | None = Field(None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$", description="AAAA-MM")
    id_servicio: int | None = Field(None, gt=0)
    id_averia: int | None = Field(None, gt=0)
    id_solicitud: int | None = Field(None, gt=0)


class NuevoCaso(BaseModel):
    tipo: TipoCaso
    canal: Canal = Field(..., description="telegram (el bot) o web (pruebas por web o API)")
    palabras_cliente: str = Field(..., min_length=1, max_length=2000,
                                  description="Lo que pidió el cliente, con sus palabras (CS-13)")
    resumen: str | None = Field(None, max_length=1000, description="Lo que entendió el agente")
    referencias: ReferenciasCaso = Field(default_factory=ReferenciasCaso)

    @field_validator("palabras_cliente", "resumen")
    @classmethod
    def _sin_espacios_sobrantes(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        valor = valor.strip()
        if not valor:
            raise ValueError("no puede estar vacío")
        return valor


class CasoRegistrado(BaseModel):
    """Respuesta de POST /mi/casos.

    `ya_existia=True`: había un caso abierto equivalente y se devuelve ese (no se
    crea otro ni se reenvía el aviso). `aviso` dice si salió el correo de prueba;
    el caso queda registrado en cualquier caso.
    """
    numero_caso: str
    tipo: TipoCaso
    estado: EstadoCaso
    ya_existia: bool
    derivado_a_nombre: str | None
    monto_discutido: float | None  # sin IGV; solo en tipos de anomalía, tomado de /mi/anomalias
    fecha_creacion: str
    aviso: ResultadoAviso


class CasoResumen(BaseModel):
    numero_caso: str
    tipo: str  # texto libre en la base: incluye tipos sembrados del modo B
    canal: str
    estado: EstadoCaso
    fecha_creacion: str
    fecha_cierre: str | None
    derivado_a_nombre: str | None
    monto_discutido: float | None
    numero_factura: str | None
    id_averia: int | None
    id_solicitud: int | None
    resumen: str | None


class ListaCasos(BaseModel):
    casos: list[CasoResumen]
