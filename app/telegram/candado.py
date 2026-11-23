"""Candado local: un solo proceso de esta PC lee mensajes con un mismo token [5.2].

Telegram admite un solo lector por token: si dos procesos llaman a getUpdates, se
reparten los mensajes y responden 409. Entre procesos de la misma PC (dos `run.bat`,
o uno más un uvicorn a mano) se evita con un archivo bloqueado por el sistema
operativo en la carpeta temporal. Entre PC distintas no hay candado posible: por eso
cada integrante usa su propio bot.

- El nombre del archivo lleva un hash del token, nunca el token [4.1].
- El bloqueo es del sistema operativo (`msvcrt.locking` en Windows, `fcntl.flock` en
  Linux y macOS): si el proceso muere, se libera solo; no quedan candados huérfanos.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def ruta_candado(token: str, carpeta: Path | None = None) -> Path:
    huella = hashlib.sha256(token.encode()).hexdigest()[:16]
    return (carpeta or Path(tempfile.gettempdir())) / f"anticipa-telegram-{huella}.lock"


class CandadoLocal:
    def __init__(self, token: str, carpeta: Path | None = None) -> None:
        self.ruta = ruta_candado(token, carpeta)
        self._archivo = None

    def tomar(self) -> bool:
        """True si este proceso queda como el único lector del token en esta PC."""
        if self._archivo is not None:
            return True
        archivo = open(self.ruta, "a+b")  # noqa: SIM115 - queda abierto mientras dure el candado
        try:
            if os.name == "nt":
                archivo.seek(0)
                msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            archivo.close()
            return False
        self._archivo = archivo
        return True

    def soltar(self) -> None:
        if self._archivo is None:
            return
        try:
            if os.name == "nt":
                self._archivo.seek(0)
                msvcrt.locking(self._archivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._archivo.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._archivo.close()
            self._archivo = None
