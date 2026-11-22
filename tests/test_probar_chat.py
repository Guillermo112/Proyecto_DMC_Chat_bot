"""scripts/probar_chat.py: la evaluación de cada turno (sin modelo real)."""
import json

import pytest

from scripts import probar_chat as pc


@pytest.fixture(scope="module")
def lista():
    return pc.casos(json.loads(pc.CASOS_JSON.read_text(encoding="utf-8")))


def test_casos_usan_los_datos_sembrados(lista):
    por_codigo = {c.codigo: c for c in lista}
    assert por_codigo["CS-01"].cliente_id == 1
    assert "F001-000255" in por_codigo["CS-01"].turnos[0].contiene
    assert "12000" in por_codigo["CS-02"].turnos[0].contiene
    assert len({c.codigo for c in lista}) == len(lista)


@pytest.mark.parametrize("respuesta", ["Se cobró S/ 12 000,00 sin IGV", "S/ 12,000.00", "S/12000"])
def test_montos_con_cualquier_separador(respuesta):
    turno = pc.Turno("x", contiene=("12000",))
    assert pc.evaluar(turno, respuesta, [], 0) == []


def test_detecta_herramienta_faltante_y_frase_prohibida():
    turno = pc.Turno("x", herramientas=frozenset({"detectar_anomalias"}))
    problemas = pc.evaluar(turno, "Listo, ya apliqué la nota de crédito.", ["ver_perfil"], 0)
    assert any("no usó detectar_anomalias" in p for p in problemas)
    assert any("ya apliqué" in p for p in problemas)


def test_fuera_de_tema_sin_herramientas_y_rag():
    assert pc.evaluar(pc.Turno("x", sin_herramientas=True), "Te ayudo con tu factura.", ["ver_saldo"], 0)
    assert pc.evaluar(pc.Turno("x", con_documentos=True), "Es proporcional.", [], 0) == ["no llegó contexto del RAG"]


def test_no_contiene():
    turno = pc.Turno("x", no_contiene=("F001-000254",))
    assert pc.evaluar(turno, "Solo puedo darte datos de tu empresa.", [], 0) == []
    assert pc.evaluar(turno, "La F001-000254 ...", [], 0)


def test_sin_modelo_sale_con_2(monkeypatch, capsys):
    from app import agente, config

    class SinModelo:
        def responder(self, *_):
            raise agente.ChatNoDisponible("No hay ningún endpoint configurado.")

    monkeypatch.setattr(agente, "ServicioChat", lambda: SinModelo())
    import logging

    db_real = config.DB_PATH
    nivel = logging.getLogger("app.rag").level
    try:
        assert pc.main(["CS-01"]) == 2
    finally:
        config.DB_PATH = db_real  # main apunta la config a una copia temporal
        logging.getLogger("app.rag").setLevel(nivel)  # y silencia el log del RAG
    assert "no está disponible" in capsys.readouterr().out
