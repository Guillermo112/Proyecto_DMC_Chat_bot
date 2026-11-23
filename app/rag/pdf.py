"""Estructura de un PDF: prosa y tablas, a partir del texto en modo `layout`.

`pypdf` con `extraction_mode="layout"` conserva la posición horizontal del texto.
En los PDF de `docs/` eso permite reconocer las tablas solo con expresiones
regulares:

- Las celdas de una misma línea están separadas por **3 o más espacios**.
- El encabezado es un bloque de líneas con al menos dos celdas, que no empieza
  en la columna 0, seguido (tras una línea en blanco) de una fila.
- Cada fila es un bloque entre líneas en blanco que empieza con **un espacio**
  (`" Paso"`) o con mucha sangría (fila con la primera celda vacía).
- La tabla termina en una línea que empieza en la columna 0 (título, prosa) o en
  una viñeta o lista numerada.
- Cada trozo de texto va a la columna cuyo inicio está más cerca a su izquierda.

Este módulo solo describe la estructura: qué entra al índice lo decide `ingesta`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_RE_CELDA = re.compile(r"\S+(?:\s{1,2}\S+)*")      # trozos separados por 3+ espacios
_RE_FILA = re.compile(r"^ \S")                       # fila: un solo espacio inicial
_RE_SANGRIA = re.compile(r"^ {5,}\S")                # fila con la primera celda vacía
_RE_LISTA = re.compile(r"^ {1,6}(?:•|\d+\.)\s")      # viñeta o ítem numerado
_RE_TITULO = re.compile(r"^(?:P?\d+\.)\s+\S")        # "3. Cómo debes sonar", "P1. Política…"
_RE_PIE = re.compile(r"^\S.*\bPágina\s+\d+\s*$")     # pie de página
TOLERANCIA = 3                                        # columnas a menos de 3 caracteres = la misma


@dataclass
class Tabla:
    titulo: str                      # último título visto antes de la tabla
    encabezados: list[str]
    filas: list[list[str]]           # una celda por columna ("" si está vacía)


@dataclass
class Pagina:
    numero: int
    prosa: str                       # texto corrido, sin tablas ni pie
    tablas: list[Tabla] = field(default_factory=list)


def leer_paginas(ruta: Path) -> list[tuple[int, str]]:
    """Texto de cada página en modo layout (conserva columnas)."""
    import logging

    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    lector = PdfReader(str(ruta))
    return [(i + 1, p.extract_text(extraction_mode="layout") or "")
            for i, p in enumerate(lector.pages)]


def _es_ruido(linea: str) -> bool:
    """Pie de página o título espaciado ("B A S E   D E …")."""
    if _RE_PIE.match(linea):
        return True
    fichas = linea.split()
    return len(fichas) >= 6 and all(len(f) == 1 for f in fichas)


def _celdas(linea: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(0)) for m in _RE_CELDA.finditer(linea)]


def _bloques(lineas: list[str]) -> list[tuple[int, int]]:
    """(inicio, fin) de cada grupo de líneas no vacías consecutivas."""
    bloques, inicio = [], None
    for i, linea in enumerate([*lineas, ""]):
        if linea.strip() and inicio is None:
            inicio = i
        elif not linea.strip() and inicio is not None:
            bloques.append((inicio, i))
            inicio = None
    return bloques


def _es_fila(primera: str) -> bool:
    return bool(_RE_FILA.match(primera) or _RE_SANGRIA.match(primera)) and not _RE_LISTA.match(primera)


def _es_encabezado(bloque: list[str], siguiente: str | None) -> bool:
    primera = bloque[0]
    if not primera.startswith(" ") or _RE_LISTA.match(primera) or siguiente is None:
        return False
    return any(len(_celdas(l)) >= 2 for l in bloque) and bool(_RE_FILA.match(siguiente))


def _columnas(encabezado: list[str], filas: list[list[str]]) -> list[int]:
    inicios = sorted({pos for l in encabezado for pos, _ in _celdas(l)})
    primera_fila = min((len(l) - len(l.lstrip()) for f in filas for l in f[:1]), default=1)
    if inicios and primera_fila < inicios[0] - TOLERANCIA:
        inicios.insert(0, primera_fila)      # columna de etiquetas sin encabezado
    columnas: list[int] = []
    for pos in inicios:
        if not columnas or pos - columnas[-1] > TOLERANCIA:
            columnas.append(pos)
    return columnas


def _repartir(lineas: list[str], columnas: list[int]) -> list[str]:
    celdas = [[] for _ in columnas]
    for linea in lineas:
        for pos, texto in _celdas(linea):
            indice = max((i for i, c in enumerate(columnas) if c <= pos + TOLERANCIA), default=0)
            celdas[indice].append(texto)
    return [" ".join(" ".join(c).split()) for c in celdas]


def analizar(paginas: list[tuple[int, str]]) -> list[Pagina]:
    """Separa prosa y tablas de cada página. El título se arrastra entre páginas."""
    resultado: list[Pagina] = []
    titulo = ""
    for numero, texto in paginas:
        lineas = [l.rstrip() for l in texto.splitlines() if not _es_ruido(l.strip())]
        bloques = _bloques(lineas)
        prosa: list[str] = []
        tablas: list[Tabla] = []
        i = 0
        while i < len(bloques):
            ini, fin = bloques[i]
            bloque = lineas[ini:fin]
            siguiente = lineas[bloques[i + 1][0]] if i + 1 < len(bloques) else None
            if _es_encabezado(bloque, siguiente):
                filas_crudas: list[list[str]] = []
                i += 1
                while i < len(bloques) and _es_fila(lineas[bloques[i][0]]):
                    filas_crudas.append(lineas[bloques[i][0]:bloques[i][1]])
                    i += 1
                columnas = _columnas(bloque, filas_crudas)
                tablas.append(Tabla(
                    titulo=titulo,
                    encabezados=_repartir(bloque, columnas),
                    filas=[_repartir(f, columnas) for f in filas_crudas],
                ))
                continue
            for linea in bloque:
                if _RE_TITULO.match(linea):
                    titulo = linea.strip()
                prosa.append(linea.strip())
            i += 1
        resultado.append(Pagina(numero=numero, prosa=" ".join(" ".join(prosa).split()),
                                tablas=tablas))
    return resultado
