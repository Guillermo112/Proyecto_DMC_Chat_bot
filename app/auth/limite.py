"""Límite de solicitudes por IP (ventana deslizante, en memoria).

Protege `/auth/solicitar-codigo` de spam de correos, de enumerar RUCs y de pedir
códigos en masa para adivinarlos. Complementa la espera de reenvío por cliente
(OTP_ESPERA_REENVIO_SEG) y los intentos por código (OTP_MAX_INTENTOS).

Límites conocidos:
- Vive en la memoria del proceso: con varios workers de uvicorn cada uno cuenta
  por su lado, y se reinicia al reiniciar la app. Para eso habría que guardarlo
  en la base o en un servicio compartido.
- Usa la IP de la conexión (`request.client.host`). Detrás de un proxy todas las
  peticiones llegarían con la IP del proxy; no se lee X-Forwarded-For porque el
  cliente puede falsificarla.
"""
import math
import threading
import time
from collections import deque
from typing import Callable

from fastapi import HTTPException, Request

from app import config


class LimitadorPorIP:
    def __init__(
        self,
        maximo: Callable[[], int],
        ventana_seg: Callable[[], int],
        reloj: Callable[[], float] = time.monotonic,
    ):
        # maximo y ventana se leen en cada llamada (config puede cambiar en tests).
        self._maximo = maximo
        self._ventana = ventana_seg
        self._reloj = reloj
        self._por_ip: dict[str, deque[float]] = {}
        self._lock = threading.Lock()  # las rutas síncronas corren en un pool de hilos

    def registrar(self, ip: str) -> float | None:
        """Cuenta una solicitud de `ip`.

        Devuelve None si está permitida, o los segundos que faltan para que se libere
        un cupo si ya alcanzó el máximo (en ese caso no se cuenta).
        """
        ahora = self._reloj()
        ventana = self._ventana()
        maximo = self._maximo()
        with self._lock:
            tiempos = self._por_ip.setdefault(ip, deque())
            while tiempos and tiempos[0] <= ahora - ventana:
                tiempos.popleft()
            if len(tiempos) >= maximo:
                return tiempos[0] + ventana - ahora
            tiempos.append(ahora)
            self._limpiar(ahora - ventana)
            return None

    def _limpiar(self, corte: float) -> None:
        """Quita las IPs sin solicitudes recientes para que la memoria no crezca."""
        if len(self._por_ip) < 1000:
            return
        for ip in [ip for ip, t in self._por_ip.items() if not t or t[-1] <= corte]:
            del self._por_ip[ip]

    def reiniciar(self) -> None:
        with self._lock:
            self._por_ip.clear()


limitador_solicitudes = LimitadorPorIP(
    maximo=lambda: config.AUTH_MAX_SOLICITUDES_POR_IP,
    ventana_seg=lambda: config.AUTH_VENTANA_SOLICITUDES_SEG,
)


def limitar_solicitudes(request: Request) -> None:
    """Dependencia FastAPI: 429 con Retry-After si la IP superó el límite."""
    ip = request.client.host if request.client else "desconocida"
    espera = limitador_solicitudes.registrar(ip)
    if espera is not None:
        segundos = max(1, math.ceil(espera))
        raise HTTPException(
            status_code=429,
            detail=f"Demasiadas solicitudes de código desde esta conexión; intenta en {segundos} s",
            headers={"Retry-After": str(segundos)},
        )
