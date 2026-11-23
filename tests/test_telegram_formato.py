"""Formato de las respuestas para Telegram (app/telegram/formato.py)."""
import pytest

from app.telegram import formato as f


@pytest.mark.parametrize("texto, esperado", [
    ("Hola", "Hola"),
    ("Tu saldo es **S/ 1 234,50**.", "Tu saldo es <b>S/ 1 234,50</b>."),
    ("**a** y **b**", "<b>a</b> y <b>b</b>"),
    ("1 < 2 & 3 > 2", "1 &lt; 2 &amp; 3 &gt; 2"),
    ("**<script>**", "<b>&lt;script&gt;</b>"),
    ('Comillas "dobles" y \'simples\'', 'Comillas "dobles" y \'simples\''),
    ("**sin cerrar", "**sin cerrar"),
    ("- uno\n- dos", "- uno\n- dos"),
    ("*cursiva* no cambia", "*cursiva* no cambia"),
])
def test_a_html(texto, esperado):
    assert f.a_html(texto) == esperado


def test_igual_que_la_web():
    """La web (chat.html, formatear) escapa y convierte solo **negrita**."""
    assert f.a_html("**F001-000255** <ok>") == "<b>F001-000255</b> &lt;ok&gt;"


def test_texto_corto_una_parte():
    assert f.partir("  hola  ") == ["hola"]
    assert f.partir("   ") == [] and f.partir("") == []


def _comprobar(partes, limite):
    assert partes and all(p.strip() == p and p for p in partes)
    assert all(len(f.a_html(p)) <= limite for p in partes)


def test_parte_entre_lineas():
    texto = "\n".join(f"Línea {i}: " + "x" * 40 for i in range(10))
    partes = f.partir(texto, limite=120)
    _comprobar(partes, 120)
    assert "\n".join(partes).split("\n") == texto.split("\n")  # no se pierde ni se corta una línea


def test_linea_larga_se_corta_por_palabras():
    texto = " ".join(f"palabra{i}" for i in range(100))
    partes = f.partir(texto, limite=100)
    _comprobar(partes, 100)
    assert " ".join(partes).split() == texto.split()


def test_palabra_enorme_y_caracteres_que_crecen():
    """'&' ocupa 5 caracteres en HTML: el corte se mide sobre el HTML."""
    for texto in ["a" * 1000, "&" * 1000, "<>" * 300]:
        partes = f.partir(texto, limite=100)
        _comprobar(partes, 100)
        assert "".join(partes) == texto


def test_negrita_no_se_corta_si_la_linea_cabe():
    texto = "x" * 50 + "\n**importante**"
    partes = f.partir(texto, limite=60)
    assert partes == ["x" * 50, "**importante**"]
    assert f.a_html(partes[1]) == "<b>importante</b>"


def test_limite_real_de_telegram():
    texto = ("Detalle de la factura con **monto** y <símbolos> & más.\n" * 200).strip()
    partes = f.partir(texto)
    _comprobar(partes, 4096)
    assert len(partes) > 1
