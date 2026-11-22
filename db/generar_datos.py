#!/usr/bin/env python3
"""
ANTICIPA - Generador de la base de datos SQLite con datos ficticios.

Uso:
    python3 generar_datos.py            # crea anticipa.db junto a este script

- Lee schema.sql (tablas, vistas, parámetros, tramos).
- Siembra 13 clientes con casuísticas CS-01..CS-13 (datos fijos y reproducibles).
- Genera 37 clientes adicionales con facturación calibrada a ~S/ 100 M en 6 meses
  (jun-nov 2026), es decir ~S/ 200 M anualizados.
- Valida con aserciones que cada vista de detección devuelve exactamente lo sembrado.
Todo es ficticio: RUC con prefijo 99. Los clientes 1-13 pueden recibir el código OTP
en correos reales del equipo: CORREO_PRUEBA_1..5 (y opcional NOMBRE_PRUEBA_1..5) en
../.env, repartidos en rotación (slot = (id_cliente - 1) % 5 + 1). Un slot vacío
deja sus clientes con facturacion@clienteNN.example. Para ignorar el .env:
    python3 generar_datos.py --publico     # todos los correos terminan en .example
Requiere AUTH_SECRET en ../.env: los códigos de prueba se guardan con el mismo HMAC que la app.
CORREO_EJECUTIVO_1..5 en ../.env: correo del ejecutivo de los clientes de cada slot (para
recibir el aviso de los casos derivados); el nombre del ejecutivo no cambia.
"""
import sqlite3, random, json, os, sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
# Mismo hash que la app (HMAC con AUTH_SECRET del .env): se importa para no duplicarlo.
sys.path.insert(0, os.path.dirname(HERE))
from app.auth.otp import hash_codigo  # noqa: E402
DB_PATH = os.path.join(HERE, "anticipa.db")
SCHEMA = os.path.join(HERE, "schema.sql")
JSON_OUT = os.path.join(HERE, "casos_datos.json")

PUBLICO = "--publico" in sys.argv

# Correos reales del equipo para la demo de OTP: se leen de ../.env para no versionarlos.
# Clientes sembrados 1-13 en rotación por 5 slots:
#   slot 1 -> 1, 6, 11 | slot 2 -> 2, 7, 12 | slot 3 -> 3, 8, 13 | slot 4 -> 4, 9 | slot 5 -> 5, 10
# Slot vacío, o --publico: el cliente queda con su correo .example y contacto generado.
N_SLOTS = 5
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, "..", ".env"), override=False)
except ImportError:
    pass
SLOTS = {n: (os.getenv(f"NOMBRE_PRUEBA_{n}", "").strip() or None,
             os.getenv(f"CORREO_PRUEBA_{n}", "").strip())
         for n in range(1, N_SLOTS + 1)}
CONTACTOS_PRUEBA = {} if PUBLICO else {  # id_cliente -> (contacto o None, correo)
    cid: SLOTS[(cid - 1) % N_SLOTS + 1]
    for cid in range(1, 14) if SLOTS[(cid - 1) % N_SLOTS + 1][1]
}


def ejecutivo_de(cid):
    """Ejecutivo de cuenta (id_personal 1-5) de un cliente."""
    return (cid % 5) + 1


def ejecutivo_del_slot(n):
    """Ejecutivo de los clientes de prueba del slot n: todos comparten el mismo
    (slot 1 -> 2, slot 2 -> 3, slot 3 -> 4, slot 4 -> 5, slot 5 -> 1)."""
    ejecutivos = {ejecutivo_de(cid) for cid in range(1, 14) if (cid - 1) % N_SLOTS + 1 == n}
    assert len(ejecutivos) == 1, f"el slot {n} tiene clientes con distintos ejecutivos"
    return ejecutivos.pop()


# Correo del ejecutivo de los clientes de tu slot (CORREO_EJECUTIVO_n): para recibir el
# aviso de los casos que se derivan (con NOTIFICAR_DERIVACIONES=true). Solo cambia el
# correo; el nombre del ejecutivo se mantiene. Vacío, o --publico: @anticipa.example.
CORREOS_EJECUTIVO = {} if PUBLICO else {  # id_personal -> correo
    ejecutivo_del_slot(n): os.getenv(f"CORREO_EJECUTIVO_{n}", "").strip()
    for n in range(1, N_SLOTS + 1) if os.getenv(f"CORREO_EJECUTIVO_{n}", "").strip()
}

FECHA_ACTUAL = date(2026, 12, 5)
IGV = 0.18
PERIODOS = ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]
TARGET_SUBTOTAL = 100_000_000
rng = random.Random(2026)

# ---------------------------------------------------------------- utilidades
def next_month_first(periodo):
    y, m = map(int, periodo.split("-"))
    return date(y + (m == 12), 1 if m == 12 else m + 1, 1)

def fmt_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")

def tramo_for(monto):
    if monto <= 100: return 1
    if monto <= 1000: return 2
    if monto <= 50000: return 3
    return 4

def r2(x):
    return round(x + 1e-9, 2)

# ---------------------------------------------------------------- catálogo
PRODUCTOS = [
    ("INT500", "Internet dedicado 500 Mbps", "Enlace simétrico con IP fija", "enlace", 4500.0, 0.995, None, None),
    ("MPLS", "Enlace de datos MPLS", "Red privada entre sedes", "enlace", 12000.0, 0.997, None, None),
    ("SIP", "Troncal SIP", "Voz sobre IP con numeración", "troncal", 3200.0, 0.995, None, None),
    ("MOV", "Móvil corporativo", "Plan por línea con bolsa de datos", "línea", 80.0, None, 10.0, 2.0),
]
PROD = {p[0]: p for p in PRODUCTOS}
NOMBRE_CONCEPTO = {"INT500": "Internet dedicado 500 Mbps", "MPLS": "Enlace MPLS",
                   "SIP": "Troncal SIP", "MOV": "Móvil corporativo"}

