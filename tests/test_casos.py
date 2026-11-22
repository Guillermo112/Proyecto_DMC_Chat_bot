"""Registrar y derivar caso (POST y GET /mi/casos), modo A.

Cada test escribe en una COPIA de anticipa.db (fixture `base`), nunca en la real.
"""
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config
from app.auth import otp, sesion
from app.data import casos, detectar_anomalias
from app.data.casos import ReferenciaNoEncontrada
from app.main import app
from app.schemas import NuevoCaso

api = TestClient(app)
BASE_REAL = config.DB_PATH


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    """Copia de la base por test; el aviso por correo empieza desactivado.

    La base sembrada solo trae casos por correo y telegram. Los de canal `web` salen de
    probar el chat o la API a mano: se quitan de la copia para que cada test parta de
    los casos sembrados aunque la base real ya se haya usado.
    """
    copia = tmp_path / "anticipa.db"
    shutil.copy(BASE_REAL, copia)
    con = sqlite3.connect(copia)
    try:
        web = "SELECT id_caso FROM caso WHERE canal = 'web'"
        con.execute(f"DELETE FROM interaccion_log WHERE id_caso IN ({web})")
        con.execute(f"DELETE FROM ajuste WHERE id_caso IN ({web})")
        con.execute("DELETE FROM caso WHERE canal = 'web'")
        con.commit()
    finally:
        con.close()
    monkeypatch.setattr(config, "DB_PATH", copia)
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", False)
    monkeypatch.setattr(config, "CORREO_DERIVACIONES", "")
    return copia


def _q(sql, *params):
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _caso(**kw) -> NuevoCaso:
    datos = {"canal": "web", "palabras_cliente": "Texto del cliente", **kw}
    return NuevoCaso(**datos)


def _como(cliente_id: int) -> dict:
    token, _ = sesion.emitir_token(cliente_id)
    return {"Authorization": f"Bearer {token}"}


def _id(numero: str) -> int:
    return int(numero.split("-")[1])


def _siguiente() -> str:
    """Número que tendrá el próximo caso de la copia (no se supone una base recién generada)."""
    ultimo = _q("SELECT COALESCE(MAX(id_caso), 0) AS n FROM caso")[0]["n"]
    return f"C-{ultimo + 1:06d}"


# ------------------------------------------------------------------ registrar: anomalías

def test_cs01_registra_y_deriva_al_ejecutivo():
    esperado = _siguiente()
    r = casos.registrar_caso(1, _caso(tipo="factura_duplicada", palabras_cliente="Me llegaron dos facturas de noviembre"))
    assert r.numero_caso == esperado and not r.ya_existia
    assert (r.estado, r.monto_discutido, r.aviso) == ("derivado", 185000.0, "no_enviado")
    assert r.fecha_creacion.startswith("2026-12-05 ")  # fecha ficticia, hora real
    [fila] = _q("SELECT c.*, f.numero FROM caso c JOIN factura f USING (id_factura) WHERE id_caso = ?", _id(r.numero_caso))
    assert (fila["opcion"], fila["tramo"], fila["canal"], fila["tipo_caso"]) == ("A", None, "web", "factura_duplicada")
    assert fila["numero"] == "F001-000254"  # referencia canónica: la primera factura
    assert "F001-000254, F001-000255" in fila["sustento"]
    ejecutivo = _q("SELECT p.nombre FROM cliente c JOIN personal p ON p.id_personal = c.id_ejecutivo WHERE id_cliente = 1")
    assert r.derivado_a_nombre == ejecutivo[0]["nombre"] and fila["id_derivado_a"] is not None


def test_el_historial_guarda_las_palabras_del_cliente_y_el_aviso():
    r = casos.registrar_caso(1, _caso(tipo="factura_duplicada", palabras_cliente="Me llegaron dos facturas"))
    log = [(x["rol"], x["mensaje"]) for x in _q("SELECT rol, mensaje FROM interaccion_log WHERE id_caso = ? ORDER BY id_log",
                                               _id(r.numero_caso))]
    assert log[0] == ("cliente", "Me llegaron dos facturas")
    assert log[1][0] == "sistema" and r.numero_caso in log[1][1] and "derivado a" in log[1][1]
    assert log[2] == ("sistema", "Aviso por correo desactivado (NOTIFICAR_DERIVACIONES).")


