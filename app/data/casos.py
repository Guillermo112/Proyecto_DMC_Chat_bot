"""Registrar y derivar caso (modo A): la única escritura de la capa de datos.

Reglas (ver docs/capa_datos.md, "Casos"):
- El cliente sale del token; toda referencia (factura, servicio, avería,
  solicitud) se valida contra él. Una ajena responde igual que una inexistente.
- Modo A: el caso queda `derivado` al ejecutivo del cliente, con `opcion='A'`,
  sin tramo ni ajuste. Nunca se modifica ni borra un caso.
- Tipos de anomalía: el servidor busca la anomalía en `detectar_anomalias` y
  toma de ella la referencia canónica y el monto (nunca del bot).
- Sin duplicados: si ya hay un caso abierto equivalente, se devuelve ese. La
  comprobación y el INSERT van en la misma transacción (`BEGIN IMMEDIATE`).
- Aviso: siempre en `interaccion_log`; por correo (NOTIFICAR_DERIVACIONES) al
  ejecutivo, o a CORREO_DERIVACIONES solo con ENTORNO=dev, y después de confirmar
  la transacción, así un fallo de SMTP no pierde el caso.
"""
import logging
from datetime import datetime
from pathlib import Path

from app import config
from app.auth import otp
from app.data.conexion import get_connection
from app.data.facturacion import (
    ESTADOS_CASO_ABIERTO,
    TIPO_CASO_POR_GRUPO,
    _fecha_actual,
    _validar_cliente_id,
    consultar_solicitudes,
    detectar_anomalias,
    numero_caso,
    referencia_anomalia,
)
from app.schemas.casos import CasoRegistrado, CasoResumen, ListaCasos, NuevoCaso, ReferenciasCaso

log = logging.getLogger(__name__)

GRUPO_POR_TIPO = {tipo: grupo for grupo, tipo in TIPO_CASO_POR_GRUPO.items()}
_ABIERTOS = ", ".join(f"'{e}'" for e in ESTADOS_CASO_ABIERTO)  # constantes del código, no del usuario


class ReferenciaNoEncontrada(LookupError):
    """La referencia no existe o es de otro cliente (no se distingue)."""


# ------------------------------------------------------------------ lectura de apoyo

def _cliente_y_ejecutivo(con, cliente_id: int):
    fila = con.execute(
        """
        SELECT c.razon_social, c.ruc, p.id_personal, p.nombre, p.rol, p.correo
        FROM cliente c JOIN personal p ON p.id_personal = c.id_ejecutivo
        WHERE c.id_cliente = ?
        """,
        (cliente_id,),
    ).fetchone()
    if fila is None:
        raise ReferenciaNoEncontrada("Cliente no encontrado")
    return fila


def _id_factura(con, cliente_id: int, numero: str) -> int:
    fila = con.execute(
        "SELECT id_factura FROM factura WHERE numero = ? AND id_cliente = ?",
        (numero.strip().upper(), cliente_id),
    ).fetchone()
    if fila is None:
        raise ReferenciaNoEncontrada("Factura no encontrada")
    return fila["id_factura"]


def _validar_referencias(con, cliente_id: int, ref: ReferenciasCaso) -> None:
    """Toda referencia dada debe ser del cliente; si no, ReferenciaNoEncontrada."""
    if ref.numero_factura is not None:
        _id_factura(con, cliente_id, ref.numero_factura)
    consultas = (
        (ref.id_servicio, "SELECT 1 FROM servicio_contratado WHERE id_servicio = ? AND id_cliente = ?", "Servicio"),
        (ref.id_averia, "SELECT 1 FROM averia a JOIN servicio_contratado s ON s.id_servicio = a.id_servicio "
                        "WHERE a.id_averia = ? AND s.id_cliente = ?", "Avería"),
        (ref.id_solicitud, "SELECT 1 FROM solicitud WHERE id_solicitud = ? AND id_cliente = ?", "Solicitud"),
    )
    for valor, sql, nombre in consultas:
        if valor is not None and con.execute(sql, (valor, cliente_id)).fetchone() is None:
            raise ReferenciaNoEncontrada(f"{nombre} no encontrada")