PERSONAL = [
    (1, "Carla Mendoza Ríos", "Ejecutivo de cuenta"),
    (2, "Jorge Salazar Vega", "Ejecutivo de cuenta"),
    (3, "Lucía Paredes Cano", "Ejecutivo de cuenta"),
    (4, "Diego Quispe Alva", "Ejecutivo de cuenta"),
    (5, "Rosa Huamán Torres", "Ejecutivo de cuenta"),
    (6, "Martín Cáceres Luna", "Jefatura de facturación"),
    (7, "Patricia Ugarte Soto", "Jefatura de facturación"),
    (8, "Fernando Valdivia Rey", "Gerencia y Finanzas"),
    (9, "Andrea Lozano Peña", "Área técnica"),
    (10, "Raúl Meza Campos", "Área técnica"),
]

SEEDED = {
    1: ("Minera Cordillera Azul S.A.C.", "Minería", "Mediano"),
    2: ("Distribuidora Pacífico Norte S.A.", "Comercio", "Mediano"),
    3: ("Constructora Andes Lima S.A.C.", "Construcción", "Mediano"),
    4: ("Retail Mercado Central S.A.", "Retail", "Mediano"),
    5: ("Agroexportadora Valle Verde S.A.C.", "Agroindustria", "Mediano"),
    6: ("Pesquera Mar Austral S.A.", "Pesca", "Mediano"),
    7: ("Logística Rápida del Callao S.A.C.", "Logística", "Mediano"),
    8: ("Clínica Santa Aurora S.A.C.", "Salud", "Pequeño"),
    9: ("Textiles Inca Real S.A.", "Manufactura", "Pequeño"),
    10: ("Universidad Técnica Horizonte", "Educación", "Pequeño"),
    11: ("Hotelera Costa Dorada S.A.C.", "Turismo", "Pequeño"),
    12: ("Seguros Atlántico Perú S.A.", "Seguros", "Pequeño"),
    13: ("Farmacias Salud Total S.A.C.", "Retail", "Pequeño"),
}

# (cliente, producto, sede, cantidad, activación, baja)
SEEDED_SERVICES = [
    (1, "INT500", "Lima", 10), (1, "MPLS", "Lima", 6), (1, "MPLS", "Arequipa", 4), (1, "SIP", "Lima", 5), (1, "MOV", "Lima", 50),
    (2, "INT500", "Lima", 6), (2, "MPLS", "Lima", 3), (2, "MPLS", "Cusco", 1, None, "2026-09-30"), (2, "SIP", "Lima", 3), (2, "MOV", "Lima", 40),
    (3, "INT500", "Lima", 4), (3, "MPLS", "Lima", 3), (3, "SIP", "Lima", 2), (3, "MOV", "Lima", 30),
    (4, "INT500", "Lima", 5), (4, "MPLS", "Lima", 2), (4, "SIP", "Lima", 2), (4, "MOV", "Lima", 120),
    (5, "INT500", "Lima", 3), (5, "MPLS", "Lima", 3), (5, "MPLS", "Trujillo", 2), (5, "SIP", "Lima", 4), (5, "MOV", "Lima", 60),
    (6, "INT500", "Lima", 5), (6, "INT500", "Piura", 3), (6, "MPLS", "Lima", 2), (6, "SIP", "Lima", 3), (6, "MOV", "Lima", 25),
    (7, "INT500", "Lima", 4), (7, "MPLS", "Lima", 3), (7, "MPLS", "Callao", 2, "2026-10-01"), (7, "SIP", "Lima", 4), (7, "MOV", "Lima", 80),
    (8, "INT500", "Lima", 4), (8, "MPLS", "Lima", 2), (8, "SIP", "Lima", 3), (8, "MOV", "Lima", 50),
    (9, "INT500", "Lima", 5), (9, "INT500", "Arequipa", 3, "2026-09-15"), (9, "MPLS", "Lima", 2), (9, "SIP", "Lima", 2), (9, "MOV", "Lima", 20),
    (10, "INT500", "Lima", 6), (10, "MPLS", "Lima", 3), (10, "SIP", "Lima", 2), (10, "MOV", "Lima", 40),
    (11, "INT500", "Lima", 4), (11, "MPLS", "Lima", 4), (11, "SIP", "Lima", 3), (11, "MOV", "Lima", 35),
    (12, "INT500", "Lima", 3), (12, "MPLS", "Lima", 2), (12, "SIP", "Lima", 2), (12, "MOV", "Lima", 25),
    (13, "INT500", "Lima", 3), (13, "MPLS", "Lima", 1), (13, "SIP", "Lima", 2), (13, "MOV", "Lima", 15),
]

SECT = ["Minería", "Comercio", "Construcción", "Retail", "Banca", "Energía", "Salud", "Educación",
        "Transporte", "Manufactura", "Telecom", "Alimentos", "Turismo", "Tecnología"]
N1 = ["Corporación", "Grupo", "Inversiones", "Industrias", "Servicios", "Comercial", "Operadora", "Consorcio"]
N2 = ["Andina", "del Sur", "Pacífico", "Altiplano", "Amazonas", "Nazca", "Rímac", "Chavín", "Sol Naciente",
      "Los Andes", "Tahuantinsuyo", "Costa Norte", "Cóndor", "Sierra Verde", "Lima Centro", "Huascarán",
      "Machu", "Paracas", "Titicaca", "Pampa Real", "Inti", "Kuntur", "Qhapaq", "Wari", "Moche",
      "Chimú", "Nasca", "Lambayeque", "Cajamarca", "Ayacucho", "Junín", "Tacna", "Ucayali", "Loreto",
      "Puno", "Piura Sur", "Ancash", "Ica Norte", "Huánuco"]