def test_reintento_no_duplica():
    primero = casos.registrar_caso(1, _caso(tipo="factura_duplicada"))
    antes = len(_q("SELECT 1 FROM caso"))
    segundo = casos.registrar_caso(1, _caso(tipo="factura_duplicada", referencias={"numero_factura": "F001-000255"}))
    assert segundo.ya_existia and segundo.numero_caso == primero.numero_caso and segundo.aviso == "no_enviado"
    assert len(_q("SELECT 1 FROM caso")) == antes


def test_anomalias_marcan_el_caso_abierto():
    assert detectar_anomalias(1).facturas_duplicadas[0].caso_abierto is None
    r = casos.registrar_caso(1, _caso(tipo="factura_duplicada"))
    assert detectar_anomalias(1).facturas_duplicadas[0].caso_abierto == r.numero_caso


def test_cs02_cualquier_referencia_lleva_a_la_misma_canonica():
    """Con la segunda factura o con el servicio, el caso es el mismo (primera factura, F001-000205)."""
    r = casos.registrar_caso(2, _caso(tipo="servicio_baja_facturado", referencias={"numero_factura": "F001-000256"}))
    assert r.monto_discutido == 24000.0
    assert _q("SELECT f.numero FROM caso c JOIN factura f USING (id_factura) WHERE id_caso = ?",
              _id(r.numero_caso))[0]["numero"] == "F001-000205"
    otra = casos.registrar_caso(2, _caso(tipo="servicio_baja_facturado", referencias={"id_servicio": 8}))
    assert otra.ya_existia and otra.numero_caso == r.numero_caso


@pytest.mark.parametrize("cliente_id, tipo, referencias, monto", [
    (3, "tarifa_distinta", {}, 13500.0),
    (4, "exceso_sin_sustento", {"periodo": "2026-10"}, 300.0),
    (5, "sla_averia", {"id_averia": 1}, 464.0),
    (6, "sla_averia", {}, 33.75),
])
def test_el_monto_sale_de_la_anomalia(cliente_id, tipo, referencias, monto):
    assert casos.registrar_caso(cliente_id, _caso(tipo=tipo, referencias=referencias)).monto_discutido == monto


def test_anomalia_no_detectada_sugiere_consulta_no_resuelta():
    with pytest.raises(ValueError, match="consulta_no_resuelta"):
        casos.registrar_caso(7, _caso(tipo="tarifa_distinta"))


def test_referencia_que_no_coincide_con_la_anomalia():
    with pytest.raises(ValueError):
        casos.registrar_caso(1, _caso(tipo="factura_duplicada", referencias={"periodo": "2026-10"}))


# ------------------------------------------------------------------ registrar: referencias ajenas

@pytest.mark.parametrize("referencias", [
    {"numero_factura": "F001-000254"},  # del cliente 1
    {"id_servicio": 1},
    {"id_averia": 1},                   # del cliente 5
    {"id_solicitud": 1},                # del cliente 10
    {"numero_factura": "F999-999999"},  # inexistente: misma respuesta
])
def test_referencia_ajena_o_inexistente(referencias):
    antes = len(_q("SELECT 1 FROM caso"))
    with pytest.raises(ReferenciaNoEncontrada):
        casos.registrar_caso(2, _caso(tipo="consulta_no_resuelta", referencias=referencias))
    assert len(_q("SELECT 1 FROM caso")) == antes


# ------------------------------------------------------------------ registrar: tipos libres

def test_cs06_solicitud_fuera_de_plazo_avisa_al_responsable():
    r = casos.registrar_caso(10, _caso(tipo="solicitud_fuera_de_plazo", referencias={"id_solicitud": 1}))
    mensajes = [x["mensaje"] for x in _q("SELECT mensaje FROM interaccion_log WHERE id_caso = ?", _id(r.numero_caso))]
    assert any(m.startswith("Aviso al responsable de la solicitud:") for m in mensajes)
    assert r.monto_discutido is None


