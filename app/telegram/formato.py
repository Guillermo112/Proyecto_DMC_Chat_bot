"""Formato de las respuestas para Telegram (`parse_mode=HTML`).

El modelo escribe texto con `**negrita**` y listas con guiones (ver el estilo en
`app/agente/prompt.py`), igual que en la web, donde `formatear()` de
`app/static/chat.html` hace lo mismo que `a_html`:

- se escapan `&`, `<` y `>` (Telegram rechaza el mensaje si el HTML no es válido);
- `**texto**` pasa a `<b>texto</b>`; lo demás queda tal cual.

Un mensaje de Telegram admite hasta 4096 caracteres: `partir` corta el texto en
partes que, ya convertidas a HTML, caben en ese límite, de preferencia entre
párrafos o líneas y nunca dentro de una etiqueta.
"""
from __future__ import annotations

import html
import re

LIMITE = 4096
_NEGRITA = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def a_html(texto: str) -> str:
    return _NEGRITA.sub(r"<b>\1</b>", html.escape(texto, quote=False))


def _cabe(texto: str, limite: int) -> bool:
    return len(a_html(texto)) <= limite


def _cortar_linea(linea: str, limite: int) -> list[str]:
    """Una línea que no cabe sola: se corta por palabras (o por caracteres si hace falta)."""
    partes, actual = [], ""
    for palabra in re.split(r"(?<= )", linea):
        if _cabe(actual + palabra, limite):
            actual += palabra
            continue
        if actual:
            partes.append(actual)
        actual = ""
        while not _cabe(palabra, limite):  # una "palabra" enorme (p. ej. un enlace)
            corte = limite
            while corte > 1 and not _cabe(palabra[:corte], limite):
                corte -= max(1, corte // 8)
            partes.append(palabra[:corte])
            palabra = palabra[corte:]
        actual = palabra
    if actual:
        partes.append(actual)
    return partes


def partir(texto: str, limite: int = LIMITE) -> list[str]:
    """Partes de `texto` (sin convertir) cuyo HTML cabe en `limite`. Sin partes vacías.

    Una negrita que quede cortada entre dos partes se muestra con sus asteriscos: es
    raro (la respuesta del modelo es corta) y preferible a un HTML inválido.
    """
    texto = texto.strip()
    if not texto:
        return []
    if _cabe(texto, limite):
        return [texto]
    partes, actual = [], ""
    for linea in texto.split("\n"):
        candidato = f"{actual}\n{linea}" if actual else linea
        if _cabe(candidato, limite):
            actual = candidato
            continue
        if actual:
            partes.append(actual)
        if _cabe(linea, limite):
            actual = linea
        else:
            *completas, actual = _cortar_linea(linea, limite)
            partes.extend(completas)
    if actual:
        partes.append(actual)
    return [p.strip() for p in partes if p.strip()]
