"""
CRUD por entidad para Anticipa.

Cada entidad tiene su propia clase. Los métodos CRUD están disponibles en cada
clase mediante BaseEntityCRUD; los métodos específicos de las casuísticas están
declarados dentro de la clase correspondiente.

IMPORTANTE: validar nombres de columnas y nombres/columnas de vistas contra el
DDL real de anticipa.db antes de producción. El documento nombra 8 vistas, aunque
indica que existen 9. No se inventa la novena vista.
"""

from datetime import date
from pathlib import Path
from typing import Any, Mapping

from app.data.conexion import get_connection


class BaseEntityCRUD:
    tabla = ""
    pk = ""
    columnas = ()
    permite_delete_fisico = True

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path

    def _validar_datos(self, datos: Mapping[str, Any]) -> dict:
        if not isinstance(datos, Mapping) or not datos:
            raise ValueError("Debes enviar un diccionario no vacío")
        valores = dict(datos)
        invalidas = set(valores) - set(self.columnas)
        if invalidas:
            raise ValueError(f"Columnas no permitidas en {self.tabla}: {sorted(invalidas)}")
        return valores

    def _one(self, sql, params=()):
        with get_connection(self.db_path) as con:
            row = con.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def _all(self, sql, params=()):
        with get_connection(self.db_path) as con:
            rows = con.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def _run(self, sql, params=()):
        with get_connection(self.db_path) as con:
            cur = con.execute(sql, params)
            return cur.rowcount, cur.lastrowid

    # CRUD común para todas las entidades
    # def crear(self, datos: Mapping[str, Any]):
    #     values = self._validar_datos(datos)
    #     cols = list(values)
    #     sql = (f'INSERT INTO "{self.tabla}" '
    #            f'({", ".join(chr(34)+c+chr(34) for c in cols)}) '
    #            f'VALUES ({", ".join("?" for _ in cols)})')
    #     _, new_id = self._run(sql, list(values.values()))
    #     return values.get(self.pk, new_id)

    def crear(self, datos: Mapping[str, Any]):
        valores = dict(datos)
        # Permitir la PK si se proporciona manualmente
        columnas_permitidas = set(self.columnas) | {self.pk}
        invalidas = set(valores) - columnas_permitidas
        if invalidas:
            raise ValueError(
                f"Columnas no permitidas en {self.tabla}: {sorted(invalidas)}"
            )
        if not valores:
            raise ValueError("Debes enviar al menos un campo")
        cols = list(valores)
        sql = (
            f'INSERT INTO "{self.tabla}" '
            f'({", ".join(chr(34)+c+chr(34) for c in cols)}) '
            f'VALUES ({", ".join("?" for _ in cols)})'
        )
        _, new_id = self._run(sql, list(valores.values()))
        return valores.get(self.pk, new_id)


    def obtener(self, registro_id):
        if registro_id is None:
            raise ValueError(f"{self.pk} es obligatorio")
        return self._one(
            f'SELECT * FROM "{self.tabla}" WHERE "{self.pk}" = ?',
            (registro_id,),
        )

    def listar(self, filtros=None, limite=50, offset=0,
               ordenar_por=None, descendente=False):
        filtros = dict(filtros or {})
        allowed = set(self.columnas) | {self.pk}
        if set(filtros) - allowed:
            raise ValueError("Hay filtros con columnas no permitidas")
        ordenar_por = ordenar_por or self.pk
        if ordenar_por not in allowed:
            raise ValueError("Columna de ordenamiento no permitida")
        condiciones, params = [], []
        for col, val in filtros.items():
            if val is None:
                condiciones.append(f'"{col}" IS NULL')
            else:
                condiciones.append(f'"{col}" = ?')
                params.append(val)
        where = f" WHERE {' AND '.join(condiciones)}" if condiciones else ""
        direction = "DESC" if descendente else "ASC"
        params.extend([max(1, min(int(limite), 500)), max(0, int(offset))])
        sql = (f'SELECT * FROM "{self.tabla}"{where} '
               f'ORDER BY "{ordenar_por}" {direction} LIMIT ? OFFSET ?')
        return self._all(sql, params)

    def actualizar(self, registro_id, datos: Mapping[str, Any]):
        if registro_id is None:
            raise ValueError(f"{self.pk} es obligatorio")
        values = self._validar_datos(datos)
        sets = ", ".join(f'"{col}" = ?' for col in values)
        count, _ = self._run(
            f'UPDATE "{self.tabla}" SET {sets} WHERE "{self.pk}" = ?',
            [*values.values(), registro_id],
        )
        return count > 0

    def eliminar(self, registro_id):
        if registro_id is None:
            raise ValueError(f"{self.pk} es obligatorio")
        if not self.permite_delete_fisico:
            raise ValueError(f"DELETE físico deshabilitado para {self.tabla}")
        count, _ = self._run(
            f'DELETE FROM "{self.tabla}" WHERE "{self.pk}" = ?',
            (registro_id,),
        )
        return count > 0

    def desactivar(self, registro_id, estado="inactivo"):
        if "estado" not in self.columnas:
            raise ValueError(f"{self.tabla} no tiene columna estado")
        return self.actualizar(registro_id, {"estado": estado})


