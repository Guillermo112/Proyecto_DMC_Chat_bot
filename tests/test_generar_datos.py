"""db/generar_datos.py: correos de prueba de ejecutivos por slot (sin regenerar la base)."""
import importlib.util

from app import config


def _generador(monkeypatch, **env):
    for n in range(1, 6):
        monkeypatch.delenv(f"CORREO_EJECUTIVO_{n}", raising=False)
    for clave, valor in env.items():
        monkeypatch.setenv(clave, valor)
    spec = importlib.util.spec_from_file_location("generar_datos_prueba",
                                                  config.RAIZ_PROYECTO / "db" / "generar_datos.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)  # solo define datos y funciones: main() no corre al importar
    return modulo


def test_todos_los_clientes_de_un_slot_comparten_ejecutivo(monkeypatch):
    g = _generador(monkeypatch)
    assert {n: g.ejecutivo_del_slot(n) for n in range(1, 6)} == {1: 2, 2: 3, 3: 4, 4: 5, 5: 1}
    for cid in range(1, 14):
        assert g.ejecutivo_de(cid) == g.ejecutivo_del_slot((cid - 1) % 5 + 1)


def test_correo_ejecutivo_del_slot(monkeypatch):
    g = _generador(monkeypatch, CORREO_EJECUTIVO_2="ejecutiva@correo.com")
    assert g.CORREOS_EJECUTIVO == {3: "ejecutiva@correo.com"}  # slot 2 -> Lucía Paredes (id 3)
    assert g.PERSONAL[2][1] == "Lucía Paredes Cano"            # el nombre no cambia
