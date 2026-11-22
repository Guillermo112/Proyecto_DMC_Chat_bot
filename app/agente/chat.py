"""El turno del chat: RAG previo, modelo con herramientas y memoria corta.

Misma metodología que `chat_service.py` de sesion7, con dos cambios por costo:

1. **El RAG se consulta antes de llamar al modelo**, no como herramienta. La
   búsqueda es local y gratis; si algún fragmento pasa el umbral se agrega como
   contexto. Así una pregunta de glosario no gasta una llamada extra al modelo.
2. **Tope de vueltas** (`CHAT_MAX_VUELTAS`): cada herramienta que el modelo pide
   cuesta una llamada más; el tope evita que un error encadene llamadas.

El `cliente_id` llega del token de sesión (lo pone la ruta) y se ata a las
herramientas: el modelo nunca lo elige. El historial guarda solo los textos del
usuario y del asistente (no los resultados de herramientas ni el contexto), y vive
en memoria: se pierde al reiniciar la API.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from app import config
from app.agente.prompt import SYSTEM_PROMPT
from app.data import facturacion
from app.llm import SinProveedores, crear_router
from app.tools import ESQUEMAS, Herramientas

log = logging.getLogger(__name__)

# Herramientas de solo lectura: si el modelo repite la misma llamada en el turno,
# se reutiliza el resultado (no se repite la consulta).
IDEMPOTENTES = frozenset({"ver_perfil", "listar_facturas", "ver_factura", "ver_saldo",
                          "detectar_anomalias", "ver_servicios", "comparar_periodos",
                          "consultar_solicitudes", "listar_casos"})
MAX_RESULTADO = 12000   # caracteres de un resultado de herramienta enviados al modelo
SIN_RESPUESTA = "No pude completar la respuesta. ¿Me lo repites con otras palabras?"

# Para el saludo: qué se encontró al revisar la cuenta (anomalías sin caso abierto).
ETIQUETAS_ANOMALIA = {
    "facturas_duplicadas": ("una factura duplicada", "facturas duplicadas"),
    "servicios_baja_facturados": ("un servicio dado de baja que se sigue facturando",
                                  "servicios dados de baja que se siguen facturando"),
    "tarifas_distintas": ("una tarifa distinta a la pactada", "tarifas distintas a las pactadas"),
    "excesos_sin_sustento": ("un exceso de consumo sin sustento", "excesos de consumo sin sustento"),
    "averias_sla_incumplido": ("una avería que superó el SLA", "averías que superaron el SLA"),
}
OPCIONES = "\n".join([
    "- revisar o explicar una factura",
    "- ver si hay cobros que no corresponden",
    "- consultar tu saldo y vencimientos",
    "- revisar tus solicitudes o tus casos",
])


class ChatNoDisponible(RuntimeError):
    """No hay modelo configurado o ningún endpoint respondió."""


@dataclass
class Turno:
    """Respuesta de un turno y su traza (lo que muestra el panel de la página)."""

    texto: str
    herramientas: list[dict[str, Any]] = field(default_factory=list)
    documentos: list[dict[str, Any]] = field(default_factory=list)
    llamadas: int = 0
    tokens: dict[str, int] = field(default_factory=lambda: {"entrada": 0, "salida": 0, "cache": 0})
    modelo: str = ""
    ms: int = 0
    aviso: str | None = None


def _resumen(resultado: dict[str, Any]) -> str:
    if "error" in resultado:
        return f"error: {resultado['error']}"
    for clave in ("numero_caso", "cantidad", "total", "comparable"):
        if clave in resultado:
            return f"{clave}={resultado[clave]}"
    listas = [f"{k}={len(v)}" for k, v in resultado.items() if isinstance(v, list)]
    return ", ".join(listas[:3]) or "ok"


class ServicioChat:
    """Un servicio por proceso; las conversaciones se separan por cliente y por id."""

    def __init__(self, router: Any = None, indice: Any = None,
                 herramientas: Callable[[int, str], Herramientas] = Herramientas) -> None:
        self._router = router
        self._indice = indice
        self._herramientas = herramientas
        self._conversaciones: OrderedDict[tuple[int, str], deque] = OrderedDict()
        self._candado = threading.Lock()

    # -- dependencias perezosas -------------------------------------------------
    def router(self) -> Any:
        if self._router is None:
            self._router = crear_router()
        return self._router

    def indice(self) -> Any:
        if self._indice is None:
            from app.rag.indice import obtener_indice

            self._indice = obtener_indice()
        return self._indice

    # -- memoria ----------------------------------------------------------------
    def _historial(self, clave: tuple[int, str]) -> deque:
        with self._candado:
            if clave not in self._conversaciones:
                self._conversaciones[clave] = deque(maxlen=config.CHAT_MAX_MENSAJES)
                while len(self._conversaciones) > config.CHAT_MAX_CONVERSACIONES:
                    self._conversaciones.popitem(last=False)
            self._conversaciones.move_to_end(clave)
            return self._conversaciones[clave]

    def reiniciar(self, cliente_id: int, conversacion_id: str) -> None:
        with self._candado:
            self._conversaciones.pop((cliente_id, conversacion_id), None)

    # -- saludo -----------------------------------------------------------------
    def saludar(self, cliente_id: int, conversacion_id: str) -> str:
        """Saludo al autenticarse: sin modelo (no cuesta tokens) y guardado en el historial,
        para que el modelo sepa qué se le preguntó al cliente si responde "sí".

        Revisa la cuenta antes de saludar (Anticipa se anticipa al reclamo): si hay
        anomalías sin caso abierto, las menciona y ofrece explicarlas.
        """
        self.reiniciar(cliente_id, conversacion_id)
        texto = self._texto_saludo(cliente_id)
        self._historial((cliente_id, conversacion_id)).append({"role": "assistant", "content": texto})
        return texto

    @staticmethod
    def _texto_saludo(cliente_id: int) -> str:
        try:
            cliente = facturacion.obtener_cliente(cliente_id)
            anomalias = facturacion.detectar_anomalias(cliente_id)
        except Exception as exc:  # noqa: BLE001 - un saludo genérico es mejor que ninguno
            log.warning("chat.saludo_sin_datos %s: %s", type(exc).__name__, exc)
            return "¡Hola! Soy Anticipa, tu asistente de facturación. ¿Qué quieres hacer hoy? Puedo:\n" + OPCIONES
        nombre = (cliente.contacto_nombre or "").split()[0] if cliente and cliente.contacto_nombre else ""
        inicio = (f"¡Hola{', ' + nombre if nombre else ''}! Soy Anticipa, tu asistente de facturación "
                  f"({cliente.razon_social}).")
        hallazgos, en_revision = [], set()
        for campo, (uno, varios) in ETIQUETAS_ANOMALIA.items():
            todas = getattr(anomalias, campo)
            en_revision |= {a.caso_abierto for a in todas if getattr(a, "caso_abierto", None)}
            pendientes = [a for a in todas if not getattr(a, "caso_abierto", None)]
            if len(pendientes) == 1:
                hallazgos.append(uno)
            elif pendientes:
                hallazgos.append(f"{len(pendientes)} {varios}")
        if en_revision:
            casos_txt = ", ".join(sorted(en_revision))
            inicio += (f" Tu caso {casos_txt} sigue en revisión con tu ejecutivo." if len(en_revision) == 1
                       else f" Tus casos {casos_txt} siguen en revisión con tu ejecutivo.")
        if hallazgos:
            lista = hallazgos[0] if len(hallazgos) == 1 else ", ".join(hallazgos[:-1]) + " y " + hallazgos[-1]
            return (f"{inicio}\n\nAntes de empezar: revisé tu cuenta y encontré {lista} que conviene "
                    "revisar. ¿Quieres que te lo explique, o prefieres consultar otra cosa?")
        return f"{inicio}\n\n¿Qué quieres hacer hoy? Puedo:\n{OPCIONES}"

    # -- RAG previo -------------------------------------------------------------
    def _contexto(self, mensaje: str) -> tuple[str, list[dict[str, Any]], str | None]:
        try:
            hallazgos = self.indice().buscar(mensaje)
        except Exception as exc:  # noqa: BLE001 - sin RAG el chat sigue con herramientas
            log.warning("chat.rag_no_disponible %s: %s", type(exc).__name__, exc)
            return "", [], "Documentos no disponibles en este momento."
        if not hallazgos:
            return "", [], None
        texto = "\n\n".join(
            f"[{h['fuente']}" + (f", pág. {h['pagina']}" if h.get("pagina") else "") + f"]\n{h['texto']}"
            for h in hallazgos
        )
        documentos = [{k: h.get(k) for k in ("id", "fuente", "pagina", "seccion", "score", "texto")}
                      for h in hallazgos]
        return texto, documentos, None

    # -- turno ------------------------------------------------------------------
    def responder(self, cliente_id: int, conversacion_id: str, mensaje: str) -> Turno:
        inicio = time.perf_counter()
        historial = self._historial((cliente_id, conversacion_id))
        contexto, documentos, aviso = self._contexto(mensaje)

        mensajes: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *historial]
        if contexto:
            mensajes.append({"role": "system", "content":
                             "Contexto de documentos (políticas y glosario; no son datos del cliente):\n\n"
                             + contexto})
        mensajes.append({"role": "user", "content": mensaje})

        turno = Turno(texto="", documentos=documentos, aviso=aviso)
        herramientas = self._herramientas(cliente_id, mensaje)
        cache: dict[str, dict[str, Any]] = {}
        try:
            texto = self._bucle(mensajes, herramientas, cache, turno)
        except SinProveedores as exc:
            raise ChatNoDisponible(str(exc).splitlines()[0]) from exc

        turno.texto = texto
        turno.ms = int((time.perf_counter() - inicio) * 1000)
        historial.append({"role": "user", "content": mensaje})
        historial.append({"role": "assistant", "content": texto})
        log.info("chat.turno cliente=%s herramientas=%s documentos=%s llamadas=%s tokens=%s ms=%s",
                 cliente_id, [h["nombre"] for h in turno.herramientas], len(documentos),
                 turno.llamadas, turno.tokens, turno.ms)
        return turno

    def _llamar(self, mensajes: list[dict[str, Any]], turno: Turno, con_herramientas: bool) -> Any:
        resp = self.router().chat(mensajes, tools=ESQUEMAS if con_herramientas else None,
                                  temperature=config.CHAT_TEMPERATURA,
                                  max_tokens=config.CHAT_MAX_TOKENS)
        turno.llamadas += 1
        turno.modelo = resp.modelo or turno.modelo
        uso = resp.uso or {}
        turno.tokens["entrada"] += int(uso.get("prompt_tokens", 0) or 0)
        turno.tokens["salida"] += int(uso.get("completion_tokens", 0) or 0)
        # DeepSeek informa cuánto del prompt salió de su caché (se cobra más barato).
        turno.tokens["cache"] += int(uso.get("prompt_cache_hit_tokens", 0) or 0)
        return resp

    def _bucle(self, mensajes: list[dict[str, Any]], herramientas: Herramientas,
               cache: dict[str, dict[str, Any]], turno: Turno) -> str:
        for _ in range(config.CHAT_MAX_VUELTAS):
            resp = self._llamar(mensajes, turno, con_herramientas=True)
            if not resp.tool_calls:
                return (resp.texto or "").strip() or SIN_RESPUESTA
            mensajes.append({
                "role": "assistant", "content": resp.texto or "",
                "tool_calls": [{"id": tc["id"], "type": "function",
                                "function": {"name": tc["name"],
                                             "arguments": json.dumps(tc.get("arguments") or {},
                                                                     ensure_ascii=False)}}
                               for tc in resp.tool_calls],
            })
            for tc in resp.tool_calls:
                nombre, argumentos = tc["name"], tc.get("arguments") or {}
                firma = nombre + json.dumps(argumentos, sort_keys=True, ensure_ascii=False)
                t0 = time.perf_counter()
                if nombre in IDEMPOTENTES and firma in cache:
                    resultado = cache[firma]
                else:
                    resultado = herramientas.ejecutar(nombre, argumentos)
                    if nombre in IDEMPOTENTES:
                        cache[firma] = resultado
                contenido = json.dumps(resultado, ensure_ascii=False, default=str)
                turno.herramientas.append({
                    "nombre": nombre,
                    "argumentos": {k: v for k, v in argumentos.items() if k != "cliente_id"},
                    "ok": "error" not in resultado,
                    "ms": int((time.perf_counter() - t0) * 1000),
                    "resumen": _resumen(resultado),
                    "resultado": contenido[:1500],
                })
                mensajes.append({"role": "tool", "tool_call_id": tc["id"], "name": nombre,
                                 "content": contenido[:MAX_RESULTADO]})
        # Se acabaron las vueltas: una última llamada sin herramientas para cerrar.
        resp = self._llamar(mensajes, turno, con_herramientas=False)
        return (resp.texto or "").strip() or SIN_RESPUESTA


_servicio: ServicioChat | None = None
_candado_servicio = threading.Lock()


def obtener_servicio() -> ServicioChat:
    global _servicio
    if _servicio is None:
        with _candado_servicio:
            if _servicio is None:
                _servicio = ServicioChat()
    return _servicio