NOMS = ["Ana", "Luis", "María", "Carlos", "Sofía", "Pedro", "Elena", "Miguel", "Camila", "Hugo", "Valeria",
        "Raúl", "Diana", "Óscar", "Gabriela", "Iván", "Lorena", "Sergio", "Natalia", "César"]
APES = ["Rojas", "Flores", "Castillo", "Vargas", "Ramos", "Chávez", "Medina", "Núñez", "Aguilar", "Pacheco",
        "Silva", "Herrera", "Cruz", "Delgado", "Mamani", "Condori", "Salas", "Ortiz", "Ponce", "Zegarra"]
SEDES_EXTRA = ["Arequipa", "Trujillo", "Piura", "Cusco", "Chiclayo", "Callao", "Huancayo", "Ica"]

# ---------------------------------------------------------------- clientes
def build_clients():
    clients = {}
    rucs = set()
    def new_ruc():
        while True:
            r = "99" + "".join(str(rng.randint(0, 9)) for _ in range(9))
            if r not in rucs:
                rucs.add(r)
                return r
    used = set()
    for cid in range(1, 51):
        if cid in SEEDED:
            nombre, sector, seg = SEEDED[cid]
        else:
            while True:
                nombre = f"{rng.choice(N1)} {rng.choice(N2)} S.A.C."
                if nombre not in used:
                    break
            sector = rng.choice(SECT)
            seg = "Grande" if cid <= 21 else ("Mediano" if cid <= 35 else "Pequeño")
        used.add(nombre)
        contacto = f"{rng.choice(NOMS)} {rng.choice(APES)} {rng.choice(APES)}"
        slug = f"cliente{cid:02d}"
        correo = f"facturacion@{slug}.example"
        if cid in CONTACTOS_PRUEBA:   # se asigna después de sortear: no altera el resto de datos
            nombre_prueba, correo = CONTACTOS_PRUEBA[cid]
            contacto = nombre_prueba or contacto
        clients[cid] = dict(id=cid, ruc=new_ruc(), nombre=nombre, sector=sector, seg=seg,
                            correo=correo, contacto=contacto,
                            ejecutivo=ejecutivo_de(cid))
    return clients

# ---------------------------------------------------------------- servicios
RANGOS = {  # base por segmento: (min, max)
    "Grande":  {"INT500": (60, 120), "MPLS": (40, 80), "SIP": (20, 40), "MOV": (400, 1200)},
    "Mediano": {"INT500": (15, 30), "MPLS": (8, 16), "SIP": (6, 12), "MOV": (100, 300)},
    "Pequeño": {"INT500": (4, 10), "MPLS": (2, 5), "SIP": (2, 5), "MOV": (30, 90)},
}

def split_qty(q, k):
    if k <= 1 or q < k:
        return [q]
    cuts = sorted(rng.sample(range(1, q), k - 1))
    parts, prev = [], 0
    for c in cuts + [q]:
        parts.append(c - prev)
        prev = c
    return parts

def noise_base(clients):
    """Cantidades base (independientes del factor de calibración) y estructura de sedes."""
    base = {}
    for cid, c in clients.items():
        if cid in SEEDED:
            continue
        spec = []
        for prod, (lo, hi) in RANGOS[c["seg"]].items():
            q = rng.randint(lo, hi)
            k = 1
            if prod in ("INT500", "MPLS"):
                k = rng.choice([1, 1, 2, 3])
            sedes = ["Lima"] + rng.sample(SEDES_EXTRA, k - 1) if k > 1 else ["Lima"]
            fracs = [rng.random() + 0.3 for _ in sedes]
            spec.append((prod, sedes, q, fracs))
        act_base = rng.choice(["2023-05-01", "2024-02-01", "2024-09-01", "2025-01-01", "2025-04-01"])
        base[cid] = (spec, act_base)
    return base

def build_services(clients, base, f):
    servicios = []
    sid = 0
    def add(cid, prod, sede, cant, act, baja=None, bug=False):
        nonlocal sid
        sid += 1
        p = PROD[prod]
        servicios.append(dict(id=sid, cliente=cid, prod=prod, sede=sede, cantidad=cant,
                              tarifa=p[4], sla=p[5], act=act, baja=baja,
                              estado="baja" if baja else "activo", bug=bug))
        return sid
    for row in SEEDED_SERVICES:
        cid, prod, sede, cant = row[:4]
        act = row[4] if len(row) > 4 and row[4] else "2025-03-01"
        baja = row[5] if len(row) > 5 else None
        new_id = add(cid, prod, sede, cant, act, baja, bug=(cid == 2 and baja is not None))
        if cid == 3 and prod == "MPLS":
            servicios[-1]["tarifa"] = 10500.0   # tarifa pactada con descuento (CS-03)
    for cid, (spec, act_base) in base.items():
        for prod, sedes, q, fracs in spec:
            total_q = max(len(sedes), round(q * f))
            tot = sum(fracs)
            cants = [max(1, round(total_q * fr / tot)) for fr in fracs]
            for sede, cant in zip(sedes, cants):
                add(cid, prod, sede, cant, act_base)
    # controles negativos (no deben disparar ninguna vista)
    add(25, "MPLS", "Chiclayo", 1, "2024-02-01", baja="2026-08-31")   # baja bien aplicada
    add(30, "SIP", "Ica", 2, "2026-08-10")                             # alta con prorrateo legítimo
    return servicios