# ------------------------------ MAESTROS -----------------------------------

class PersonalCRUD(BaseEntityCRUD):
    tabla, pk = "personal", "id_personal"
    columnas = ("nombre", "rol", "correo")

    def obtener_por_rol(self, rol):
        return self.listar({"rol": rol})

    def obtener_por_correo(self, correo):
        return self._one("SELECT * FROM personal WHERE correo = ?", (correo,))


class ProductoCRUD(BaseEntityCRUD):
    tabla, pk = "producto", "codigo"
    columnas = ("nombre", "descripcion", "unidad", "tarifa_mensual",
                "sla_disponibilidad", "gb_incluidos_por_linea", "precio_gb_exceso")


class ClienteCRUD(BaseEntityCRUD):
    tabla, pk = "cliente", "id_cliente"
    columnas = ("ruc", "razon_social", "sector", "segmento",
                "correo_facturacion", "contacto_nombre", "id_ejecutivo",
                "plazo_atencion_dias", "estado")

    def obtener_por_ruc(self, ruc):
        return self._one("SELECT * FROM cliente WHERE ruc = ?", (ruc.strip(),))

    def obtener_contacto_facturacion(self, cliente_id):
        return self._one(
            """SELECT id_cliente, correo_facturacion, contacto_nombre
               FROM cliente WHERE id_cliente = ?""", (cliente_id,))

    def obtener_ejecutivo(self, cliente_id):
        return self._one(
            """SELECT p.id_personal, p.nombre, p.rol, p.correo
               FROM cliente c JOIN personal p ON p.id_personal=c.id_ejecutivo
               WHERE c.id_cliente = ?""", (cliente_id,))


class ServicioContratadoCRUD(BaseEntityCRUD):
    tabla, pk = "servicio_contratado", "id_servicio"
    columnas = ("id_cliente", "codigo_producto", "sede", "cantidad",
                "tarifa_pactada", "sla_pactado", "fecha_activacion",
                "fecha_baja", "estado")

    def listar_servicios_cliente(self, cliente_id):
        return self._all(
            """SELECT sc.*, p.nombre AS producto_nombre
               FROM servicio_contratado sc JOIN producto p
               ON p.codigo=sc.codigo_producto
               WHERE sc.id_cliente=? ORDER BY sc.id_servicio""", (cliente_id,))

    def obtener_tarifa_y_sla(self, servicio_id):
        return self.obtener(servicio_id)

    def detectar_baja_facturada(self, cliente_id):
        return self._all(
            "SELECT * FROM v_servicios_baja_facturados WHERE id_cliente=?",
            (cliente_id,))


# ------------------------------ FACTURACIÓN --------------------------------

class FacturaCRUD(BaseEntityCRUD):
    tabla, pk = "factura", "id_factura"
    columnas = ("numero", "id_cliente", "periodo", "fecha_emision",
                "fecha_vencimiento", "subtotal", "igv", "total", "estado")
    permite_delete_fisico = False

    def obtener_por_numero(self, cliente_id, numero):
        return self._one(
            "SELECT * FROM factura WHERE id_cliente=? AND numero=?",
            (cliente_id, numero.strip().upper()))

    def obtener_por_periodo(self, cliente_id, periodo):
        return self._all(
            """SELECT * FROM factura WHERE id_cliente=? AND periodo=?
               ORDER BY fecha_emision, id_factura""", (cliente_id, periodo))

    def obtener_factura_con_lineas(self, cliente_id, periodo):
        return self._all(
            """SELECT f.*, l.id_linea, l.id_servicio, l.tipo, l.concepto,
                      l.cantidad, l.precio_unitario, l.monto
               FROM factura f LEFT JOIN factura_linea l ON l.id_factura=f.id_factura
               WHERE f.id_cliente=? AND f.periodo=?
               ORDER BY f.id_factura, l.id_linea""", (cliente_id, periodo))

    def consultar_saldo(self, cliente_id):
        return self._one(
            """SELECT COALESCE(SUM(CASE WHEN estado IN
                      ('emitida','vencida','en_disputa') THEN total ELSE 0 END),0)
                      AS saldo_total,
                      COALESCE(SUM(CASE WHEN estado='vencida'
                      THEN total ELSE 0 END),0) AS saldo_vencido,
                      SUM(CASE WHEN estado IN
                      ('emitida','vencida','en_disputa') THEN 1 ELSE 0 END)
                      AS cantidad_pendiente
               FROM factura WHERE id_cliente=?""", (cliente_id,))

    def detectar_duplicadas(self, cliente_id):
        return self._all(
            "SELECT * FROM v_facturas_duplicadas WHERE id_cliente=?",
            (cliente_id,))

    def detectar_variacion_facturacion(self, cliente_id):
        return self._all(
            "SELECT * FROM v_variacion_facturacion WHERE id_cliente=?",
            (cliente_id,))


