"""Prueba en vivo del OTP por correo.

Uso (desde la raíz):  python -X utf8 -m scripts.demo_otp
Requiere SMTP_* en .env y, para recibirlo tú, tu correo en CORREO_PRUEBA_n + regenerar_base.bat.
"""
from app import config
from app.auth import solicitar_codigo, verificar_codigo
from app.data import obtener_cliente

try:
    id_verificacion, correo = solicitar_codigo(input("RUC del cliente (11 dígitos): "))
except (ValueError, RuntimeError) as exc:
    raise SystemExit(f"No se pudo enviar: {exc}")
if correo:
    print(f"Enviamos un código a {correo}. Revisa tu bandeja (y spam).")
    print(f"(Si pediste otro hace menos de {config.OTP_ESPERA_REENVIO_SEG} s, no se envía uno nuevo: usa el que ya llegó.)")
else:
    print("El RUC no está registrado.")
    raise SystemExit(1)

for _ in range(config.OTP_MAX_INTENTOS):
    cliente_id = verificar_codigo(id_verificacion, input("Código de 6 dígitos: "))
    if cliente_id:
        print(f"Verificado: {obtener_cliente(cliente_id).razon_social} (cliente_id={cliente_id})")
        break
    print("Código incorrecto, vencido o bloqueado.")
