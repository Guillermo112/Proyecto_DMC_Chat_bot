"""El router marca `cortada` cuando el proveedor corta la salida por max_tokens."""
import pytest

from app.llm import router as r

RESPUESTAS = {
    "openai": lambda fin: {"choices": [{"message": {"content": "Hola"}, "finish_reason": fin}], "usage": {}},
    "anthropic": lambda fin: {"content": [{"type": "text", "text": "Hola"}], "stop_reason": fin, "usage": {}},
    "gemini": lambda fin: {"candidates": [{"content": {"parts": [{"text": "Hola"}]}, "finishReason": fin}]},
}
CORTE = {"openai": ("length", "stop"), "anthropic": ("max_tokens", "end_turn"), "gemini": ("MAX_TOKENS", "STOP")}


@pytest.mark.parametrize("familia", sorted(RESPUESTAS))
@pytest.mark.parametrize("cortada", [True, False])
def test_cortada_por_familia(monkeypatch, familia, cortada):
    fin = CORTE[familia][0 if cortada else 1]
    monkeypatch.setattr(r, "_http_post", lambda *a, **k: (200, RESPUESTAS[familia](fin)))
    router = r.Router(endpoints=[r.Endpoint(base_url="http://local.test", api_key="x", modelo="m",
                                            familia=familia)],
                      razonamiento="off", modo_herramientas="ninguno")
    resp = router.chat([{"role": "user", "content": "hola"}], max_tokens=10)
    assert resp.texto == "Hola" and resp.cortada is cortada