class FacturaLineaCRUD(BaseEntityCRUD):
    tabla, pk = "factura_linea", "id_linea"
    columnas = ("id_factura", "id_servicio", "tipo", "concepto",
                "cantidad", "precio_unitario", "monto")
    permite_delete_fisico = False

    def listar_por_factura(self, factura_id):
        return self._all(
            "SELECT * FROM factura_linea WHERE id_factura=? ORDER BY id_linea",
            (factura_id,))

    def detectar_tarifas_distintas(self, cliente_id):
        return self._all(
            "SELECT * FROM v_tarifa_distinta WHERE id_cliente=?", (cliente_id,))

    def detectar_excesos_sin_sustento(self, cliente_id):
        return self._all(
            "SELECT * FROM v_exceso_sin_sustento WHERE id_cliente=?", (cliente_id,))


class ConsumoCRUD(BaseEntityCRUD):
    tabla, pk = "consumo", "id_consumo"
    columnas = ("id_servicio", "periodo", "gb_incluidos", "gb_usados",
                "exceso_gb", "monto_exceso")
    permite_delete_fisico = False

    def obtener_consumo(self, servicio_id, periodo):
        return self._one(
            "SELECT * FROM consumo WHERE id_servicio=? AND periodo=?",
            (servicio_id, periodo))


# ------------------------------ OPERACIÓN ----------------------------------

class AveriaCRUD(BaseEntityCRUD):
    tabla, pk = "averia", "id_averia"
    columnas = ("id_servicio", "unidades_afectadas", "fecha_inicio",
                "fecha_fin", "horas_caida", "causa", "estado")
    permite_delete_fisico = False

    def listar_averias_cliente(self, cliente_id):
        return self._all(
            """SELECT a.*, sc.id_cliente, sc.tarifa_pactada, sc.sla_pactado
               FROM averia a JOIN servicio_contratado sc
               ON sc.id_servicio=a.id_servicio
               WHERE sc.id_cliente=? ORDER BY a.fecha_inicio DESC""",
            (cliente_id,))

    def detectar_sin_compensar(self, cliente_id):
        return self._all(
            "SELECT * FROM v_averias_sin_compensar WHERE id_cliente=?",
            (cliente_id,))


class SolicitudCRUD(BaseEntityCRUD):
    tabla, pk = "solicitud", "id_solicitud"
    columnas = ("id_cliente", "id_servicio", "tipo", "descripcion",
                "fecha_registro", "fecha_cierre", "estado", "id_responsable")
    permite_delete_fisico = False

    def listar_solicitudes_cliente(self, cliente_id):
        return self._all(
            """SELECT * FROM solicitud WHERE id_cliente=?
               ORDER BY fecha_registro DESC""", (cliente_id,))

    def detectar_vencidas(self, cliente_id):
        return self._all(
            "SELECT * FROM v_solicitudes_vencidas WHERE id_cliente=?",
            (cliente_id,))

    def actualizar_estado(self, solicitud_id, estado):
        return self.actualizar(solicitud_id, {"estado": estado})


# --------------------------- GESTIÓN DEL AGENTE ----------------------------

class CasoCRUD(BaseEntityCRUD):
    tabla, pk = "caso", "id_caso"
    columnas = ("id_cliente", "canal", "opcion", "tipo_caso", "id_factura",
                "id_averia", "id_solicitud", "monto_discutido", "tramo",
                "estado", "id_derivado_a", "sustento", "fecha_creacion",
                "fecha_cierre")
    permite_delete_fisico = False

    def listar_casos_cliente(self, cliente_id):
        return self._all(
            "SELECT * FROM caso WHERE id_cliente=? ORDER BY fecha_creacion DESC",
            (cliente_id,))

    def derivar_caso(self, caso_id, responsable_id):
        return self.actualizar(caso_id, {
            "id_derivado_a": responsable_id, "estado": "escalado"})

    def cerrar_caso(self, caso_id, sustento=None):
        data = {"estado": "cerrado", "fecha_cierre": date.today().isoformat()}
        if sustento is not None:
            data["sustento"] = sustento
        return self.actualizar(caso_id, data)


