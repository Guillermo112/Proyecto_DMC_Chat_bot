"""scripts/clientes_prueba.py: lee los clientes 1 a 13 de la base de pruebas."""
import json

import pytest

from scripts import clientes_prueba as cp


def test_lee_los_13_con_ruc_fijo_y_slot():
    clientes, _ = cp.leer()
    assert [c.id for c in clientes] == list(range(1, 14))
    assert all(len(c.ruc) == 11 and c.ruc.startswith("99") for c in clientes)
    # Semilla fija del generador: el cliente 1 siempre tiene este RUC (lo cita el README).
    assert clientes[0].ruc == "99813998698"
    assert [c.slot for c in clientes] == [1, 2, 3, 4, 5, 1, 2, 3, 4, 5, 1, 2, 3]


def test_casuisticas_desde_el_json(tmp_path):
    casos = tmp_path / "casos.json"
    casos.write_text(json.dumps({
        "fecha_actual": "2026-12-05",
        "CS01": {"cliente": 1, "ruc": "x"},
        "CS10": {"cliente": 9}, "CS11": {"cliente": 9, "estado": "vencida"},
        "CS12": {"cliente": 13, "ruc_inexistente": "99000000001"},
    }), encoding="utf-8")
    clientes, inexistente = cp.leer(casos_json=casos)
    por_id = {c.id: c.casuisticas for c in clientes}
    assert por_id[1] == ("CS-01",) and por_id[9] == ("CS-10", "CS-11") and por_id[11] == ()
    assert inexistente == "99000000001"


def test_sin_json_no_falla(tmp_path):
    clientes, inexistente = cp.leer(casos_json=tmp_path / "no_existe.json")
    assert len(clientes) == 13 and all(c.casuisticas == () for c in clientes)
    assert inexistente is None


def test_sin_base_avisa(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cp.config, "DB_PATH", tmp_path / "no_existe.db")
    assert cp.main([]) == 1
    assert "install.bat" in capsys.readouterr().out


def test_tabla_marca_correos_que_no_reciben():
    clientes = [cp.ClientePrueba(1, "99813998698", "Minera", "facturacion@cliente01.example", ("CS-01",)),
                cp.ClientePrueba(2, "99309114170", "Distribuidora", "yo@correo.com", ())]
    texto = cp.tabla(clientes, {"CS-01": "Factura duplicada"}, "99000000001")
    assert "cliente01.example (no recibe)" in texto and "yo@correo.com (no recibe)" not in texto
    assert "CS-01  Factura duplicada" in texto and "99000000001" in texto


def test_filtra_por_slot(capsys):
    assert cp.main(["3"]) == 0
    filas = [l for l in capsys.readouterr().out.splitlines() if l[:2].strip().isdigit()]
    assert [int(l[:2]) for l in filas] == [3, 8, 13]


@pytest.mark.parametrize("argv", [["6"], ["x"], ["copiar"], ["copiar", "x"], ["1", "2"]])
def test_argumentos_invalidos(argv, capsys):
    assert cp.main(argv) == 2
    assert "Uso:" in capsys.readouterr().out


def test_copiar(monkeypatch, capsys):
    copiado = []
    monkeypatch.setattr(cp, "copiar", lambda texto: copiado.append(texto) or True)
    assert cp.main(["copiar", "1"]) == 0
    assert copiado == ["99813998698"] and "copiado" in capsys.readouterr().out
    assert cp.main(["copiar", "20"]) == 2