def _coincide(anomalia, ref: ReferenciasCaso) -> bool:
    """La anomalía corresponde a alguna de las referencias dadas."""
    numeros, periodos, servicio, averia = set(), set(), None, None
    if hasattr(anomalia, "facturas"):  # duplicada
        numeros = {f.numero for f in anomalia.facturas}
        periodos = {anomalia.periodo}
    if hasattr(anomalia, "cobros"):  # baja facturada, tarifa distinta
        numeros = {c.numero_factura for c in anomalia.cobros}
        periodos = {c.periodo for c in anomalia.cobros}
    if hasattr(anomalia, "numero_factura"):  # exceso
        numeros = {anomalia.numero_factura}
    if hasattr(anomalia, "periodo") and not hasattr(anomalia, "facturas"):
        periodos = {anomalia.periodo}
    if hasattr(anomalia, "servicio"):
        servicio = anomalia.servicio.id_servicio
    if hasattr(anomalia, "id_averia"):
        averia = anomalia.id_averia
    numero = ref.numero_factura.strip().upper() if ref.numero_factura else None
    return any((
        numero is not None and numero in numeros,
        ref.periodo is not None and ref.periodo in periodos,
        ref.id_servicio is not None and ref.id_servicio == servicio,
        ref.id_averia is not None and ref.id_averia == averia,
    ))


def _detalle_anomalia(anomalia) -> str:
    """Texto para el sustento: todas las facturas y periodos, no solo la referencia."""
    if hasattr(anomalia, "facturas"):
        return f"Facturas {', '.join(f.numero for f in anomalia.facturas)} del periodo {anomalia.periodo}."
    if hasattr(anomalia, "cobros"):
        cobros = ", ".join(f"{c.numero_factura} ({c.periodo})" for c in anomalia.cobros)
        return f"Servicio {anomalia.servicio.producto} {anomalia.servicio.sede}; cobros: {cobros}."
    if hasattr(anomalia, "id_averia"):
        return (f"Avería {anomalia.id_averia} en {anomalia.servicio.sede}, {anomalia.fecha_inicio} a "
                f"{anomalia.fecha_fin}: {anomalia.horas_caida} h.")
    return f"Factura {anomalia.numero_factura} ({anomalia.periodo}): {anomalia.gb_facturados} GB de exceso."


def _anomalia_del_caso(cliente_id: int, tipo: str, ref: ReferenciasCaso, db_path):
    anomalias = getattr(detectar_anomalias(cliente_id, db_path), GRUPO_POR_TIPO[tipo])
    hay_referencias = any(v is not None for v in ref.model_dump().values())
    candidatas = [a for a in anomalias if _coincide(a, ref)] if hay_referencias else anomalias
    if not candidatas:
        raise ValueError(
            f"No se detectó una anomalía '{tipo}' con esas referencias. "
            "Si el cliente insiste, registrar como 'consulta_no_resuelta'."
        )
    if len(candidatas) > 1:
        raise ValueError(f"Más de una anomalía '{tipo}' coincide: indicar la factura, el servicio o la avería.")
    return candidatas[0]


# ------------------------------------------------------------------ aviso

# Dominios reservados (RFC 2606 / 6761): no existen, un correo ahí rebota o se pierde.
# Los correos del personal en la base de prueba son de este tipo (@anticipa.example).
_TLD_RESERVADOS = {"example", "test", "invalid", "localhost"}
_DOMINIOS_RESERVADOS = ("example.com", "example.net", "example.org")


def dominio_reservado(correo: str) -> bool:
    """True si el correo es de un dominio reservado (no entregable)."""
    dominio = correo.rpartition("@")[2].strip().lower().rstrip(".")
    return (dominio.rpartition(".")[2] in _TLD_RESERVADOS
            or any(dominio == d or dominio.endswith("." + d) for d in _DOMINIOS_RESERVADOS))


def _destinatarios(*personas) -> list:
    """Personas a avisar, sin repetir correo (en CS-06 el responsable puede ser el ejecutivo)."""
    vistos, resultado = set(), []
    for p in personas:
        if p is not None and p["correo"].lower() not in vistos:
            vistos.add(p["correo"].lower())
            resultado.append(p)
    return resultado


