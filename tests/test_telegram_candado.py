"""Candado local del bot (app/telegram/candado.py): un lector por token en esta PC [5.2]."""
import subprocess
import sys

from app import config
from app.telegram.candado import CandadoLocal, ruta_candado

TOKEN = "123456:TOKEN-DE-PRUEBA-secreto"


def test_un_solo_dueno_por_token(tmp_path):
    a, b = CandadoLocal(TOKEN, tmp_path), CandadoLocal(TOKEN, tmp_path)
    assert a.tomar() and a.tomar()  # tomarlo de nuevo no falla
    assert not b.tomar()
    a.soltar()
    assert b.tomar()
    b.soltar()


def test_tokens_distintos_no_se_bloquean(tmp_path):
    a, b = CandadoLocal(TOKEN, tmp_path), CandadoLocal("999:OTRO", tmp_path)
    assert a.tomar() and b.tomar()
    a.soltar()
    b.soltar()


def test_el_archivo_no_lleva_el_token(tmp_path):
    """[4.1]"""
    ruta = ruta_candado(TOKEN, tmp_path)
    assert TOKEN not in str(ruta) and "123456" not in ruta.name
    assert ruta.name.startswith("anticipa-telegram-") and ruta.suffix == ".lock"


def test_soltar_sin_tomar_no_falla(tmp_path):
    CandadoLocal(TOKEN, tmp_path).soltar()


_OTRO_PROCESO = """
import pathlib, sys
from app.telegram.candado import CandadoLocal
c = CandadoLocal(sys.argv[1], pathlib.Path(sys.argv[2]))
print("tomado" if c.tomar() else "ocupado", flush=True)
sys.stdin.readline()
"""


def test_entre_procesos(tmp_path):
    """El bloqueo es del sistema operativo: vale entre procesos y se libera al terminar."""
    otro = subprocess.Popen([sys.executable, "-c", _OTRO_PROCESO, TOKEN, str(tmp_path)],
                            cwd=config.RAIZ_PROYECTO, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True)
    try:
        assert otro.stdout.readline().strip() == "tomado"
        assert not CandadoLocal(TOKEN, tmp_path).tomar()
    finally:
        otro.communicate("fin\n", timeout=10)
    local = CandadoLocal(TOKEN, tmp_path)
    assert local.tomar()  # el otro proceso terminó: el candado quedó libre
    local.soltar()
