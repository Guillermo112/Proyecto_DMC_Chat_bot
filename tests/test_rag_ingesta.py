"""Ingesta del RAG: lista blanca de catalogo.json y control de modo B.

Sin red ni modelo: solo lee catalogo.json y textos de PDF simulados.
"""
import copy
import json
import re
from pathlib import Path

import pytest

from app import config
from app.rag.ingesta import (
    POLITICAS_EXCLUIDAS,
    ContenidoModoB,
    fragmentos_catalogo,
    fragmentos_pdf,
    marcas_modo_b,
    trocear,
)


@pytest.fixture(scope="module")
def catalogo() -> dict:
    with open(config.RAG_CATALOGO, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def fragmentos(catalogo) -> list:
    return fragmentos_catalogo(catalogo)


def _todo(fragmentos) -> str:
    return "\n".join(f.texto for f in fragmentos)


# -- lista blanca -------------------------------------------------------------
def test_el_catalogo_real_pasa_el_control(fragmentos, catalogo):
    esperados = (len(catalogo["casuisticas"]) + len(catalogo["servicios"])
                 + len(catalogo["tramos"])
                 + len(set(catalogo["agente"]["politicas"]) - POLITICAS_EXCLUIDAS))
    assert len(fragmentos) == esperados


def test_no_entra_la_opcion_b(fragmentos, catalogo):
    texto = _todo(fragmentos)
    for r in catalogo["casuisticas"]:
        assert r["opcion_b"] not in texto
        assert r["opcion_a"] in texto


def test_no_entra_la_accion_del_tramo(fragmentos, catalogo):
    texto = _todo(fragmentos)
    for r in catalogo["tramos"]:
        assert r["accion_agente"] not in texto


def test_no_entran_vistas_internas(fragmentos):
    assert not re.search(r"\bv_\w+", _todo(fragmentos))


def test_no_entra_el_precio_de_catalogo(fragmentos, catalogo):
    servicios = {f.id: f.texto for f in fragmentos if f.seccion == "servicios"}
    for r in catalogo["servicios"]:
        precio = r["precio"]
        for forma in (f"{precio:.2f}", f"{precio:,.2f}".replace(",", " ").replace(".", ","),
                      f"{precio:,.0f}".replace(",", " "), str(int(precio))):
            assert forma not in servicios[r["codigo"]], (r["codigo"], forma)


def test_politica_del_gesto_excluida(fragmentos):
    ids = {f.id for f in fragmentos}
    assert "politica-gesto_comercial" not in ids
    assert "politica-facturacion" in ids


def test_campo_nuevo_no_autorizado_no_cambia_el_indice(catalogo, fragmentos):
    otro = copy.deepcopy(catalogo)
    for r in otro["casuisticas"]:
        r["opcion_b_detalle"] = "Emite la nota de crédito y aplica el gesto."
    otro["servicios"][0]["precio_secreto"] = 123.0
    assert fragmentos_catalogo(otro) == fragmentos


def test_modo_b_en_campo_autorizado_hace_fallar_la_ingesta(catalogo):
    otro = copy.deepcopy(catalogo)
    otro["casuisticas"][0]["opcion_a"] = "Emite la nota de crédito y avisa al cliente."
    with pytest.raises(ContenidoModoB, match=otro["casuisticas"][0]["codigo"]):
        fragmentos_catalogo(otro)


def test_todo_fragmento_es_citable(fragmentos):
    for f in fragmentos:
        assert f.id and f.fuente == "catalogo.json" and f.seccion and f.texto
    assert len({f.id for f in fragmentos}) == len(fragmentos)


# -- control de modo B ----------------------------------------------------------
@pytest.mark.parametrize("texto", [
    "Solo en la opción B.",
    "Cuando es posible, emito la nota de crédito.",
    "El agente aplica el gesto si corresponde.",
    "Puedo aplicar un gesto comercial.",
    "Propone el ajuste al ejecutivo.",
    "Aviso a quien corresponde según el tramo.",
    # Formas que aparecen en los PDF 01 y 03
    "Tramo 1: aplicas la nota de crédito.",
    "Tramos 2 y 3: propones el ajuste para aprobación.",
    "Se propone el ajuste y lo aprueba el ejecutivo de cuenta.",
    "Modo B: se emite la nota de crédito o débito.",
    "Calcula con calcular_ajuste y registra el caso.",
    "Todo lo de A y además calculas el ajuste.",
])
def test_detecta_marcas_modo_b(texto):
    assert marcas_modo_b(texto)


@pytest.mark.parametrize("texto", [
    "Anticipa registra el caso y lo deriva a tu ejecutivo.",
    "Una nota de crédito corrige una factura emitida.",
    "La opción A registra y deriva.",
    "En modo A solo registras y derivas.",
    "El día en que se emite la factura: el 1 del mes siguiente.",
    "Nota de débito: aumenta lo que el cliente debe.",
])
def test_no_marca_textos_de_modo_a(texto):
    assert not marcas_modo_b(texto)


# -- PDF ------------------------------------------------------------------------
_RELLENO = " ".join(["La facturación es mes vencido y se emite el día uno."] * 3)


def test_pdf_quita_solo_la_oracion_modo_b(caplog):
    paginas = [(1, "En modo B el agente emite la nota de crédito. " + _RELLENO)]
    resultado = fragmentos_pdf(Path("Prueba.pdf"), paginas=paginas)
    assert [f.id for f in resultado] == ["Prueba-p1-c0"] and resultado[0].seccion == "pdf"
    assert "modo B" not in resultado[0].texto and "mes vencido" in resultado[0].texto
    assert "rag.descartado" in caplog.text and "pagina=1" in caplog.text


# Tabla como la entrega pypdf en modo layout: celdas a 3+ espacios, filas con un
# espacio inicial, una celda que sigue en la línea de abajo y un pie de página.
_TABLA = """\
P1. Política por tramos
El tramo se calcula sobre el monto sin IGV del ajuste.

 Tramo            Monto                  Qué ocurre                        Tarifa de lista

 1: automático    hasta 100              Modo B: se emite la nota.         4 500,00
                                         Modo A: se registra y deriva.

 2: ejecutivo     más de 100             Se propone el ajuste al jefe.     12 000,00

Ejemplos. S/ 33,75 es tramo 1 y S/ 300,00 es tramo 2 según la tabla anterior de tramos.
Anticipa   Políticas                                                       Página 1
"""

_TABLA_MODOS = """\
5. Modos de operación

                    Modo A: consultas                   Modo B: prevención

 Qué haces          Identificas y registras             Calculas el ajuste.

                    Registras el caso y lo derivas      Tramo 1: aplicas la nota.
 Si hay un error    al ejecutivo.
"""


def test_tabla_una_fila_por_fragmento_sin_modo_b_ni_tarifa(caplog):
    resultado = fragmentos_pdf(Path("Prueba.pdf"), paginas=[(1, _TABLA)])
    filas = [f for f in resultado if f.seccion == "pdf-tabla"]
    assert [f.texto for f in filas] == [
        "P1. Política por tramos. Tramo: 1: automático; Monto: hasta 100; "
        "Qué ocurre: Modo A: se registra y deriva.",
        "P1. Política por tramos. Tramo: 2: ejecutivo; Monto: más de 100.",
    ]
    assert filas[0].id == "Prueba-p1-t0-f0" and filas[0].pagina == 1
    assert "columna='Tarifa de lista'" in caplog.text
    prosa = " ".join(f.texto for f in resultado if f.seccion == "pdf")
    assert "Ejemplos." in prosa and "Página" not in prosa and "4 500" not in prosa


def test_tabla_columna_modo_b_se_descarta_entera():
    resultado = fragmentos_pdf(Path("Prueba.pdf"), paginas=[(2, _TABLA_MODOS)])
    assert [f.texto for f in resultado] == [
        "5. Modos de operación. Qué haces; Modo A: consultas: Identificas y registras.",
        "5. Modos de operación. Si hay un error; Modo A: consultas: "
        "Registras el caso y lo derivas al ejecutivo.",
    ]


def test_pdf_descarta_trozos_cortos():
    assert fragmentos_pdf(Path("Prueba.pdf"), paginas=[(1, "Índice. Página 3.")]) == []


def test_trocear_respeta_maximo_y_solapa():
    texto = " ".join(f"Oración número {i} con algunas palabras más." for i in range(40))
    trozos = trocear(texto, max_palabras=30, overlap_palabras=7)
    assert len(trozos) > 1
    assert all(len(t.split()) <= 30 for t in trozos)
    assert trozos[0].split()[-7:] == trozos[1].split()[:7]