def _redireccion_de_prueba() -> str:
    """Casilla de CORREO_DERIVACIONES, solo con ENTORNO=dev.

    Fuera de dev se ignora: un .env copiado de desarrollo mandaría a una sola casilla
    los datos de los casos de todos los clientes en vez de a cada ejecutivo.
    """
    if not config.CORREO_DERIVACIONES:
        return ""
    if config.ENTORNO != "dev":
        log.warning("CORREO_DERIVACIONES se ignora con ENTORNO=%s: el aviso va al ejecutivo real.",
                    config.ENTORNO)
        return ""
    return config.CORREO_DERIVACIONES


def _avisar(numero: str, tipo: str, cliente, palabras: str, sustento: str, destinatarios: list) -> tuple[str, str]:
    """Avisa por correo a quien se derivó el caso. Devuelve (resultado, texto para el log).

    - NOTIFICAR_DERIVACIONES desactivado: no se envía nada.
    - CORREO_DERIVACIONES definido y ENTORNO=dev: se REDIRIGE ahí un solo correo
      (pruebas), que dice a quién iba dirigido. Fuera de dev se ignora.
    - Sin redirección: va a cada destinatario real, salvo a dominios reservados
      (`.example`), que en la base de prueba no existen.
    El caso ya está registrado: un fallo de SMTP solo se anota.
    """
    if not config.NOTIFICAR_DERIVACIONES:
        return "no_enviado", "Aviso por correo desactivado (NOTIFICAR_DERIVACIONES)."
    para = ", ".join(f"{d['nombre']} ({d['rol']}) <{d['correo']}>" for d in destinatarios)
    nombres = ", ".join(d["nombre"] for d in destinatarios)
    cuerpo = (
        f"Caso {numero} ({tipo}), derivado a {cliente['nombre']} ({cliente['rol']}).\n"
        f"Cliente: {cliente['razon_social']} (RUC {cliente['ruc']}).\n\n"
        f"Palabras del cliente:\n{palabras}\n\nSustento:\n{sustento}\n"
    )
    asunto = f"[Anticipa] Caso {numero} derivado: {tipo}"

    redireccion = _redireccion_de_prueba()
    if redireccion:  # solo en desarrollo
        envios = [(redireccion, f"[PRUEBA] {asunto}", f"Para: {para}\n\n{cuerpo}")]
        exito = (f"Aviso para {nombres} redirigido a la casilla de prueba "
                 f"({otp.enmascarar(redireccion)}).")
    else:
        reales = [d for d in destinatarios if not dominio_reservado(d["correo"])]
        omitidos = [d for d in destinatarios if dominio_reservado(d["correo"])]
        if not reales:
            return "no_enviado", (f"Aviso por correo no enviado: el correo de {nombres} es de prueba "
                                  "(dominio reservado). En dev: CORREO_EJECUTIVO_n o CORREO_DERIVACIONES.")
        envios = [(d["correo"], asunto, cuerpo) for d in reales]
        exito = "Aviso por correo enviado a " + ", ".join(
            f"{d['nombre']} ({otp.enmascarar(d['correo'])})" for d in reales) + "."
        if omitidos:
            exito += " No enviado a " + ", ".join(d["nombre"] for d in omitidos) + " (dominio reservado)."

    try:
        for destino, asunto_envio, cuerpo_envio in envios:
            otp.enviar_correo(destino, asunto_envio, cuerpo_envio)
    except Exception as exc:  # noqa: BLE001 - SMTP caído o mal configurado: el caso ya está registrado
        log.exception("No se pudo enviar el aviso del caso %s", numero)
        return "fallido", f"Aviso por correo falló ({type(exc).__name__}); el caso queda registrado."
    return "enviado", exito


# ------------------------------------------------------------------ escritura

