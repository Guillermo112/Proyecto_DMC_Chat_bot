"""Límite de solicitudes de código por IP (app/auth/limite.py)."""
import shutil

import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth import otp
from app.auth.limite import LimitadorPorIP
from app.main import app


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _limitador(maximo=3, ventana=60):
    reloj = Reloj()
    return LimitadorPorIP(lambda: maximo, lambda: ventana, reloj), reloj


# --- Lógica del limitador (sin HTTP) ------------------------------------------

def test_permite_hasta_el_maximo_y_luego_bloquea():
    lim, _ = _limitador(maximo=3)
    assert [lim.registrar("1.1.1.1") for _ in range(3)] == [None, None, None]
    assert lim.registrar("1.1.1.1") == pytest.approx(60)


def test_ventana_deslizante_libera_cupos():
    lim, reloj = _limitador(maximo=2, ventana=60)
    lim.registrar("ip")            # t=1000
    reloj.t += 30
    lim.registrar("ip")            # t=1030
    reloj.t += 10                  # t=1040: lleno, se libera en 1060
    assert lim.registrar("ip") == pytest.approx(20)
    reloj.t = 1060                 # sale la primera
    assert lim.registrar("ip") is None
    assert lim.registrar("ip") == pytest.approx(30)  # la de 1030 sale en 1090


def test_las_rechazadas_no_alargan_el_bloqueo():
    lim, reloj = _limitador(maximo=1, ventana=60)
    lim.registrar("ip")
    for _ in range(10):
        reloj.t += 5
        lim.registrar("ip")
    reloj.t = 1060
    assert lim.registrar("ip") is None


def test_ips_independientes():
    lim, _ = _limitador(maximo=1)
    assert lim.registrar("a") is None
    assert lim.registrar("a") is not None
    assert lim.registrar("b") is None


def test_no_acumula_ips_viejas():
    lim, reloj = _limitador(maximo=5, ventana=60)
    for i in range(1500):
        lim.registrar(f"10.0.{i // 256}.{i % 256}")
    reloj.t += 61
    lim.registrar("nueva")
    assert len(lim._por_ip) < 10


# --- Endpoint /auth/solicitar-codigo ----------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    copia = tmp_path / "anticipa.db"
    shutil.copy(config.DB_PATH, copia)
    monkeypatch.setattr(config, "DB_PATH", copia)
    monkeypatch.setattr(otp, "enviar_correo", lambda *a: None)
    monkeypatch.setattr(config, "AUTH_MAX_SOLICITUDES_POR_IP", 3)
    monkeypatch.setattr(config, "AUTH_VENTANA_SOLICITUDES_SEG", 900)
    return TestClient(app)


def test_endpoint_responde_429_con_retry_after(api):
    # RUCs inexistentes: no envían correo ni chocan con la espera de reenvío.
    rucs = ["99999999901", "99999999902", "99999999903", "99999999904"]
    codigos = [api.post("/auth/solicitar-codigo", json={"ruc": r}).status_code for r in rucs]
    assert codigos == [200, 200, 200, 429]
    r = api.post("/auth/solicitar-codigo", json={"ruc": "99999999905"})
    assert r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= 900


def test_peticiones_mal_formadas_tambien_cuentan(api):
    for _ in range(3):
        assert api.post("/auth/solicitar-codigo", json={"ruc": "123"}).status_code == 422
    assert api.post("/auth/solicitar-codigo", json={"ruc": "99999999901"}).status_code == 429


def test_bloqueo_no_registra_nada_en_la_base(api):
    import sqlite3
    for i in range(3):
        api.post("/auth/solicitar-codigo", json={"ruc": f"9999999990{i}"})
    with sqlite3.connect(config.DB_PATH) as con:
        antes = con.execute("SELECT COUNT(*) FROM verificacion").fetchone()[0]
    assert api.post("/auth/solicitar-codigo", json={"ruc": "99999999909"}).status_code == 429
    with sqlite3.connect(config.DB_PATH) as con:
        assert con.execute("SELECT COUNT(*) FROM verificacion").fetchone()[0] == antes


def test_verificar_codigo_no_esta_limitado_por_ip(api):
    """El límite es para pedir códigos; verificar ya tiene OTP_MAX_INTENTOS por código."""
    for i in range(3):
        api.post("/auth/solicitar-codigo", json={"ruc": f"9999999990{i}"})
    r = api.post("/auth/verificar-codigo", json={"id_verificacion": 1, "codigo": "000000"})
    assert r.status_code == 401