class AjusteCRUD(BaseEntityCRUD):
    tabla, pk = "ajuste", "id_ajuste"
    columnas = ("id_caso", "id_factura", "id_averia", "tipo_documento",
                "motivo", "monto_sin_igv", "igv", "total", "estado",
                "id_aprobador", "fecha_creacion", "fecha_aplicacion")
    permite_delete_fisico = False

    def listar_por_caso(self, caso_id):
        return self._all(
            "SELECT * FROM ajuste WHERE id_caso=? ORDER BY id_ajuste",
            (caso_id,))

    def validar_gesto_mensual(self, cliente_id, periodo):
        return self._all(
            """SELECT * FROM v_gestos_mes_actual
               WHERE id_cliente=? AND periodo=?""", (cliente_id, periodo))

    def aprobar_ajuste(self, ajuste_id, aprobador_id):
        return self.actualizar(ajuste_id, {
            "estado": "aprobado", "id_aprobador": aprobador_id})

    def rechazar_ajuste(self, ajuste_id, aprobador_id):
        return self.actualizar(ajuste_id, {
            "estado": "rechazado", "id_aprobador": aprobador_id})

    def aplicar_ajuste(self, ajuste_id, fecha_aplicacion):
        return self.actualizar(ajuste_id, {
            "estado": "aplicado", "fecha_aplicacion": fecha_aplicacion})


class VerificacionCRUD(BaseEntityCRUD):
    tabla, pk = "verificacion", "id_verificacion"
    columnas = ("id_cliente", "ruc_ingresado", "codigo_hash", "fecha_envio",
                "fecha_expira", "intentos", "estado")
    permite_delete_fisico = False

    def obtener_ultima_por_ruc(self, ruc):
        return self._one(
            """SELECT * FROM verificacion WHERE ruc_ingresado=?
               ORDER BY id_verificacion DESC LIMIT 1""", (ruc,))

    def incrementar_intentos(self, verificacion_id):
        count, _ = self._run(
            """UPDATE verificacion SET intentos=intentos+1
               WHERE id_verificacion=?""", (verificacion_id,))
        return count > 0

    def bloquear(self, verificacion_id):
        return self.actualizar(verificacion_id, {"estado": "bloqueado"})

    def validar_vigencia(self, verificacion_id, ahora_iso):
        return self._one(
            """SELECT id_verificacion FROM verificacion
               WHERE id_verificacion=? AND fecha_expira>=?
               AND intentos<3 AND estado NOT IN ('bloqueado','expirado')""",
            (verificacion_id, ahora_iso)) is not None


class InteraccionLogCRUD(BaseEntityCRUD):
    tabla, pk = "interaccion_log", "id_log"
    columnas = ("id_cliente", "id_caso", "fecha", "rol", "mensaje")
    permite_delete_fisico = False

    def obtener_historial_cliente(self, cliente_id, limite=50):
        return self._all(
            """SELECT * FROM interaccion_log WHERE id_cliente=?
               ORDER BY fecha DESC LIMIT ?""",
            (cliente_id, max(1, min(int(limite), 500))))

    def listar_por_caso(self, caso_id):
        return self._all(
            """SELECT * FROM interaccion_log WHERE id_caso=?
               ORDER BY fecha, id_log""", (caso_id,))


# -------------------------------- REGLAS ------------------------------------

class PoliticaTramoCRUD(BaseEntityCRUD):
    tabla, pk = "politica_tramo", "id_tramo"
    columnas = ("nombre", "monto_desde", "monto_hasta", "accion", "aprobador_rol")

    def obtener_tramo_por_monto(self, monto_sin_igv):
        return self._one(
            """SELECT * FROM politica_tramo
               WHERE ? > monto_desde
               AND (monto_hasta IS NULL OR ? <= monto_hasta)
               ORDER BY monto_desde LIMIT 1""",
            (monto_sin_igv, monto_sin_igv))


class ParametroCRUD(BaseEntityCRUD):
    tabla, pk = "parametro", "clave"
    columnas = ("valor", "descripcion")

    def obtener_valor(self, clave, default=None):
        row = self._one("SELECT valor FROM parametro WHERE clave=?", (clave,))
        return row["valor"] if row else default

    def obtener_fecha_sistema(self):
        return self.obtener_valor("fecha_actual", date.today().isoformat())


# Instancias listas para importar.
personal_crud = PersonalCRUD()
producto_crud = ProductoCRUD()
cliente_crud = ClienteCRUD()
servicio_contratado_crud = ServicioContratadoCRUD()
factura_crud = FacturaCRUD()
factura_linea_crud = FacturaLineaCRUD()
consumo_crud = ConsumoCRUD()
averia_crud = AveriaCRUD()
solicitud_crud = SolicitudCRUD()
caso_crud = CasoCRUD()
ajuste_crud = AjusteCRUD()
verificacion_crud = VerificacionCRUD()
interaccion_log_crud = InteraccionLogCRUD()
politica_tramo_crud = PoliticaTramoCRUD()
parametro_crud = ParametroCRUD()
