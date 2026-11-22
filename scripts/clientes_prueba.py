"""Clientes de prueba (1 a 13): RUC, casuística, slot y correo, leídos de la base.

Uso (desde la raíz):
    python -X utf8 -m scripts.clientes_prueba            # los 13
    python -X utf8 -m scripts.clientes_prueba 3          # solo el slot 3
    python -X utf8 -m scripts.clientes_prueba copiar 1   # copia el RUC del cliente 1

Lo usan `clientes_prueba.bat` y `regenerar_base.bat`. Solo lee: abre la base en
modo lectura. Los RUC no cambian al regenerar (el generador usa semilla fija y los
correos del .env se asignan después de sortear); los correos sí dependen del .env.

La casuística de cada cliente sale de `db/casos_datos.json` (lo escribe el
generador junto con la base) y su nombre, de `catalogo.json`.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app import config

N_SLOTS = 5
CLIENTES_PRUEBA = range(1, 14)
CASOS_JSON = config.RAIZ_PROYECTO / "db" / "casos_datos.json"


@dataclass(frozen=True)
class ClientePrueba:
    id: int
    ruc: str
    razon_social: str
    correo: str
    casuisticas: tuple[str, ...]

    @property
    def slot(self) -> int:
        return (self.id - 1) % N_SLOTS + 1

    @property
    def recibe_correo(self) -> bool:
        return not self.correo.lower().endswith(".example")


def _casuisticas(casos_json: Path) -> tuple[dict[int, list[str]], str | None]:
    """{id_cliente: ["CS-01", ...]} y el RUC inexistente de CS-12, si existe el JSON."""
    if not casos_json.is_file():
        return {}, None
    datos = json.loads(casos_json.read_text(encoding="utf-8"))
    por_cliente: dict[int, list[str]] = {}
    for clave, valor in datos.items():
        if clave.startswith("CS") and isinstance(valor, dict) and "cliente" in valor:
            por_cliente.setdefault(int(valor["cliente"]), []).append(f"CS-{clave[2:]}")
    inexistente = (datos.get("CS12") or {}).get("ruc_inexistente")
    return {k: sorted(v) for k, v in por_cliente.items()}, inexistente


def nombres_casuisticas(catalogo: Path | None = None) -> dict[str, str]:
    ruta = catalogo or config.RAIZ_PROYECTO / "catalogo.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return {c["codigo"]: c["nombre"] for c in datos.get("casuisticas", [])}


def leer(db_path: Path | None = None, casos_json: Path | None = None) -> tuple[list[ClientePrueba], str | None]:
    """Clientes 1 a 13 de la base y el RUC inexistente. FileNotFoundError si no hay base."""
    db_path = db_path or config.DB_PATH
    if not Path(db_path).is_file():
        raise FileNotFoundError(db_path)
    casos, inexistente = _casuisticas(casos_json or CASOS_JSON)
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        filas = con.execute(
            "SELECT id_cliente, ruc, razon_social, correo_facturacion FROM cliente"
            " WHERE id_cliente BETWEEN ? AND ? ORDER BY id_cliente",
            (CLIENTES_PRUEBA.start, CLIENTES_PRUEBA.stop - 1),
        ).fetchall()
    finally:
        con.close()
    clientes = [ClientePrueba(i, r, s, c, tuple(casos.get(i, ()))) for i, r, s, c in filas]
    return clientes, inexistente


def tabla(clientes: list[ClientePrueba], nombres: dict[str, str], inexistente: str | None) -> str:
    ancho_razon = max((len(c.razon_social) for c in clientes), default=12)
    lineas = [f" #  RUC          {'Razón social':<{ancho_razon}}  Casuística    Slot  Correo"]
    for c in clientes:
        casos = ", ".join(c.casuisticas) or "—"
        correo = c.correo if c.recibe_correo else f"{c.correo} (no recibe)"
        lineas.append(f"{c.id:>2}  {c.ruc}  {c.razon_social:<{ancho_razon}}  {casos:<12}  {c.slot:>4}  {correo}")
    usados = sorted({cs for c in clientes for cs in c.casuisticas})
    if usados:
        lineas += ["", "Casuísticas:"]
        lineas += [f"  {cs}  {nombres.get(cs, '')}" for cs in usados]
    if any(c.id == 13 for c in clientes):
        lineas += ["", "Cliente 13: tiene un intento bloqueado en su historial (CS-12); "
                       "si pides un código nuevo, puede ingresar."]
    if inexistente:
        lineas.append(f"RUC inexistente para probar CS-12: {inexistente} "
                      "(la respuesta es la misma que con un RUC válido y no llega correo).")
    if any(not c.recibe_correo for c in clientes):
        lineas.append("(no recibe) = correo .example: pon tu correo en tu slot CORREO_PRUEBA_n "
                      "del .env y ejecuta regenerar_base.bat.")
    return "\n".join(lineas)


def copiar(texto: str) -> bool:
    """Copia al portapapeles de Windows (`clip`). False si no se pudo."""
    try:
        subprocess.run(["clip"], input=texto, text=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


AYUDA = ("Uso: clientes_prueba.bat [slot 1-5] | clientes_prueba.bat copiar <cliente 1-13>\n"
         "  sin argumentos: los 13 clientes de prueba")


def main(argv: list[str]) -> int:
    try:
        clientes, inexistente = leer()
    except FileNotFoundError:
        print("No existe la base. Ejecuta install.bat (o regenerar_base.bat).")
        return 1

    if argv[:1] == ["copiar"]:
        if len(argv) != 2 or not argv[1].isdigit():
            print(AYUDA)
            return 2
        elegido = next((c for c in clientes if c.id == int(argv[1])), None)
        if elegido is None:
            print(f"No hay cliente de prueba {argv[1]} (son del 1 al 13).")
            return 2
        if copiar(elegido.ruc):
            print(f"RUC {elegido.ruc} copiado ({elegido.razon_social}).")
        else:
            print(f"RUC {elegido.ruc} ({elegido.razon_social}). No se pudo copiar: cópialo de aquí.")
        return 0

    if argv:
        if len(argv) != 1 or not argv[0].isdigit() or not 1 <= int(argv[0]) <= N_SLOTS:
            print(AYUDA)
            return 2
        clientes = [c for c in clientes if c.slot == int(argv[0])]
    print(tabla(clientes, nombres_casuisticas(), inexistente))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
