"""API FastAPI del chatbot de facturación.

Por ahora solo expone /health. Los endpoints con datos de clientes se
agregarán cuando exista la verificación por RUC + código, para no exponer
datos indexados por cliente_id sin autenticación.
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.data import get_connection

app = FastAPI(title="Chatbot de facturación AnticIpA", version="0.1.0")


@app.get("/health")
def health():
    try:
        with get_connection() as con:
            con.execute("SELECT 1").fetchone()
        return {"status": "ok", "db": "ok"}
    except Exception as exc:  # noqa: BLE001 - salud: reportar cualquier fallo
        return JSONResponse(status_code=503, content={"status": "error", "db": str(exc)})