def registrar_caso(cliente_id: int, nuevo: NuevoCaso, db_path: Path | None = None) -> CasoRegistrado:
    """Registra el caso y lo deriva al ejecutivo del cliente (modo A).

    ValueError: anomalía no detectada o ambigua, o solicitud que no está fuera de
    plazo. ReferenciaNoEncontrada: referencia inexistente o de otro cliente.
    """
    _validar_cliente_id(cliente_id)
    ref = nuevo.referencias
    with get_connection(db_path) as con:
        cliente = _cliente_y_ejecutivo(con, cliente_id)
        _validar_referencias(con, cliente_id, ref)
        fecha = f"{_fecha_actual(con)} {datetime.now():%H:%M}"  # fecha ficticia, hora real

        id_factura = _id_factura(con, cliente_id, ref.numero_factura) if ref.numero_factura else None
        id_averia, id_solicitud, monto = ref.id_averia, ref.id_solicitud, None
        detalle, responsable = "", None
        if nuevo.tipo in GRUPO_POR_TIPO:
            anomalia = _anomalia_del_caso(cliente_id, nuevo.tipo, ref, db_path)
            numero_ref, id_averia = referencia_anomalia(anomalia)
            id_factura = _id_factura(con, cliente_id, numero_ref) if numero_ref else None
            monto, detalle = anomalia.monto_observado, _detalle_anomalia(anomalia)
        elif nuevo.tipo == "solicitud_fuera_de_plazo":
            if ref.id_solicitud is None:
                raise ValueError("'solicitud_fuera_de_plazo' requiere referencias.id_solicitud")
            sol = next(s for s in consultar_solicitudes(cliente_id, db_path=db_path).solicitudes
                       if s.id_solicitud == ref.id_solicitud)
            if not sol.fuera_de_plazo:
                raise ValueError(f"La solicitud {sol.id_solicitud} está dentro del plazo ({sol.dias_transcurridos} días).")
            detalle = f"Solicitud {sol.id_solicitud} ({sol.tipo}), {sol.dias_transcurridos} días."
            responsable = con.execute(
                "SELECT p.nombre, p.rol, p.correo FROM solicitud s JOIN personal p ON p.id_personal = s.id_responsable "
                "WHERE s.id_solicitud = ? AND s.id_cliente = ?",
                (sol.id_solicitud, cliente_id),
            ).fetchone()
        sustento = " ".join(x for x in (nuevo.resumen, detalle) if x) or None

    with get_connection(db_path, escritura=True) as con:
        con.execute("BEGIN IMMEDIATE")  # un escritor a la vez: comprobar e insertar sin carreras
        existente = _caso_equivalente(con, cliente_id, nuevo, id_factura, id_averia, id_solicitud)
        if existente is not None:
            return CasoRegistrado(
                numero_caso=numero_caso(existente["id_caso"]), tipo=nuevo.tipo, estado=existente["estado"],
                ya_existia=True, derivado_a_nombre=existente["derivado_a_nombre"],
                monto_discutido=existente["monto_discutido"], fecha_creacion=existente["fecha_creacion"],
                aviso="no_enviado",
            )
        id_caso = con.execute(
            """
            INSERT INTO caso (id_cliente, canal, opcion, tipo_caso, id_factura, id_averia, id_solicitud,
                              monto_discutido, tramo, estado, id_derivado_a, sustento, fecha_creacion, fecha_cierre)
            VALUES (?, ?, 'A', ?, ?, ?, ?, ?, NULL, 'derivado', ?, ?, ?, NULL)
            """,
            (cliente_id, nuevo.canal, nuevo.tipo, id_factura, id_averia, id_solicitud, monto,
             cliente["id_personal"], sustento, fecha),
        ).lastrowid
        numero = numero_caso(id_caso)
        mensajes = [("cliente", nuevo.palabras_cliente),
                    ("sistema", f"Caso {numero} registrado y derivado a {cliente['nombre']} ({cliente['rol']}).")]
        if responsable:
            mensajes.append(("sistema", f"Aviso al responsable de la solicitud: {responsable['nombre']}."))
        _log(con, cliente_id, id_caso, fecha, mensajes)

    aviso, texto_aviso = _avisar(numero, nuevo.tipo, cliente, nuevo.palabras_cliente, sustento or "",
                                 _destinatarios(cliente, responsable))
    with get_connection(db_path, escritura=True) as con:
        _log(con, cliente_id, id_caso, f"{fecha[:10]} {datetime.now():%H:%M}", [("sistema", texto_aviso)])

    return CasoRegistrado(
        numero_caso=numero, tipo=nuevo.tipo, estado="derivado", ya_existia=False,
        derivado_a_nombre=cliente["nombre"], monto_discutido=monto, fecha_creacion=fecha, aviso=aviso,
    )


