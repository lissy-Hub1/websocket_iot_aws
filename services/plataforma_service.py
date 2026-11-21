"""Práctica 4.3: servicios de soporte compartidos.

* `Plataforma`: llama cualquier SP de PlataformaRepository en su propia transacción.
* `AuditoriaService`: bitácora (best effort: una falla al auditar no tumba la operación).
* `ControlExclusivo`: evita que dos sesiones muevan la misma unidad al mismo tiempo.
* `LimiteSolicitudes`: límite simple por IP para login y sesiones de invitado.
"""
import asyncio
import hashlib
import logging
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Iterator, Optional

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from database import Database
from repositories.plataforma_repository import PlataformaRepository

log = logging.getLogger("app_iot.plataforma")


def hash_token(token: str) -> str:
    """En RDS nunca se guarda un token, solo su SHA-256."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Plataforma:
    """`plataforma.validar_sesion(h)` abre una transacción, llama el SP y hace commit."""

    def __init__(self, db: Database):
        self._db = db

    @contextmanager
    def transaccion(self) -> Iterator[PlataformaRepository]:
        with self._db.transaccion() as sp:
            yield PlataformaRepository(sp)

    def __getattr__(self, nombre: str):
        metodo = getattr(PlataformaRepository, nombre)

        def llamar(*args):
            with self._db.transaccion() as sp:
                return metodo(PlataformaRepository(sp), *args)

        return llamar


class AuditoriaService:
    def __init__(self, plataforma: Plataforma):
        self._p = plataforma

    def registrar_actor(self, id_actor: Optional[int], actor_rol: str, accion: str, recurso: str,
                        id_recurso=None, resultado: str = "OK", detalle: Optional[dict] = None) -> None:
        try:
            self._p.auditar(id_actor, actor_rol, accion, recurso, id_recurso, resultado, detalle)
        except Exception:
            log.exception("No se pudo registrar la auditoría de %s", accion)

    def registrar(self, ident, accion: str, recurso: str, id_recurso=None, resultado: str = "OK",
                  detalle: Optional[dict] = None) -> None:
        """`ident` es una Identidad (o None si aún no se sabe quién es)."""
        self.registrar_actor(
            getattr(ident, "id_usuario", None), getattr(ident, "rol_auditoria", "SISTEMA"),
            accion, recurso, id_recurso, resultado, detalle,
        )

    async def registrar_async(self, *args, **kwargs) -> None:
        await run_in_threadpool(self.registrar, *args, **kwargs)


class ControlExclusivo:
    """Solo una sesión opera cada unidad a la vez. Quien la usó tiene prioridad durante `ventana_s`
    segundos desde su último comando. DETENER siempre pasa (la seguridad va primero)."""

    def __init__(self, ventana_s: float = 15.0):
        self._ventana = ventana_s
        self._duenos: dict[int, tuple[str, float]] = {}

    def otro_operando(self, id_vehiculo: int, clave: str) -> Optional[int]:
        """Segundos que faltan para que se libere, si otra sesión la está operando; None si está libre."""
        actual = self._duenos.get(id_vehiculo)
        if not actual or actual[0] == clave:
            return None
        transcurrido = time.monotonic() - actual[1]
        return None if transcurrido >= self._ventana else int(self._ventana - transcurrido) + 1

    def marcar(self, id_vehiculo: int, clave: str) -> None:
        self._duenos[id_vehiculo] = (clave, time.monotonic())

    def liberar(self, id_vehiculo: int, clave: Optional[str] = None) -> None:
        actual = self._duenos.get(id_vehiculo)
        if actual and (clave is None or actual[0] == clave):
            self._duenos.pop(id_vehiculo, None)


class LimiteSolicitudes:
    """Ventana deslizante por clave (IP + ruta). 1 worker: basta con memoria."""

    def __init__(self, maximo: int, ventana_s: float):
        self._max, self._ventana = maximo, ventana_s
        self._marcas: dict[str, deque] = defaultdict(deque)
        self._candado = asyncio.Lock()

    async def comprobar(self, clave: str) -> None:
        async with self._candado:
            ahora = time.monotonic()
            marcas = self._marcas[clave]
            while marcas and ahora - marcas[0] > self._ventana:
                marcas.popleft()
            if len(marcas) >= self._max:
                raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Espera un momento.")
            marcas.append(ahora)