# ---------------------------------------------------------------- facturación
def billed_in_period(s, periodo):
    first = date(int(periodo[:4]), int(periodo[5:]), 1)
    nxt = next_month_first(periodo)
    act = date.fromisoformat(s["act"])
    if act >= nxt:
        return None
    if s["baja"] and periodo > s["baja"][:7] and not s["bug"]:
        return None
    if act.year == first.year and act.month == first.month and act.day > 1:
        return ("prorrateo", 30 - act.day)
    return ("cargo_mensual", 30)

TARIFA_OVERRIDE = {}   # (id_servicio, periodo) -> tarifa facturada distinta
FAKE_EXCESO = {}       # (id_servicio, periodo) -> GB facturados sin sustento

def bill(clients, servicios, tarifa_override, fake_exceso):
    facturas, consumos = [], []
    by_cli = {}
    for s in servicios:
        by_cli.setdefault(s["cliente"], []).append(s)
    for periodo in PERIODOS:
        emi = next_month_first(periodo)
        venc = emi + timedelta(days=20)
        for cid in sorted(clients):
            lineas = []
            for s in by_cli.get(cid, []):
                tipo = billed_in_period(s, periodo)
                if not tipo:
                    continue
                kind, dias = tipo
                tarifa = tarifa_override.get((s["id"], periodo), s["tarifa"])
                if kind == "prorrateo":
                    precio = r2(tarifa * dias / 30)
                    concepto = f"{NOMBRE_CONCEPTO[s['prod']]} {s['sede']} (prorrateo {dias} días)"
                else:
                    precio = tarifa
                    concepto = f"{NOMBRE_CONCEPTO[s['prod']]} {s['sede']}"
                lineas.append(dict(id_servicio=s["id"], tipo=kind, concepto=concepto,
                                   cantidad=s["cantidad"], precio=precio, monto=r2(s["cantidad"] * precio)))
                if s["prod"] == "MOV":
                    incl = s["cantidad"] * PROD["MOV"][6]
                    rr = random.Random(f"{s['id']}-{periodo}")
                    seeded = cid in SEEDED
                    if (not seeded) and rr.random() < 0.15:
                        exceso = float(rr.randint(5, 40))
                    else:
                        exceso = 0.0
                    usados = incl + exceso if exceso > 0 else round(incl * rr.uniform(0.55, 0.95), 1)
                    consumos.append(dict(id_servicio=s["id"], periodo=periodo, incl=incl, usados=usados,
                                         exceso=exceso, monto=r2(exceso * PROD["MOV"][7])))
                    if exceso > 0:
                        lineas.append(dict(id_servicio=s["id"], tipo="exceso",
                                           concepto=f"Exceso de datos {s['sede']}", cantidad=exceso,
                                           precio=PROD["MOV"][7], monto=r2(exceso * PROD["MOV"][7])))
                    if (s["id"], periodo) in fake_exceso:
                        gb = float(fake_exceso[(s["id"], periodo)])
                        lineas.append(dict(id_servicio=s["id"], tipo="exceso",
                                           concepto=f"Exceso de datos {s['sede']}", cantidad=gb,
                                           precio=PROD["MOV"][7], monto=r2(gb * PROD["MOV"][7])))
            if not lineas:
                continue
            sub = r2(sum(l["monto"] for l in lineas))
            igv = r2(sub * IGV)
            facturas.append(dict(cliente=cid, periodo=periodo, emision=emi, venc=venc,
                                 subtotal=sub, igv=igv, total=r2(sub + igv), lineas=lineas, estado=None))
    return facturas, consumos

def total_subtotal(facturas):
    return sum(f["subtotal"] for f in facturas)

