"""Punto de entrada.
Local:      python -m uvicorn main:app --reload --port 8000
Producción: uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 (detrás de Caddy, ver deploy/)"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse

from config import get_settings, origenes_cors
from dependencies import Contenedor
from exceptions import ErrorDeNegocio
from routers import comandos, demos, estado, movimientos, vehiculos, ws
from routers import admin, auth, invitados, mis_vehiculos  # práctica 4.3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app_iot")

DESCRIPCION = """
API pública para el vehículo IoT (examen 2.6) en Amazon EC2. Base de datos: Amazon RDS `vehiculo_iot`.

* **Movimiento individual** (`POST /vehiculos/{id}/movimientos`): actualiza estado + historial y notifica por WebSocket.
* **DEMO** (`POST /vehiculos/{id}/demos/{id_demo}/iniciar`): transmite N movimientos por WebSocket **sin** historial.
* **WebSocket seguro (WSS):** `wss://<este-mismo-dominio>/ws/vehiculos/{id_vehiculo}` (Swagger no documenta WebSocket; ver README).
* Las operaciones de control y eliminación requieren el encabezado `X-API-Key`.

**Práctica 4.3 (Administración):** inicio de sesión con Google (`POST /auth/google`) y roles
ADMINISTRADOR, USUARIO (comprador) e INVITADO. Envía `Authorization: Bearer <token>`. Cada ruta de un vehículo
comprueba el permiso sobre ESA unidad (401 sin sesión, 403 sin permiso). `X-API-Key` queda como acceso técnico
de servicio. El WebSocket se autentica con el primer mensaje `{"tipo":"auth","token":"…"}`.
"""

ETIQUETAS = [
    {"name": "Vehículos", "description": "Alta, consulta, edición y baja de vehículos"},
    {"name": "Comandos", "description": "Catálogo de comandos de cada vehículo"},
    {"name": "Estado", "description": "Último estado registrado"},
    {"name": "Movimientos e historial", "description": "Movimientos individuales y su bitácora (máx. 10)"},
    {"name": "DEMO", "description": "DEMO, sus movimientos y su ejecución por WebSocket"},
    {"name": "Autenticación (4.3)", "description": "Login con Google, sesión y salud de API/RDS"},
    {"name": "Administración (4.3)", "description": "Dashboard, modelos, unidades, clientes, asignaciones y auditoría"},
    {"name": "Mis vehículos y demos (4.3)", "description": "Unidades propias, soporte autorizado y editor de demos"},
    {"name": "Invitados (4.3)", "description": "Catálogo público y prueba temporal con reserva exclusiva"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.contenedor = Contenedor.crear(get_settings())  # falla al arrancar si falta configuración
    app.state.contenedor.vigilante.iniciar()  # 4.3: cierra pruebas de Invitado vencidas y detiene la unidad
    log.info("API lista (documentación en /docs)")
    yield
    await app.state.contenedor.vigilante.cerrar()
    await app.state.contenedor.runner.cerrar()


app = FastAPI(
    title="API IoT – Vehículo (examen 2.6)",
    description=DESCRIPCION,
    version="1.0.0",
    openapi_tags=ETIQUETAS,
    lifespan=lifespan,
)

# CORS no autentica: solo indica qué páginas pueden leer las respuestas desde el navegador.
if origenes := origenes_cors():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origenes,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    )

for modulo in (vehiculos, comandos, estado, movimientos, demos, ws, auth, admin, mis_vehiculos, invitados):
    app.include_router(modulo.router)


@app.exception_handler(ErrorDeNegocio)
async def manejar_error_negocio(_: Request, exc: ErrorDeNegocio):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.mensaje})


@app.exception_handler(Exception)
async def manejar_error_inesperado(_: Request, exc: Exception):
    log.exception("Error no controlado")  # el detalle queda en el log, no en la respuesta
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})


PANEL = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
async def panel():
    """Panel web del vehículo (HTML estático que usa la propia API y el WSS)."""
    return FileResponse(PANEL)