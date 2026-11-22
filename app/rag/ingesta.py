"""Ingesta del RAG: fuentes → fragmentos de texto con metadatos.

Fuentes (ver `PENDIENTES_rag.md`, sección 3):

- PDF de `docs/` listados en `RAG_PDFS`: `app/rag/pdf.py` separa prosa y tablas.
  La prosa se corta por oraciones con solape; cada fila de tabla es un fragmento.
- `catalogo.json`: **lista blanca** de campos por sección, un fragmento por
  registro. Un campo nuevo en el JSON no entra hasta autorizarlo aquí.
- `faq.json` **no** entra: va a su propio clasificador.

Después de armar los fragmentos se aplica el **control de modo B** (fuera de
alcance): en los JSON, una marca hace fallar la ingesta (`ContenidoModoB`); en
los PDF se quita la oración, la celda o la columna marcada, y se registra en el log.

Esta capa no consulta la base ni recibe `cliente_id`: el RAG nunca es fuente de
un monto, fecha o estado del cliente.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app import config
from app.rag import pdf

log = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)  # avisos de fuentes de los PDF


@dataclass(frozen=True)
class Fragmento:
    """Unidad que se indexa y se cita."""

    id: str
    fuente: str          # nombre del archivo
    seccion: str         # "pdf" o la sección del JSON
    texto: str
    pagina: int | None = None  # solo PDF

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "fuente": self.fuente, "seccion": self.seccion,
                "pagina": self.pagina, "texto": self.texto}


# ---------------------------------------------------------------------------
# Control de modo B
# ---------------------------------------------------------------------------
# Formas verbales amplias (\w*): "emite/emito/se emite", "aplica/aplicas", "propone/propones".
MARCAS_MODO_B: tuple[str, ...] = (
    r"\bopci[oó]n\s+b\b",
    r"\bmodo\s+b\b",
    r"\b(?:emit|aplic)\w*\s+la\s+nota",
    r"\b(?:propon|calcul|aplic)\w*\s+el\s+ajuste",
    r"\bcalcular_ajuste\b",
    r"\baplic\w*\s+el\s+gesto",
    r"\bpuedo\s+aplicar",
    r"\bseg[uú]n\s+el\s+tramo",
)
_RE_MODO_B = re.compile("|".join(MARCAS_MODO_B), re.IGNORECASE)


class ContenidoModoB(ValueError):
    """Un texto de una fuente controlada (JSON) describe acciones del modo B."""


def marcas_modo_b(texto: str) -> list[str]:
    """Frases del modo B presentes en el texto (vacío = limpio)."""
    return [m.group(0) for m in _RE_MODO_B.finditer(texto)]


def _exigir_modo_a(fragmentos: Iterable[Fragmento]) -> None:
    for f in fragmentos:
        marcas = marcas_modo_b(f.texto)
        if marcas:
            raise ContenidoModoB(
                f"{f.fuente} [{f.seccion}/{f.id}] describe acciones del modo B: {marcas}. "
                "Reescribe el texto o quítalo de la lista blanca de app/rag/ingesta.py."
            )


# ---------------------------------------------------------------------------
# catalogo.json: lista blanca por sección
# ---------------------------------------------------------------------------
# Políticas de `agente.politicas` que no entran (P6 es solo modo B).
POLITICAS_EXCLUIDAS = frozenset({"gesto_comercial"})


def _num(valor: float) -> str:
    """99.5 -> '99,5'; 100.0 -> '100' (formato de los documentos)."""
    texto = f"{valor:,.2f}".rstrip("0").rstrip(".")
    return texto.replace(",", " ").replace(".", ",")


def _casuistica(r: dict[str, Any]) -> Fragmento:
    return Fragmento(
        id=r["codigo"], fuente="", seccion="casuisticas",
        texto=(f"{r['codigo']} · {r['nombre']} (categoría: {r['categoria']}). "
               f"Qué hace Anticipa: {r['opcion_a']}"),
    )


def _servicio(r: dict[str, Any]) -> Fragmento:
    texto = f"Servicio {r['nombre']}: {r['specs']}. Se cobra {r['unidad_cobro']}."
    if r.get("sla_pct") is not None:  # el móvil no tiene SLA
        texto += f" SLA {_num(r['sla_pct'])} %"
        if r.get("tolerancia_horas_mes") is not None:
            texto += f" (tolerancia de {_num(r['tolerancia_horas_mes'])} horas al mes)"
        texto += "."
    if r.get("nota"):
        texto += f" {r['nota']}"
    return Fragmento(id=r["codigo"], fuente="", seccion="servicios", texto=texto)


def _tramo(r: dict[str, Any]) -> Fragmento:
    desde, hasta = r["monto_desde_sin_igv"], r.get("monto_hasta_sin_igv")
    rango = (f"desde S/ {_num(desde)} hasta S/ {_num(hasta)} sin IGV" if hasta is not None
             else f"más de S/ {_num(desde)} sin IGV")
    return Fragmento(
        id=r["codigo"], fuente="", seccion="tramos",
        texto=f"Tramo de aprobación {r['nombre']}: ajustes {rango}. Aprueba: {r['aprueba']}.",
    )


def fragmentos_catalogo(datos: dict[str, Any], fuente: str = "catalogo.json") -> list[Fragmento]:
    """Proyecta el catálogo con la lista blanca y exige que quede en modo A."""
    crudos: list[Fragmento] = []
    crudos += [_casuistica(r) for r in datos.get("casuisticas", [])]
    crudos += [_servicio(r) for r in datos.get("servicios", [])]
    crudos += [_tramo(r) for r in datos.get("tramos", [])]
    politicas = (datos.get("agente") or {}).get("politicas") or {}
    crudos += [
        Fragmento(id=f"politica-{clave}", fuente="", seccion="politicas",
                  texto=f"Política ({clave.replace('_', ' ')}): {texto}")
        for clave, texto in politicas.items() if clave not in POLITICAS_EXCLUIDAS
    ]
    fragmentos = [Fragmento(f.id, fuente, f.seccion, f.texto) for f in crudos]
    _exigir_modo_a(fragmentos)
    return fragmentos


def leer_catalogo(ruta: Path) -> list[Fragmento]:
    with open(ruta, encoding="utf-8") as fh:
        return fragmentos_catalogo(json.load(fh), fuente=ruta.name)


# ---------------------------------------------------------------------------
# PDF: oraciones agrupadas con solape (como sesion7, sin spaCy)
# ---------------------------------------------------------------------------
_RE_FRONTERA = re.compile(r"(?<=[.!?…])\s+(?=[¿¡A-ZÁÉÍÓÚÑ0-9])")
_RE_ABREVIATURA = re.compile(
    r"(?:\b(?:dr|dra|sr|sra|srta|ing|lic|prof|etc|s\.a|n|num|pág|pag|art|inc|cap|fig)\.)$",
    re.IGNORECASE,
)
MIN_PALABRAS = 12  # un trozo de 3 palabras no responde nada


def dividir_oraciones(texto: str) -> list[str]:
    limpio = " ".join(texto.split())
    oraciones: list[str] = []
    for o in (x.strip() for x in _RE_FRONTERA.split(limpio)):
        if not o:
            continue
        if oraciones and _RE_ABREVIATURA.search(oraciones[-1]):
            oraciones[-1] = f"{oraciones[-1]} {o}"
        else:
            oraciones.append(o)
    return oraciones


def trocear(texto: str, max_palabras: int = 0, overlap_palabras: int | None = None) -> list[str]:
    """Agrupa oraciones hasta `max_palabras` y repite las últimas N palabras."""
    max_palabras = max_palabras or config.CHUNK_MAX_PALABRAS
    overlap = config.CHUNK_OVERLAP_PALABRAS if overlap_palabras is None else overlap_palabras
    trozos: list[str] = []
    actual: list[str] = []
    for oracion in dividir_oraciones(texto):
        palabras = oracion.split()
        if len(palabras) > max_palabras:  # oración gigante (tablas aplanadas)
            if actual:
                trozos.append(" ".join(actual))
                actual = []
            trozos += [" ".join(palabras[i:i + max_palabras])
                       for i in range(0, len(palabras), max_palabras)]
            continue
        if actual and len(actual) + len(palabras) > max_palabras:
            trozos.append(" ".join(actual))
            cola = actual[-overlap:] if overlap else []
            while cola and len(cola) + len(palabras) > max_palabras:
                cola = cola[1:]
            actual = list(cola)
        actual.extend(palabras)
    if actual:
        trozos.append(" ".join(actual))
    return trozos


# Columnas de tabla que no entran aunque no tengan marcas del modo B
# (misma decisión que `precio` en catalogo.json: la tarifa sale de la herramienta).
COLUMNAS_EXCLUIDAS = re.compile(r"\btarifa\s+de\s+lista\b", re.IGNORECASE)


def _sin_modo_b(texto: str, donde: str) -> str:
    """Quita las oraciones con marcas del modo B y registra cada descarte."""
    conservadas = []
    for oracion in dividir_oraciones(texto):
        marcas = marcas_modo_b(oracion)
        if marcas:
            log.warning("rag.descartado %s marcas=%s texto=%r", donde, marcas, oracion[:80])
        else:
            conservadas.append(oracion)
    return " ".join(conservadas)


def _filas_tabla(tabla: pdf.Tabla, donde: str) -> list[str]:
    """Una línea de texto por fila, sin columnas excluidas ni oraciones del modo B."""
    columnas = []
    for i, encabezado in enumerate(tabla.encabezados):
        if marcas_modo_b(encabezado) or COLUMNAS_EXCLUIDAS.search(encabezado):
            log.warning("rag.descartado %s columna=%r", donde, encabezado)
        else:
            columnas.append(i)
    textos = []
    for fila in tabla.filas:
        celdas = [(tabla.encabezados[i], _sin_modo_b(fila[i], donde)) for i in columnas]
        if not celdas or not celdas[0][1]:          # sin etiqueta, la fila no se entiende
            continue
        partes = [f"{e}: {c.rstrip('.')}" if e else c.rstrip(".") for e, c in celdas if c]
        if len(partes) < 2:                          # solo la etiqueta: nada que decir
            continue
        prefijo = f"{tabla.titulo}. " if tabla.titulo else ""
        texto = prefijo + "; ".join(partes)
        textos.append(texto if texto[-1] in ".!?”\"" else texto + ".")
    return textos


def fragmentos_pdf(ruta: Path, paginas: list[tuple[int, str]] | None = None) -> list[Fragmento]:
    """Fragmentos de un PDF: prosa por oraciones (con solape) y una fila de tabla por fragmento.

    `paginas` es el texto en modo layout de cada página (por defecto se lee el PDF).
    Lo marcado como modo B se quita por oración, celda o columna, y se registra.
    """
    paginas = pdf.leer_paginas(ruta) if paginas is None else paginas
    fragmentos: list[Fragmento] = []
    for pagina in pdf.analizar(paginas):
        donde = f"fuente={ruta.name} pagina={pagina.numero}"
        prosa = _sin_modo_b(pagina.prosa, donde)
        for orden, trozo in enumerate(trocear(prosa)):
            if len(trozo.split()) >= MIN_PALABRAS:
                fragmentos.append(Fragmento(
                    id=f"{ruta.stem}-p{pagina.numero}-c{orden}", fuente=ruta.name,
                    seccion="pdf", texto=trozo, pagina=pagina.numero))
        for t, tabla in enumerate(pagina.tablas):
            for f, texto in enumerate(_filas_tabla(tabla, donde)):
                fragmentos.append(Fragmento(
                    id=f"{ruta.stem}-p{pagina.numero}-t{t}-f{f}", fuente=ruta.name,
                    seccion="pdf-tabla", texto=texto, pagina=pagina.numero))
    return fragmentos


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------
def construir_fragmentos(pdfs: Iterable[Path] | None = None,
                         catalogo: Path | None = None) -> list[Fragmento]:
    """Fragmentos de todas las fuentes configuradas. Falla si falta un archivo."""
    pdfs = list(config.RAG_PDFS if pdfs is None else pdfs)
    catalogo = config.RAG_CATALOGO if catalogo is None else catalogo
    faltan = [str(p) for p in [*pdfs, catalogo] if not Path(p).is_file()]
    if faltan:
        raise FileNotFoundError(f"Fuentes del RAG no encontradas: {faltan}")
    fragmentos: list[Fragmento] = []
    for ruta in pdfs:
        fragmentos += fragmentos_pdf(Path(ruta))
    fragmentos += leer_catalogo(Path(catalogo))
    return fragmentos