# ---------------------------------------------------------------- principal
def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    clients = build_clients()
    base = noise_base(clients)

    # Calibración del factor de cantidades para ~S/ 100 M en 6 meses
    f = 1.0
    for _ in range(8):
        servicios = build_services(clients, base, f)
        ids_c3 = [s["id"] for s in servicios if s["cliente"] == 3 and s["prod"] == "MPLS"][0]
        ids_c4 = [s["id"] for s in servicios if s["cliente"] == 4 and s["prod"] == "MOV"][0]
        TARIFA_OVERRIDE = {(ids_c3, p): 12000.0 for p in ("2026-09", "2026-10", "2026-11")}
        FAKE_EXCESO = {(ids_c4, "2026-10"): 150}
        facturas, consumos = bill(clients, servicios, TARIFA_OVERRIDE, FAKE_EXCESO)
        tot = total_subtotal(facturas)
        if abs(tot - TARGET_SUBTOTAL) / TARGET_SUBTOTAL < 0.004:
            break
        f *= TARGET_SUBTOTAL / tot
    print(f"Factor de calibración: {f:.3f} | Subtotal 6 meses: S/ {tot:,.2f}")

    # Estados de facturas
    dup_c1 = None
    for fa in facturas:
        fa["estado"] = "pagada" if fa["venc"] < FECHA_ACTUAL else "emitida"
        if fa["cliente"] == 9 and fa["periodo"] == "2026-10":
            fa["estado"] = "vencida"
    # CS-01: duplicado de la factura de noviembre del cliente 1
    orig = [x for x in facturas if x["cliente"] == 1 and x["periodo"] == "2026-11"][0]
    dup = dict(orig, lineas=[dict(l) for l in orig["lineas"]], estado="emitida")
    facturas.append(dup)
    # Duplicados legados ya resueltos (factura repetida anulada)
    legacy_dups = []
    for cid, per in [(15, "2026-07"), (24, "2026-08"), (38, "2026-09")]:
        o = [x for x in facturas if x["cliente"] == cid and x["periodo"] == per][0]
        d = dict(o, lineas=[dict(l) for l in o["lineas"]], estado="anulada")
        facturas.append(d)
        legacy_dups.append((cid, per, d))

    # Numeración (orden por periodo, cliente; duplicados al final de su periodo)
    facturas.sort(key=lambda x: (x["periodo"], x["cliente"], x["estado"] in ("anulada",) or x is dup))
    for i, fa in enumerate(facturas, 1):
        fa["id"] = i
        fa["numero"] = f"F001-{i:06d}"

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(open(SCHEMA, encoding="utf-8").read())
    cur = con.cursor()

    for pid, nombre, rol in PERSONAL:
        correo = nombre.lower().replace(" ", ".").replace("á", "a").replace("é", "e").replace("í", "i") \
            .replace("ó", "o").replace("ú", "u").replace("ñ", "n") + ".example"
        correo = CORREOS_EJECUTIVO.get(pid) or f"{correo[:-8]}@anticipa.example"
        cur.execute("INSERT INTO personal VALUES (?,?,?,?)", (pid, nombre, rol, correo))
    cur.executemany("INSERT INTO producto VALUES (?,?,?,?,?,?,?,?)", PRODUCTOS)
    for c in clients.values():
        cur.execute("INSERT INTO cliente VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (c["id"], c["ruc"], c["nombre"], c["sector"], c["seg"], c["correo"], c["contacto"],
                     c["ejecutivo"], 10, "activo"))
    for s in servicios:
        cur.execute("INSERT INTO servicio_contratado VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (s["id"], s["cliente"], s["prod"], s["sede"], s["cantidad"], s["tarifa"], s["sla"],
                     s["act"], s["baja"], s["estado"]))

    lid = 0
    for fa in facturas:
        cur.execute("INSERT INTO factura VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (fa["id"], fa["numero"], fa["cliente"], fa["periodo"], fa["emision"].isoformat(),
                     fa["venc"].isoformat(), fa["subtotal"], fa["igv"], fa["total"], fa["estado"]))
        for l in fa["lineas"]:
            lid += 1
            cur.execute("INSERT INTO factura_linea VALUES (?,?,?,?,?,?,?,?)",
                        (lid, fa["id"], l["id_servicio"], l["tipo"], l["concepto"], l["cantidad"],
                         l["precio"], l["monto"]))
    for i, c in enumerate(consumos, 1):
        cur.execute("INSERT INTO consumo VALUES (?,?,?,?,?,?,?)",
                    (i, c["id_servicio"], c["periodo"], c["incl"], c["usados"], c["exceso"], c["monto"]))

    # --------------------------------------------------------- averías
    aid = 0
    usadas = set()
    svc_by_id = {s["id"]: s for s in servicios}
    def add_averia(sid, ini, horas, causa, unidades=1):
        nonlocal aid
        aid += 1
        fin = ini + timedelta(hours=horas)
        cur.execute("INSERT INTO averia VALUES (?,?,?,?,?,?,?,?)",
                    (aid, sid, unidades, fmt_dt(ini), fmt_dt(fin), horas, causa, "cerrada"))
        usadas.add((sid, ini.strftime("%Y-%m")))
        return aid

    sid_tru = [s["id"] for s in servicios if s["cliente"] == 5 and s["sede"] == "Trujillo"][0]
    sid_piu = [s["id"] for s in servicios if s["cliente"] == 6 and s["sede"] == "Piura"][0]
    av_c5 = add_averia(sid_tru, datetime(2026, 10, 18, 8, 0), 30.0, "Corte de fibra por obra civil")
    av_c6 = add_averia(sid_piu, datetime(2026, 10, 3, 6, 0), 9.0, "Falla de equipo de acceso")

    noise_sla = [s for s in servicios if s["cliente"] not in SEEDED and s["sla"] and not s["baja"]
                 and s["id"] not in (sid_tru, sid_piu)]
    rng.shuffle(noise_sla)

    # Averías legadas con compensación ya aplicada (4)
    legacy_av = []
    for s in noise_sla[:4]:
        per = rng.choice(["2026-07", "2026-08", "2026-09"])
        tol = (1 - s["sla"]) * 720
        horas = round(tol + rng.uniform(4, 14), 1)
        ini = datetime(int(per[:4]), int(per[5:]), rng.randint(2, 24), rng.randint(0, 20), 0)
        a_id = add_averia(s["id"], ini, horas, "Falla en nodo de agregación")
        desc = r2(s["tarifa"] * 1 * (horas - tol) / 720)
        fact = [x for x in facturas if x["cliente"] == s["cliente"] and x["periodo"] == per][0]
        legacy_av.append((s, a_id, desc, fact, per))
    # Averías menores dentro de tolerancia (30)
    for s in noise_sla[4:34]:
        per = rng.choice(PERIODOS)
        if (s["id"], per) in usadas:
            continue
        tol = (1 - s["sla"]) * 720
        horas = round(rng.uniform(0.3, tol * 0.9), 1)
        ini = datetime(int(per[:4]), int(per[5:]), rng.randint(1, 25), rng.randint(0, 20), 0)
        add_averia(s["id"], ini, horas, rng.choice(["Mantenimiento correctivo", "Reinicio de equipo", "Corte eléctrico"]))

    # --------------------------------------------------------- solicitudes
    solid = 0
    def add_sol(cid, tipo, desc, reg, cierre, estado, resp, sid=None):
        nonlocal solid
        solid += 1
        cur.execute("INSERT INTO solicitud VALUES (?,?,?,?,?,?,?,?,?)",
                    (solid, cid, sid, tipo, desc, reg, cierre, estado, resp))
        return solid
    sol_c10 = add_sol(10, "actualización de datos", "Actualizar la razón social y dirección fiscal en la factura",
                      "2026-11-14", None, "abierta", clients[10]["ejecutivo"])
    add_sol(10, "información", "Detalle de líneas móviles activas por sede", "2026-11-30", None, "en_proceso", clients[10]["ejecutivo"])
    add_sol(10, "información", "Copia de factura de agosto", "2026-09-10", "2026-09-12", "cerrada", clients[10]["ejecutivo"])
    tipos = [("actualización de datos", "Cambio de contacto de facturación"),
             ("información", "Solicitud de copia de factura"),
             ("información", "Consulta sobre fecha de corte"),
             ("cambio de servicio", "Aumento de ancho de banda en sede principal")]
    for cid in range(14, 51):
        for _ in range(rng.choice([0, 1, 2])):
            t, d = rng.choice(tipos)
            reg = date(2026, rng.choice([8, 9, 10]), rng.randint(1, 25))
            add_sol(cid, t, d, reg.isoformat(), (reg + timedelta(days=rng.randint(1, 8))).isoformat(),
                    "cerrada", clients[cid]["ejecutivo"])
        if rng.random() < 0.10:
            reg = FECHA_ACTUAL - timedelta(days=rng.randint(1, 8))
            t, d = rng.choice(tipos)
            add_sol(cid, t, d, reg.isoformat(), None, rng.choice(["abierta", "en_proceso"]), clients[cid]["ejecutivo"])

    # --------------------------------------------------------- casos / ajustes
    cid_caso = 0
    aj_id = 0
    def add_caso(cli, canal, opcion, tipo, fac=None, av=None, sol=None, monto=None, estado="resuelto",
                 deriv=None, sustento=None, creado="2026-11-20 10:00", cierre=None):
        nonlocal cid_caso
        cid_caso += 1
        tr = tramo_for(monto) if monto else None
        cur.execute("INSERT INTO caso VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cid_caso, cli, canal, opcion, tipo, fac, av, sol, monto, tr, estado, deriv, sustento, creado, cierre))
        return cid_caso
    def add_ajuste(caso, fac, av, tipo_doc, motivo, monto, estado, aprob, creado, aplic):
        nonlocal aj_id
        aj_id += 1
        igv = r2(monto * IGV)
        cur.execute("INSERT INTO ajuste VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (aj_id, caso, fac, av, tipo_doc, motivo, monto, igv, r2(monto + igv), estado, aprob, creado, aplic))
        return aj_id
    def add_log(cli, caso, fecha, rol, msg):
        cur.execute("INSERT INTO interaccion_log (id_cliente,id_caso,fecha,rol,mensaje) VALUES (?,?,?,?,?)",
                    (cli, caso, fecha, rol, msg))
    def add_verif(cli, ruc, envio, intentos, estado, code="123456"):
        exp = datetime.strptime(envio, "%Y-%m-%d %H:%M") + timedelta(minutes=10)
        h = hash_codigo(code) if code else None
        cur.execute("INSERT INTO verificacion (id_cliente,ruc_ingresado,codigo_hash,fecha_envio,fecha_expira,intentos,estado) "
                    "VALUES (?,?,?,?,?,?,?)", (cli, ruc, h, envio, fmt_dt(exp), intentos, estado))

    # Duplicados legados (anulados)
    for cid, per, d in legacy_dups:
        c = add_caso(cid, "correo", "B", "factura_duplicada", fac=d["id"], monto=d["subtotal"], estado="resuelto",
                     deriv=7 if tramo_for(d["subtotal"]) == 3 else 8, sustento="Factura repetida; se anuló el duplicado",
                     creado=f"{next_month_first(per).isoformat()} 09:00", cierre=f"{next_month_first(per).isoformat()} 17:00")
    # Averías legadas con compensación aplicada
    for s, a_id, desc, fact, per in legacy_av:
        creado = (next_month_first(per) + timedelta(days=4)).isoformat() + " 10:00"
        c = add_caso(s["cliente"], "telegram", "B", "sla_averia", fac=fact["id"], av=a_id, monto=desc,
                     estado="resuelto", sustento="Compensación por incumplimiento de SLA", creado=creado, cierre=creado)
        add_ajuste(c, fact["id"], a_id, "nota_credito", "sla_averia", desc, "aplicado",
                   clients[s["cliente"]]["ejecutivo"] if tramo_for(desc) == 2 else None, creado, creado)
    # Consultas resueltas por el agente (opción A)
    for k, cid in enumerate([14, 17, 20, 22, 28, 33, 41, 47]):
        dia = 10 + k
        t0 = f"2026-11-{dia:02d} 09:{10+k:02d}"
        add_verif(cid, clients[cid]["ruc"], t0, 1, "verificado")
        c = add_caso(cid, "telegram", "A", "consulta_detalle_factura", estado="resuelto",
                     sustento="Se explicó el detalle del cargo; sin diferencias", creado=t0, cierre=t0)
        add_log(cid, c, t0, "cliente", "¿Por qué mi factura de octubre subió respecto a septiembre?")
        add_log(cid, c, t0, "agente", "Revisé el detalle: la variación corresponde al consumo de datos del periodo. No hay cobros duplicados.")
        add_log(cid, c, t0, "cliente", "Gracias, entendido.")

    # --- CS-08 gesto comercial (cliente 8)
    fac_c8 = [x for x in facturas if x["cliente"] == 8 and x["periodo"] == "2026-11"][0]
    t_g = "2026-12-02 11:30"
    add_verif(8, clients[8]["ruc"], "2026-12-02 11:20", 1, "verificado")
    c_g1 = add_caso(8, "telegram", "B", "gesto_comercial", fac=fac_c8["id"], monto=60.0, estado="resuelto",
                    sustento="Gesto comercial por demora en atención (P6)", creado=t_g, cierre=t_g)
    aj_gesto = add_ajuste(c_g1, fac_c8["id"], None, "nota_credito", "gesto_comercial", 60.0, "aplicado", None, t_g, t_g)
    t_g2 = "2026-12-04 15:00"
    c_g2 = add_caso(8, "telegram", "B", "gesto_comercial", fac=fac_c8["id"], monto=40.0, estado="cerrado",
                    sustento="Rechazado: ya existe un gesto comercial este mes (P6)", creado=t_g2, cierre=t_g2)
    add_log(8, c_g2, t_g2, "cliente", "¿Pueden darme otro descuento por la demora?")
    add_log(8, c_g2, t_g2, "agente", "Ya aplicamos un gesto comercial este mes. Puedo derivar tu caso a tu ejecutivo de cuenta.")

    # --- CS-12 identificación fallida (cliente 13) y RUC inexistente
    add_verif(13, clients[13]["ruc"], "2026-12-04 10:00", 3, "bloqueado")
    add_verif(None, "99000000001", "2026-12-04 12:00", 0, "bloqueado", code=None)
    # --- CS-13 fuera de alcance (cliente 12)
    t_f = "2026-12-03 16:00"
    add_verif(12, clients[12]["ruc"], "2026-12-03 15:50", 1, "verificado")
    c_f = add_caso(12, "telegram", "A", "fuera_de_alcance", estado="derivado", deriv=clients[12]["ejecutivo"],
                   sustento="El cliente pide renegociar tarifas; fuera del alcance del agente", creado=t_f)
    add_log(12, c_f, t_f, "cliente", "Quiero que me bajen la tarifa del MPLS para el próximo año.")
    add_log(12, c_f, t_f, "agente", "Eso lo gestiona tu ejecutivo de cuenta; ya registré tu pedido y lo derivé.")

    con.commit()

    # --------------------------------------------------------- VALIDACIONES
    def q(sql):
        return cur.execute(sql).fetchall()
    ok = True
    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FALLA"), msg)
        ok &= bool(cond)

    check(q("PRAGMA integrity_check")[0][0] == "ok", "integrity_check")
    check(q("PRAGMA foreign_key_check") == [], "foreign_key_check sin errores")
    check(q("SELECT COUNT(*) FROM cliente")[0][0] == 50, "50 clientes")
    bad = q("""SELECT f.id_factura FROM factura f JOIN factura_linea l USING(id_factura)
               GROUP BY f.id_factura HAVING ABS(SUM(l.monto) - f.subtotal) > 0.01""")
    check(bad == [], "subtotal = suma de líneas")
    bad = q("SELECT id_factura FROM factura WHERE ABS(subtotal*0.18 - igv) > 0.011 OR ABS(subtotal+igv-total) > 0.011")
    check(bad == [], "IGV y total consistentes")
    sub6 = q("SELECT SUM(subtotal) FROM factura WHERE estado<>'anulada'")[0][0]
    check(abs(sub6 - TARGET_SUBTOTAL) / TARGET_SUBTOTAL < 0.01, f"subtotal 6 meses ≈ S/ 100 M (real {sub6:,.0f})")
    c1m = q("SELECT SUM(subtotal) FROM factura WHERE id_cliente=1 AND periodo='2026-09'")[0][0]
    check(abs(c1m - 185000) < 0.01, "cliente 1 factura S/ 185,000 mensual")

    r = q("SELECT id_cliente, periodo, id_original, id_duplicada, monto_a_acreditar FROM v_facturas_duplicadas")
    check(len(r) == 1 and r[0][0] == 1 and r[0][1] == "2026-11" and abs(r[0][4] - 185000) < 0.01, f"v_facturas_duplicadas = CS-01 {r}")
    r = q("SELECT id_cliente, id_servicio, periodo, monto_a_acreditar FROM v_servicios_baja_facturados ORDER BY periodo")
    check(len(r) == 2 and all(x[0] == 2 for x in r) and [x[2] for x in r] == ["2026-10", "2026-11"]
          and all(abs(x[3] - 12000) < 0.01 for x in r), f"v_servicios_baja_facturados = CS-02 {r}")
    r = q("SELECT id_cliente, periodo, diferencia FROM v_tarifa_distinta ORDER BY periodo")
    check(len(r) == 3 and all(x[0] == 3 and abs(x[2] - 4500) < 0.01 for x in r), f"v_tarifa_distinta = CS-03 {r}")
    r = q("SELECT id_cliente, periodo, gb_facturados, gb_reales, monto_a_acreditar FROM v_exceso_sin_sustento")
    check(len(r) == 1 and r[0][0] == 4 and r[0][1] == "2026-10" and abs(r[0][4] - 300) < 0.01, f"v_exceso_sin_sustento = CS-04 {r}")
    r = q("SELECT id_averia, id_cliente, horas_fuera, descuento_sin_igv FROM v_averias_sin_compensar ORDER BY id_cliente")
    check(len(r) == 2 and r[0][1] == 5 and abs(r[0][3] - 464.0) < 0.01 and r[1][1] == 6 and abs(r[1][3] - 33.75) < 0.01,
          f"v_averias_sin_compensar = CS-05 y CS-07 {r}")
    r = q("SELECT id_solicitud, id_cliente, dias_abierta FROM v_solicitudes_vencidas")
    check(len(r) == 1 and r[0][1] == 10 and r[0][2] == 21, f"v_solicitudes_vencidas = CS-06 {r}")
    r = q("SELECT id_cliente, monto_sin_igv FROM v_gestos_mes_actual")
    check(len(r) == 1 and r[0][0] == 8 and abs(r[0][1] - 60) < 0.01, f"v_gestos_mes_actual = CS-08 {r}")
    r = q("SELECT id_cliente, periodo, subtotal, subtotal_anterior FROM v_variacion_facturacion")
    check(len(r) == 1 and r[0][0] == 7 and r[0][1] == "2026-10", f"v_variacion_facturacion = CS-09 {r}")
    r = q("SELECT id_cliente, periodo, estado FROM factura WHERE estado='vencida'")
    check(len(r) == 1 and r[0][0] == 9 and r[0][1] == "2026-10", f"factura vencida = CS-11 {r}")
    pr = q("""SELECT l.concepto, l.monto FROM factura_linea l JOIN factura f USING(id_factura)
              WHERE f.id_cliente=9 AND f.periodo='2026-09' AND l.tipo='prorrateo'""")
    check(len(pr) == 1 and abs(pr[0][1] - 6750) < 0.01, f"prorrateo cliente 9 sept = 6,750 {pr}")

    # --------------------------------------------------------- JSON de casos
    def one(sql):
        return q(sql)[0]
    fac_dup = q("SELECT id_original,id_duplicada FROM v_facturas_duplicadas")[0]
    num = lambda i: q(f"SELECT numero FROM factura WHERE id_factura={i}")[0][0]
    resumen = q("SELECT periodo, facturas, subtotal, total FROM v_resumen_facturacion ORDER BY periodo")
    data = dict(
        fecha_actual=FECHA_ACTUAL.isoformat(),
        factor_calibracion=round(f, 3),
        subtotal_6_meses=round(sub6, 2),
        resumen_mensual=[dict(periodo=a, facturas=b, subtotal=c, total=d) for a, b, c, d in resumen],
        CS01=dict(cliente=1, ruc=clients[1]["ruc"], razon=clients[1]["nombre"], periodo="2026-11",
                  factura_original=num(fac_dup[0]), factura_duplicada=num(fac_dup[1]), subtotal=185000.0,
                  igv=r2(185000 * IGV), total=r2(185000 * 1.18), tramo=4),
        CS02=dict(cliente=2, ruc=clients[2]["ruc"], razon=clients[2]["nombre"], servicio="MPLS Cusco 1 enlace",
                  baja="2026-09-30", periodos=["2026-10", "2026-11"], por_periodo=12000.0, total_sin_igv=24000.0, tramo=3),
        CS03=dict(cliente=3, ruc=clients[3]["ruc"], razon=clients[3]["nombre"], servicio="MPLS Lima 3 enlaces",
                  tarifa_pactada=10500.0, tarifa_facturada=12000.0, diferencia_por_periodo=4500.0,
                  periodos=["2026-09", "2026-10", "2026-11"], total_sin_igv=13500.0, tramo=3),
        CS04=dict(cliente=4, ruc=clients[4]["ruc"], razon=clients[4]["nombre"], periodo="2026-10",
                  gb_facturados=150, gb_reales=0, precio_gb=2.0, monto=300.0, tramo=2),
        CS05=dict(cliente=5, ruc=clients[5]["ruc"], razon=clients[5]["nombre"], averia=av_c5, servicio="MPLS Trujillo",
                  inicio="2026-10-18 08:00", fin="2026-10-19 14:00", horas=30.0, sla=0.997, tolerancia_h=2.16,
                  horas_fuera=27.84, tarifa=12000.0, descuento=464.0, tramo=2),
        CS06=dict(cliente=10, ruc=clients[10]["ruc"], razon=clients[10]["nombre"], solicitud=sol_c10,
                  registro="2026-11-14", dias=21, plazo=10),
        CS07=dict(cliente=6, ruc=clients[6]["ruc"], razon=clients[6]["nombre"], averia=av_c6, servicio="INT500 Piura",
                  inicio="2026-10-03 06:00", fin="2026-10-03 15:00", horas=9.0, sla=0.995, tolerancia_h=3.6,
                  horas_fuera=5.4, tarifa=4500.0, descuento=33.75, tramo=1),
        CS08=dict(cliente=8, ruc=clients[8]["ruc"], razon=clients[8]["nombre"], gesto=60.0, fecha="2026-12-02",
                  segundo_pedido=40.0, resultado_segundo="rechazado por P6"),
        CS09=dict(cliente=7, ruc=clients[7]["ruc"], razon=clients[7]["nombre"], periodo="2026-10",
                  subtotal_anterior=73200.0, subtotal=97200.0, causa="Alta de 2 enlaces MPLS Callao el 2026-10-01",
                  variacion_pct=32.8),
        CS10=dict(cliente=9, ruc=clients[9]["ruc"], razon=clients[9]["nombre"], periodo="2026-09",
                  servicio="INT500 Arequipa 3 enlaces", activacion="2026-09-15", dias=15, prorrateo=6750.0),
        CS11=dict(cliente=9, periodo="2026-10", estado="vencida", vencimiento="2026-11-21"),
        CS12=dict(cliente=13, ruc=clients[13]["ruc"], razon=clients[13]["nombre"], intentos=3, estado="bloqueado",
                  ruc_inexistente="99000000001"),
        CS13=dict(cliente=12, ruc=clients[12]["ruc"], razon=clients[12]["nombre"], pedido="renegociar tarifa MPLS"),
    )
    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, default=str)

    print("\nFilas por tabla:")
    for (t,) in q("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        print(f"  {t:20s} {q(f'SELECT COUNT(*) FROM {t}')[0][0]:>7}")
    con.close()
    if not ok:
        print("\nHAY VALIDACIONES FALLIDAS")
        sys.exit(1)
    print("\nBase creada:", DB_PATH)

if __name__ == "__main__":
    main()
