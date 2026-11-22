"""Configuración del bot de Telegram (app/config.py)."""
import pytest

from app import config


@pytest.mark.parametrize("texto, esperado", [
    ("", frozenset()),
    ("   ", frozenset()),
    ("123", frozenset({123})),
    (" 123 , 456,,", frozenset({123, 456})),
    ("123,123", frozenset({123})),
])
def test_ids_validos(texto, esperado):
    assert config.leer_ids_telegram(texto) == esperado


@pytest.mark.parametrize("texto", ["abc", "123,@usuario", "-5", "0", "12.5", "123;456", "²"])
def test_ids_invalidos_son_error(texto):
    """Mal escrito no se salta: una lista que queda vacía abriría el bot a cualquiera."""
    with pytest.raises(ValueError, match="TELEGRAM_USUARIOS_PERMITIDOS"):
        config.leer_ids_telegram(texto)


def test_ejemplo_documenta_las_variables():
    ejemplo = (config.RAIZ_PROYECTO / ".env.example").read_text(encoding="utf-8")
    for nombre in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_USUARIOS_PERMITIDOS", "TELEGRAM_MAX_SOLICITUDES",
                   "TELEGRAM_VENTANA_SEG", "TELEGRAM_HILOS"):
        assert f"\n{nombre}=" in ejemplo, nombre
    assert "\nTELEGRAM_BOT_TOKEN=\n" in ejemplo  # sin token de verdad en el ejemplo