@pytest.mark.parametrize("referencias", [{"id_solicitud": 2}, {}])  # 2: en proceso, 5 días
def test_cs06_exige_una_solicitud_fuera_de_plazo(referencias):
    with pytest.raises(ValueError):
        casos.registrar_caso(10, _caso(tipo="solicitud_fuera_de_plazo", referencias=referencias))


def test_cs13_mismo_pedido_ya_registrado_devuelve_el_caso_sembrado():
    """El cliente 12 tiene el caso 18 (derivado) con este mismo texto: un reintento no crea otro."""
    texto = "Quiero que me bajen la tarifa del MPLS para el próximo año."
    r = casos.registrar_caso(12, _caso(tipo="fuera_de_alcance", palabras_cliente=texto, canal="telegram"))
    assert r.ya_existia and r.numero_caso == "C-000018"
    otro = casos.registrar_caso(12, _caso(tipo="fuera_de_alcance", palabras_cliente="Necesito pagar en cuotas"))
    assert not otro.ya_existia and otro.numero_caso != "C-000018"


def test_tipo_libre_con_factura_propia():
    r = casos.registrar_caso(7, _caso(tipo="alta_no_solicitada", referencias={"numero_factura": "f001-000210"}))
    assert _q("SELECT f.numero FROM caso c JOIN factura f USING (id_factura) WHERE id_caso = ?",
              _id(r.numero_caso))[0]["numero"] == "F001-000210"


# ------------------------------------------------------------------ aviso por correo

def test_aviso_va_solo_a_la_casilla_de_prueba(monkeypatch):
    enviados = []
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", True)
    monkeypatch.setattr(config, "CORREO_DERIVACIONES", "pruebas@equipo.example")
    monkeypatch.setattr(otp, "enviar_correo", lambda destino, asunto, cuerpo: enviados.append((destino, asunto, cuerpo)))
    r = casos.registrar_caso(1, _caso(tipo="factura_duplicada", palabras_cliente="Dos facturas iguales"))
    assert r.aviso == "enviado"
    [(destino, asunto, cuerpo)] = enviados
    assert destino == "pruebas@equipo.example" and r.numero_caso in asunto and "Dos facturas iguales" in cuerpo
    ultimo = _q("SELECT mensaje FROM interaccion_log WHERE id_caso = ? ORDER BY id_log DESC LIMIT 1", _id(r.numero_caso))
    assert otp.enmascarar("pruebas@equipo.example") in ultimo[0]["mensaje"]  # el log no guarda el correo completo
    assert "pruebas@equipo.example" not in ultimo[0]["mensaje"]


def test_redireccion_dice_a_quien_iba(monkeypatch):
    enviados = []
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", True)
    monkeypatch.setattr(config, "CORREO_DERIVACIONES", "pruebas@equipo.example")
    monkeypatch.setattr(otp, "enviar_correo", lambda *a: enviados.append(a))
    r = casos.registrar_caso(1, _caso(tipo="factura_duplicada"))
    [(destino, asunto, cuerpo)] = enviados
    ejecutivo = _q("SELECT p.nombre, p.correo FROM cliente c JOIN personal p ON p.id_personal = c.id_ejecutivo "
                   "WHERE id_cliente = 1")[0]
    assert destino == "pruebas@equipo.example" and asunto.startswith("[PRUEBA] ")
    assert cuerpo.startswith(f"Para: {ejecutivo['nombre']} (Ejecutivo de cuenta) <{ejecutivo['correo']}>")
    ultimo = _q("SELECT mensaje FROM interaccion_log WHERE id_caso = ? ORDER BY id_log DESC LIMIT 1", _id(r.numero_caso))
    assert "redirigido a la casilla de prueba" in ultimo[0]["mensaje"] and ejecutivo["nombre"] in ultimo[0]["mensaje"]