def _log(con, cliente_id: int, id_caso: int, fecha: str, mensajes: list[tuple[str, str]]) -> None:
    con.executemany(
        "INSERT INTO interaccion_log (id_cliente, id_caso, fecha, rol, mensaje) VALUES (?, ?, ?, ?, ?)",
        [(cliente_id, id_caso, fecha, rol, texto) for rol, texto in mensajes],
    )


def _caso_equivalente(con, cliente_id: int, nuevo: NuevoCaso, id_factura, id_averia, id_solicitud):
    """Caso abierto del mismo cliente y tipo que ya cubre este pedido, o None.

    Con referencias: mismo tipo y mismas referencias. Sin ninguna (p. ej.
    fuera_de_alcance): mismo tipo y mismas palabras del cliente, para absorber
    reintentos del bot sin fundir pedidos distintos.
    """
    base = f"""
        SELECT c.id_caso, c.estado, c.monto_discutido, c.fecha_creacion, p.nombre AS derivado_a_nombre
        FROM caso c LEFT JOIN personal p ON p.id_personal = c.id_derivado_a
        WHERE c.id_cliente = ? AND c.tipo_caso = ? AND c.estado IN ({_ABIERTOS})
    """
    if any(v is not None for v in (id_factura, id_averia, id_solicitud)):
        return con.execute(
            base + " AND c.id_factura IS ? AND c.id_averia IS ? AND c.id_solicitud IS ? ORDER BY c.id_caso LIMIT 1",
            (cliente_id, nuevo.tipo, id_factura, id_averia, id_solicitud),
        ).fetchone()
    return con.execute(
        base + """ AND c.id_factura IS NULL AND c.id_averia IS NULL AND c.id_solicitud IS NULL
               AND EXISTS (SELECT 1 FROM interaccion_log l
                           WHERE l.id_caso = c.id_caso AND l.rol = 'cliente' AND l.mensaje = ?)
               ORDER BY c.id_caso LIMIT 1""",
        (cliente_id, nuevo.tipo, nuevo.palabras_cliente),
    ).fetchone()


# ------------------------------------------------------------------ lectura

def listar_casos(cliente_id: int, db_path: Path | None = None) -> ListaCasos:
    """Casos del cliente, del más reciente al más antiguo (incluye los sembrados del modo B)."""
    _validar_cliente_id(cliente_id)
    with get_connection(db_path) as con:
        filas = con.execute(
            """
            SELECT c.id_caso, c.tipo_caso, c.canal, c.estado, c.fecha_creacion, c.fecha_cierre,
                   p.nombre AS derivado_a_nombre, c.monto_discutido, f.numero AS numero_factura,
                   c.id_averia, c.id_solicitud, c.sustento
            FROM caso c
            LEFT JOIN personal p ON p.id_personal = c.id_derivado_a
            LEFT JOIN factura f ON f.id_factura = c.id_factura AND f.id_cliente = c.id_cliente
            WHERE c.id_cliente = ?
            ORDER BY c.fecha_creacion DESC, c.id_caso DESC
            """,
            (cliente_id,),
        ).fetchall()
    return ListaCasos(casos=[
        CasoResumen(
            numero_caso=numero_caso(f["id_caso"]), tipo=f["tipo_caso"], canal=f["canal"], estado=f["estado"],
            fecha_creacion=f["fecha_creacion"], fecha_cierre=f["fecha_cierre"],
            derivado_a_nombre=f["derivado_a_nombre"], monto_discutido=f["monto_discutido"],
            numero_factura=f["numero_factura"], id_averia=f["id_averia"], id_solicitud=f["id_solicitud"],
            resumen=f["sustento"],
        )
        for f in filas
    ])