def test_sin_redireccion_va_al_ejecutivo(monkeypatch):
    """Producción: sin CORREO_DERIVACIONES, el aviso va al correo real del ejecutivo."""
    enviados = []
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", True)
    monkeypatch.setattr(otp, "enviar_correo", lambda *a: enviados.append(a))
    con = sqlite3.connect(config.DB_PATH)
    con.execute("UPDATE personal SET correo = 'ejecutivo@empresa.pe' "
                "WHERE id_personal = (SELECT id_ejecutivo FROM cliente WHERE id_cliente = 1)")
    con.commit()
    con.close()
    r = casos.registrar_caso(1, _caso(tipo="factura_duplicada"))
    [(destino, asunto, cuerpo)] = enviados
    assert destino == "ejecutivo@empresa.pe" and not asunto.startswith("[PRUEBA]") and not cuerpo.startswith("Para:")
    assert r.aviso == "enviado"


def test_sin_redireccion_no_envia_a_dominios_reservados(monkeypatch):
    """Con la base de prueba (@anticipa.example) y sin redirección: no se intenta un envío que rebotaría."""
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", True)
    monkeypatch.setattr(otp, "enviar_correo", lambda *a: pytest.fail("no debía enviar"))
    r = casos.registrar_caso(1, _caso(tipo="factura_duplicada"))
    assert r.aviso == "no_enviado"
    ultimo = _q("SELECT mensaje FROM interaccion_log WHERE id_caso = ? ORDER BY id_log DESC LIMIT 1", _id(r.numero_caso))
    assert "dominio reservado" in ultimo[0]["mensaje"] and "CORREO_DERIVACIONES" in ultimo[0]["mensaje"]


def test_cs06_un_solo_aviso_si_el_responsable_es_el_ejecutivo(monkeypatch):
    """En la base, la responsable de la solicitud 1 es la misma ejecutiva del cliente 10."""
    enviados = []
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", True)
    monkeypatch.setattr(config, "CORREO_DERIVACIONES", "pruebas@equipo.example")
    monkeypatch.setattr(otp, "enviar_correo", lambda *a: enviados.append(a))
    casos.registrar_caso(10, _caso(tipo="solicitud_fuera_de_plazo", referencias={"id_solicitud": 1}))
    [(_, _, cuerpo)] = enviados
    assert cuerpo.splitlines()[0].count("<") == 1


def test_cs06_avisa_al_responsable_y_al_ejecutivo_si_son_distintos(monkeypatch):
    enviados = []
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", True)
    monkeypatch.setattr(otp, "enviar_correo", lambda *a: enviados.append(a))
    con = sqlite3.connect(config.DB_PATH)
    con.execute("UPDATE personal SET correo = 'responsable@empresa.pe' WHERE id_personal = 6")
    con.execute("UPDATE solicitud SET id_responsable = 6 WHERE id_solicitud = 1")
    con.commit()
    con.close()
    r = casos.registrar_caso(10, _caso(tipo="solicitud_fuera_de_plazo", referencias={"id_solicitud": 1}))
    # El ejecutivo (@anticipa.example) se omite; el responsable (real) recibe el aviso.
    assert [d for d, *_ in enviados] == ["responsable@empresa.pe"] and r.aviso == "enviado"
    ultimo = _q("SELECT mensaje FROM interaccion_log WHERE id_caso = ? ORDER BY id_log DESC LIMIT 1", _id(r.numero_caso))
    assert "No enviado a" in ultimo[0]["mensaje"] and "dominio reservado" in ultimo[0]["mensaje"]


@pytest.mark.parametrize("correo, reservado", [
    ("jorge.salazar.vega@anticipa.example", True), ("a@x.test", True), ("a@x.invalid", True),
    ("a@localhost", True), ("a@example.com", True), ("a@mail.example.org", True), ("a@ANTICIPA.EXAMPLE", True),
    ("a@gmail.com", False), ("a@empresa.pe", False), ("a@notexample.com", False), ("a@example.com.pe", False),
])
def test_dominio_reservado(correo, reservado):
    assert casos.dominio_reservado(correo) is reservado


def test_si_falla_el_correo_el_caso_queda_registrado(monkeypatch):
    def falla(*_):
        raise OSError("SMTP caído")
    monkeypatch.setattr(config, "NOTIFICAR_DERIVACIONES", True)
    monkeypatch.setattr(config, "CORREO_DERIVACIONES", "pruebas@equipo.example")
    monkeypatch.setattr(otp, "enviar_correo", falla)
    r = casos.registrar_caso(1, _caso(tipo="factura_duplicada"))
    assert r.aviso == "fallido"
    assert _q("SELECT estado FROM caso WHERE id_caso = ?", _id(r.numero_caso))[0]["estado"] == "derivado"
    ultimo = _q("SELECT mensaje FROM interaccion_log WHERE id_caso = ? ORDER BY id_log DESC LIMIT 1", _id(r.numero_caso))
    assert "falló (OSError)" in ultimo[0]["mensaje"]


# ------------------------------------------------------------------ listar

def test_listar_casos_del_cliente():
    r = casos.registrar_caso(1, _caso(tipo="factura_duplicada"))
    lista = casos.listar_casos(1).casos
    assert lista[0].numero_caso == r.numero_caso and lista[0].numero_factura == "F001-000254"
    assert all(c.numero_caso != r.numero_caso for c in casos.listar_casos(2).casos)


def test_la_base_real_no_se_toca():
    def contar() -> int:
        con = sqlite3.connect(f"{BASE_REAL.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM caso").fetchone()[0]
        finally:
            con.close()

    antes = contar()
    casos.registrar_caso(1, _caso(tipo="factura_duplicada"))
    assert contar() == antes


# ------------------------------------------------------------------ API

def test_api_201_y_luego_200_con_ya_existia():
    cuerpo = {"tipo": "factura_duplicada", "canal": "telegram", "palabras_cliente": "Dos facturas"}
    esperado = _siguiente()
    r = api.post("/mi/casos", json=cuerpo, headers=_como(1))
    assert r.status_code == 201 and r.json()["numero_caso"] == esperado
    r = api.post("/mi/casos", json=cuerpo, headers=_como(1))
    assert r.status_code == 200 and r.json()["ya_existia"] is True


def test_api_el_cliente_y_el_monto_no_salen_del_cuerpo():
    cuerpo = {"tipo": "servicio_baja_facturado", "canal": "web", "palabras_cliente": "Me cobran Cusco",
              "cliente_id": 1, "monto_discutido": 1.0}
    r = api.post("/mi/casos", json=cuerpo, headers=_como(2))
    assert r.status_code == 201 and r.json()["monto_discutido"] == 24000.0
    assert _q("SELECT id_cliente FROM caso WHERE id_caso = ?", _id(r.json()["numero_caso"]))[0]["id_cliente"] == 2


@pytest.mark.parametrize("cuerpo, codigo", [
    ({"tipo": "x", "canal": "web", "palabras_cliente": "a"}, 422),
    ({"tipo": "fuera_de_alcance", "canal": "manual", "palabras_cliente": "a"}, 422),
    ({"tipo": "fuera_de_alcance", "canal": "web", "palabras_cliente": "   "}, 422),
    ({"tipo": "fuera_de_alcance", "canal": "web", "palabras_cliente": "a" * 2001}, 422),
    ({"tipo": "consulta_no_resuelta", "canal": "web", "palabras_cliente": "a",
      "referencias": {"numero_factura": "F001-000254"}}, 404),
    ({"tipo": "tarifa_distinta", "canal": "web", "palabras_cliente": "a"}, 400),
])
def test_api_entradas_invalidas(cuerpo, codigo):
    assert api.post("/mi/casos", json=cuerpo, headers=_como(2)).status_code == codigo


def test_api_get_casos_y_sin_token():
    api.post("/mi/casos", json={"tipo": "contacto_persona", "canal": "web", "palabras_cliente": "Quiero hablar con alguien"},
             headers=_como(3))
    r = api.get("/mi/casos", headers=_como(3))
    assert r.status_code == 200 and r.json()["casos"][0]["tipo"] == "contacto_persona"
    assert api.get("/mi/casos").status_code == 401
    assert api.post("/mi/casos", json={}).status_code == 401
